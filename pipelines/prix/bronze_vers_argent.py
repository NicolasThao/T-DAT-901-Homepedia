"""
Pipeline prix, étape 1 : bronze -> argent. Une ligne par vente DVF, qualité marquée (jamais supprimée).

Entrée  : bronze/dvf/<année>.csv.gz (fichiers Etalab tels que téléchargés), bronze/referentiel/communes.csv
Sortie  : argent/dvf/ (Parquet, partitionné par année), remplacé en entier à chaque exécution (rejouable)

Mêmes règles que db/load_dvf.py (version SQL qui alimente la base locale) ; la parité des deux est
contrôlée par pipelines/prix/parite_argent.py :
- une vente = un id_mutation ; une ligne hors marché rend toute la vente hors marché ;
- vente sur plusieurs communes : la commune du logement s'il y en a un ;
- logement = (parcelle, type, surface, pièces, lot), compté sur UNE nature de culture (le max) ;
- surface de terrain sommée sur les (parcelle, culture) distincts ;
- prix au m² arrondi au centime comme la colonne générée PostgreSQL ; douteux si logements à plusieurs adresses.

Un seul fichier, sans import local : c'est la forme d'une action « Custom PySpark » d'OVHcloud Data Platform.
Local  : spark-submit pipelines/prix/bronze_vers_argent.py   (lac dans data/lac, cf. docs/deploiement_ovh.md)
OVH    : action Custom PySpark, entrée customfunc(event)
"""

import os
import time
from datetime import datetime, timezone

from pyspark.sql import functions as F

ETAPE = "bronze_vers_argent"
ANNEES_DEFAUT = "2022,2023,2024,2025"  # HOMEPEDIA_ANNEES : à régler sur les 3 actions à la fois
SOURCE = "dvf-geolocalisees-etalab"
MARCHE = ["Vente", "Vente en l'état futur d'achèvement"]
LOGEMENT = ["Maison", "Appartement"]


# --- Accès au lac (bloc identique dans chaque étape : une action OVH ne peut pas importer un autre fichier) ---
def parametre(nom, defaut=None):
    """Variable de l'action : sur OVH, dictionnaire PARAMS du SDK (variables d'environnement de l'action ou du
    workflow), sinon os.environ (local, conteneur)."""
    try:
        from forepaas.core.settings import PARAMS
        if PARAMS.get(nom) not in (None, ""):
            return str(PARAMS[nom])
    except ImportError:
        pass
    return os.environ.get(nom, defaut)


def contexte(nom):
    """(spark, url) ; url("bronze/dvf/2022.csv.gz") donne l'adresse du fichier dans le lac.

    Paramètres lus par parametre() :
    - HOMEPEDIA_URL_LAC défini (ex. s3a://homepedia) : adresse directe, session Spark existante ;
    - SDK OVHcloud présent (forepaas) : source Buckets HOMEPEDIA_SOURCE (défaut « homepedia ») ;
    - sinon, local : dossier HOMEPEDIA_LAC (défaut data/lac à la racine du dépôt).
    """
    from pyspark.sql import SparkSession
    base = parametre("HOMEPEDIA_URL_LAC")
    if base:
        return SparkSession.builder.appName(nom).getOrCreate(), lambda chemin: f"{base.rstrip('/')}/{chemin}"
    try:
        from forepaas.dwh import connect
    except ImportError:
        from pathlib import Path
        racine = Path(parametre("HOMEPEDIA_LAC", Path(__file__).resolve().parents[2] / "data" / "lac"))
        spark = SparkSession.builder.appName(nom).master("local[*]").getOrCreate()
        return spark, lambda chemin: str(racine / chemin)
    cn = connect(f"dwh/{parametre('HOMEPEDIA_SOURCE', 'homepedia')}/")
    bucket = parametre("HOMEPEDIA_BUCKET", "homepedia")

    def url(chemin):
        dossier, _, fichier = chemin.rpartition("/")
        return cn.get_spark_url(dossier, fichier, bucket=bucket)
    return cn.get_spark_session(), url


