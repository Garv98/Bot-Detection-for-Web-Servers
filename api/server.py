"""FastAPI bot-detection serving layer (Phase 5).

Endpoints
---------
POST /api/check        score a single live request {ip, useragent, path}
GET  /api/score        firewall/WAF lookup by ?ip=
POST /api/bulk-score   score many IPs at once
GET  /api/stats        totals, bot ratio, top-10 flagged IPs
GET  /api/health       model version, HBase status, uptime

Rate limiting (slowapi, keyed on the caller's source address; honours
X-Forwarded-For):
    * 100 req/min per exact IP
    * 500 req/min per /24 CIDR block
Allowlisted IPs (config/allowlist.txt) skip both rate limiting and scoring.

HBase reads are cached for 60s via functools.lru_cache (time-bucketed key).
Configuration is entirely via environment variables; no hardcoded secrets.

Run:
    uvicorn api.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import contextvars
import ipaddress
import os
import sys
import time
from functools import lru_cache
from typing import Any, Optional

# --- make sibling packages importable when run as `python api/server.py` ---
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from api import analytics  # noqa: E402
from db.event_log import EventLog, cidr_block  # noqa: E402
from hbase.client import HBaseClient  # noqa: E402
from ml.scorer import ModelScorer, signal_breakdown, ua_features  # noqa: E402

# --------------------------------------------------------------------------
# Configuration (env-driven)
# --------------------------------------------------------------------------
MODELS_DIR = os.environ.get("MODELS_DIR", "models")
ALLOWLIST_PATH = os.environ.get("ALLOWLIST_PATH", "config/allowlist.txt")
RATE_LIMIT_IP = os.environ.get("RATE_LIMIT_IP", "100/minute")
RATE_LIMIT_CIDR = os.environ.get("RATE_LIMIT_CIDR", "500/minute")
HBASE_CACHE_TTL = int(os.environ.get("HBASE_CACHE_TTL", "60"))

START_TIME = time.time()

# Current caller IP, populated by middleware so exempt_when() can read it.
_current_ip: contextvars.ContextVar[str] = contextvars.ContextVar("current_ip", default="")


# --------------------------------------------------------------------------
# Allowlist
# --------------------------------------------------------------------------
class Allowlist:
    def __init__(self, path: str) -> None:
        self.exact: set[str] = set()
        self.networks: list[ipaddress._BaseNetwork] = []
        self.load(path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        for line in open(path, encoding="utf-8"):
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            if "/" in entry:
                try:
                    self.networks.append(ipaddress.ip_network(entry, strict=False))
                except ValueError:
                    continue
            else:
                self.exact.add(entry)

    def contains(self, ip: str) -> bool:
        if not ip:
            return False
        if ip in self.exact:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.networks)


# --------------------------------------------------------------------------
# Key functions for slowapi
# --------------------------------------------------------------------------
def _caller_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ip_key(request: Request) -> str:
    return _caller_ip(request)


def cidr_key(request: Request) -> str:
    ip = _caller_ip(request)
    block = cidr_block(ip)
    return block or ip


# --------------------------------------------------------------------------
# App + shared services
# --------------------------------------------------------------------------
allowlist = Allowlist(ALLOWLIST_PATH)
scorer = ModelScorer(MODELS_DIR)
event_log = EventLog()


def _connect_hbase() -> tuple[Optional[HBaseClient], str]:
    """Try the real HBase; fall back to the in-memory backend if unreachable."""
    try:
        client = HBaseClient()  # autoconnects using HBASE_* env vars
        return client, "connected"
    except Exception as exc:  # noqa: BLE001 - want any connection failure
        try:
            return HBaseClient(use_fake=True), f"fake (unreachable: {type(exc).__name__})"
        except Exception:  # pragma: no cover
            return None, "unavailable"


hbase_client, HBASE_STATUS = _connect_hbase()


def _is_exempt() -> bool:
    return allowlist.contains(_current_ip.get())


limiter = Limiter(key_func=ip_key)
app = FastAPI(title="Bot Detection API", version=scorer.model_version)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS so the Next.js front end (default :3000) can call the API in dev.
class _CallerIPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        _current_ip.set(_caller_ip(request))
        return await call_next(request)


# Middleware is applied outermost-first by the LAST add_middleware call, so add
# the IP middleware first and CORS last — CORS must be outermost so that even
# error responses (500s, rate-limit 429s) carry Access-Control-Allow-Origin.
app.add_middleware(_CallerIPMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# HBase profile cache (60s TTL via time-bucketed lru_cache)
# --------------------------------------------------------------------------
@lru_cache(maxsize=8192)
def _cached_profile(ip: str, _bucket: int) -> dict[str, str]:
    if hbase_client is None:
        return {}
    try:
        return hbase_client.get_profile(ip)
    except Exception:  # noqa: BLE001 - HBase optional; never fail a request on it
        return {}


def get_profile_cached(ip: str) -> dict[str, str]:
    bucket = int(time.time() // HBASE_CACHE_TTL)
    return _cached_profile(ip, bucket)


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------
class CheckRequest(BaseModel):
    ip: str
    useragent: Optional[str] = None
    path: Optional[str] = None


class BulkScoreRequest(BaseModel):
    ips: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Core scoring helper
# --------------------------------------------------------------------------
def score_ip(ip: str, useragent: Optional[str] = None) -> dict[str, Any]:
    profile = get_profile_cached(ip)
    # Merge stored behavioural features with on-the-fly UA features.
    feats: dict[str, Any] = dict(profile)
    if useragent is not None:
        feats.update(ua_features(useragent))
    risk_score, is_bot, reason = scorer.score(features=profile, useragent=useragent)
    return {
        "ip": ip,
        "risk_score": risk_score,
        "is_bot": is_bot,
        "reason": reason,
        "session_count": int(profile.get("session_count", 0) or 0),
        "last_seen": profile.get("last_seen"),
        "req_count": int(profile.get("req_count", 0) or 0),
        "features": feats,
        "signals": signal_breakdown(feats),
    }


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.post("/api/check")
@limiter.limit(RATE_LIMIT_IP, exempt_when=_is_exempt)
@limiter.limit(RATE_LIMIT_CIDR, key_func=cidr_key, exempt_when=_is_exempt)
async def check(request: Request, body: CheckRequest) -> dict[str, Any]:
    if allowlist.contains(body.ip):
        return {"ip": body.ip, "risk_score": 0.0, "is_bot": False,
                "reason": "allowlisted", "session_count": 0,
                "features": {}, "signals": [
                    {"key": "allow", "label": "Allowlist", "value": "trusted",
                     "severity": "ok", "note": "IP is on the allowlist — scoring skipped"}]}
    result = score_ip(body.ip, useragent=body.useragent)
    # Persist to the live event log for Superset.
    event_log.log_event(
        ip=body.ip, path=body.path, useragent=body.useragent,
        risk_score=result["risk_score"], is_bot=result["is_bot"],
    )
    # Persist the score to the HBase profile store (score family + UA meta).
    if hbase_client is not None:
        try:
            hbase_client.upsert_profile(body.ip, {
                **ua_features(body.useragent),
                "risk_score": result["risk_score"],
                "is_bot": int(result["is_bot"]),
                "threshold_used": scorer.threshold,
                "model_version": scorer.model_version,
            })
            if result["is_bot"]:
                hbase_client.flag_ip(body.ip, reason=result["reason"],
                                     request_count=result["req_count"])
        except Exception:  # noqa: BLE001 - HBase optional
            pass
    return {k: result[k] for k in
            ("ip", "risk_score", "is_bot", "reason", "session_count", "features", "signals")}


@app.get("/api/score")
@limiter.limit(RATE_LIMIT_IP, exempt_when=_is_exempt)
@limiter.limit(RATE_LIMIT_CIDR, key_func=cidr_key, exempt_when=_is_exempt)
async def score(request: Request, ip: str = Query(..., description="IP to score")) -> dict[str, Any]:
    if allowlist.contains(ip):
        return {"ip": ip, "risk_score": 0.0, "flagged": False,
                "last_seen": None, "req_count": 0}
    r = score_ip(ip)
    return {"ip": ip, "risk_score": r["risk_score"], "flagged": r["is_bot"],
            "last_seen": r["last_seen"], "req_count": r["req_count"]}


@app.post("/api/bulk-score")
@limiter.limit(RATE_LIMIT_IP, exempt_when=_is_exempt)
@limiter.limit(RATE_LIMIT_CIDR, key_func=cidr_key, exempt_when=_is_exempt)
async def bulk_score(request: Request, body: BulkScoreRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ip in body.ips:
        if allowlist.contains(ip):
            out.append({"ip": ip, "risk_score": 0.0, "is_bot": False})
            continue
        r = score_ip(ip)
        out.append({"ip": ip, "risk_score": r["risk_score"], "is_bot": r["is_bot"]})
    return out


@app.get("/api/stats")
async def stats(request: Request) -> dict[str, Any]:
    s = event_log.stats(top_n=10)
    return {
        "total_ips": s["total_ips"],
        "total_events": s["total_events"],
        "bot_ratio": s["bot_ratio"],
        "top_flagged": s["top_flagged"],
    }


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "model_version": scorer.model_version,
        "model_ready": scorer.ready,
        "threshold": scorer.threshold,
        "hbase_status": HBASE_STATUS,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# --------------------------------------------------------------------------
# Analytics / dashboard endpoints (consumed by the Next.js UI)
# --------------------------------------------------------------------------
@app.get("/api/analytics/overview")
async def analytics_overview(request: Request) -> dict[str, Any]:
    return analytics.overview()


@app.get("/api/analytics/top-bots")
async def analytics_top_bots(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    return analytics.top_bots(limit=limit)


@app.get("/api/analytics/risk-distribution")
async def analytics_risk_distribution(request: Request) -> list[dict[str, Any]]:
    return analytics.risk_distribution()


@app.get("/api/analytics/scatter")
async def analytics_scatter(request: Request, limit: int = 600) -> list[dict[str, Any]]:
    return analytics.scatter_sample(limit=limit)


@app.get("/api/model/metrics")
async def model_metrics(request: Request) -> dict[str, Any]:
    return analytics.model_comparison()


@app.get("/api/model/feature-importances")
async def model_feature_importances(request: Request) -> list[dict[str, Any]]:
    return analytics.feature_importances()


@app.get("/api/model/groundtruth")
async def model_groundtruth(request: Request) -> dict[str, Any]:
    """Honest benchmark trained on the Zenodo ground-truth ROBOT label."""
    return analytics.groundtruth_comparison()


@app.get("/api/model/groundtruth/feature-importances")
async def model_groundtruth_fi(request: Request, limit: int = 15) -> list[dict[str, Any]]:
    return analytics.groundtruth_feature_importances(limit=limit)


@app.get("/api/events/timeseries")
async def events_timeseries(request: Request, bucket_seconds: int = 300) -> list[dict[str, Any]]:
    return analytics.events_timeseries(event_log, bucket_seconds=bucket_seconds)


@app.get("/api/events/heatmap")
async def events_heatmap(request: Request) -> list[dict[str, Any]]:
    return analytics.events_heatmap(event_log)


@app.get("/api/events/recent")
async def events_recent(request: Request, limit: int = 12) -> list[dict[str, Any]]:
    """Most recent scored events for the live detections feed."""
    return analytics.events_recent(event_log, limit=limit)


class SimulateRequest(BaseModel):
    n: int = 200


@app.post("/api/simulate")
async def simulate(request: Request, body: SimulateRequest) -> dict[str, Any]:
    """Replay real IPs from the feature table through the scorer into the live
    event log AND the HBase profile store so the dashboard charts populate."""
    return analytics.simulate_traffic(event_log, scorer, hbase_client=hbase_client, n=body.n)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")))
