"""
Contrôle de parité (local, pas une action OVH) : la couche argent produite par Spark (bronze_vers_argent.py)
est-elle identique, vente par vente, à mutation_dvf chargée en SQL par db/load_dvf.py ?

Compare chaque colonne pour chaque id_mutation ; PASS si aucune différence. À lancer dans le conteneur Spark,
la base locale étant joignable depuis le conteneur (cf. docs/deploiement_ovh.md, section 5) :
  spark-submit --jars jobs/lib/postgresql-42.7.4.jar pipelines/prix/parite_argent.py
"""

import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

RACINE = Path(__file__).resolve().parents[2]
LAC = Path(os.environ.get("HOMEPEDIA_LAC", RACINE / "data" / "lac"))
HOTE = os.environ.get("HOMEPEDIA_PG_HOTE", "host.docker.internal")
EXACTES = ["date_mutation", "nature_mutation", "valeur_fonciere", "code_insee_source", "code_insee", "type_local",
           "nb_logements", "surface_bati_m2", "nb_pieces", "surface_terrain_m2", "nb_lignes_source", "nb_adresses",
           "prix_m2", "hors_marche", "prix_m2_douteux"]
REQUETE = """SELECT id, cle_mutation, extract(year FROM date_mutation)::int AS annee, date_mutation, nature_mutation,
                    valeur_fonciere, code_insee_source::text AS code_insee_source, code_insee::text AS code_insee,
                    type_local, nb_logements, surface_bati_m2, nb_pieces, surface_terrain_m2, nb_lignes_source,
                    nb_adresses, prix_m2, hors_marche, prix_m2_douteux,
                    ST_X(position) AS longitude, ST_Y(position) AS latitude
             FROM mutation_dvf"""


def main():
    env = dict(l.split("=", 1) for l in (RACINE / "db" / ".env").read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.startswith("#"))
    spark = SparkSession.builder.appName("parite-argent").master("local[*]").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    # Lecture découpée en 16 tranches d'id (connexions courtes, en parallèle)
    proprietes = {"user": env["POSTGRES_USER"], "password": env["POSTGRES_PASSWORD"],
                  "driver": "org.postgresql.Driver", "fetchsize": "20000"}
    url_pg = f"jdbc:postgresql://{HOTE}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}"
    sql = spark.read.jdbc(url_pg, f"({REQUETE}) AS m", predicates=[f"mod(id, 16) = {i}" for i in range(16)],
                          properties=proprietes).drop("id")
    argent = spark.read.parquet(str(LAC / "argent" / "dvf"))

    a = argent.select("cle_mutation", "annee", *[F.col(c).alias(f"a_{c}") for c in EXACTES + ["longitude", "latitude"]])
    s = sql.select("cle_mutation", "annee", *[F.col(c).alias(f"s_{c}") for c in EXACTES + ["longitude", "latitude"]])
    j = a.join(s, ["cle_mutation", "annee"], "full_outer")
    diff = [F.sum(F.col("a_date_mutation").isNull().cast("int")).alias("absentes_spark"),
            F.sum(F.col("s_date_mutation").isNull().cast("int")).alias("en_trop_spark")]
    for c in EXACTES:
        diff.append(F.sum((~F.col(f"a_{c}").eqNullSafe(F.col(f"s_{c}"))
                           & F.col("a_date_mutation").isNotNull() & F.col("s_date_mutation").isNotNull())
                          .cast("int")).alias(c))
    for c in ("longitude", "latitude"):
        ecart = F.abs(F.col(f"a_{c}") - F.col(f"s_{c}"))
        diff.append(F.sum((F.coalesce(ecart, F.lit(0.0)) > 1e-6).cast("int")
                          + (F.col(f"a_{c}").isNull() != F.col(f"s_{c}").isNull()).cast("int")).alias(c))
    r = j.groupBy("annee").agg(F.count(F.lit(1)).alias("ventes"), *diff).orderBy("annee").collect()

    echecs = 0
    for ligne in r:
        ecarts = {k: v for k, v in ligne.asDict().items() if k not in ("annee", "ventes") and v}
        echecs += bool(ecarts)
        print(f"{'PASS' if not ecarts else 'FAIL'}  {ligne.annee} : {ligne.ventes} ventes, écarts {ecarts or 'aucun'}")
    if echecs:
        # Exemples pour diagnostiquer la première colonne en écart
        for c in EXACTES:
            ex = j.filter(~F.col(f"a_{c}").eqNullSafe(F.col(f"s_{c}"))
                          & F.col("a_date_mutation").isNotNull() & F.col("s_date_mutation").isNotNull()).limit(3)
            if ex.count():
                ex.select("cle_mutation", f"a_{c}", f"s_{c}").show(truncate=False)
    print(f"\n{'FAIL' if echecs else 'PASS'} — parité argent Spark = mutation_dvf SQL")
    spark.stop()
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
