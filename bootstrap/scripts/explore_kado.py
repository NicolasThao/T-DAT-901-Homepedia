import os
import sys

BOOTSTRAP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOOTSTRAP_DIR)

from spark_session import get_spark_session
from pyspark.sql import functions as F

spark = get_spark_session("explore-kado")
df = spark.read.csv(os.path.join(BOOTSTRAP_DIR, "data", "KaDo.csv"), header=True, inferSchema=True)

print("ROWS", df.count())
print("SCHEMA")
df.printSchema()

print("DISTINCT MOIS_VENTE", df.select("MOIS_VENTE").distinct().count())
df.select("MOIS_VENTE").distinct().orderBy("MOIS_VENTE").show(20)

print("DISTINCT TICKET_ID", df.select("TICKET_ID").distinct().count())
print("DISTINCT CLI_ID", df.select("CLI_ID").distinct().count())
print("DISTINCT FAMILLE", df.select("FAMILLE").distinct().count())
print("DISTINCT UNIVERS", df.select("UNIVERS").distinct().count())
print("DISTINCT MAILLE", df.select("MAILLE").distinct().count())
print("DISTINCT LIBELLE", df.select("LIBELLE").distinct().count())

ticket_client = df.groupBy("TICKET_ID").agg(F.countDistinct("CLI_ID").alias("nb_clients"))
print("TICKETS WITH >1 CLIENT", ticket_client.filter(F.col("nb_clients") > 1).count())

prod_hier = df.groupBy("LIBELLE").agg(F.countDistinct("FAMILLE", "UNIVERS", "MAILLE").alias("nb_hier"))
print("PRODUITS WITH >1 HIERARCHIE", prod_hier.filter(F.col("nb_hier") > 1).count())

univ_fam = df.groupBy("UNIVERS").agg(F.countDistinct("FAMILLE").alias("nb_fam"))
print("UNIVERS WITH >1 FAMILLE", univ_fam.filter(F.col("nb_fam") > 1).count())

maille_univ = df.groupBy("MAILLE").agg(F.countDistinct("UNIVERS").alias("nb_univ"))
print("MAILLE WITH >1 UNIVERS", maille_univ.filter(F.col("nb_univ") > 1).count())

for c in df.columns:
    n = df.filter(F.col(c).isNull()).count()
    print("NULLS", c, n)

spark.stop()
