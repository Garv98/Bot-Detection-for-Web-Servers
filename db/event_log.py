"""SQLite event log for live bot-detection events (Phase 6).

Every scored request can be appended to ``bot_events`` for the Superset live
dashboard.  Provides schema creation, indexes, and the derived ``session_id``
and ``cidr_block`` helpers.

    session_id  = MD5(ip + floor(timestamp / 1800))   # 30-min session bucket
    cidr_block  = first three octets + '.0/24'

Path comes from ``BOT_EVENTS_DB`` env var (default: ``data/bot_events.db``).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from typing import Any, Optional

DEFAULT_DB_PATH = os.environ.get("BOT_EVENTS_DB", "data/bot_events.db")

SESSION_WINDOW_SECONDS = 1800

SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ip          TEXT    NOT NULL,
    timestamp   REAL    NOT NULL,
    path        TEXT,
    useragent   TEXT,
    risk_score  REAL,
    is_bot      INTEGER,
    status_code INTEGER,
    bytes_sent  INTEGER,
    session_id  TEXT,
    cidr_block  TEXT
);
CREATE INDEX IF NOT EXISTS idx_timestamp ON bot_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_ip        ON bot_events(ip);
CREATE INDEX IF NOT EXISTS idx_path      ON bot_events(path);
CREATE INDEX IF NOT EXISTS idx_is_bot    ON bot_events(is_bot);
"""


