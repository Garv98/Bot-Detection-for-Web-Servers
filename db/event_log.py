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
