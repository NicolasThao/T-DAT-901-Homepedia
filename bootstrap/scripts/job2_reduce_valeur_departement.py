"""
Exercice bootstrap (exo.md) - ReduceByKey : calculer la valeur fonciere
par departement, sur france_total_real_estate_sales_2022.

Piege identifie a l'etape 3 (job1) : une meme mutation (transaction) peut
apparaitre sur plusieurs lignes du CSV quand elle porte sur plusieurs
lots (ex: maison + dependance + garage vendus ensemble), avec la MEME
"Valeur fonciere" repetee sur chaque ligne. Une somme naive par
Code departement compte donc cette valeur plusieurs fois.

Ce script produit les deux versions et les documente :
  - somme "brute" (chaque ligne comptee telle quelle) -> ce que
    l'exercice demande litteralement ("calculer la valeur fonciere
    par departement")
  - somme "dedupliquee" (1 ligne conservee par mutation, identifiee par
    Date mutation + Code departement + Code commune + Section + No plan
    + Valeur fonciere) -> version methodologiquement correcte, a
    retenir pour le Follow-up 1.

Perimetre : reprend le filtre de job1 (Type local in Appartement/
Maison, surface batie renseignee et > 0), pour rester coherent avec le
pipeline "marche du logement residentiel" de l'exercice.
"""

import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from spark_session import get_spark_session
from pyspark.sql import functions as F

spark = get_spark_session("job2-reduce-valeur-departement")

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

# --- Somme brute (litteralement ce que demande l'exercice) ---
rdd_brut = ventes_valides.select("Code departement", "valeur_fonciere").rdd.map(
    lambda row: (row[0], row[1])
)
valeur_brute_par_dept = rdd_brut.reduceByKey(lambda a, b: a + b)

# --- Somme dedupliquee (1 ligne par mutation) ---
mutation_key_cols = ["Date mutation", "Code departement", "Code commune", "Section", "No plan", "valeur_fonciere"]
mutations_uniques = ventes_valides.dropDuplicates(mutation_key_cols)

nb_lignes = ventes_valides.count()
nb_mutations = mutations_uniques.count()
print("LIGNES (ventes valides Appartement/Maison)", nb_lignes)
print("MUTATIONS UNIQUES APRES DEDUP", nb_mutations)
print("LIGNES EN DOUBLON (memes lots d'une meme mutation)", nb_lignes - nb_mutations)

rdd_dedup = mutations_uniques.select("Code departement", "valeur_fonciere").rdd.map(
    lambda row: (row[0], row[1])
)
valeur_dedup_par_dept = rdd_dedup.reduceByKey(lambda a, b: a + b)

# Chaque cote est petit (~100 departements) : on collecte separement puis on
# fusionne cote driver plutot que de faire un join RDD distribue (plus fragile
# sur de gros volumes en amont, cf. crash worker observe avec le join).
brut_dict = dict(valeur_brute_par_dept.collect())
dedup_dict = dict(valeur_dedup_par_dept.collect())

resultat_rows = sorted(
    (
        (dept, round(brut, 2), round(dedup_dict.get(dept, 0.0), 2), round(brut - dedup_dict.get(dept, 0.0), 2))
        for dept, brut in brut_dict.items()
    ),
    key=lambda r: r[0],
)

print("DEPARTEMENT | VALEUR_BRUTE | VALEUR_DEDUP | ECART")
for dept, brut, dedup, ecart in resultat_rows:
    print(dept, brut, dedup, ecart)

ecart_total = sum(r[3] for r in resultat_rows)
print("ECART TOTAL (brut - dedup), toute la France", round(ecart_total, 2))

out_path = os.path.join(BOOTSTRAP_DIR, "data", "processed", "valeur_fonciere_par_departement.csv")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
import pandas as pd

pd.DataFrame(
    resultat_rows, columns=["code_departement", "valeur_fonciere_brute", "valeur_fonciere_dedup", "ecart"]
).sort_values("code_departement").to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
