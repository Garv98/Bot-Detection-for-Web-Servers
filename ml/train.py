"""Train and compare bot-detection classifiers.

Loads ``data/parquet/features.csv`` (produced by the Spark/pandas ETL), trains
a RandomForest and a GradientBoosting classifier with 5-fold stratified CV,
and selects the model + decision threshold that maximises **recall subject to
precision >= 0.8** (missing a bot is worse than a false positive).

Artifacts written to ``models/``:
    best_model.pkl   joblib-pickled sklearn Pipeline (scaler + classifier)
    metrics.json     CV scores for both models + feature_importances
    threshold.txt    chosen decision threshold (float)

Usage:
    python ml/train.py --features data/parquet/features.csv --models-dir models
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MODEL_VERSION = "1.0.0"
TARGET = "is_robot"
# Columns that are identifiers / timestamps, not model features.
NON_FEATURES = {"ip", "first_seen", "last_seen", "date", TARGET}

MIN_PRECISION = 0.80
THRESHOLD_GRID = np.round(np.arange(0.30, 0.71, 0.01), 2)
N_SPLITS = 5
RANDOM_STATE = 42


def load_features(path: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    df = pd.read_csv(path)
    feature_cols = [c for c in df.columns if c not in NON_FEATURES]
    x = df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    y = df[TARGET].astype(int)
    return x, y, feature_cols


def build_models() -> dict[str, Pipeline]:
    """Two candidate pipelines (scaler is harmless for trees, helps consistency)."""
    return {
        "random_forest": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                n_estimators=200,
                class_weight="balanced",
                n_jobs=-1,
                random_state=RANDOM_STATE,
            )),
        ]),
        "gradient_boosting": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=200,
                learning_rate=0.05,
                random_state=RANDOM_STATE,
            )),
        ]),
    }


def best_threshold_for_recall(y_true: np.ndarray, y_proba: np.ndarray) -> tuple[float, dict[str, float]]:
    """Pick threshold in [0.3, 0.7] maximising recall s.t. precision >= 0.8.

    Falls back to the threshold with best F1 if no threshold satisfies the
    precision floor (e.g. tiny/degenerate datasets).
    """
    best: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    for thr in THRESHOLD_GRID:
        pred = (y_proba >= thr).astype(int)
        if pred.sum() == 0:
            continue
        prec = precision_score(y_true, pred, zero_division=0)
        rec = recall_score(y_true, pred, zero_division=0)
        f1 = f1_score(y_true, pred, zero_division=0)
        row = {"threshold": float(thr), "precision": prec, "recall": rec, "f1": f1}
        if fallback is None or f1 > fallback["f1"]:
            fallback = row
        if prec >= MIN_PRECISION:
            # maximise recall, tie-break on precision
            if best is None or (rec, prec) > (best["recall"], best["precision"]):
                best = row
    chosen = best or fallback or {"threshold": 0.5, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    return chosen["threshold"], chosen


def evaluate(name: str, model: Pipeline, x: pd.DataFrame, y: pd.Series,
             cv: StratifiedKFold) -> dict[str, Any]:
    """Cross-validated out-of-fold probabilities and metrics."""
    proba = cross_val_predict(model, x, y, cv=cv, method="predict_proba", n_jobs=-1)[:, 1]
    y_arr = y.to_numpy()
    thr, thr_metrics = best_threshold_for_recall(y_arr, proba)
    pred = (proba >= thr).astype(int)
    auc = roc_auc_score(y_arr, proba) if len(np.unique(y_arr)) > 1 else float("nan")
    return {
        "model": name,
        "threshold": thr,
        "precision": float(precision_score(y_arr, pred, zero_division=0)),
        "recall": float(recall_score(y_arr, pred, zero_division=0)),
        "f1": float(f1_score(y_arr, pred, zero_division=0)),
        "auc_roc": float(auc),
        "threshold_search": thr_metrics,
        "_proba": proba,  # internal; stripped before JSON dump
    }


def feature_importances(model: Pipeline, feature_cols: list[str]) -> dict[str, float]:
    clf = model.named_steps["clf"]
    importances = getattr(clf, "feature_importances_", None)
    if importances is None:
        return {}
    return {c: float(v) for c, v in sorted(
        zip(feature_cols, importances), key=lambda kv: kv[1], reverse=True
    )}


def train(features_path: str, models_dir: str) -> dict[str, Any]:
    os.makedirs(models_dir, exist_ok=True)
    x, y, feature_cols = load_features(features_path)
    print(f"[train] {len(x):,} rows, {len(feature_cols)} features, "
          f"{int(y.sum())} robots / {int((1 - y).sum())} humans")

    cv = StratifiedKFold(n_splits=min(N_SPLITS, int(y.value_counts().min())),
                         shuffle=True, random_state=RANDOM_STATE)
    models = build_models()
    results = {name: evaluate(name, m, x, y, cv) for name, m in models.items()}

    for name, r in results.items():
        print(f"[train] {name:18s} P={r['precision']:.3f} R={r['recall']:.3f} "
              f"F1={r['f1']:.3f} AUC={r['auc_roc']:.3f} thr={r['threshold']}")

    # Pick best model by recall, tie-break on precision (recall is priority).
    best_name = max(results, key=lambda n: (results[n]["recall"], results[n]["precision"]))
    best_result = results[best_name]
    print(f"[train] BEST = {best_name} (recall={best_result['recall']:.3f})")

    # Refit the winning pipeline on all data and persist.
    best_model = build_models()[best_name].fit(x, y)
    joblib.dump(best_model, os.path.join(models_dir, "best_model.pkl"))

    threshold = best_result["threshold"]
    with open(os.path.join(models_dir, "threshold.txt"), "w") as fh:
        fh.write(str(threshold))

    metrics = {
        "model_version": MODEL_VERSION,
        "best_model": best_name,
        "chosen_threshold": threshold,
        "feature_columns": feature_cols,
        "n_samples": int(len(x)),
        "n_robots": int(y.sum()),
        "models": {n: {k: v for k, v in r.items() if not k.startswith("_")}
                   for n, r in results.items()},
        "feature_importances": feature_importances(best_model, feature_cols),
    }
    with open(os.path.join(models_dir, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)

    print(f"[train] saved best_model.pkl, metrics.json, threshold.txt -> {models_dir}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default="data/parquet/features.csv")
    parser.add_argument("--models-dir", default="models")
    args = parser.parse_args()
    train(args.features, args.models_dir)


if __name__ == "__main__":
    main()
