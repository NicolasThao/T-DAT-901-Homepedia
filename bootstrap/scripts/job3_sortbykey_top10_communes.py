"""
Exercice bootstrap (exo.md) - SortByKey : 10 communes avec les prix les
plus eleves par departement, sur france_total_real_estate_sales_2022.

Choix methodologiques :
  - Prix au m2 calcule PAR MUTATION, pas par ligne : on regroupe les lignes
    d'un meme acte (cle de mutation, cf. dvf.py), puis on ne garde que les
    ventes (nature "Vente") d'UN SEUL logement. Un acte de 3 appartements
    n'a pas de prix au m2 interpretable, et c'etait la source des prix_m2
    aberrants du job 1. Meme regle que l'index partiel de db/postgres/schema.sql.
  - Indicateur = MEDIANE du prix au m2 par commune, pas la moyenne : robuste
    aux valeurs aberrantes restantes (c'est aussi l'indicateur des notaires).
  - Seuil minimum de 5 ventes par commune pour entrer au classement : evite
    qu'une commune a 1 vente ressorte en tete faute de volume.
  - Commune identifiee par son code INSEE (les arrondissements de Paris, Lyon,
    Marseille sont des codes distincts dans DVF : 75106, 69381, 13201...).
"""

import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

import pandas as pd
from dvf import PROCESSED_DIR, lignes_logement
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from spark_session import get_spark_session

MIN_VENTES_PAR_COMMUNE = 5
TOP_N = 10

spark = get_spark_session("job3-sortbykey-top10-communes")

# --- 1 ligne par mutation : nombre de logements et surface batie totale de l'acte ---
mutations = (
    lignes_logement(spark)
    .filter(F.col("nature_mutation") == "Vente")
    .groupBy("cle_mutation")
    .agg(
        F.first("code_departement").alias("code_departement"),
        F.first("code_insee").alias("code_insee"),
        F.first("commune").alias("commune"),
        F.first("valeur_fonciere").alias("valeur_fonciere"),
        F.count("*").alias("nb_logements"),
        F.sum("surface_bati").alias("surface_bati"),
    )
)

ventes_1_logement = mutations.filter(
    (F.col("nb_logements") == 1) & (F.col("surface_bati") > 0)
).withColumn("prix_m2", F.col("valeur_fonciere") / F.col("surface_bati"))

par_commune = ventes_1_logement.groupBy("code_departement", "code_insee").agg(
    F.first("commune").alias("commune"),
    F.count("*").alias("nb_ventes"),
    F.round(F.expr("percentile_approx(prix_m2, 0.5)"), 2).alias("prix_m2_median"),
)
par_commune_filtre = par_commune.filter(F.col("nb_ventes") >= MIN_VENTES_PAR_COMMUNE)

print("MUTATIONS 'Vente' AVEC AU MOINS UN LOGEMENT", mutations.count())
print("VENTES D'UN SEUL LOGEMENT (surface > 0)", ventes_1_logement.count())
print("COMMUNES AVANT FILTRE VOLUME", par_commune.count())
print(f"COMMUNES AVEC >= {MIN_VENTES_PAR_COMMUNE} VENTES", par_commune_filtre.count())

# Top N par departement : fonction de fenetre (classement a l'interieur de chaque departement)
window_dept = Window.partitionBy("code_departement").orderBy(F.col("prix_m2_median").desc())
top10 = par_commune_filtre.withColumn("rang", F.row_number().over(window_dept)).filter(F.col("rang") <= TOP_N)

# SortByKey (RDD) : paires (code_departement, ...) triees par departement.
# Les codes sont sur 2-3 caracteres (dvf.py), donc l'ordre alphabetique est le bon :
# 01 < 02 < ... < 29 < 2A < 2B < 30 < ... < 95 < 971
rdd_top10 = top10.select("code_departement", "rang", "code_insee", "commune", "prix_m2_median", "nb_ventes").rdd.map(
    lambda r: (r[0], (r[1], r[2], r[3], r[4], r[5]))
)
resultat = rdd_top10.sortByKey().collect()

print("CODE_DEPT | RANG | CODE_INSEE | COMMUNE | PRIX_M2_MEDIAN | NB_VENTES")
for dept, (rang, code_insee, commune, prix, nb) in resultat:
    print(dept, rang, code_insee, commune, prix, nb)

# Verification de coherence sur des departements connus pour leurs prix eleves
for dept, nom in [("75", "Paris"), ("06", "Alpes-Maritimes")]:
    print(f"\nVERIFICATION - top 3 du departement {dept} ({nom})")
    for row in [r for r in resultat if r[0] == dept][:3]:
        print(row)

out_path = os.path.join(PROCESSED_DIR, "top10_communes_par_departement.csv")
os.makedirs(PROCESSED_DIR, exist_ok=True)
pd.DataFrame(
    [(dept, *valeurs) for dept, valeurs in resultat],
    columns=["code_departement", "rang", "code_insee", "commune", "prix_m2_median", "nb_ventes"],
).to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
