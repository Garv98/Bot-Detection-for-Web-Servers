"""Pandas reference implementation of the Spark ETL (no-JVM fallback).

Produces a ``features.csv`` with the *exact same schema* as ``etl.py`` so the
rest of the pipeline (ML training, API, Superset) can run on machines without
a JVM/Spark install, and so the feature logic can be unit-tested cheaply.

For production-scale data use ``etl.py`` with ``spark-submit``; this module is
intended for smoke tests and small/medium datasets that fit in memory.

Usage:
    python spark/etl_pandas.py --input data/raw/logs.ndjson \\
                               --output data/parquet
"""

from __future__ import annotations

import argparse
import math
import os
import re
from collections import Counter
from typing import Optional

import pandas as pd

SESSION_GAP_SECONDS = 1800

BOT_UA_REGEX = re.compile(
    r"(bot|crawl|spider|slurp|googlebot|bingbot|baiduspider|yandex|"
    r"duckduckbot|ahrefs|semrush|mj12bot|dotbot|petalbot|applebot|"
    r"facebookexternalhit|ia_archiver|icc-crawler|curl|wget|python-requests|"
    r"python-urllib|scrapy|httpclient|java/|go-http-client|libwww|okhttp|"
    r"headlesschrome|phantomjs)",
    re.IGNORECASE,
)
BROWSER_UA_REGEX = re.compile(r"(chrome|firefox|safari|edg|opera|msie|trident)", re.IGNORECASE)

FEATURE_COLUMNS = [
    "ip", "req_count", "avg_interval", "std_interval", "min_interval",
    "requests_per_hour", "session_count", "avg_session_length",
    "unique_paths_ratio", "error_rate", "rate_404", "avg_bytes",
    "ua_is_known_bot", "ua_is_browser", "ua_entropy",
    "first_seen", "last_seen", "date", "is_robot",
]


def shannon_entropy(text: Optional[str]) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


def _session_count(times: pd.Series) -> int:
    """Number of sessions: a gap > SESSION_GAP_SECONDS starts a new one."""
    if len(times) == 0:
        return 0
    diffs = times.sort_values().diff().dt.total_seconds()
    # first request (NaN diff) + every gap over the threshold starts a session
    return int((diffs.isna() | (diffs > SESSION_GAP_SECONDS)).sum())


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["ip", "ts"])
    df["useragent"] = df.get("useragent", "").fillna("")
    df["status_code"] = pd.to_numeric(df.get("status_code"), errors="coerce")
    df["bytes_sent"] = pd.to_numeric(df.get("bytes_sent"), errors="coerce")
    if "path" not in df:
        df["path"] = df.get("resource")

    df = df.sort_values(["ip", "ts"])
    df["interval"] = df.groupby("ip")["ts"].diff().dt.total_seconds()

    rows = []
    for ip, g in df.groupby("ip", sort=False):
        req_count = len(g)
        intervals = g["interval"].dropna()
        first_seen, last_seen = g["ts"].min(), g["ts"].max()
        window_hours = max((last_seen - first_seen).total_seconds() / 3600.0, 1.0 / 3600.0)
        sessions = _session_count(g["ts"])
        ua_sample = next((u for u in g["useragent"] if u), "")
        is_known_bot = int(bool(BOT_UA_REGEX.search(ua_sample)))
        is_browser = int(bool(BROWSER_UA_REGEX.search(ua_sample)) and not is_known_bot)
        rate_404 = float((g["status_code"] == 404).sum()) / req_count
        gt = g["is_robot"] if "is_robot" in g else (g["robot"] if "robot" in g else None)
        gt_label = None
        if gt is not None and gt.notna().any():
            gt_label = int(gt.dropna().max())

        is_robot = gt_label if gt_label is not None else int(is_known_bot == 1 or rate_404 > 0.5)

        rows.append({
            "ip": ip,
            "req_count": req_count,
            "avg_interval": float(intervals.mean()) if not intervals.empty else 0.0,
            "std_interval": float(intervals.std(ddof=1)) if len(intervals) > 1 else 0.0,
            "min_interval": float(intervals.min()) if not intervals.empty else 0.0,
            "requests_per_hour": req_count / window_hours,
            "session_count": sessions,
            "avg_session_length": req_count / sessions if sessions else float(req_count),
            "unique_paths_ratio": g["path"].nunique() / req_count,
            "error_rate": float((g["status_code"] >= 400).sum()) / req_count,
            "rate_404": rate_404,
            "avg_bytes": float(g["bytes_sent"].mean()) if g["bytes_sent"].notna().any() else 0.0,
            "ua_is_known_bot": is_known_bot,
            "ua_is_browser": is_browser,
            "ua_entropy": shannon_entropy(ua_sample),
            "first_seen": first_seen.strftime("%Y-%m-%dT%H:%M:%S"),
            "last_seen": last_seen.strftime("%Y-%m-%dT%H:%M:%S"),
            "date": last_seen.strftime("%Y-%m-%d"),
            "is_robot": is_robot,
        })

    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)


def run(input_path: str, output_dir: str) -> pd.DataFrame:
    os.makedirs(output_dir, exist_ok=True)
    raw = pd.read_json(input_path, lines=True)
    features = compute_features(raw)

    csv_path = os.path.join(output_dir, "features.csv")
    features.to_csv(csv_path, index=False)
    print(f"[etl_pandas] {len(features):,} IPs, "
          f"{int(features['is_robot'].sum()):,} robots -> {csv_path}")

    # Partitioned parquet (mirrors Spark output layout) if pyarrow is present.
    try:
        parquet_path = os.path.join(output_dir, "features.parquet")
        features.to_parquet(parquet_path, partition_cols=["date"], index=False)
        print(f"[etl_pandas] wrote Parquet (partitioned by date) -> {parquet_path}")
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[etl_pandas] skipped parquet ({exc})")
    return features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/logs.ndjson")
    parser.add_argument("--output", default="data/parquet")
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
