"""Apache Spark ETL for the bot-detection pipeline.

Reads newline-delimited JSON web-server logs (see ``prepare_data.py``) and
computes a rich per-IP feature table using Spark window functions, then
writes:

    * ``data/parquet/features.parquet``  (columnar, partitioned by ``date``)
    * ``data/parquet/features.csv``      (single CSV for ML training fallback)

Run locally:
    spark-submit spark/etl.py --input data/raw/logs.ndjson \\
                              --output data/parquet

Requires a JVM (Java 8/11/17) on PATH for PySpark.
"""

from __future__ import annotations

import argparse
import math
import os
from collections import Counter
from typing import Optional

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

# --- Session gap that starts a new session (seconds) -----------------------
SESSION_GAP_SECONDS = 1800

# --- User-Agent classification --------------------------------------------
BOT_UA_REGEX = (
    r"(?i)(bot|crawl|spider|slurp|googlebot|bingbot|baiduspider|yandex|"
    r"duckduckbot|ahrefs|semrush|mj12bot|dotbot|petalbot|applebot|"
    r"facebookexternalhit|ia_archiver|icc-crawler|curl|wget|python-requests|"
    r"python-urllib|scrapy|httpclient|java/|go-http-client|libwww|okhttp|"
    r"headlesschrome|phantomjs)"
)
BROWSER_UA_REGEX = r"(?i)(chrome|firefox|safari|edg|opera|msie|trident)"


def _shannon_entropy(text: Optional[str]) -> float:
    """Shannon entropy (base-2) over the characters of a string."""
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


ua_entropy_udf = F.udf(_shannon_entropy, T.DoubleType())


def build_spark(app_name: str = "bot-detection-etl") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", os.environ.get("SPARK_SHUFFLE_PARTITIONS", "8"))
        .getOrCreate()
    )


def read_logs(spark: SparkSession, input_path: str) -> DataFrame:
    """Read NDJSON logs and normalise column names / types.

    Tolerates either the canonical schema (ip, timestamp, useragent, path,
    method, status_code, bytes_sent) or the raw Zenodo aliases
    (resource, response, bytes).
    """
    df = spark.read.json(input_path)
    cols = set(df.columns)

    def pick(*names: str) -> Optional[str]:
        return next((n for n in names if n in cols), None)

    path_col = pick("path", "resource")
    status_col = pick("status_code", "response", "status")
    bytes_col = pick("bytes_sent", "bytes")

    df = df.select(
        F.col("ip").cast("string").alias("ip"),
        F.to_timestamp("timestamp").alias("ts"),
        F.coalesce(F.col("useragent"), F.lit("")).cast("string").alias("useragent"),
        (F.col(path_col) if path_col else F.lit(None)).cast("string").alias("path"),
        (F.col("method") if "method" in cols else F.lit(None)).cast("string").alias("method"),
        (F.col(status_col) if status_col else F.lit(None)).cast("int").alias("status_code"),
        (F.col(bytes_col) if bytes_col else F.lit(None)).cast("long").alias("bytes_sent"),
        # Carry a ground-truth label through if the dataset provides one.
        (
            F.col("is_robot") if "is_robot" in cols
            else (F.col("robot") if "robot" in cols else F.lit(None))
        ).cast("int").alias("gt_is_robot"),
    )
    return df.filter(F.col("ip").isNotNull() & F.col("ts").isNotNull())


def add_intervals_and_sessions(df: DataFrame) -> DataFrame:
    """Add per-request inter-arrival interval and a per-IP session index."""
    w_ip = Window.partitionBy("ip").orderBy("ts")
    prev_ts = F.lag("ts").over(w_ip)
    interval = (F.col("ts").cast("long") - prev_ts.cast("long")).cast("double")

    df = df.withColumn("interval", interval)
    # A new session starts on the first request or after a gap > threshold.
    new_session = (
        F.when(F.col("interval").isNull() | (F.col("interval") > SESSION_GAP_SECONDS), 1)
        .otherwise(0)
    )
    df = df.withColumn("_new_session", new_session)
    df = df.withColumn(
        "session_index",
        F.sum("_new_session").over(w_ip.rowsBetween(Window.unboundedPreceding, 0)),
    )
    return df


