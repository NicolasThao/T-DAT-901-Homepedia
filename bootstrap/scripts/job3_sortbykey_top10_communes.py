"""
Exercice bootstrap (exo.md) - SortByKey : 10 communes avec les prix les
plus eleves par departement, sur france_total_real_estate_sales_2022.

Choix methodologiques documentes (coherents avec les etapes 3-4) :
  - Meme perimetre que job1/job2 : Appartement/Maison, surface batie
    renseignee et > 0, mutations deduplipliquees (cf. job2 : ~19.6% de
    lignes en doublon sinon).
  - Indicateur de prix retenu = MEDIANE du prix au m2 par commune, pas
    la moyenne : l'etape 3 a mis en evidence des valeurs aberrantes
    (prix_m2 jusqu'a 46M euros/m2) qui feraient dominer un classement
    base sur une moyenne ou un max par quelques mutations corrompues.
    La mediane est la metrique standard des indicateurs immobiliers
    (ex. notaires-services.fr) pour cette raison.
  - Seuil minimum de 5 ventes par commune pour entrer dans le
    classement : evite qu'une commune avec 1 seule vente (donc 1 seule
    donnee, potentiellement une anomalie) ressorte en tete faute de
    volume. Seuil arbitraire mais documente, a ajuster si besoin.
"""

import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from spark_session import get_spark_session
from pyspark.sql import functions as F
from pyspark.sql.window import Window

MIN_VENTES_PAR_COMMUNE = 5
TOP_N = 10

spark = get_spark_session("job3-sortbykey-top10-communes")

csv_path = os.path.join(BOOTSTRAP_DIR, "data", "france_total_real_estate_sales_2022.csv")
df = spark.read.csv(csv_path, header=True, sep=",", quote='"', encoding="UTF-8")

df = df.withColumn(
    "valeur_fonciere", F.regexp_replace(F.col("Valeur fonciere"), ",", ".").cast("double")
).withColumn(
    "surface_bati", F.col("Surface reelle bati").cast("double")
)

ventes_valides = df.filter(
    F.col("Type local").isin("Appartement", "Maison")
    & F.col("valeur_fonciere").isNotNull()
    & F.col("surface_bati").isNotNull()
    & (F.col("surface_bati") > 0)
)

mutation_key_cols = ["Date mutation", "Code departement", "Code commune", "Section", "No plan", "valeur_fonciere"]
mutations_uniques = ventes_valides.dropDuplicates(mutation_key_cols).withColumn(
    "prix_m2", F.round(F.col("valeur_fonciere") / F.col("surface_bati"), 2)
)

par_commune = mutations_uniques.groupBy(
    F.col("Code departement").alias("code_departement"), F.col("Commune").alias("commune")
).agg(
    F.count("*").alias("nb_ventes"),
    F.round(F.expr("percentile_approx(prix_m2, 0.5)"), 2).alias("prix_m2_median"),
)

par_commune_filtre = par_commune.filter(F.col("nb_ventes") >= MIN_VENTES_PAR_COMMUNE)

print("COMMUNES AVANT FILTRE VOLUME", par_commune.count())
print(f"COMMUNES AVEC >= {MIN_VENTES_PAR_COMMUNE} VENTES", par_commune_filtre.count())

window_dept = Window.partitionBy("code_departement").orderBy(F.col("prix_m2_median").desc())
top10 = (
    par_commune_filtre.withColumn("rang", F.row_number().over(window_dept))
    .filter(F.col("rang") <= TOP_N)
)

# SortByKey (RDD) pour la sortie finale, triee par departement
rdd_top10 = top10.select("code_departement", "rang", "commune", "prix_m2_median", "nb_ventes").rdd.map(
    lambda r: (r[0], (r[1], r[2], r[3], r[4]))
)
resultat = rdd_top10.sortByKey().collect()

print("CODE_DEPT | RANG | COMMUNE | PRIX_M2_MEDIAN | NB_VENTES")
for dept, (rang, commune, prix, nb) in resultat:
    print(dept, rang, commune, prix, nb)

# Verification de coherence sur des departements connus pour leurs prix eleves
print("\nVERIFICATION - top 3 du departement 75 (Paris)")
for row in [r for r in resultat if r[0] == "75"][:3]:
    print(row)
print("VERIFICATION - top 3 du departement 06 (Alpes-Maritimes)")
for row in [r for r in resultat if r[0] == "6"][:3]:
    print(row)

out_path = os.path.join(BOOTSTRAP_DIR, "data", "processed", "top10_communes_par_departement.csv")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
import pandas as pd

pd.DataFrame(
    [(dept, rang, commune, prix, nb) for dept, (rang, commune, prix, nb) in resultat],
    columns=["code_departement", "rang", "commune", "prix_m2_median", "nb_ventes"],
).to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
