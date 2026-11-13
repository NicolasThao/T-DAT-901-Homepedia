import os
import platform


def get_spark_session(app_name="homepedia", jars=()):
    """Session Spark locale.

    `jars` : chemins de .jar locaux (ex. driver JDBC Postgres), ajoutés au classpath du driver.
    En mode local[*], les exécuteurs tournent dans la JVM du driver : ce classpath suffit.
    (spark.jars.packages est évité : sous Windows il exige winutils.exe / HADOOP_HOME.)
    """
    if platform.system() == "Windows" and not os.environ.get("JAVA_HOME"):
        local_jdk = os.path.expanduser(r"~\.jdk\jdk-17.0.20.1+1")
        if os.path.isdir(local_jdk):
            os.environ["JAVA_HOME"] = local_jdk

    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name).master("local[*]")
    if jars:
        builder = builder.config("spark.driver.extraClassPath", os.pathsep.join(str(j) for j in jars))
    return builder.getOrCreate()
