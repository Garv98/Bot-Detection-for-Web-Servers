"""Analytics + demo helpers backing the web dashboard.

Reads the feature table (Parquet via DuckDB), the training ``metrics.json``,
and the live SQLite event log, and exposes aggregate queries the Next.js UI
consumes. Also provides a ``simulate_traffic`` helper that replays real IPs
from the feature table through the scorer into the event log so the live
dashboard lights up during a demo.
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Optional

PARQUET_GLOB = os.environ.get(
    "FEATURES_PARQUET",
    "data/parquet/features.parquet/**/*.parquet",
)
FEATURES_CSV = os.environ.get("FEATURES_CSV", "data/parquet/features.csv")
METRICS_PATH = os.environ.get("METRICS_PATH", "models/metrics.json")
GT_METRICS_PATH = os.environ.get("GT_METRICS_PATH", "models/groundtruth_metrics.json")

# Numeric feature columns used when building a profile dict for scoring.
_FEATURE_KEYS = [
    "req_count", "avg_interval", "std_interval", "min_interval",
    "requests_per_hour", "session_count", "avg_session_length",
    "unique_paths_ratio", "error_rate", "rate_404", "avg_bytes",
    "ua_is_known_bot", "ua_is_browser", "ua_entropy",
]


def _duckdb_conn():
    import duckdb

    con = duckdb.connect()
    # Prefer Parquet; fall back to the CSV if Parquet isn't present.
    if _parquet_available():
        con.execute(
            f"CREATE VIEW features AS SELECT * FROM "
            f"read_parquet('{PARQUET_GLOB}', hive_partitioning=1)"
        )
    elif os.path.exists(FEATURES_CSV):
        con.execute(
            f"CREATE VIEW features AS SELECT * FROM read_csv_auto('{FEATURES_CSV}')"
        )
    else:
        con.execute("CREATE TABLE features (ip VARCHAR, is_robot INT, req_count INT)")
    return con


def _parquet_available() -> bool:
    base = PARQUET_GLOB.split("**")[0]
    return os.path.isdir(base) and any(
        f.endswith(".parquet")
        for _root, _dirs, files in os.walk(base)
        for f in files
    )


def load_metrics() -> dict[str, Any]:
    if not os.path.exists(METRICS_PATH):
        return {}
    with open(METRICS_PATH) as fh:
        return json.load(fh)


def load_groundtruth_metrics() -> dict[str, Any]:
    if not os.path.exists(GT_METRICS_PATH):
        return {}
    with open(GT_METRICS_PATH) as fh:
        return json.load(fh)


def groundtruth_comparison() -> dict[str, Any]:
    m = load_groundtruth_metrics()
    return {
        "available": bool(m),
        "best_model": m.get("best_model"),
        "chosen_threshold": m.get("chosen_threshold"),
        "n_samples": m.get("n_samples"),
        "n_robots": m.get("n_robots"),
        "label": m.get("label"),
        "dataset": m.get("dataset"),
        "models": m.get("models", {}),
    }


def groundtruth_feature_importances(limit: int = 15) -> list[dict[str, Any]]:
    fi = load_groundtruth_metrics().get("feature_importances", {})
    return [{"feature": k, "importance": v} for k, v in list(fi.items())[:limit]]


def overview() -> dict[str, Any]:
    """Dataset-wide rollup from the feature table + model AUC."""
    con = _duckdb_conn()
    try:
        row = con.execute(
            """SELECT COUNT(*)                AS total_ips,
                      COALESCE(SUM(is_robot),0) AS bots,
                      COALESCE(SUM(req_count),0) AS total_requests,
                      COALESCE(AVG(requests_per_hour),0) AS avg_rph
               FROM features"""
        ).fetchone()
    finally:
        con.close()
    total_ips, bots, total_requests, avg_rph = row
    # Headline model stats prefer the honest ground-truth benchmark when present.
    gt = load_groundtruth_metrics()
    metrics = load_metrics()
    if gt:
        best = gt.get("best_model")
        auc = gt.get("models", {}).get(best, {}).get("auc_roc")
        label_kind = "ground truth"
    else:
        best = metrics.get("best_model")
        auc = metrics.get("models", {}).get(best, {}).get("auc_roc") if best else None
        label_kind = "heuristic"
    return {
        "total_ips": int(total_ips or 0),
        "bots": int(bots or 0),
        "humans": int((total_ips or 0) - (bots or 0)),
        "bot_ratio": round((bots / total_ips), 4) if total_ips else 0.0,
        "total_requests": int(total_requests or 0),
        "avg_requests_per_hour": round(float(avg_rph or 0), 2),
        "best_model": best,
        "model_auc": auc,
        "label_kind": label_kind,
        "model_version": metrics.get("model_version") or gt.get("model_version"),
    }


def top_bots(limit: int = 20) -> list[dict[str, Any]]:
    con = _duckdb_conn()
    try:
        rows = con.execute(
            """SELECT ip, req_count, requests_per_hour, rate_404, ua_entropy,
                      error_rate, session_count
               FROM features
               WHERE is_robot = 1
               ORDER BY req_count DESC
               LIMIT ?""",
            [limit],
        ).fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    return [dict(zip(cols, r)) for r in rows]


def risk_distribution(bins: int = 20) -> list[dict[str, Any]]:
    """Histogram of requests_per_hour (log-ish behavioural signal), bot vs human."""
    con = _duckdb_conn()
    try:
        rows = con.execute(
            """SELECT
                   LEAST(CAST(requests_per_hour / 50 AS INTEGER), 20) AS bucket,
                   SUM(CASE WHEN is_robot=1 THEN 1 ELSE 0 END) AS bots,
                   SUM(CASE WHEN is_robot=0 THEN 1 ELSE 0 END) AS humans
               FROM features
               GROUP BY bucket ORDER BY bucket"""
        ).fetchall()
    finally:
        con.close()
    return [{"requests_per_hour_bucket": int(b) * 50, "bots": int(bo), "humans": int(h)}
            for b, bo, h in rows]


def scatter_sample(limit: int = 600) -> list[dict[str, Any]]:
    """Sample of IPs for a behavioural scatter (rph vs error_rate, coloured by label)."""
    con = _duckdb_conn()
    try:
        rows = con.execute(
            f"""SELECT ip, requests_per_hour, error_rate, unique_paths_ratio,
                      ua_entropy, req_count, is_robot
               FROM features
               USING SAMPLE {int(limit)} ROWS"""
        ).fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    return [dict(zip(cols, r)) for r in rows]


def feature_importances() -> list[dict[str, Any]]:
    fi = load_metrics().get("feature_importances", {})
    return [{"feature": k, "importance": v} for k, v in fi.items()]


def model_comparison() -> dict[str, Any]:
    metrics = load_metrics()
    return {
        "best_model": metrics.get("best_model"),
        "chosen_threshold": metrics.get("chosen_threshold"),
        "n_samples": metrics.get("n_samples"),
        "n_robots": metrics.get("n_robots"),
        "models": metrics.get("models", {}),
    }


# --- live event-log queries ------------------------------------------------
def events_timeseries(event_log, bucket_seconds: int = 300) -> list[dict[str, Any]]:
    with event_log._connect() as conn:  # noqa: SLF001 - intentional internal use
        rows = conn.execute(
            f"""SELECT CAST(timestamp / {bucket_seconds} AS INTEGER) * {bucket_seconds} AS bucket,
                       SUM(CASE WHEN is_bot=1 THEN 1 ELSE 0 END) AS bots,
                       SUM(CASE WHEN is_bot=0 THEN 1 ELSE 0 END) AS humans
                FROM bot_events GROUP BY bucket ORDER BY bucket""",
        ).fetchall()
    return [{"t": int(b), "bots": int(bo), "humans": int(h)} for b, bo, h in rows]


def events_heatmap(event_log) -> list[dict[str, Any]]:
    with event_log._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            """SELECT CAST(strftime('%w', datetime(timestamp,'unixepoch')) AS INTEGER) AS dow,
                      CAST(strftime('%H', datetime(timestamp,'unixepoch')) AS INTEGER) AS hour,
                      COUNT(*) AS requests
               FROM bot_events GROUP BY dow, hour""",
        ).fetchall()
    return [{"dow": int(d), "hour": int(h), "requests": int(r)} for d, h, r in rows]


def events_recent(event_log, limit: int = 12) -> list[dict[str, Any]]:
    """Most recent scored events for the live detections feed."""
    with event_log._connect() as conn:  # noqa: SLF001  (_connect sets sqlite3.Row)
        rows = conn.execute(
            """SELECT ip, timestamp, path, risk_score, is_bot, cidr_block
               FROM bot_events ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {"ip": r["ip"], "t": float(r["timestamp"]), "path": r["path"],
         "risk_score": r["risk_score"], "is_bot": int(r["is_bot"] or 0),
         "cidr_block": r["cidr_block"]}
        for r in rows
    ]


