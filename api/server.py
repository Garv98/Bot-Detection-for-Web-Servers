"""FastAPI bot-detection serving layer (Phase 5).

Endpoints
---------
POST   /api/check                    score a single live request {ip, useragent, path}
GET    /api/score                    firewall/WAF lookup by ?ip=
POST   /api/bulk-score               score many IPs at once (vectorised)
GET    /api/stats                    totals, bot ratio, top-10 flagged IPs
GET    /api/health                   model version, HBase status, uptime
GET    /api/analytics/top-paths      top paths by volume (bot vs human)
GET    /api/analytics/cidr-activity  top /24 subnets by event count
GET    /api/events/summary           live event-log summary stats
GET    /api/events/recent            recent events (limit/offset/since_id)
DELETE /api/events                   clear the event log (X-Admin-Token)

Rate limiting (slowapi, keyed on the caller's source address; honours
X-Forwarded-For):
    * 100 req/min per exact IP
    * 500 req/min per /24 CIDR block
Allowlisted IPs (config/allowlist.txt) skip both rate limiting and scoring.

Blocking I/O (HBase, SQLite, DuckDB, the pandas replay) is pushed to a thread
pool so the async event loop is never blocked. HBase profile reads are cached
for ``HBASE_CACHE_TTL`` seconds in an asyncio-locked TTL dict. Configuration is
entirely via environment variables; no hardcoded secrets.

Run:
    uvicorn api.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json
import logging
import os
import re
import sys
import time
import uuid
from typing import Any, Optional

# --- make sibling packages importable when run as `python api/server.py` ---
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import (  # noqa: E402
    FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402
from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from api import analytics  # noqa: E402
from db.event_log import EventLog, cidr_block  # noqa: E402
from hbase.client import HBaseClient  # noqa: E402
from ml.scorer import ModelScorer, decide, signal_breakdown, ua_features  # noqa: E402

# --------------------------------------------------------------------------
# Configuration (env-driven)
# --------------------------------------------------------------------------
MODELS_DIR = os.environ.get("MODELS_DIR", "models")
ALLOWLIST_PATH = os.environ.get("ALLOWLIST_PATH", "config/allowlist.txt")
RATE_LIMIT_IP = os.environ.get("RATE_LIMIT_IP", "100/minute")
RATE_LIMIT_CIDR = os.environ.get("RATE_LIMIT_CIDR", "500/minute")
HBASE_CACHE_TTL = int(os.environ.get("HBASE_CACHE_TTL", "60"))
# Admin endpoints fail closed: with no ADMIN_TOKEN set they are disabled (503)
# rather than guessable. Set ADMIN_TOKEN in the environment to enable them.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or None
PROFILE_CACHE_MAX = int(os.environ.get("PROFILE_CACHE_MAX", "50000"))
RATE_LIMIT_ADMIN = os.environ.get("RATE_LIMIT_ADMIN", "30/minute")
ANALYTICS_CACHE = "max-age=30"
# How often the /ws/live WebSocket polls the event log for new detections to
# push to connected clients (real-time monitoring layer).
WS_POLL_SECONDS = float(os.environ.get("WS_POLL_SECONDS", "1.5"))

START_TIME = time.time()

# Per-request context populated by middleware.
_current_ip: contextvars.ContextVar[str] = contextvars.ContextVar("current_ip", default="")
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


# --------------------------------------------------------------------------
# Structured logging (request_id on every line; JSON when LOG_FORMAT=json)
# --------------------------------------------------------------------------
class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in ("path", "method", "status", "ip"):
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        return json.dumps(payload)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if os.environ.get("LOG_FORMAT", "").lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    return logging.getLogger("botsentry.api")


logger = _setup_logging()


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
        logger.info("HBase connected at %s:%s", client.host, client.port)
        return client, "connected"
    except Exception as exc:  # noqa: BLE001 - want any connection failure
        logger.warning("HBase unreachable (%s); using in-memory backend", exc)
        try:
            return HBaseClient(use_fake=True), "fake (HBase unreachable)"
        except Exception:  # pragma: no cover
            logger.error("In-memory HBase backend also failed to initialise")
            return None, "unavailable"


hbase_client, HBASE_STATUS = _connect_hbase()

if ADMIN_TOKEN is None:
    logger.warning("ADMIN_TOKEN is not set — admin endpoints (DELETE /api/events, "
                   "POST /api/allowlist) are DISABLED. Set ADMIN_TOKEN to enable them.")


def _require_admin(token: Optional[str]) -> None:
    """Gate admin endpoints: fail closed if no token is configured, 403 on
    mismatch. Constant-time compare to avoid token-length/timing leaks."""
    import hmac
    if ADMIN_TOKEN is None:
        raise HTTPException(status_code=503, detail="admin endpoints disabled (ADMIN_TOKEN unset)")
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="invalid admin token")


def _is_exempt() -> bool:
    return allowlist.contains(_current_ip.get())


limiter = Limiter(key_func=ip_key)
app = FastAPI(title="Bot Detection API", version=scorer.model_version)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --------------------------------------------------------------------------
# Middleware: request id + caller ip
# --------------------------------------------------------------------------
class _RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        _request_id.set(rid)
        _current_ip.set(_caller_ip(request))
        start = time.time()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method, request.url.path, response.status_code,
            (time.time() - start) * 1000,
            extra={"path": request.url.path, "method": request.method,
                   "status": response.status_code, "ip": _current_ip.get()},
        )
        return response


# Middleware is applied outermost-first by the LAST add_middleware call, so add
# the context middleware first and CORS last — CORS must be outermost so that
# even error responses (500s, 429s) carry Access-Control-Allow-Origin.
app.add_middleware(_RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# --------------------------------------------------------------------------
# HBase profile cache — bounded LRU + TTL, guarded by an asyncio.Lock.
# (A plain dict keyed by IP would grow without bound as new IPs are scored.)
# --------------------------------------------------------------------------
from collections import OrderedDict  # noqa: E402

_profile_cache: "OrderedDict[str, tuple[float, dict[str, str]]]" = OrderedDict()
_cache_lock = asyncio.Lock()


async def get_profile_cached(ip: str) -> dict[str, str]:
    now = time.time()
    async with _cache_lock:
        hit = _profile_cache.get(ip)
        if hit and now - hit[0] < HBASE_CACHE_TTL:
            _profile_cache.move_to_end(ip)  # mark as recently used
            return hit[1]
    if hbase_client is None:
        return {}
    try:
        profile = await run_in_threadpool(hbase_client.get_profile, ip)
    except Exception:  # noqa: BLE001 - HBase optional; never fail a request on it
        logger.warning("HBase get_profile failed for %s", ip)
        profile = {}
    async with _cache_lock:
        _profile_cache[ip] = (time.time(), profile)
        _profile_cache.move_to_end(ip)
        # Evict least-recently-used entries past the cap.
        while len(_profile_cache) > PROFILE_CACHE_MAX:
            _profile_cache.popitem(last=False)
    return profile


# --------------------------------------------------------------------------
# Request/response models
# --------------------------------------------------------------------------
# The Zenodo dataset anonymises IPs into a dotted pseudo-form (e.g.
# "216.244.58782" preserves the /16 group while masking the host bits), so a
# strict IPvAnyAddress check would reject the real demo data. We accept either a
# genuine IPv4/IPv6 address OR that dotted-numeric pseudo-form, and reject
# anything else (garbage / injection attempts).
_PSEUDO_IP = re.compile(r"^\d{1,5}(\.\d{1,5}){2,3}$")


def _valid_ip(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("ip must not be empty")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if _PSEUDO_IP.match(value):
        return value
    raise ValueError("ip must be a valid IPv4/IPv6 address or dataset pseudo-IP")


class CheckRequest(BaseModel):
    ip: str
    useragent: Optional[str] = Field(default=None, max_length=1024)
    path: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        return _valid_ip(v)

    @field_validator("path")
    @classmethod
    def _check_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not v.startswith("/"):
            raise ValueError("path must start with '/'")
        return v


class BulkScoreRequest(BaseModel):
    ips: list[str] = Field(default_factory=list, max_length=1000)


class AllowlistRequest(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        return _valid_ip(v)


class SimulateRequest(BaseModel):
    n: int = Field(default=200, ge=1, le=20000)
    clear_first: bool = False


# --------------------------------------------------------------------------
# Core scoring helper
# --------------------------------------------------------------------------
async def score_ip(ip: str, useragent: Optional[str] = None) -> dict[str, Any]:
    profile = await get_profile_cached(ip)
    # Merge stored behavioural features with on-the-fly UA features.
    feats: dict[str, Any] = dict(profile)
    if useragent is not None:
        feats.update(ua_features(useragent))
    risk_score, is_bot, reason = await run_in_threadpool(scorer.score, profile, useragent)
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


def _persist_check(ip: str, path: Optional[str], useragent: Optional[str],
                   result: dict[str, Any]) -> None:
    """Blocking persistence (SQLite + HBase), run in a thread pool."""
    event_log.log_event(
        ip=ip, path=path, useragent=useragent,
        risk_score=result["risk_score"], is_bot=result["is_bot"],
    )
    if hbase_client is not None:
        try:
            hbase_client.upsert_profile(ip, {
                **ua_features(useragent),
                "risk_score": result["risk_score"],
                "is_bot": int(result["is_bot"]),
                "threshold_used": scorer.threshold,
                "model_version": scorer.model_version,
            })
            if result["is_bot"]:
                hbase_client.flag_ip(ip, reason=result["reason"],
                                     request_count=result["req_count"])
        except Exception:  # noqa: BLE001 - HBase optional
            logger.warning("HBase persist failed for %s", ip)


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
                     "severity": "ok", "note": "IP is on the allowlist — scoring skipped"}],
                **decide(0.0, False, allowlisted=True)}
    result = await score_ip(body.ip, useragent=body.useragent)
    await run_in_threadpool(_persist_check, body.ip, body.path, body.useragent, result)
    decision = decide(result["risk_score"], result["is_bot"])
    return {**{k: result[k] for k in
               ("ip", "risk_score", "is_bot", "reason", "session_count", "features", "signals")},
            **decision}


@app.get("/api/score")
@limiter.limit(RATE_LIMIT_IP, exempt_when=_is_exempt)
@limiter.limit(RATE_LIMIT_CIDR, key_func=cidr_key, exempt_when=_is_exempt)
async def score(request: Request, ip: str = Query(..., description="IP to score")) -> dict[str, Any]:
    if allowlist.contains(ip):
        return {"ip": ip, "risk_score": 0.0, "flagged": False,
                "last_seen": None, "req_count": 0}
    r = await score_ip(ip)
    return {"ip": ip, "risk_score": r["risk_score"], "flagged": r["is_bot"],
            "last_seen": r["last_seen"], "req_count": r["req_count"]}


@app.post("/api/bulk-score")
@limiter.limit(RATE_LIMIT_IP, exempt_when=_is_exempt)
@limiter.limit(RATE_LIMIT_CIDR, key_func=cidr_key, exempt_when=_is_exempt)
async def bulk_score(request: Request, body: BulkScoreRequest) -> list[dict[str, Any]]:
    # Fetch profiles (cached), then score the whole batch in one vectorised call.
    to_score: list[tuple[int, str]] = []
    out: list[Optional[dict[str, Any]]] = [None] * len(body.ips)
    profiles: list[dict[str, Any]] = []
    for i, ip in enumerate(body.ips):
        if allowlist.contains(ip):
            out[i] = {"ip": ip, "risk_score": 0.0, "is_bot": False}
            continue
        to_score.append((i, ip))
        profiles.append(await get_profile_cached(ip))
    if to_score:
        scored = await run_in_threadpool(scorer.score_batch, profiles)
        for (i, ip), (risk, is_bot, _reason) in zip(to_score, scored):
            out[i] = {"ip": ip, "risk_score": risk, "is_bot": is_bot}
    return [r for r in out if r is not None]


@app.post("/api/allowlist")
@limiter.limit(RATE_LIMIT_ADMIN)
async def add_allowlist(request: Request, body: AllowlistRequest,
                        x_admin_token: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """Add an IP to the in-memory allowlist and persist it to the allowlist
    file so future scoring skips it. Idempotent. Admin-only: allowlisting an IP
    bypasses both scoring and rate limiting, so it must be authenticated."""
    _require_admin(x_admin_token)
    ip = body.ip
    already = allowlist.contains(ip)
    if not already:
        allowlist.exact.add(ip)
        try:
            await run_in_threadpool(_append_allowlist_file, ip)
        except OSError:
            logger.warning("could not persist allowlist entry %s to file", ip)
    return {"ip": ip, "allowlisted": True, "already_present": already}


def _append_allowlist_file(ip: str) -> None:
    with open(ALLOWLIST_PATH, "a", encoding="utf-8") as fh:
        fh.write(f"{ip}\n")


@app.get("/api/stats")
async def stats(request: Request) -> dict[str, Any]:
    s = await run_in_threadpool(event_log.stats, 10)
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
async def analytics_overview(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = ANALYTICS_CACHE
    return await run_in_threadpool(analytics.overview)


@app.get("/api/analytics/top-bots")
async def analytics_top_bots(request: Request, response: Response, limit: int = 20) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = ANALYTICS_CACHE
    return await run_in_threadpool(analytics.top_bots, limit)


@app.get("/api/analytics/risk-distribution")
async def analytics_risk_distribution(request: Request, response: Response) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = ANALYTICS_CACHE
    return await run_in_threadpool(analytics.risk_distribution)


@app.get("/api/analytics/scatter")
async def analytics_scatter(request: Request, response: Response, limit: int = 600) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = ANALYTICS_CACHE
    return await run_in_threadpool(analytics.scatter_sample, limit)


@app.get("/api/analytics/top-paths")
async def analytics_top_paths(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    """Top requested paths from the live event log, split bot vs human."""
    return await run_in_threadpool(analytics.top_paths, event_log, limit)


@app.get("/api/analytics/cidr-activity")
async def analytics_cidr_activity(request: Request, limit: int = 15) -> list[dict[str, Any]]:
    """Top /24 subnets by event count with bot ratio (WAF-ready intel)."""
    return await run_in_threadpool(analytics.cidr_activity, event_log, limit)


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
    return await run_in_threadpool(analytics.events_timeseries, event_log, bucket_seconds)


@app.get("/api/events/heatmap")
async def events_heatmap(request: Request) -> list[dict[str, Any]]:
    return await run_in_threadpool(analytics.events_heatmap, event_log)


@app.get("/api/events/summary")
async def events_summary(request: Request) -> dict[str, Any]:
    """Live event-log rollup for the dashboard header."""
    return await run_in_threadpool(analytics.events_summary, event_log)


@app.get("/api/events/recent")
async def events_recent(
    request: Request,
    limit: int = 12,
    offset: int = 0,
    since_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Most recent scored events for the live detections feed. ``since_id``
    lets the frontend poll incrementally without re-fetching seen rows."""
    return await run_in_threadpool(event_log.get_recent, limit, offset, since_id)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """Real-time monitoring channel (Analytics layer in the architecture).

    On connect, pushes a snapshot of recent detections + the live summary, then
    streams newly-scored events as they land — a true server push, so the
    dashboard feed updates without polling.
    """
    await websocket.accept()
    logger.info("ws_live client connected")
    try:
        # Send a snapshot on connect, then push the latest detections each tick.
        # Always sending the latest window (rather than tracking a server-side
        # cursor) keeps the feed correct across the Clear / Reset buttons, which
        # truncate the table and reset the autoincrement id. The client dedups by
        # id, so re-sent rows don't churn the UI.
        msg_type = "snapshot"
        while True:
            events = await run_in_threadpool(event_log.get_recent, 25, 0, None)
            summary = await run_in_threadpool(event_log.summary)
            await websocket.send_json({"type": msg_type, "events": events, "summary": summary})
            msg_type = "events"
            await asyncio.sleep(WS_POLL_SECONDS)
    except WebSocketDisconnect:
        logger.info("ws_live client disconnected")
    except Exception:  # noqa: BLE001 - never let a socket error crash the app
        logger.warning("ws_live connection closed on error")
        try:
            await websocket.close()
        except Exception:  # pragma: no cover
            pass


@app.delete("/api/events")
@limiter.limit(RATE_LIMIT_ADMIN)
async def clear_events(request: Request, x_admin_token: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """Truncate the live event log (demo reset). Requires X-Admin-Token."""
    _require_admin(x_admin_token)
    removed = await run_in_threadpool(event_log.clear)
    logger.info("event log cleared (%s rows) via admin endpoint", removed)
    return {"cleared": True, "removed": removed}


@app.post("/api/simulate")
@limiter.limit(RATE_LIMIT_ADMIN)
async def simulate(request: Request, body: SimulateRequest) -> dict[str, Any]:
    """Replay real IPs from the feature table through the scorer into the live
    event log AND the HBase profile store so the dashboard charts populate."""
    return await run_in_threadpool(
        analytics.simulate_traffic, event_log, scorer, hbase_client, body.n, 7200, body.clear_first
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")))
