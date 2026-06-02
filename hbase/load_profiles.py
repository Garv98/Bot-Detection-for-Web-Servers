"""Seed the HBase ``bot_profiles`` table from the computed feature table.

Reads ``data/parquet/features.csv``, scores each IP with the trained model,
and bulk-upserts the full per-IP profile (stats + meta + score families) into
HBase. After running this, ``get_profile`` / ``get_risk_score`` and the
``/api/score`` endpoint return real data for the dataset's IPs.

Usage:
    # against the dockerised stack's thrift gateway:
    HBASE_HOST=localhost HBASE_PORT=9090 HBASE_THRIFT_TRANSPORT=buffered \\
        python hbase/load_profiles.py --features data/parquet/features.csv
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hbase.client import HBaseClient, META_FIELDS, STATS_FIELDS  # noqa: E402
from ml.scorer import ModelScorer  # noqa: E402


def load(features_path: str, models_dir: str, batch_size: int = 500,
         limit: int | None = None) -> int:
    df = pd.read_csv(features_path)
    if limit:
        df = df.head(limit)
    scorer = ModelScorer(models_dir)
    client = HBaseClient()  # uses HBASE_* env vars (real or fake)

    keep = [c for c in (STATS_FIELDS + META_FIELDS) if c in df.columns]

    # Vectorised scoring: one predict_proba over the whole matrix (far faster
    # than 27k per-row calls). Falls back to the heuristic if no model loaded.
    if scorer.ready:
        import numpy as np
        x = np.column_stack([
            pd.to_numeric(df.get(col, 0.0), errors="coerce").fillna(0.0).to_numpy()
            for col in scorer.feature_columns
        ])
        proba = scorer.model.predict_proba(x)[:, 1]
    else:
        proba = (
            ((df.get("ua_is_known_bot", 0) == 1) | (df.get("rate_404", 0) > 0.5))
            .astype(float) * 0.9 + 0.1
        ).to_numpy()

    ips = df["ip"].astype(str).tolist()
    profiles: list[dict] = []
    for i, (_, row) in enumerate(df.iterrows()):
        profiles.append({
            **{c: row[c] for c in keep},
            "risk_score": round(float(proba[i]), 4),
            "is_bot": int(proba[i] >= scorer.threshold),
            "threshold_used": scorer.threshold,
            "model_version": scorer.model_version,
        })

    n = client.bulk_upsert(ips, profiles, batch_size=batch_size)
    print(f"[load_profiles] upserted {n:,} profiles into HBase '{client.host}:{client.port}'")
    client.close()
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default="data/parquet/features.csv")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--limit", type=int, default=None, help="cap rows (debug)")
    args = parser.parse_args()
    load(args.features, args.models_dir, limit=args.limit)


if __name__ == "__main__":
    main()
