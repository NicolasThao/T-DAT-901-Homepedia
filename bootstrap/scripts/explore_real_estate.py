import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from spark_session import get_spark_session
from pyspark.sql import functions as F

spark = get_spark_session("explore-real-estate")

csv_path = os.path.join(BOOTSTRAP_DIR, "data", "france_total_real_estate_sales_2022.csv")
df = spark.read.csv(csv_path, header=True, sep=",", quote='"', encoding="UTF-8")

print("ROWS", df.count())
print("SCHEMA")
df.printSchema()

print("DISTINCT Type local")
df.select("Type local").distinct().show(20, truncate=False)

print("DISTINCT Code departement (sample 120)")
df.select("Code departement").distinct().orderBy("Code departement").show(120, truncate=False)

print("SAMPLE Valeur fonciere / Surface reelle bati")
df.select("Valeur fonciere", "Surface reelle bati", "Type local").show(10, truncate=False)

spark.stop()
