"""SparkSession with Delta Lake. Local lake by default; MinIO (s3a) when LAKE_BACKEND=s3."""
import os
import sys
from pathlib import Path

import pyspark
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession


def local_uri(p: Path) -> str:
    """file:///D:/... without percent-encoding (Path.as_uri turns dt= into dt%3D)."""
    return "file:///" + p.resolve().as_posix().lstrip("/")


def lake_path(layer: str, table: str) -> str:
    if os.getenv("LAKE_BACKEND", "s3") == "local":
        root = Path(os.getenv("LAKE_ROOT", "data/lake"))
        return local_uri(root / layer / table)
    return f"s3a://{layer}/{table}"


def get_spark(app: str = "india-market") -> SparkSession:
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    # Use the pip-installed PySpark that delta-spark is built against, not a
    # system-wide SPARK_HOME of a different version (NoClassDefFoundError otherwise).
    os.environ["SPARK_HOME"] = os.path.dirname(pyspark.__file__)
    b = (
        SparkSession.builder.appName(app)
        .master(os.getenv("SPARK_MASTER", "local[*]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.session.timeZone", "Asia/Kolkata")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.showConsoleProgress", "false")
    )
    extra = []
    if os.getenv("LAKE_BACKEND", "s3") == "s3":
        extra = ["org.apache.hadoop:hadoop-aws:3.4.1"]
        b = (
            b.config("spark.hadoop.fs.s3a.endpoint", os.getenv("MINIO_ENDPOINT", "http://localhost:9000"))
            .config("spark.hadoop.fs.s3a.access.key", os.getenv("MINIO_ROOT_USER", "minioadmin"))
            .config("spark.hadoop.fs.s3a.secret.key", os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"))
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
        )
    spark = configure_spark_with_delta_pip(b, extra_packages=extra).getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