def aggregate_features(df: DataFrame) -> DataFrame:
    """Collapse per-request rows into one feature row per IP."""
    is_error = F.when(F.col("status_code") >= 400, 1).otherwise(0)
    is_404 = F.when(F.col("status_code") == 404, 1).otherwise(0)
    is_bot_ua = F.when(F.col("useragent").rlike(BOT_UA_REGEX), 1).otherwise(0)
    is_browser_ua = F.when(
        F.col("useragent").rlike(BROWSER_UA_REGEX)
        & ~F.col("useragent").rlike(BOT_UA_REGEX),
        1,
    ).otherwise(0)

    agg = df.groupBy("ip").agg(
        F.count(F.lit(1)).alias("req_count"),
        F.avg("interval").alias("avg_interval"),
        F.stddev("interval").alias("std_interval"),
        F.min("interval").alias("min_interval"),
        F.min("ts").alias("first_seen_ts"),
        F.max("ts").alias("last_seen_ts"),
        F.max("session_index").alias("session_count"),
        F.countDistinct("path").alias("distinct_paths"),
        F.sum(is_error).alias("error_count"),
        F.sum(is_404).alias("count_404"),
        F.avg("bytes_sent").alias("avg_bytes"),
        F.max(is_bot_ua).alias("ua_is_known_bot"),
        F.max(is_browser_ua).alias("ua_is_browser"),
        F.first("useragent", ignorenulls=True).alias("_ua_sample"),
        F.max("gt_is_robot").alias("gt_is_robot"),
    )

    window_hours = F.greatest(
        (F.col("last_seen_ts").cast("long") - F.col("first_seen_ts").cast("long")) / 3600.0,
        F.lit(1.0 / 3600.0),  # floor at 1 second to avoid div-by-zero
    )

    features = agg.select(
        "ip",
        "req_count",
        F.coalesce("avg_interval", F.lit(0.0)).alias("avg_interval"),
        F.coalesce("std_interval", F.lit(0.0)).alias("std_interval"),
        F.coalesce("min_interval", F.lit(0.0)).alias("min_interval"),
        (F.col("req_count") / window_hours).alias("requests_per_hour"),
        "session_count",
        (F.col("req_count") / F.col("session_count")).alias("avg_session_length"),
        (F.col("distinct_paths") / F.col("req_count")).alias("unique_paths_ratio"),
        (F.col("error_count") / F.col("req_count")).alias("error_rate"),
        (F.col("count_404") / F.col("req_count")).alias("rate_404"),
        F.coalesce("avg_bytes", F.lit(0.0)).alias("avg_bytes"),
        "ua_is_known_bot",
        "ua_is_browser",
        ua_entropy_udf(F.col("_ua_sample")).alias("ua_entropy"),
        F.date_format("first_seen_ts", "yyyy-MM-dd'T'HH:mm:ss").alias("first_seen"),
        F.date_format("last_seen_ts", "yyyy-MM-dd'T'HH:mm:ss").alias("last_seen"),
        F.to_date("last_seen_ts").alias("date"),
        "gt_is_robot",
    )

    # Label: prefer ground truth, else heuristic (known-bot UA OR many 404s).
    features = features.withColumn(
        "is_robot",
        F.when(F.col("gt_is_robot").isNotNull(), F.col("gt_is_robot")).otherwise(
            F.when(
                (F.col("ua_is_known_bot") == 1) | (F.col("rate_404") > 0.5), 1
            ).otherwise(0)
        ),
    ).drop("gt_is_robot")

    return features


def run_etl(input_path: str, output_dir: str) -> DataFrame:
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")

    logs = read_logs(spark, input_path)
    enriched = add_intervals_and_sessions(logs)
    features = aggregate_features(enriched).cache()

    n_ips = features.count()
    n_bots = features.filter(F.col("is_robot") == 1).count()
    print(f"[etl] computed features for {n_ips:,} IPs; {n_bots:,} labelled robot")

    parquet_path = os.path.join(output_dir, "features.parquet")
    csv_path = os.path.join(output_dir, "features.csv")

    features.write.mode("overwrite").partitionBy("date").parquet(parquet_path)
    print(f"[etl] wrote Parquet (partitioned by date) -> {parquet_path}")

    # Single CSV for the sklearn training fallback.
    (
        features.drop("date")
        .coalesce(1)
        .write.mode("overwrite")
        .option("header", True)
        .csv(csv_path + ".tmp")
    )
    _merge_single_csv(spark, csv_path + ".tmp", csv_path)
    print(f"[etl] wrote CSV -> {csv_path}")

    spark.stop()
    return features


def _merge_single_csv(spark: SparkSession, tmp_dir: str, target_csv: str) -> None:
    """Move Spark's part-file out to a plain ``features.csv`` path."""
    import glob
    import shutil

    parts = sorted(glob.glob(os.path.join(tmp_dir, "part-*.csv")))
    if parts:
        if os.path.exists(target_csv):
            os.remove(target_csv)
        shutil.move(parts[0], target_csv)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default=os.environ.get("ETL_INPUT", "data/raw/logs.ndjson"),
        help="NDJSON logs path (file or directory).",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("ETL_OUTPUT", "data/parquet"),
        help="Output directory for features.parquet / features.csv.",
    )
    args = parser.parse_args()
    run_etl(args.input, args.output)


if __name__ == "__main__":
    main()
