"""
Exercice bootstrap (exo.md) - Map : prix au m2 pour chaque vente de type
appartement ou maison, sur france_total_real_estate_sales_2022.

Colonne source cle "Valeur fonciere" au format francais ("55000,00") ->
convertie en double. Lignes exclues si Type local hors {Appartement,
Maison}, ou si valeur fonciere / surface reelle bati absente ou nulle.
"""

import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from spark_session import get_spark_session
from pyspark.sql import functions as F

spark = get_spark_session("job1-map-prix-m2")

csv_path = os.path.join(BOOTSTRAP_DIR, "data", "france_total_real_estate_sales_2022.csv")
df = spark.read.csv(csv_path, header=True, sep=",", quote='"', encoding="UTF-8")

df = df.withColumn(
    "valeur_fonciere", F.regexp_replace(F.col("Valeur fonciere"), ",", ".").cast("double")
).withColumn(
    "surface_bati", F.col("Surface reelle bati").cast("double")
)

ventes = df.filter(F.col("Type local").isin("Appartement", "Maison"))

ventes_valides = ventes.filter(
    F.col("valeur_fonciere").isNotNull()
    & F.col("surface_bati").isNotNull()
    & (F.col("surface_bati") > 0)
)

ventes_prix_m2 = ventes_valides.withColumn(
    "prix_m2", F.round(F.col("valeur_fonciere") / F.col("surface_bati"), 2)
).select(
    F.col("Code departement").alias("code_departement"),
    F.col("Commune").alias("commune"),
    F.col("Type local").alias("type_local"),
    "valeur_fonciere",
    "surface_bati",
    "prix_m2",
)

total = df.count()
appart_maison = ventes.count()
valides = ventes_valides.count()

print("LIGNES TOTALES", total)
print("VENTES APPARTEMENT/MAISON", appart_maison)
print("VENTES VALIDES (surface > 0, valeur/surface non nulles)", valides)
print("EXCLUES (surface nulle/0 ou valeur nulle)", appart_maison - valides)

print("ECHANTILLON")
ventes_prix_m2.orderBy(F.rand(seed=42)).show(15, truncate=False)

print("STATS prix_m2")
ventes_prix_m2.describe("prix_m2").show()

out_path = os.path.join(BOOTSTRAP_DIR, "data", "processed", "ventes_prix_m2.csv")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
ventes_prix_m2.toPandas().to_csv(out_path, index=False)
print("ECRIT", out_path)

spark.stop()
