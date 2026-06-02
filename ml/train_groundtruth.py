"""Honest, ground-truth model training on the official Zenodo labelled features.

Unlike ``train.py`` (which trains the per-IP *behavioural* model used for live
serving, on heuristic labels), this script trains on the dataset's own
**ground-truth** ``ROBOT`` label using the provided session-level feature sets:

    data/raw/simple_features*.csv   (31 traffic/structural features)
    data/raw/semantic_features*.csv (5 content/topic features)

joined 1:1 on ``ID``. Because the label is real (not derived from the
features), the reported precision/recall/F1/AUC are a genuine benchmark.

Reuses the evaluation machinery from ``train.py`` (5-fold StratifiedKFold,
recall-optimised threshold sweep, RF vs GBT).

Outputs:
    models/groundtruth_model.pkl
    models/groundtruth_metrics.json
    models/groundtruth_threshold.txt

Usage:
    python ml/train_groundtruth.py --raw-dir data/raw --models-dir models
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

# Allow `python ml/train_groundtruth.py` from the project root to import `ml.*`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reuse the shared training logic.
from ml.train import (  # noqa: E402
    MODEL_VERSION,
    N_SPLITS,
    RANDOM_STATE,
    build_models,
    evaluate,
    feature_importances,
)

TARGET = "ROBOT"


def _find(raw_dir: str, prefix: str) -> str:
    matches = sorted(glob.glob(os.path.join(raw_dir, f"{prefix}*.csv")))
    if not matches:
        raise FileNotFoundError(f"no {prefix}*.csv in {raw_dir}")
    return matches[0]


def load_groundtruth(raw_dir: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    simple = pd.read_csv(_find(raw_dir, "simple_features"))
    semantic = pd.read_csv(_find(raw_dir, "semantic_features"))
    df = simple.merge(semantic.drop(columns=[TARGET], errors="ignore"), on="ID", how="inner")

    feature_cols = [c for c in df.columns if c not in {"ID", TARGET}]
    x = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = df[TARGET].astype(int)
    return x, y, feature_cols


def train(raw_dir: str, models_dir: str) -> dict:
    os.makedirs(models_dir, exist_ok=True)
    x, y, feature_cols = load_groundtruth(raw_dir)
    print(f"[gt] {len(x):,} sessions, {len(feature_cols)} features, "
          f"{int(y.sum()):,} robots / {int((1 - y).sum()):,} humans (ground truth)")

    cv = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    models = build_models()
    results = {name: evaluate(name, m, x, y, cv) for name, m in models.items()}

    for name, r in results.items():
        print(f"[gt] {name:18s} P={r['precision']:.3f} R={r['recall']:.3f} "
              f"F1={r['f1']:.3f} AUC={r['auc_roc']:.3f} thr={r['threshold']}")

    best_name = max(results, key=lambda n: (results[n]["recall"], results[n]["precision"]))
    best_result = results[best_name]
    print(f"[gt] BEST = {best_name} (recall={best_result['recall']:.3f})")

    best_model = build_models()[best_name].fit(x, y)
    joblib.dump(best_model, os.path.join(models_dir, "groundtruth_model.pkl"))
    with open(os.path.join(models_dir, "groundtruth_threshold.txt"), "w") as fh:
        fh.write(str(best_result["threshold"]))

    metrics = {
        "model_version": MODEL_VERSION,
        "label": "ground_truth_ROBOT",
        "dataset": "zenodo simple+semantic features (per session)",
        "best_model": best_name,
        "chosen_threshold": best_result["threshold"],
        "feature_columns": feature_cols,
        "n_samples": int(len(x)),
        "n_robots": int(y.sum()),
        "models": {n: {k: v for k, v in r.items() if not k.startswith("_")}
                   for n, r in results.items()},
        "feature_importances": feature_importances(best_model, feature_cols),
    }
    with open(os.path.join(models_dir, "groundtruth_metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)
    print(f"[gt] saved groundtruth_model.pkl, groundtruth_metrics.json, "
          f"groundtruth_threshold.txt -> {models_dir}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--models-dir", default="models")
    args = parser.parse_args()
    train(args.raw_dir, args.models_dir)


if __name__ == "__main__":
    main()
