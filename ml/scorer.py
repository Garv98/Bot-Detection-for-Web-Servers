"""Runtime model scorer shared by the API.

Loads the artifacts produced by ``ml/train.py`` (``best_model.pkl``,
``threshold.txt``, ``metrics.json``) and scores IPs.  When a request arrives
for an IP we have an HBase profile for, we score the stored features; for an
unknown IP we derive the User-Agent features on the fly and score with the
remaining features defaulted to zero.

Designed to degrade gracefully: if no model is on disk, it falls back to a
transparent heuristic (known-bot UA => high risk) so the API still runs.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any, Optional

import joblib
import numpy as np

BOT_UA_REGEX = re.compile(
    r"(bot|crawl|spider|slurp|googlebot|bingbot|baiduspider|yandex|"
    r"duckduckbot|ahrefs|semrush|mj12bot|dotbot|petalbot|applebot|"
    r"facebookexternalhit|ia_archiver|icc-crawler|curl|wget|python-requests|"
    r"python-urllib|scrapy|httpclient|java/|go-http-client|libwww|okhttp|"
    r"headlesschrome|phantomjs)",
    re.IGNORECASE,
)
BROWSER_UA_REGEX = re.compile(r"(chrome|firefox|safari|edg|opera|msie|trident)", re.IGNORECASE)

DEFAULT_THRESHOLD = 0.5


def shannon_entropy(text: Optional[str]) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


def ua_features(useragent: Optional[str]) -> dict[str, float]:
    ua = useragent or ""
    is_bot = 1.0 if BOT_UA_REGEX.search(ua) else 0.0
    is_browser = 1.0 if (BROWSER_UA_REGEX.search(ua) and not is_bot) else 0.0
    return {
        "ua_is_known_bot": is_bot,
        "ua_is_browser": is_browser,
        "ua_entropy": shannon_entropy(ua),
    }


def _f(feats: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(feats.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def signal_breakdown(feats: dict[str, Any]) -> list[dict[str, Any]]:
    """Human-readable per-signal explanation of a verdict.

    Returns an ordered list of {key, label, value, severity, note} where
    severity is one of danger / warn / ok / info. Robust to missing features
    (an IP with no behavioural history is scored on its User-Agent alone).
    """
    has_history = _f(feats, "req_count") > 0
    known_bot = _f(feats, "ua_is_known_bot") == 1
    browser = _f(feats, "ua_is_browser") == 1
    rate_404 = _f(feats, "rate_404")
    rph = _f(feats, "requests_per_hour")
    upr = _f(feats, "unique_paths_ratio")
    err = _f(feats, "error_rate")
    entropy = _f(feats, "ua_entropy")
    req = _f(feats, "req_count")
    sessions = _f(feats, "session_count")

    signals: list[dict[str, Any]] = []

    if known_bot:
        signals.append({"key": "ua", "label": "User-Agent", "value": "known bot",
                        "severity": "danger", "note": "Matches a crawler/bot signature"})
    elif browser:
        signals.append({"key": "ua", "label": "User-Agent", "value": "browser",
                        "severity": "ok", "note": "Recognized browser fingerprint"})
    else:
        signals.append({"key": "ua", "label": "User-Agent", "value": "unrecognized",
                        "severity": "warn", "note": "Neither a known browser nor a known bot"})

    if has_history:
        signals.append({
            "key": "rate_404", "label": "404 rate", "value": f"{rate_404 * 100:.0f}%",
            "severity": "danger" if rate_404 > 0.5 else "warn" if rate_404 > 0.2 else "ok",
            "note": "Scanning for endpoints" if rate_404 > 0.2 else "Normal not-found rate"})
        signals.append({
            "key": "rph", "label": "Request rate", "value": f"{rph:,.0f}/hr",
            "severity": "danger" if rph > 1000 else "warn" if rph > 200 else "ok",
            "note": "Automated-level throughput" if rph > 200 else "Human-level pace"})
        signals.append({
            "key": "upr", "label": "Path diversity", "value": f"{upr:.2f}",
            "severity": "danger" if upr < 0.05 else "warn" if upr < 0.2 else "ok",
            "note": "Highly repetitive paths" if upr < 0.2 else "Varied browsing"})
        signals.append({
            "key": "err", "label": "Error rate", "value": f"{err * 100:.0f}%",
            "severity": "warn" if err > 0.5 else "ok",
            "note": "Many failed requests" if err > 0.5 else "Mostly successful"})
        signals.append({
            "key": "vol", "label": "Volume", "value": f"{req:,.0f} reqs / {sessions:,.0f} sess",
            "severity": "info", "note": "Observed in the dataset"})
    else:
        signals.append({"key": "history", "label": "Behavioural history", "value": "none",
                        "severity": "info",
                        "note": "Unseen IP — scored on User-Agent only"})

    signals.append({"key": "entropy", "label": "UA entropy", "value": f"{entropy:.2f} bits",
                    "severity": "info", "note": "Character randomness of the User-Agent"})
    return signals


class ModelScorer:
    def __init__(self, models_dir: str = "models") -> None:
        self.models_dir = models_dir
        self.model: Any = None
        self.threshold: float = DEFAULT_THRESHOLD
        self.feature_columns: list[str] = []
        self.model_version: str = "heuristic"
        self.load()

    def load(self) -> None:
        model_path = os.path.join(self.models_dir, "best_model.pkl")
        thr_path = os.path.join(self.models_dir, "threshold.txt")
        metrics_path = os.path.join(self.models_dir, "metrics.json")

        if os.path.exists(model_path):
            try:
                self.model = joblib.load(model_path)
            except Exception as exc:  # noqa: BLE001 - degrade to heuristic, don't crash
                print(f"[scorer] could not load {model_path}: {exc}; using heuristic")
                self.model = None
        if os.path.exists(thr_path):
            try:
                self.threshold = float(open(thr_path).read().strip())
            except ValueError:
                pass
        if os.path.exists(metrics_path):
            import json
            meta = json.load(open(metrics_path))
            self.feature_columns = meta.get("feature_columns", [])
            self.model_version = meta.get("model_version", self.model_version)

    @property
    def ready(self) -> bool:
        return self.model is not None and bool(self.feature_columns)

    def _vector(self, features: dict[str, Any]) -> np.ndarray:
        row = [float(features.get(col, 0.0) or 0.0) for col in self.feature_columns]
        return np.asarray([row], dtype=float)

    def score(
        self,
        features: Optional[dict[str, Any]] = None,
        useragent: Optional[str] = None,
    ) -> tuple[float, bool, str]:
        """Return (risk_score, is_bot, reason).

        ``features`` is a profile dict (e.g. from HBase); UA-derived features
        are merged in / override when a useragent is supplied.
        """
        feats: dict[str, Any] = dict(features or {})
        if useragent is not None:
            feats.update(ua_features(useragent))

        if self.ready:
            proba = float(self.model.predict_proba(self._vector(feats))[0, 1])
            is_bot = proba >= self.threshold
            reason = self._explain(feats, proba)
            return round(proba, 4), bool(is_bot), reason

        # Heuristic fallback (no trained model on disk).
        rate_404 = float(feats.get("rate_404", 0.0) or 0.0)
        known_bot = float(feats.get("ua_is_known_bot", 0.0) or 0.0)
        proba = 0.9 if (known_bot or rate_404 > 0.5) else 0.1
        return proba, proba >= self.threshold, "heuristic: known-bot UA or rate_404>0.5"

    def _explain(self, feats: dict[str, Any], proba: float) -> str:
        reasons = []
        if float(feats.get("ua_is_known_bot", 0) or 0) == 1:
            reasons.append("known-bot user-agent")
        if float(feats.get("rate_404", 0) or 0) > 0.5:
            reasons.append("high 404 rate")
        if float(feats.get("requests_per_hour", 0) or 0) > 1000:
            reasons.append("high request rate")
        if float(feats.get("unique_paths_ratio", 1) or 1) < 0.05:
            reasons.append("repetitive paths")
        if not reasons:
            reasons.append("model score above threshold" if proba >= self.threshold
                           else "model score below threshold")
        return "; ".join(reasons)
