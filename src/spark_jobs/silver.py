"""Bronze -> Silver. Typed, trimmed, deduplicated, idempotent (Delta MERGE by date).

    python -m src.spark_jobs.silver --date 2026-10-06
    python -m src.spark_jobs.silver --start 2026-08-17 --end 2026-10-06
    python -m src.spark_jobs.silver --all
"""
import argparse
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from delta.tables import DeltaTable
from dotenv import load_dotenv
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from .parsers import adjustment_factor, parse_navall, parse_nse_date
from .session import get_spark, lake_path, local_uri

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("silver")

BHAV_COLS = ["SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
             "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS",
             "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER"]
INDEX_COLS = ["Index Name", "Index Date", "Open Index Value", "High Index Value", "Low Index Value",
              "Closing Index Value", "Points Change", "Change(%)", "Volume", "Turnover (Rs. Cr.)",
              "P/E", "P/B", "Div Yield"]


# ---------- helpers ----------

def merge_delta(spark: SparkSession, df: DataFrame, table: str, keys: list[str],
                partition_col: str | None = None) -> None:
    """Upsert: re-running the same day updates rows in place, never duplicates."""
    path = lake_path("silver", table)
    if not DeltaTable.isDeltaTable(spark, path):
        w = df.write.format("delta").mode("overwrite")
        if partition_col:
            w = w.partitionBy(partition_col)
        w.save(path)
        log.info("created silver.%s", table)
        return
    cond = " AND ".join(f"t.`{k}` = s.`{k}`" for k in keys)
    (DeltaTable.forPath(spark, path).alias("t")
     .merge(df.alias("s"), cond)
     .whenMatchedUpdateAll()
     .whenNotMatchedInsertAll()
     .execute())
    log.info("merged silver.%s", table)


def bronze_dirs(source: str, days: list[date] | None) -> list[str]:
    """Existing bronze partition dirs (days=None -> all). Holidays simply have no dir."""
    if os.getenv("LAKE_BACKEND", "s3") != "local":
        if days is None:
            return [f"s3a://bronze/{source}/"]
        return [f"s3a://bronze/{source}/dt={d.isoformat()}/" for d in days]
    root = Path(os.getenv("LAKE_ROOT", "data/lake")).resolve() / "bronze" / source
    dirs = sorted(root.glob("dt=*")) if days is None else [root / f"dt={d}" for d in days]
    return [local_uri(p) for p in dirs if p.exists()]


def num(c: str):
    """Trimmed string -> double; '-', '' and junk become null."""
    return F.expr(f"try_cast(nullif(nullif(trim(`{c}`), '-'), '') as double)")


def check_schema(df: DataFrame, expected: list[str], source: str) -> DataFrame:
    df = df.toDF(*[c.strip() for c in df.columns])
    missing = set(expected) - set(df.columns)
    if missing:
        raise ValueError(f"{source}: schema drift, missing columns {sorted(missing)}")
    return df


# ---------- stock_daily ----------

def build_stock_daily(spark: SparkSession, days: list[date] | None) -> int:
    paths = bronze_dirs("nse_bhavcopy", days)
    if not paths:
        log.info("stock_daily: no bronze files for requested days")
        return 0
    raw = (spark.read.option("header", True).option("ignoreLeadingWhiteSpace", True)
           .option("ignoreTrailingWhiteSpace", True).csv(paths))
    raw = check_schema(raw, BHAV_COLS, "nse_bhavcopy")

    df = raw.select(
        F.to_date(F.trim("DATE1"), "dd-MMM-yyyy").alias("trade_date"),
        F.upper(F.trim("SYMBOL")).alias("symbol"),
        F.upper(F.trim("SERIES")).alias("series"),
        num("PREV_CLOSE").alias("prev_close"),
        num("OPEN_PRICE").alias("open"),
        num("HIGH_PRICE").alias("high"),
        num("LOW_PRICE").alias("low"),
        num("LAST_PRICE").alias("last"),
        num("CLOSE_PRICE").alias("close"),
        num("AVG_PRICE").alias("vwap"),
        num("TTL_TRD_QNTY").cast("long").alias("volume"),
        num("TURNOVER_LACS").alias("turnover_lacs"),
        num("NO_OF_TRADES").cast("long").alias("num_trades"),
        num("DELIV_QTY").cast("long").alias("deliv_qty"),
        num("DELIV_PER").alias("deliv_pct"),
    ).withColumn("_ingested_at", F.current_timestamp())

    bad = (F.col("trade_date").isNull() | F.col("symbol").isNull() | F.col("close").isNull()
           | (F.col("close") <= 0) | (F.col("high") < F.col("low")))
    rejects = df.filter(bad)
    n_rej = rejects.count()
    if n_rej:
        merge_delta(spark, rejects.withColumn("_reason", F.lit("null/non-positive close or high<low")),
                    "_quarantine_stock_daily", ["trade_date", "symbol", "series"], "trade_date")
        log.warning("stock_daily: %d rows quarantined", n_rej)

    good = df.filter(~bad).dropDuplicates(["trade_date", "symbol", "series"])
    merge_delta(spark, good, "stock_daily", ["trade_date", "symbol", "series"], "trade_date")
    return good.count()


# ---------- index_daily ----------

