"""
Pipeline prix, étape 3 : contrôles PASS/FAIL des couches argent et or. Échoue (exception) si un contrôle échoue :
le workflow s'arrête en erreur et db/ovh.py refuse de charger un lot or non validé.

Entrée  : bronze/dvf/<année>.csv.gz, argent/dvf/, or/indicateurs_prix/
Sortie  : or/controles/ (un CSV : controle, ok, detail, _batch_id = lot or contrôlé)

Le recalcul indépendant des médianes (SQL pur, toutes zones) est fait en local par db/check.py après
chargement : il compare les indicateurs calculés sur OVHcloud aux ventes de la base locale.

Un seul fichier, sans import local : c'est la forme d'une action « Custom PySpark » d'OVHcloud Data Platform.
Local  : spark-submit pipelines/prix/controles.py
OVH    : action Custom PySpark, entrée customfunc(event)
"""

import os

from pyspark.sql import functions as F

ETAPE = "controles"
ANNEES = [int(a) for a in os.environ.get("HOMEPEDIA_ANNEES", "2022,2023,2024,2025").split(",")]
PRIX_M2_MIN, PRIX_M2_MAX = 200, 30_000


# --- Accès au lac (bloc identique dans chaque étape : une action OVH ne peut pas importer un autre fichier) ---
def contexte(nom):
    """(spark, url) ; url("bronze/dvf/2022.csv.gz") donne l'adresse du fichier dans le lac.

    - HOMEPEDIA_URL_LAC défini (ex. s3a://homepedia) : adresse directe, session Spark existante ;
    - SDK OVHcloud présent (forepaas) : source Buckets HOMEPEDIA_SOURCE (défaut « homepedia ») ;
    - sinon, local : dossier HOMEPEDIA_LAC (défaut data/lac à la racine du dépôt).
    """
    from pyspark.sql import SparkSession
    base = os.environ.get("HOMEPEDIA_URL_LAC")
    if base:
        return SparkSession.builder.appName(nom).getOrCreate(), lambda chemin: f"{base.rstrip('/')}/{chemin}"
    try:
        from forepaas.dwh import connect
    except ImportError:
        from pathlib import Path
        racine = Path(os.environ.get("HOMEPEDIA_LAC", Path(__file__).resolve().parents[2] / "data" / "lac"))
        spark = SparkSession.builder.appName(nom).master("local[*]").getOrCreate()
        return spark, lambda chemin: str(racine / chemin)
    cn = connect(f"dwh/{os.environ.get('HOMEPEDIA_SOURCE', 'homepedia')}/")
    bucket = os.environ.get("HOMEPEDIA_BUCKET", "homepedia")

    def url(chemin):
        dossier, _, fichier = chemin.rpartition("/")
        return cn.get_spark_url(dossier, fichier, bucket=bucket)
    return cn.get_spark_session(), url


def journal(message):
    print(f"[{ETAPE}] {message}", flush=True)
# ---------------------------------------------------------------------------------------------------------------


def controles_argent(spark, url):
    argent = spark.read.parquet(url("argent/dvf"))
    par_annee = {r.annee: r for r in argent.groupBy("annee").agg(
        F.count(F.lit(1)).alias("ventes"), F.countDistinct("cle_mutation").alias("cles"),
        F.sum("nb_lignes_source").alias("lignes"),
        F.sum(F.col("hors_marche").isNull().cast("int")).alias("sans_marque")).collect()}
    resultats = []
    for annee in ANNEES:
        r = par_annee.get(annee)
        lignes_bronze = spark.read.csv(url(f"bronze/dvf/{annee}.csv.gz"), header=True).count()
        resultats += [
            (f"argent {annee} : ventes présentes", r is not None and r.ventes > 0, f"{r.ventes if r else 0} ventes"),
            (f"argent {annee} : aucune ligne perdue (lignes regroupées = lignes bronze)",
             r is not None and r.lignes == lignes_bronze, f"{r.lignes if r else 0} / {lignes_bronze}"),
            (f"argent {annee} : une ligne par vente", r is not None and r.ventes == r.cles,
             f"{r.ventes if r else 0} lignes, {r.cles if r else 0} ventes distinctes"),
            (f"argent {annee} : qualité marquée sur chaque vente", r is not None and r.sans_marque == 0,
             f"{r.sans_marque if r else '?'} sans marque"),
        ]
    return resultats


