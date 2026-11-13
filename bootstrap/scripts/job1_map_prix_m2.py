"""
Exercice bootstrap (exo.md) - Map : prix au m2 pour chaque vente de type
appartement ou maison, sur france_total_real_estate_sales_2022.

Le calcul est fait avec la transformation RDD map() : chaque ligne donne
exactement une ligne en sortie (transformation 1 -> 1, etroite, sans shuffle).

Limite assumee : le map travaille ligne a ligne, or une ligne est un LOT, pas
une vente. Quand un acte contient plusieurs lots, la valeur de l'acte entier
est divisee par la surface d'un seul lot -> prix_m2 aberrants (jusqu'a
plusieurs M euros/m2). Le job 3 corrige cela en regroupant d'abord par mutation.
"""

import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from dvf import PROCESSED_DIR, lire_dvf, lignes_logement
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType
from spark_session import get_spark_session

spark = get_spark_session("job1-map-prix-m2")

logements = lignes_logement(spark)
ventes_valides = logements.filter(F.col("surface_bati") > 0)


# Mutations  pour identifactions

# ajouter date de vente

colonnes = ["code_departement", "commune", "type_local", "valeur_fonciere", "surface_bati"]
rdd_ventes = ventes_valides.select(*colonnes).rdd

# --- Map : (dept, commune, type, valeur, surface) -> meme tuple + prix au m2 ---
rdd_prix_m2 = rdd_ventes.map(lambda r: (r[0], r[1], r[2], r[3], r[4], round(r[3] / r[4], 2)))

# Schema explicite : sans lui, toDF() lance un take(1) pour deviner les types, qui coupe
# le worker Python en cours de lecture et le fait planter sous Windows.
schema = StructType([
    StructField("code_departement", StringType()),
    StructField("commune", StringType()),
    StructField("type_local", StringType()),
    StructField("valeur_fonciere", DoubleType()),
    StructField("surface_bati", DoubleType()),
    StructField("prix_m2", DoubleType()),
])
ventes_prix_m2 = rdd_prix_m2.toDF(schema)

total = lire_dvf(spark).count()
appart_maison = logements.count()
valides = ventes_valides.count()

print("LIGNES TOTALES", total)
print("LIGNES APPARTEMENT/MAISON (valeur renseignee)", appart_maison)
print("LIGNES VALIDES (surface > 0)", valides)
print("EXCLUES (surface nulle ou absente)", appart_maison - valides)

print("ECHANTILLON")
ventes_prix_m2.orderBy(F.rand(seed=42)).show(15, truncate=False)

print("STATS prix_m2")
ventes_prix_m2.describe("prix_m2").show()

out_path = os.path.join(PROCESSED_DIR, "ventes_prix_m2.csv")
os.makedirs(PROCESSED_DIR, exist_ok=True)
ventes_prix_m2.toPandas().to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