def simulate_traffic(event_log, scorer, hbase_client=None, n: int = 200,
                     spread_seconds: int = 7200) -> dict[str, Any]:
    """Replay n random IPs from the feature table through the scorer into the
    event log (SQLite) AND the HBase profile store, spread over the last
    ``spread_seconds`` so the live charts fill in. Returns counts."""
    import pandas as pd

    if not os.path.exists(FEATURES_CSV):
        return {"generated": 0, "error": "no feature table available"}
    df = pd.read_csv(FEATURES_CSV)
    if df.empty:
        return {"generated": 0}
    sample = df.sample(min(n, len(df)))
    now = time.time()
    bots = 0
    hbase_written = 0
    paths = ["/", "/Record", "/Search", "/AJAX", "/api/data", "/robots.txt",
             "/login", "/admin", "/static/app.js"]
    for _, row in sample.iterrows():
        ip = str(row["ip"])
        profile = {k: row[k] for k in _FEATURE_KEYS if k in row}
        risk, is_bot, reason = scorer.score(features=profile)
        ts = now - random.random() * spread_seconds
        event_log.log_event(
            ip=ip, path=random.choice(paths), useragent="replayed",
            risk_score=risk, is_bot=is_bot, status_code=200,
            bytes_sent=int(row.get("avg_bytes", 0) or 0), timestamp=ts,
        )
        bots += int(is_bot)
        # Persist the scored profile to HBase (the per-IP profile store).
        if hbase_client is not None:
            try:
                hbase_client.upsert_profile(ip, {
                    **profile,
                    "first_seen": str(row.get("first_seen", "")),
                    "last_seen": str(row.get("last_seen", "")),
                    "risk_score": round(risk, 4),
                    "is_bot": int(is_bot),
                    "threshold_used": scorer.threshold,
                    "model_version": scorer.model_version,
                })
                if is_bot:
                    hbase_client.flag_ip(ip, reason=reason,
                                         request_count=int(row.get("req_count", 0) or 0))
                hbase_written += 1
            except Exception:  # noqa: BLE001 - HBase optional for the demo
                pass
    return {"generated": int(len(sample)), "bots": bots,
            "humans": int(len(sample) - bots), "hbase_profiles_written": hbase_written}
