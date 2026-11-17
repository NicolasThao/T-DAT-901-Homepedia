"""
Lecture et nettoyage communs aux 3 jobs PySpark sur france_total_real_estate_sales_2022.

Une MUTATION (un acte de vente) apparait sur plusieurs lignes du CSV quand elle porte
sur plusieurs lots ou plusieurs parcelles, avec la MEME "Valeur fonciere" repetee sur
chaque ligne. Cle d'une mutation = date + code INSEE commune + nature + valeur (le CSV du
bootstrap n'a pas d'identifiant de vente ; la base, elle, charge DVF Etalab avec id_mutation,
cf. db/load_dvf.py). (La premiere version du Follow-up 1 ajoutait section + n° de
plan : cela coupait en plusieurs morceaux les actes qui portent sur plusieurs parcelles.)
"""

import os

from pyspark.sql import functions as F

BOOTSTRAP_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BOOTSTRAP_DIR, "data", "france_total_real_estate_sales_2022.csv")
PROCESSED_DIR = os.path.join(BOOTSTRAP_DIR, "data", "processed")


def completer(col, n):
    """Zeros a gauche jusqu'a n caracteres. F.lpad seul TRONQUE les chaines plus longues ("972" -> "97")."""
    return F.when(F.length(col) < n, F.lpad(col, n, "0")).otherwise(col)


def lire_dvf(spark):
    """Toutes les lignes du CSV, colonnes typees et normalisees."""
    df = spark.read.csv(CSV_PATH, header=True, sep=",", quote='"', encoding="UTF-8")

    # "Code departement" est lu tel quel ("1", "75", "2A", "971") : on le complete sur
    # 2 caracteres pour que le tri par cle (sortByKey) donne 01, 02 ... 95, 971.
    dep = completer(F.col("Code departement"), 2)
    com = completer(F.col("Code commune"), 3)
    # DOM : departement sur 3 caracteres (971) + 2 derniers chiffres de la commune -> 97101
    code_insee = F.when(F.length(dep) == 3, F.concat(dep, F.substring(com, 2, 2))).otherwise(F.concat(dep, com))
    valeur = F.regexp_replace(F.col("Valeur fonciere"), ",", ".")

    return df.select(
        F.concat_ws("|", F.col("Date mutation"), code_insee, F.col("Nature mutation"), valeur).alias("cle_mutation"),
        F.col("Nature mutation").alias("nature_mutation"),
        dep.alias("code_departement"),
        code_insee.alias("code_insee"),
        F.col("Commune").alias("commune"),
        F.col("Type local").alias("type_local"),
        valeur.cast("double").alias("valeur_fonciere"),
        F.col("Surface reelle bati").cast("double").alias("surface_bati"),
    )


def lignes_logement(spark):
    """Lignes Appartement / Maison avec une valeur fonciere renseignee."""
    return lire_dvf(spark).filter(
        F.col("type_local").isin("Appartement", "Maison") & F.col("valeur_fonciere").isNotNull()
    )
