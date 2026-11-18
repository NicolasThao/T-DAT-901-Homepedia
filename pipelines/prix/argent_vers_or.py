"""
Pipeline prix, étape 2 : argent -> or. Indicateurs du marché par zone (commune, département, région),
type de bien (Maison, Appartement, Tous) et année.

Entrée  : argent/dvf/ (Parquet), bronze/referentiel/communes.csv (commune -> département -> région)
Sortie  : or/indicateurs_prix/ (un CSV : petit, téléchargé puis chargé dans PostgreSQL par db/ovh.py)

Vente retenue (même filtre que jobs/indicateurs_prix.py, qui importe ce module, et que db/check.py) :
vente de marché, un seul logement (Maison ou Appartement), prix/m² fiable entre 200 et 30 000 €/m².
Indicateurs : médiane, déciles 1 et 9, quartiles du prix au m² ; valeur et surface médianes ; nombre de ventes.
Percentiles exacts (`percentile`, interpolation linéaire, comme percentile_cont en SQL).

Un seul fichier, sans import local : c'est la forme d'une action « Custom PySpark » d'OVHcloud Data Platform.
Local  : spark-submit pipelines/prix/argent_vers_or.py
OVH    : action Custom PySpark, entrée customfunc(event)
"""

import os
import time
from datetime import datetime, timezone

from pyspark.sql import functions as F

ETAPE = "argent_vers_or"
SOURCE = "dvf"
PRIX_M2_MIN, PRIX_M2_MAX = 200, 30_000
NIVEAUX = {"commune": "code_insee", "departement": "code_departement", "region": "code_region"}
# Ordre des colonnes du CSV = colonnes de la table indicateurs_prix (db/postgres/schema.sql)
COLONNES = ["niveau_geo", "code_geo", "type_local", "periode", "prix_m2_median", "nb_ventes",
            "prix_m2_d1", "prix_m2_q1", "prix_m2_q3", "prix_m2_d9", "valeur_mediane", "surface_mediane",
            "_source", "_date_ingestion", "_batch_id"]


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


def journal(message):
    print(f"[{ETAPE}] {message}", flush=True)
# ---------------------------------------------------------------------------------------------------------------


def ventes_retenues(ventes):
    """`ventes` : une ligne par vente avec hors_marche, prix_m2_douteux, nb_logements, type_local, prix_m2,
    date_mutation, valeur_fonciere, surface_bati_m2 et le rattachement code_insee / code_departement / code_region."""
    return ventes.filter(
        ~F.col("hors_marche") & ~F.col("prix_m2_douteux")
        & (F.col("nb_logements") == 1)
        & F.col("type_local").isin("Maison", "Appartement")
        & F.col("prix_m2").between(PRIX_M2_MIN, PRIX_M2_MAX)
    ).select(
        "code_insee", "code_departement", "code_region", "type_local",
        F.year("date_mutation").alias("periode"),
        F.col("prix_m2").cast("double").alias("prix_m2"),
        F.col("valeur_fonciere").cast("double").alias("valeur_fonciere"),
        F.col("surface_bati_m2").cast("double").alias("surface_bati_m2"),
    )


def agreger(ventes):
    """Indicateurs par (niveau_geo, code_geo, type_local, periode). Chaque vente compte pour son type et pour « Tous »."""
    ventes = ventes.withColumn("type_local", F.explode(F.array(F.col("type_local"), F.lit("Tous"))))
    resultats = None
    for niveau, colonne in NIVEAUX.items():
        r = (ventes.groupBy(F.col(colonne).alias("code_geo"), "type_local", "periode")
             .agg(F.expr("percentile(prix_m2, array(0.1, 0.25, 0.5, 0.75, 0.9))").alias("p"),
                  F.expr("percentile(valeur_fonciere, 0.5)").alias("valeur_mediane"),
                  F.expr("percentile(surface_bati_m2, 0.5)").alias("surface_mediane"),
                  F.count(F.lit(1)).cast("int").alias("nb_ventes"))
             .withColumn("niveau_geo", F.lit(niveau)))
        resultats = r if resultats is None else resultats.unionByName(r)
    return resultats.select(
        "niveau_geo", "code_geo", "type_local", "periode",
        F.col("p")[2].alias("prix_m2_median"), "nb_ventes",
        F.col("p")[0].alias("prix_m2_d1"), F.col("p")[1].alias("prix_m2_q1"),
        F.col("p")[3].alias("prix_m2_q3"), F.col("p")[4].alias("prix_m2_d9"),
        "valeur_mediane", "surface_mediane",
    )


def executer():
    t0 = time.time()
    spark, url = contexte(ETAPE)
    lot = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    communes = (spark.read.csv(url("bronze/referentiel/communes.csv"), header=True, inferSchema=False)
                .select("code_insee", "code_departement", "code_region").dropDuplicates(["code_insee"]))
    # Jointure interne : une vente sans commune, département ou région connus n'entre dans aucun indicateur
    argent = (spark.read.parquet(url("argent/dvf")).join(communes, "code_insee")
              .filter(F.col("code_departement").isNotNull() & F.col("code_region").isNotNull()))
    indicateurs = (agreger(ventes_retenues(argent))
                   .withColumn("_source", F.lit(SOURCE))
                   .withColumn("_date_ingestion", F.date_format(F.current_timestamp(), "yyyy-MM-dd'T'HH:mm:ssXXX"))
                   .withColumn("_batch_id", F.lit(lot))
                   .select(*COLONNES))
    (indicateurs.coalesce(1).write.mode("overwrite").option("header", True)
     .csv(url("or/indicateurs_prix")))
    for r in spark.read.csv(url("or/indicateurs_prix"), header=True).groupBy("niveau_geo").agg(
            F.count(F.lit(1)).alias("lignes")).orderBy("niveau_geo").collect():
        journal(f"{r.niveau_geo:12} {r.lignes} lignes")
    journal(f"lot {lot} écrit dans or/indicateurs_prix ({time.time() - t0:.0f} s)")


def customfunc(event=None):
    """Point d'entrée d'une action Custom PySpark d'OVHcloud Data Platform."""
    executer()


if __name__ == "__main__":
    executer()