def annees():
    return [int(a) for a in parametre("HOMEPEDIA_ANNEES", ANNEES_DEFAUT).split(",")]


def journal(message):
    print(f"[{ETAPE}] {message}", flush=True)
# ---------------------------------------------------------------------------------------------------------------


def lire_bronze(spark, url):
    """Lignes brutes des fichiers Etalab : tout en texte, champ vide = NULL (comme le COPY de load_dvf)."""
    morceaux = []
    for annee in annees():
        brut = spark.read.csv(url(f"bronze/dvf/{annee}.csv.gz"), header=True, inferSchema=False)
        morceaux.append(brut.withColumn("annee", F.lit(annee)))
    df = morceaux[0]
    for m in morceaux[1:]:
        df = df.unionByName(m)
    txt = lambda c: F.coalesce(F.col(c), F.lit(""))  # noqa: E731  (concaténation : vide, pas NULL)
    return df.select(
        "annee",
        F.col("id_mutation").alias("cle"),
        F.to_date("date_mutation").alias("date_mutation"),
        F.col("nature_mutation").alias("nature"),
        F.col("valeur_fonciere").cast("decimal(15,2)").alias("valeur"),
        F.col("code_commune").alias("code_insee"),
        "id_parcelle",
        F.col("code_nature_culture").alias("culture"),
        F.concat_ws("|", txt("id_parcelle"), txt("type_local"), txt("surface_reelle_bati"),
                    txt("nombre_pieces_principales"), txt("lot1_numero")).alias("cle_local"),
        F.concat_ws("|", txt("adresse_code_voie"), txt("adresse_numero")).alias("adresse"),
        "type_local",
        F.col("surface_reelle_bati").cast("decimal(18,4)").alias("surface_bati"),
        F.col("nombre_pieces_principales").cast("decimal(18,4)").alias("nb_pieces"),
        F.col("surface_terrain").cast("decimal(18,4)").alias("surface_terrain"),
        F.col("longitude").cast("double").alias("lon"),
        F.col("latitude").cast("double").alias("lat"),
    )