def build_index_daily(spark: SparkSession, days: list[date] | None) -> int:
    paths = bronze_dirs("nse_indices", days)
    if not paths:
        return 0
    raw = check_schema(spark.read.option("header", True).csv(paths), INDEX_COLS, "nse_indices")
    df = raw.select(
        F.to_date(F.trim(F.col("Index Date")), "dd-MM-yyyy").alias("trade_date"),
        F.trim(F.col("Index Name")).alias("index_name"),
        num("Open Index Value").alias("open"),
        num("High Index Value").alias("high"),
        num("Low Index Value").alias("low"),
        num("Closing Index Value").alias("close"),
        num("Points Change").alias("points_change"),
        num("Change(%)").alias("pct_change"),
        num("Volume").cast("long").alias("volume"),
        num("Turnover (Rs. Cr.)").alias("turnover_cr"),
        num("P/E").alias("pe"),
        num("P/B").alias("pb"),
        num("Div Yield").alias("div_yield"),
    ).filter(F.col("trade_date").isNotNull() & F.col("close").isNotNull()) \
     .dropDuplicates(["trade_date", "index_name"]) \
     .withColumn("_ingested_at", F.current_timestamp())
    merge_delta(spark, df, "index_daily", ["trade_date", "index_name"], "trade_date")
    return df.count()


# ---------- fund_nav ----------

def build_fund_nav(spark: SparkSession, days: list[date] | None) -> int:
    rows = []
    for uri in bronze_dirs("amfi_navall", days):
        p = Path(uri.replace("file:///", "").replace("file://", "")) / "NAVAll.txt"
        if p.exists():
            rows.extend(parse_navall(p.read_text(encoding="utf-8", errors="replace")))
    if not rows:
        return 0
    df = (spark.createDataFrame(rows, schema=(
            "scheme_code long, isin_growth string, isin_reinvest string, scheme_name string, "
            "nav double, nav_date date, amc string, category string"))
          .filter(F.col("nav").isNotNull() & (F.col("nav") > 0))
          .dropDuplicates(["scheme_code", "nav_date"])
          .withColumn("_ingested_at", F.current_timestamp()))
    merge_delta(spark, df, "fund_nav", ["scheme_code", "nav_date"], "nav_date")
    return df.count()


# ---------- corporate_actions + split-adjusted prices ----------

def build_corporate_actions(spark: SparkSession) -> int:
    rows = []
    for uri in bronze_dirs("nse_corp_actions", None):
        d = Path(uri.replace("file:///", "").replace("file://", ""))
        for f in d.glob("*.json"):
            for r in json.loads(f.read_text(encoding="utf-8")):
                adj = adjustment_factor(r.get("subject", ""))
                if not adj:
                    continue
                try:
                    ex = parse_nse_date(r["exDate"])
                except (KeyError, ValueError):
                    continue
                rows.append({"symbol": r["symbol"].strip().upper(), "series": r.get("series"),
                             "ex_date": ex, "action_type": adj[0], "factor": adj[1],
                             "subject": r["subject"].strip()})
    if not rows:
        return 0
    df = spark.createDataFrame(rows, schema=(
        "symbol string, series string, ex_date date, action_type string, factor double, subject string"
    )).dropDuplicates(["symbol", "ex_date", "action_type"])
    merge_delta(spark, df, "corporate_actions", ["symbol", "ex_date", "action_type"])
    return df.count()


def build_stock_daily_adjusted(spark: SparkSession) -> int:
    """Full rebuild: a new split changes *all* earlier prices for that symbol.

    adj_price = price / product(factor of actions with ex_date > trade_date)
    adj_volume = volume * same product
    """
    px = spark.read.format("delta").load(lake_path("silver", "stock_daily"))
    ca_path = lake_path("silver", "corporate_actions")
    if DeltaTable.isDeltaTable(spark, ca_path):
        ca = spark.read.format("delta").load(ca_path).select("symbol", "ex_date", "factor")
        cum = (px.select("symbol", "trade_date").distinct().alias("p")
               .join(ca.alias("c"), (F.col("p.symbol") == F.col("c.symbol"))
                     & (F.col("c.ex_date") > F.col("p.trade_date")))
               .groupBy("p.symbol", "p.trade_date")
               .agg(F.exp(F.sum(F.log("c.factor"))).alias("adj_factor")))
        px = px.join(cum, ["symbol", "trade_date"], "left")
    else:
        px = px.withColumn("adj_factor", F.lit(None).cast("double"))
    # exp(sum(log)) leaves float noise (3.0 -> 2.9999999999999996)
    px = px.withColumn("adj_factor", F.round(F.coalesce("adj_factor", F.lit(1.0)), 6))
    for c in ["prev_close", "open", "high", "low", "last", "close", "vwap"]:
        px = px.withColumn(f"adj_{c}", F.round(F.col(c) / F.col("adj_factor"), 4))
    px = px.withColumn("adj_volume", (F.col("volume") * F.col("adj_factor")).cast("long"))
    (px.write.format("delta").mode("overwrite").option("overwriteSchema", True)
       .partitionBy("trade_date").save(lake_path("silver", "stock_daily_adjusted")))
    n = px.filter(F.col("adj_factor") != 1.0).count()
    log.info("stock_daily_adjusted rebuilt; %d rows carry a split/bonus adjustment", n)
    return n


# ---------- entrypoint ----------

def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat)
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    p.add_argument("--all", action="store_true")
    a = p.parse_args()

    if a.all:
        days = None
    elif a.start:
        end = a.end or date.today()
        days = [a.start + timedelta(n) for n in range((end - a.start).days + 1)]
    else:
        days = [a.date or date.today()]

    spark = get_spark("silver")
    log.info("stock_daily rows: %d", build_stock_daily(spark, days))
    log.info("index_daily rows: %d", build_index_daily(spark, days))
    log.info("fund_nav rows: %d", build_fund_nav(spark, days))
    log.info("corporate_actions rows: %d", build_corporate_actions(spark))
    build_stock_daily_adjusted(spark)
    spark.stop()


if __name__ == "__main__":
    main()
