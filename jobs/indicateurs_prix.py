"""
Job Spark — prix au m² médian par commune, département et région (DVF), pour la carte.

Lit `mutation_dvf` dans PostgreSQL (JDBC, lecture répartie sur plusieurs partitions),
agrège avec Spark et réécrit la table `indicateurs_prix` (vidée puis remplie : rejouable).

Périmètre d'une vente retenue (le même filtre est recalculé en SQL par db/check.py) :
  - vente « de marché » : hors_marche = false (Vente ou VEFA) ;
  - un seul logement dans l'acte (nb_logements = 1), Maison ou Appartement ;
  - prix/m² fiable : prix_m2_douteux = false, et entre 200 et 30 000 €/m².
Médiane exacte (`percentile(..., 0.5)`, interpolation linéaire, comme percentile_cont en SQL).

Usage (venv Spark) : bootstrap/.venv/Scripts/python jobs/indicateurs_prix.py
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "bootstrap"))

from pyspark.sql import functions as F  # noqa: E402
from spark_session import get_spark_session  # noqa: E402

# Driver JDBC PostgreSQL, téléchargé une fois depuis Maven Central dans jobs/lib/ (ignoré par git)
DRIVER_URL = "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar"
DRIVER_JAR = RACINE / "jobs" / "lib" / "postgresql-42.7.4.jar"
PRIX_M2_MIN, PRIX_M2_MAX = 200, 30_000
SOURCE = "dvf"

# Mutations + rattachement géographique, lus en une requête (la jointure se fait dans Postgres)
REQUETE_MUTATIONS = """
    SELECT m.id, m.date_mutation, m.type_local, m.nb_logements, m.hors_marche,
           m.prix_m2_douteux, m.prix_m2::float8 AS prix_m2,
           m.code_insee, c.code_departement, d.code_region
    FROM mutation_dvf m
    JOIN commune c ON c.code_insee = m.code_insee
    JOIN departement d ON d.code_departement = c.code_departement
"""

NIVEAUX = {"commune": "code_insee", "departement": "code_departement", "region": "code_region"}


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


def ventes_retenues(spark, jdbc):
    # Lecture découpée en 8 partitions sur l'id : Spark lit et traite en parallèle
    bornes = (spark.read.format("jdbc").options(**jdbc)
              .option("query", "SELECT min(id) AS lo, max(id) AS hi FROM mutation_dvf").load().first())
    mutations = (spark.read.format("jdbc").options(**jdbc)
                 .option("dbtable", f"({REQUETE_MUTATIONS}) AS m")
                 .option("partitionColumn", "id").option("lowerBound", bornes.lo)
                 .option("upperBound", bornes.hi + 1).option("numPartitions", 8)
                 .load())
    return mutations.filter(
        ~F.col("hors_marche") & ~F.col("prix_m2_douteux")
        & (F.col("nb_logements") == 1)
        & F.col("type_local").isin("Maison", "Appartement")
        & F.col("prix_m2").between(PRIX_M2_MIN, PRIX_M2_MAX)
    ).withColumn("periode", F.year("date_mutation"))


def agreger(ventes):
    # Chaque vente compte pour son type (Maison / Appartement) et pour « Tous »
    ventes = ventes.withColumn("type_local", F.explode(F.array(F.col("type_local"), F.lit("Tous"))))
    resultats = None
    for niveau, colonne in NIVEAUX.items():
        r = (ventes.groupBy(F.col(colonne).alias("code_geo"), "type_local", "periode")
             .agg(F.expr("percentile(prix_m2, 0.5)").alias("prix_m2_median"),
                  F.count("*").cast("int").alias("nb_ventes"))
             .withColumn("niveau_geo", F.lit(niveau)))
        resultats = r if resultats is None else resultats.unionByName(r)
    return resultats.select(
        "niveau_geo", "code_geo", "type_local", "periode", "prix_m2_median", "nb_ventes",
        F.lit(SOURCE).alias("_source"), F.current_timestamp().alias("_date_ingestion"),
    )


def main():
    spark = get_spark_session("indicateurs-prix", jars=[driver_postgres()])
    spark.sparkContext.setLogLevel("ERROR")
    jdbc = options_jdbc(lire_env())

    indicateurs = agreger(ventes_retenues(spark, jdbc)).cache()
    # truncate : la table (clé primaire, contraintes) est gardée, seules les lignes sont remplacées
    (indicateurs.write.format("jdbc").options(**jdbc).option("dbtable", "indicateurs_prix")
     .option("truncate", "true").mode("overwrite").save())

    for ligne in indicateurs.groupBy("niveau_geo").agg(
            F.count("*").alias("lignes"), F.sum("nb_ventes").alias("ventes")).orderBy("niveau_geo").collect():
        print(f"{ligne.niveau_geo:12} {ligne.lignes:6} lignes, {ligne.ventes} ventes (types + « Tous »)")
    spark.stop()


if __name__ == "__main__":
    main()
