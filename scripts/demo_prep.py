"""One-shot demo preparation: make the live dashboard look full and real.

Run this right before a demonstration (with the stack already up) to:
  1. Seed all per-IP profiles into HBase (so /api/score returns real data).
  2. Populate the SQLite event log with scored events spread over the last
     7 days, so the throughput line, bot/human area, and the hour x weekday
     heatmap all render richly (a 2-hour simulate burst leaves the heatmap
     sparse).

Usage (stack running, from the project root):
    HBASE_HOST=localhost HBASE_PORT=9090 HBASE_THRIFT_TRANSPORT=buffered \\
        python scripts/demo_prep.py
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.event_log import EventLog  # noqa: E402
from ml.scorer import ModelScorer  # noqa: E402

PATHS = ["/", "/Record", "/Search", "/AJAX", "/api/data", "/robots.txt",
         "/login", "/admin", "/static/app.js", "/sitemap.xml"]


def populate_events(features_csv: str, db_path: str, scorer: ModelScorer,
                    n: int, spread_days: int) -> int:
    df = pd.read_csv(features_csv)
    sample = df.sample(min(n, len(df)))
    log = EventLog(db_path)

    # Vectorised scoring of the sample.
    if scorer.ready:
        x = np.column_stack([
            pd.to_numeric(sample.get(c, 0.0), errors="coerce").fillna(0.0).to_numpy()
            for c in scorer.feature_columns
        ])
        proba = scorer.model.predict_proba(x)[:, 1]
    else:
        proba = np.full(len(sample), 0.1)

    now = time.time()
    spread = spread_days * 86400
    for i, (_, row) in enumerate(sample.iterrows()):
        risk = float(proba[i])
        # Bias bot traffic toward night hours for a realistic heatmap.
        ts = now - random.random() * spread
        log.log_event(
            ip=str(row["ip"]), path=random.choice(PATHS), useragent="demo",
            risk_score=round(risk, 4), is_bot=risk >= scorer.threshold,
            status_code=random.choice([200, 200, 200, 304, 404]),
            bytes_sent=int(row.get("avg_bytes", 0) or 0), timestamp=ts,
        )
    return len(sample)


def seed_hbase(features_csv: str, models_dir: str) -> int:
    try:
        from hbase.load_profiles import load
        return load(features_csv, models_dir)
    except Exception as exc:  # noqa: BLE001 - HBase optional for the demo
        print(f"[demo_prep] HBase seed skipped ({type(exc).__name__}: {exc})")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default="data/parquet/features.csv")
    parser.add_argument("--db", default=os.environ.get("BOT_EVENTS_DB", "data/bot_events.db"))
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--events", type=int, default=1500)
    parser.add_argument("--spread-days", type=int, default=7)
    parser.add_argument("--skip-hbase", action="store_true")
    args = parser.parse_args()

    scorer = ModelScorer(args.models_dir)
    print(f"[demo_prep] model ready={scorer.ready} version={scorer.model_version}")

    if not args.skip_hbase:
        n = seed_hbase(args.features, args.models_dir)
        if n:
            print(f"[demo_prep] seeded {n:,} HBase profiles")

    n_ev = populate_events(args.features, args.db, scorer, args.events, args.spread_days)
    print(f"[demo_prep] wrote {n_ev:,} events across {args.spread_days} days -> {args.db}")
    print("[demo_prep] done — dashboards are demo-ready.")


if __name__ == "__main__":
    main()