def session_id(ip: str, timestamp: float) -> str:
    """MD5(ip + floor(timestamp / 1800)) -> stable per 30-minute window."""
    bucket = int(timestamp // SESSION_WINDOW_SECONDS)
    return hashlib.md5(f"{ip}{bucket}".encode()).hexdigest()


def cidr_block(ip: str) -> str:
    """First three octets + '.0/24'.  Returns '' for non-dotted-quad input."""
    parts = ip.split(".")
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
    return ""


class EventLog:
    """Thin SQLite wrapper for the ``bot_events`` table."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        # NORMAL is safe under WAL and substantially faster for the high write
        # volume of the live event log (only loses the very last txn on power loss).
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def log_event(
        self,
        ip: str,
        path: Optional[str] = None,
        useragent: Optional[str] = None,
        risk_score: Optional[float] = None,
        is_bot: Optional[bool] = None,
        status_code: Optional[int] = None,
        bytes_sent: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """Append one event; derives session_id and cidr_block. Returns row id."""
        ts = time.time() if timestamp is None else timestamp
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO bot_events
                   (ip, timestamp, path, useragent, risk_score, is_bot,
                    status_code, bytes_sent, session_id, cidr_block)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ip, ts, path, useragent, risk_score,
                    None if is_bot is None else int(is_bot),
                    status_code, bytes_sent,
                    session_id(ip, ts), cidr_block(ip),
                ),
            )
            return int(cur.lastrowid)

    def log_events_batch(self, events: list[dict[str, Any]]) -> int:
        """Insert many events in a single transaction. Each dict accepts the
        same keys as ``log_event``. Far cheaper than calling ``log_event`` in a
        loop (one connection + one commit instead of N). Returns rows written."""
        if not events:
            return 0
        rows = []
        for e in events:
            ts = time.time() if e.get("timestamp") is None else e["timestamp"]
            is_bot = e.get("is_bot")
            ip = e["ip"]
            rows.append((
                ip, ts, e.get("path"), e.get("useragent"), e.get("risk_score"),
                None if is_bot is None else int(is_bot),
                e.get("status_code"), e.get("bytes_sent"),
                session_id(ip, ts), cidr_block(ip),
            ))
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO bot_events
                   (ip, timestamp, path, useragent, risk_score, is_bot,
                    status_code, bytes_sent, session_id, cidr_block)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    def stats(self, top_n: int = 10) -> dict[str, Any]:
        """Aggregate stats for the admin endpoint."""
        with self._connect() as conn:
            total_events = conn.execute("SELECT COUNT(*) FROM bot_events").fetchone()[0]
            total_ips = conn.execute("SELECT COUNT(DISTINCT ip) FROM bot_events").fetchone()[0]
            bot_events = conn.execute(
                "SELECT COUNT(*) FROM bot_events WHERE is_bot=1"
            ).fetchone()[0]
            top = conn.execute(
                """SELECT ip, COUNT(*) AS req_count,
                          MAX(risk_score) AS max_risk,
                          MAX(is_bot) AS flagged
                   FROM bot_events
                   GROUP BY ip
                   ORDER BY flagged DESC, req_count DESC
                   LIMIT ?""",
                (top_n,),
            ).fetchall()
        bot_ratio = (bot_events / total_events) if total_events else 0.0
        return {
            "total_events": total_events,
            "total_ips": total_ips,
            "bot_events": bot_events,
            "bot_ratio": round(bot_ratio, 4),
            "top_flagged": [dict(r) for r in top],
        }

    def summary(self) -> dict[str, Any]:
        """Single-object live rollup for the dashboard header."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*)                                  AS total_events,
                          COALESCE(SUM(CASE WHEN is_bot=1 THEN 1 ELSE 0 END), 0) AS bot_events,
                          COUNT(DISTINCT ip)                        AS unique_ips,
                          COUNT(DISTINCT path)                      AS unique_paths,
                          MAX(timestamp)                            AS last_event_at
                   FROM bot_events"""
            ).fetchone()
        total = row["total_events"] or 0
        bots = row["bot_events"] or 0
        return {
            "total_events": int(total),
            "bot_events": int(bots),
            "human_events": int(total - bots),
            "bot_ratio": round(bots / total, 4) if total else 0.0,
            "unique_ips": int(row["unique_ips"] or 0),
            "unique_paths": int(row["unique_paths"] or 0),
            "last_event_at": float(row["last_event_at"]) if row["last_event_at"] is not None else None,
        }

    def get_recent(
        self,
        limit: int = 12,
        offset: int = 0,
        since_id: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Most recent events, newest first. ``since_id`` returns only rows with
        a higher id (efficient incremental polling); ``offset`` paginates."""
        clause = "WHERE id > ?" if since_id is not None else ""
        params: list[Any] = [since_id] if since_id is not None else []
        params += [int(limit), int(offset)]
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT id, ip, timestamp, path, risk_score, is_bot, cidr_block
                    FROM bot_events {clause}
                    ORDER BY id DESC LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [
            {"id": int(r["id"]), "ip": r["ip"], "t": float(r["timestamp"]),
             "path": r["path"], "risk_score": r["risk_score"],
             "is_bot": int(r["is_bot"] or 0), "cidr_block": r["cidr_block"]}
            for r in rows
        ]

    def clear(self) -> int:
        """Delete all events and reset the autoincrement counter. Returns the
        number of rows removed."""
        with self._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM bot_events").fetchone()[0]
            conn.execute("DELETE FROM bot_events")
            conn.execute("DELETE FROM sqlite_sequence WHERE name='bot_events'")
        return int(n)

    def top_paths(self, limit: int = 20) -> list[dict[str, Any]]:
        """Most-requested paths, split bot vs human."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT COALESCE(path, '—')                         AS path,
                          COUNT(*)                                    AS total,
                          SUM(CASE WHEN is_bot=1 THEN 1 ELSE 0 END)   AS bots,
                          SUM(CASE WHEN is_bot=0 THEN 1 ELSE 0 END)   AS humans
                   FROM bot_events
                   GROUP BY path ORDER BY total DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [{"path": r["path"], "total": int(r["total"]),
                 "bots": int(r["bots"] or 0), "humans": int(r["humans"] or 0)} for r in rows]

    def cidr_activity(self, limit: int = 15) -> list[dict[str, Any]]:
        """Top /24 subnets by event count, with bot ratio (WAF-ready intel)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT cidr_block,
                          COUNT(*)                                  AS total,
                          SUM(CASE WHEN is_bot=1 THEN 1 ELSE 0 END) AS bots,
                          SUM(CASE WHEN is_bot=0 THEN 1 ELSE 0 END) AS humans
                   FROM bot_events
                   WHERE cidr_block IS NOT NULL AND cidr_block != ''
                   GROUP BY cidr_block ORDER BY total DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        out = []
        for r in rows:
            total = int(r["total"])
            bots = int(r["bots"] or 0)
            out.append({"cidr_block": r["cidr_block"], "total": total, "bots": bots,
                        "humans": int(r["humans"] or 0),
                        "bot_ratio": round(bots / total, 4) if total else 0.0})
        return out


if __name__ == "__main__":
    log = EventLog("data/bot_events.db")
    rid = log.log_event(
        ip="1.2.3.4", path="/api/data", useragent="Crawl-Bot/1.0",
        risk_score=0.91, is_bot=True, status_code=200, bytes_sent=512,
    )
    print("inserted row", rid)
    print("session_id:", session_id("1.2.3.4", time.time()))
    print("cidr_block:", cidr_block("1.2.3.4"))
    print("stats:", log.stats())