def ventes(brut, communes):
    """Agrégation par vente : traduction ligne à ligne de la requête AGREGATION de db/load_dvf.py."""
    est_logement = F.col("type_local").isin(LOGEMENT)
    cles = ["annee", "cle"]

    m = brut.groupBy(*cles).agg(
        F.min("date_mutation").alias("date_mutation"),
        F.min("valeur").alias("valeur_fonciere"),
        F.coalesce(F.min(F.when(~F.col("nature").isin(MARCHE), F.col("nature"))),
                   F.min("nature")).alias("nature_mutation"),
        F.coalesce(F.min(F.when(est_logement, F.col("code_insee"))),
                   F.min("code_insee")).alias("code_insee_source"),
        F.count(F.lit(1)).cast("int").alias("nb_lignes_source"),
        F.avg("lon").alias("lon_toutes"), F.avg("lat").alias("lat_toutes"),
        F.countDistinct(F.when(est_logement, F.col("type_local"))).alias("nb_types_logement"),
        F.max(F.when(est_logement, F.col("type_local"))).alias("type_logement"),
        F.max(F.when(F.col("type_local").startswith("Local"), F.col("type_local"))).alias("type_local_pro"),
        F.max("type_local").alias("type_autre"),
    ).select(
        *cles, "date_mutation", "valeur_fonciere", "nature_mutation", "code_insee_source", "nb_lignes_source",
        "lon_toutes", "lat_toutes",
        F.when(F.col("nb_types_logement") > 1, F.lit("Mixte"))
         .otherwise(F.coalesce("type_logement", "type_local_pro", "type_autre")).alias("type_local"),
    )

    # Un groupe = un logement type ; n = logements identiques (lignes pour une même nature de culture)
    par_culture = (brut.filter(est_logement)
                   .groupBy(*cles, "cle_local", "culture")
                   .agg(F.count(F.lit(1)).alias("n"), F.min("adresse").alias("adresse"),
                        F.min("surface_bati").alias("surface_bati"), F.min("nb_pieces").alias("nb_pieces"),
                        F.avg("lon").alias("lon"), F.avg("lat").alias("lat")))
    locaux = (par_culture.groupBy(*cles, "cle_local")
              .agg(F.max("n").alias("n"), F.min("adresse").alias("adresse"),
                   F.min("surface_bati").alias("surface_bati"), F.min("nb_pieces").alias("nb_pieces"),
                   F.avg("lon").alias("lon"), F.avg("lat").alias("lat")))
    logements = (locaux.groupBy(*cles)
                 .agg(F.sum("n").cast("int").alias("nb_logements"),
                      F.countDistinct("adresse").cast("int").alias("nb_adresses"),
                      F.sum(F.col("surface_bati") * F.col("n")).alias("surface_bati"),
                      F.sum(F.col("nb_pieces") * F.col("n")).alias("nb_pieces"),
                      F.avg("lon").alias("lon_logements"), F.avg("lat").alias("lat_logements")))

    terrains = (brut.select(*cles, "id_parcelle", "culture", "surface_terrain").distinct()
                .groupBy(*cles).agg(F.sum("surface_terrain").alias("surface_terrain")))

    surface = F.round(F.col("surface_bati"), 2).cast("decimal(12,2)")
    v = (m.join(logements, cles, "left").join(terrains, cles, "left")
         .join(communes.select(F.col("code_insee").alias("code_insee_source")).distinct()
               .withColumn("code_insee", F.col("code_insee_source")), "code_insee_source", "left"))
    return v.select(
        F.col("cle").alias("cle_mutation"), "annee", "date_mutation", "nature_mutation", "valeur_fonciere",
        "code_insee_source", "code_insee", "type_local",
        F.coalesce("nb_logements", F.lit(0)).alias("nb_logements"),
        surface.alias("surface_bati_m2"),
        F.round("nb_pieces").cast("int").alias("nb_pieces"),
        F.round("surface_terrain", 2).cast("decimal(14,2)").alias("surface_terrain_m2"),
        "nb_lignes_source", "nb_adresses",
        F.coalesce("lon_logements", "lon_toutes").alias("longitude"),
        F.coalesce("lat_logements", "lat_toutes").alias("latitude"),
        F.when(surface > 0, F.round(F.col("valeur_fonciere") / surface, 2)).cast("decimal(12,2)").alias("prix_m2"),
        (~F.col("nature_mutation").isin(MARCHE)).alias("hors_marche"),
        (F.col("nb_adresses") > 1).alias("prix_m2_douteux"),
    )


def executer():
    t0 = time.time()
    spark, url = contexte(ETAPE)
    lot = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    communes = spark.read.csv(url("bronze/referentiel/communes.csv"), header=True, inferSchema=False)
    argent = (ventes(lire_bronze(spark, url), communes)
              .withColumn("_source", F.lit(SOURCE))
              .withColumn("_date_ingestion", F.current_timestamp())
              .withColumn("_batch_id", F.lit(lot)))
    argent.write.mode("overwrite").partitionBy("annee").parquet(url("argent/dvf"))
    for r in spark.read.parquet(url("argent/dvf")).groupBy("annee").agg(
            F.count(F.lit(1)).alias("ventes"), F.sum("nb_lignes_source").alias("lignes")).orderBy("annee").collect():
        journal(f"{r.annee} : {r.lignes} lignes -> {r.ventes} ventes")
    journal(f"lot {lot} écrit dans argent/dvf ({time.time() - t0:.0f} s)")


def customfunc(event=None):
    """Point d'entrée d'une action Custom PySpark d'OVHcloud Data Platform."""
    executer()


if __name__ == "__main__":
    executer()
