import os
import platform


def get_spark_session(app_name="homepedia"):
    if platform.system() == "Windows" and not os.environ.get("JAVA_HOME"):
        local_jdk = os.path.expanduser(r"~\.jdk\jdk-17.0.20.1+1")
        if os.path.isdir(local_jdk):
            os.environ["JAVA_HOME"] = local_jdk

    from pyspark.sql import SparkSession

    return SparkSession.builder.appName(app_name).master("local[*]").getOrCreate()
