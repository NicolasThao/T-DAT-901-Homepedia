"""
Exercice bootstrap (exo.md) - ReduceByKey : calculer la valeur fonciere
par departement, sur france_total_real_estate_sales_2022.

Piege : une meme mutation (acte de vente) apparait sur plusieurs lignes du
CSV quand elle porte sur plusieurs lots ou parcelles, avec la MEME "Valeur
fonciere" repetee sur chaque ligne. Une somme naive par departement compte
donc cette valeur plusieurs fois.

Ce script produit les deux versions, entierement en RDD :
  - somme "brute" : (dept, valeur) -> reduceByKey(+)
    = lecture litterale de l'exercice
  - somme "dedupliquee" : (cle_mutation, (dept, valeur)) -> reduceByKey qui
    garde une seule valeur par mutation -> (dept, valeur) -> reduceByKey(+)
    = version a retenir pour Homepedia

Perimetre : Type local in Appartement/Maison, surface batie > 0 (identique au job 1).
Cle de mutation : cf. dvf.py (date + code INSEE + nature + valeur).
"""

import os
import sys
from operator import add

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

import pandas as pd
from dvf import PROCESSED_DIR, lignes_logement
from pyspark.sql import functions as F
from spark_session import get_spark_session

spark = get_spark_session("job2-reduce-valeur-departement")

ventes_valides = lignes_logement(spark).filter(F.col("surface_bati") > 0)

# (cle_mutation, code_departement, valeur_fonciere), reutilise par les deux calculs
lignes = ventes_valides.select("cle_mutation", "code_departement", "valeur_fonciere").rdd.cache()

# --- Somme brute ---
valeur_brute_par_dept = lignes.map(lambda r: (r[1], r[2])).reduceByKey(add)

# --- Somme dedupliquee : une seule ligne conservee par mutation ---
mutations = lignes.map(lambda r: (r[0], (r[1], r[2]))).reduceByKey(lambda a, b: a)
valeur_dedup_par_dept = mutations.map(lambda kv: kv[1]).reduceByKey(add)

nb_lignes = lignes.count()
nb_mutations = mutations.count()
print("LIGNES (ventes valides Appartement/Maison)", nb_lignes)
print("MUTATIONS UNIQUES", nb_mutations)
print("LIGNES EN DOUBLON (autres lots d'une meme mutation)", nb_lignes - nb_mutations,
      f"({(nb_lignes - nb_mutations) / nb_lignes:.1%})")

# Chaque cote est petit (~100 departements) : on collecte separement puis on
# fusionne cote driver plutot que de faire un join RDD distribue.
brut_dict = dict(valeur_brute_par_dept.collect())
dedup_dict = dict(valeur_dedup_par_dept.collect())

resultat_rows = sorted(
    (dept, round(brut, 2), round(dedup_dict[dept], 2), round(brut - dedup_dict[dept], 2))
    for dept, brut in brut_dict.items()
)

print("DEPARTEMENT | VALEUR_BRUTE | VALEUR_DEDUP | ECART")
for dept, brut, dedup, ecart in resultat_rows:
    print(dept, brut, dedup, ecart)

total_brut = sum(r[1] for r in resultat_rows)
total_dedup = sum(r[2] for r in resultat_rows)
print("TOTAL BRUT", round(total_brut, 2))
print("TOTAL DEDUP", round(total_dedup, 2))
print("ECART TOTAL (brut - dedup), toute la France", round(total_brut - total_dedup, 2))

out_path = os.path.join(PROCESSED_DIR, "valeur_fonciere_par_departement.csv")
os.makedirs(PROCESSED_DIR, exist_ok=True)
pd.DataFrame(
    resultat_rows, columns=["code_departement", "valeur_fonciere_brute", "valeur_fonciere_dedup", "ecart"]
).to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
