"""Memory-bounded streaming ETL for the full Zenodo dump (no JVM, no pandas load).

``etl.py`` (PySpark) is the production path; ``etl_pandas.py`` is a convenient
small-data reference. Neither is ideal for running the full 3.2 GB
``public_v2.json`` on a single machine without a JVM: Spark needs Java and the
pandas path would load the whole dataset into memory.

This module streams the raw single-object JSON **once**, accumulating compact
per-IP state (timestamps as ints, path hashes in a set, running counters), and
emits the exact same feature schema as the other ETLs:

    data/parquet/features.csv
    data/parquet/features.parquet   (partitioned by date)

Peak memory is roughly proportional to (#requests + #distinct (ip,path) pairs)
as small ints, not the raw 3.2 GB of text.

Usage:
    python spark/etl_stream.py --input data/raw/public_v2.json --output data/parquet
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

# Allow `python spark/etl_stream.py` from the project root to import siblings.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from etl_pandas import (  # noqa: E402
    BOT_UA_REGEX,
    BROWSER_UA_REGEX,
    FEATURE_COLUMNS,
    SESSION_GAP_SECONDS,
    shannon_entropy,
)
from prepare_data import iter_records  # noqa: E402


def _parse_epoch(ts: Any) -> Optional[float]:
    """Parse an ISO-8601 timestamp (e.g. '2018-02-28T22:00:01.000Z') to epoch."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class _IPState:
    """Compact per-IP accumulator."""

    __slots__ = ("times", "path_hashes", "bytes_sum", "bytes_n",
                 "err", "c404", "ua")

    def __init__(self) -> None:
        self.times: list[float] = []
        self.path_hashes: set[int] = set()
        self.bytes_sum: float = 0.0
        self.bytes_n: int = 0
        self.err: int = 0
        self.c404: int = 0
        self.ua: str = ""


def _finalize(ip: str, st: _IPState) -> dict[str, Any]:
    times = sorted(st.times)
    req_count = len(times)
    diffs = [times[i] - times[i - 1] for i in range(1, req_count)]
    avg_interval = sum(diffs) / len(diffs) if diffs else 0.0
    if len(diffs) > 1:
        mean = avg_interval
        var = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
        std_interval = var ** 0.5
    else:
        std_interval = 0.0
    min_interval = min(diffs) if diffs else 0.0

    first_seen, last_seen = times[0], times[-1]
    window_hours = max((last_seen - first_seen) / 3600.0, 1.0 / 3600.0)
    sessions = 1 + sum(1 for d in diffs if d > SESSION_GAP_SECONDS)

    is_known_bot = 1 if BOT_UA_REGEX.search(st.ua) else 0
    is_browser = 1 if (BROWSER_UA_REGEX.search(st.ua) and not is_known_bot) else 0
    rate_404 = st.c404 / req_count
    is_robot = int(is_known_bot == 1 or rate_404 > 0.5)

    return {
        "ip": ip,
        "req_count": req_count,
        "avg_interval": avg_interval,
        "std_interval": std_interval,
        "min_interval": min_interval,
        "requests_per_hour": req_count / window_hours,
        "session_count": sessions,
        "avg_session_length": req_count / sessions,
        "unique_paths_ratio": len(st.path_hashes) / req_count,
        "error_rate": st.err / req_count,
        "rate_404": rate_404,
        "avg_bytes": (st.bytes_sum / st.bytes_n) if st.bytes_n else 0.0,
        "ua_is_known_bot": is_known_bot,
        "ua_is_browser": is_browser,
        "ua_entropy": shannon_entropy(st.ua),
        "first_seen": datetime.fromtimestamp(first_seen, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "last_seen": datetime.fromtimestamp(last_seen, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "date": datetime.fromtimestamp(last_seen, tz=timezone.utc).strftime("%Y-%m-%d"),
        "is_robot": is_robot,
    }


def run(input_path: str, output_dir: str, progress_every: int = 500_000) -> str:
    os.makedirs(output_dir, exist_ok=True)
    states: dict[str, _IPState] = {}
    seen = 0
    skipped = 0

    for record in iter_records(input_path):
        ip = record.get("ip")
        ts = _parse_epoch(record.get("timestamp"))
        if not ip or ts is None:
            skipped += 1
            continue
        st = states.get(ip)
        if st is None:
            st = states[ip] = _IPState()
        st.times.append(ts)

        path = record.get("resource")
        if path:
            st.path_hashes.add(hash(path))
        status = _to_int(record.get("response"))
        if status is not None:
            if status >= 400:
                st.err += 1
            if status == 404:
                st.c404 += 1
        nbytes = _to_int(record.get("bytes"))
        if nbytes is not None:
            st.bytes_sum += nbytes
            st.bytes_n += 1
        ua = record.get("useragent")
        if ua and ua != "-" and not st.ua:
            st.ua = ua

        seen += 1
        if seen % progress_every == 0:
            print(f"  ... {seen:,} requests, {len(states):,} IPs", file=sys.stderr, flush=True)

    print(f"[etl_stream] read {seen:,} requests ({skipped:,} skipped), "
          f"{len(states):,} distinct IPs", file=sys.stderr)

    rows = [_finalize(ip, st) for ip, st in states.items()]
    features = pd.DataFrame(rows, columns=FEATURE_COLUMNS)

    csv_path = os.path.join(output_dir, "features.csv")
    features.to_csv(csv_path, index=False)
    n_bots = int(features["is_robot"].sum())
    print(f"[etl_stream] {len(features):,} IPs, {n_bots:,} robots -> {csv_path}")

    try:
        parquet_path = os.path.join(output_dir, "features.parquet")
        features.to_parquet(parquet_path, partition_cols=["date"], index=False)
        print(f"[etl_stream] wrote Parquet (partitioned by date) -> {parquet_path}")
    except Exception as exc:  # pragma: no cover
        print(f"[etl_stream] skipped parquet ({exc})")
    return csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/public_v2.json")
    parser.add_argument("--output", default="data/parquet")
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