def controles_or(spark, url):
    ind = spark.read.csv(url("or/indicateurs_prix"), header=True, inferSchema=True)
    lots = [r._batch_id for r in ind.select("_batch_id").distinct().collect()]
    periodes = sorted(r.periode for r in ind.select("periode").distinct().collect())
    par_niveau = (ind.filter(F.col("type_local") == "Tous").groupBy("periode", "niveau_geo")
                  .agg(F.sum("nb_ventes").alias("ventes")).groupBy("periode")
                  .agg(F.countDistinct("ventes").alias("totaux_distincts")).collect())
    hors_ordre = ind.filter(~((F.col("prix_m2_d1") <= F.col("prix_m2_q1")) & (F.col("prix_m2_q1") <= F.col("prix_m2_median"))
                              & (F.col("prix_m2_median") <= F.col("prix_m2_q3")) & (F.col("prix_m2_q3") <= F.col("prix_m2_d9")))).count()
    hors_bornes = ind.filter(~F.col("prix_m2_median").between(PRIX_M2_MIN, PRIX_M2_MAX)).count()
    paris6 = ind.filter((F.col("niveau_geo") == "commune") & (F.col("code_geo").cast("string") == "75106")
                        & (F.col("type_local") == "Appartement") & (F.col("periode") == max(ANNEES))).first()
    return lots, [
        ("or : un seul lot", len(lots) == 1, ", ".join(map(str, lots))),
        ("or : une série par année DVF", periodes == ANNEES, str(periodes)),
        ("or : même nombre de ventes aux échelles commune, département, région",
         bool(par_niveau) and all(r.totaux_distincts == 1 for r in par_niveau), f"{len(par_niveau)} années"),
        ("or : déciles et quartiles ordonnés (D1 ≤ Q1 ≤ médiane ≤ Q3 ≤ D9)", hors_ordre == 0, f"{hors_ordre} zones hors ordre"),
        (f"or : médianes entre {PRIX_M2_MIN} et {PRIX_M2_MAX} €/m²", hors_bornes == 0, f"{hors_bornes} hors bornes"),
        (f"or : repère Paris 6e appartements {max(ANNEES)} entre 10 000 et 20 000 €/m²",
         paris6 is not None and 10_000 <= paris6.prix_m2_median <= 20_000,
         f"{paris6.prix_m2_median:.0f} €/m²" if paris6 else "absent"),
    ]


def executer():
    spark, url = contexte(ETAPE)
    resultats = controles_argent(spark, url)
    lots, resultats_or = controles_or(spark, url)
    resultats += resultats_or
    for nom, ok, detail in resultats:
        journal(f"{'PASS' if ok else 'FAIL'}  {nom}  ({detail})")
    lot = lots[0] if len(lots) == 1 else "incoherent"
    rapport = spark.createDataFrame([(nom, bool(ok), str(detail), lot) for nom, ok, detail in resultats],
                                    "controle string, ok boolean, detail string, _batch_id string")
    rapport.coalesce(1).write.mode("overwrite").option("header", True).csv(url("or/controles"))
    echecs = [nom for nom, ok, _ in resultats if not ok]
    journal(f"{'FAIL' if echecs else 'PASS'} — {len(resultats) - len(echecs)}/{len(resultats)} contrôles OK (lot or {lot})")
    if echecs:
        raise RuntimeError(f"{len(echecs)} contrôle(s) en échec : {'; '.join(echecs)}")


def customfunc(event=None):
    """Point d'entrée d'une action Custom PySpark d'OVHcloud Data Platform."""
    executer()


if __name__ == "__main__":
    executer()
