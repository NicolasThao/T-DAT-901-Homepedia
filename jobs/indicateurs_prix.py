"""
Job Spark local — indicateurs de prix par commune, département et région (DVF), pour la carte.

Lit `mutation_dvf` dans PostgreSQL (JDBC, lecture répartie sur plusieurs partitions),
agrège avec Spark et réécrit la table `indicateurs_prix` (vidée puis remplie : rejouable).

Le filtre des ventes retenues et le calcul des indicateurs sont ceux du pipeline OVHcloud
(pipelines/prix/argent_vers_or.py, importé ici) : une seule logique, deux exécutions possibles.
Version OVHcloud : db/ovh.py recuperer charge le même résultat calculé sur Data Platform.

Usage (venv Spark) : bootstrap/.venv/Scripts/python jobs/indicateurs_prix.py
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "bootstrap"))
sys.path.insert(0, str(RACINE / "pipelines" / "prix"))

from datetime import datetime, timezone  # noqa: E402

from pyspark.sql import functions as F  # noqa: E402
from spark_session import get_spark_session  # noqa: E402
from argent_vers_or import agreger, ventes_retenues  # noqa: E402

# Driver JDBC PostgreSQL, téléchargé une fois depuis Maven Central dans jobs/lib/ (ignoré par git)
DRIVER_URL = "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar"
DRIVER_JAR = RACINE / "jobs" / "lib" / "postgresql-42.7.4.jar"
SOURCE = "dvf"

# Mutations + rattachement géographique, lus en une requête (la jointure se fait dans Postgres)
REQUETE_MUTATIONS = """
    SELECT m.id, m.date_mutation, m.type_local, m.nb_logements, m.hors_marche,
           m.prix_m2_douteux, m.prix_m2::float8 AS prix_m2,
           m.valeur_fonciere::float8 AS valeur_fonciere, m.surface_bati_m2::float8 AS surface_bati_m2,
           m.code_insee, c.code_departement, d.code_region
    FROM mutation_dvf m
    JOIN commune c ON c.code_insee = m.code_insee
    JOIN departement d ON d.code_departement = c.code_departement
"""


def driver_postgres():
    """Chemin du jar JDBC ; téléchargé et vérifié (SHA-1 publié par Maven Central) s'il manque."""
    if not DRIVER_JAR.exists():
        DRIVER_JAR.parent.mkdir(parents=True, exist_ok=True)
        contenu = urllib.request.urlopen(DRIVER_URL, timeout=60).read()
        attendu = urllib.request.urlopen(DRIVER_URL + ".sha1", timeout=60).read().decode().split()[0]
        if hashlib.sha1(contenu).hexdigest() != attendu:
            raise SystemExit(f"SHA-1 du driver JDBC incorrect, téléchargement refusé : {DRIVER_URL}")
        DRIVER_JAR.write_bytes(contenu)
    return DRIVER_JAR


def lire_env():
    lignes = (RACINE / "db" / ".env").read_text(encoding="utf-8").splitlines()
    return dict(l.split("=", 1) for l in lignes if l.strip() and not l.startswith("#"))


def options_jdbc(env):
    return {
        "url": f"jdbc:postgresql://127.0.0.1:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}",
        "user": env["POSTGRES_USER"],
        "password": env["POSTGRES_PASSWORD"],
        "driver": "org.postgresql.Driver",
    }


def mutations(spark, jdbc):
    # Lecture découpée en 8 partitions sur l'id : Spark lit et traite en parallèle
    bornes = (spark.read.format("jdbc").options(**jdbc)
              .option("query", "SELECT min(id) AS lo, max(id) AS hi FROM mutation_dvf").load().first())
    return (spark.read.format("jdbc").options(**jdbc)
            .option("dbtable", f"({REQUETE_MUTATIONS}) AS m")
            .option("partitionColumn", "id").option("lowerBound", bornes.lo)
            .option("upperBound", bornes.hi + 1).option("numPartitions", 8)
            .load())


def main():
    spark = get_spark_session("indicateurs-prix", jars=[driver_postgres()])
    spark.sparkContext.setLogLevel("ERROR")
    jdbc = options_jdbc(lire_env())

    lot = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    indicateurs = (agreger(ventes_retenues(mutations(spark, jdbc)))
                   .withColumn("_source", F.lit(SOURCE)).withColumn("_date_ingestion", F.current_timestamp())
                   .withColumn("_batch_id", F.lit(lot)).cache())
    # truncate : la table (clé primaire, contraintes) est gardée, seules les lignes sont remplacées
    (indicateurs.write.format("jdbc").options(**jdbc).option("dbtable", "indicateurs_prix")
     .option("truncate", "true").mode("overwrite").save())

    for ligne in indicateurs.groupBy("niveau_geo").agg(
            F.count("*").alias("lignes"), F.sum("nb_ventes").alias("ventes")).orderBy("niveau_geo").collect():
        print(f"{ligne.niveau_geo:12} {ligne.lignes:6} lignes, {ligne.ventes} ventes (types + « Tous »)")
    spark.stop()


if __name__ == "__main__":
    main()
