"""HBase integration for per-IP bot profiles.

Table: ``bot_profiles`` (row key = IP address)

Column families:
    stats:  req_count, avg_interval, std_interval, min_interval,
            requests_per_hour, session_count, avg_session_length,
            unique_paths_ratio, error_rate, rate_404, avg_bytes, ua_entropy
    meta:   first_seen, last_seen, ua_is_known_bot, ua_is_browser
    score:  risk_score, is_bot, threshold_used, model_version
    alerts: flagged_at, reason, request_count_at_flag   (TTL = 3600s)

Connection details come from environment variables (no hardcoded creds):
    HBASE_HOST   (default: localhost)
    HBASE_PORT   (default: 9090, the Thrift port)
    HBASE_TABLE_PREFIX (optional)

If ``happybase``/the Thrift server is unavailable, set ``HBASE_FAKE=1`` (or
construct ``HBaseClient(use_fake=True)``) to use an in-memory backend with the
same API — useful for local development, CI, and smoke tests.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterable, Optional

# Column families and the TTL (seconds) applied to the alerts family.
COLUMN_FAMILIES: dict[str, dict[str, Any]] = {
    "stats": dict(),
    "meta": dict(),
    "score": dict(),
    "alerts": dict(time_to_live=3600),
}

TABLE_NAME = "bot_profiles"

# Which feature keys land in which column family.
STATS_FIELDS = [
    "req_count", "avg_interval", "std_interval", "min_interval",
    "requests_per_hour", "session_count", "avg_session_length",
    "unique_paths_ratio", "error_rate", "rate_404", "avg_bytes", "ua_entropy",
]
META_FIELDS = ["first_seen", "last_seen", "ua_is_known_bot", "ua_is_browser"]
SCORE_FIELDS = ["risk_score", "is_bot", "threshold_used", "model_version"]


def _b(value: Any) -> bytes:
    """Encode any value as HBase cell bytes."""
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _flatten(profile: dict[bytes, bytes]) -> dict[str, str]:
    """Turn a raw HBase row ({b'cf:col': b'val'}) into a flat {col: val} dict."""
    out: dict[str, str] = {}
    for raw_key, raw_val in profile.items():
        key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        col = key.split(":", 1)[1] if ":" in key else key
        out[col] = raw_val.decode() if isinstance(raw_val, bytes) else str(raw_val)
    return out


def _to_cells(feature_dict: dict[str, Any]) -> dict[bytes, bytes]:
    """Map a flat feature dict to fully-qualified HBase cells."""
    cells: dict[bytes, bytes] = {}
    for field in STATS_FIELDS:
        if field in feature_dict:
            cells[_b(f"stats:{field}")] = _b(feature_dict[field])
    for field in META_FIELDS:
        if field in feature_dict:
            cells[_b(f"meta:{field}")] = _b(feature_dict[field])
    for field in SCORE_FIELDS:
        if field in feature_dict:
            cells[_b(f"score:{field}")] = _b(feature_dict[field])
    return cells


class _FakeTable:
    """Minimal in-memory stand-in for a happybase Table."""

    def __init__(self) -> None:
        self._rows: dict[bytes, dict[bytes, bytes]] = {}

    def put(self, row: bytes, data: dict[bytes, bytes]) -> None:
        self._rows.setdefault(row, {}).update(data)

    def row(self, row: bytes, columns: Optional[Iterable[bytes]] = None) -> dict[bytes, bytes]:
        data = self._rows.get(row, {})
        if columns is None:
            return dict(data)
        wanted = {c if isinstance(c, bytes) else _b(c) for c in columns}
        return {k: v for k, v in data.items()
                if k in wanted or any(k.startswith(c + b":") for c in wanted)}

    def scan(self, **_kwargs: Any):
        for key, data in self._rows.items():
            yield key, dict(data)

    def batch(self, **_kwargs: Any) -> "_FakeBatch":
        return _FakeBatch(self)


class _FakeBatch:
    """Context-manager batch matching happybase's Table.batch() API."""

    def __init__(self, table: "_FakeTable") -> None:
        self._table = table

    def put(self, row: bytes, data: dict[bytes, bytes]) -> None:
        self._table.put(row, data)

    def __enter__(self) -> "_FakeBatch":
        return self

    def __exit__(self, *_exc: Any) -> None:
        pass


class _FakeConnection:
    """In-memory connection providing the slice of happybase we use."""

    def __init__(self) -> None:
        self._tables: dict[bytes, _FakeTable] = {}

    def create_table(self, name: str, families: dict[str, dict[str, Any]]) -> None:
        self._tables.setdefault(_b(name), _FakeTable())

    def tables(self) -> list[bytes]:
        return list(self._tables.keys())

    def table(self, name: str) -> _FakeTable:
        return self._tables.setdefault(_b(name), _FakeTable())

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


class HBaseClient:
    """Typed wrapper around the ``bot_profiles`` HBase table."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        table_prefix: Optional[str] = None,
        use_fake: Optional[bool] = None,
        autoconnect: bool = True,
    ) -> None:
        self.host = host or os.environ.get("HBASE_HOST", "localhost")
        self.port = int(port or os.environ.get("HBASE_PORT", "9090"))
        self.table_prefix = table_prefix or os.environ.get("HBASE_TABLE_PREFIX") or None
        # bde2020/HBase 1.x Thrift defaults to buffered transport / binary
        # protocol; expose both so deployments can match their gateway.
        self.transport = os.environ.get("HBASE_THRIFT_TRANSPORT", "buffered")
        self.protocol = os.environ.get("HBASE_THRIFT_PROTOCOL", "binary")
        if use_fake is None:
            use_fake = os.environ.get("HBASE_FAKE", "0") == "1"
        self.use_fake = use_fake
        self._conn: Any = None
        if autoconnect:
            self.connect()

    # -- connection / schema ------------------------------------------------
    def connect(self) -> None:
        if self.use_fake:
            self._conn = _FakeConnection()
        else:
            import happybase  # imported lazily so the fake path has no dependency

            self._conn = happybase.Connection(
                host=self.host, port=self.port, table_prefix=self.table_prefix,
                transport=self.transport, protocol=self.protocol,
            )
        self.ensure_table()

    def ensure_table(self) -> None:
        existing = {t.decode() if isinstance(t, bytes) else t for t in self._conn.tables()}
        if TABLE_NAME not in existing:
            self._conn.create_table(TABLE_NAME, COLUMN_FAMILIES)

    @property
    def table(self) -> Any:
        return self._conn.table(TABLE_NAME)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _op(self, fn):
        """Run an HBase op; on a dropped/stale Thrift socket, reconnect once
        and retry. Long-lived happybase connections go stale (the gateway
        closes idle sockets, or the HBase master restarts under it) and raise a
        variety of errors — BrokenPipeError/OSError, EOFError, or thriftpy2's
        ``TTransportException`` (which is *not* an OSError). happybase returns
        ``{}`` for a missing row rather than raising, so any exception here means
        a transport/connection problem: reconnect once and retry."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - treat any error as a stale conn
            try:
                self.connect()
                return fn()
            except Exception as retry_exc:  # noqa: BLE001
                raise retry_exc from exc

    # -- CRUD ---------------------------------------------------------------
    def upsert_profile(self, ip: str, feature_dict: dict[str, Any]) -> None:
        """Insert or update the stats/meta/score columns for an IP."""
        self._op(lambda: self.table.put(_b(ip), _to_cells(feature_dict)))

    def bulk_upsert(self, ip_list: list[str], feature_dicts: list[dict[str, Any]],
                    batch_size: int = 500) -> int:
        """Upsert many profiles at once (parallel lists). Returns count."""
        if len(ip_list) != len(feature_dicts):
            raise ValueError("ip_list and feature_dicts must be the same length")

        def _run() -> None:
            with self.table.batch(batch_size=batch_size) as batch:
                for ip, fd in zip(ip_list, feature_dicts):
                    batch.put(_b(ip), _to_cells(fd))

        self._op(_run)
        return len(ip_list)

    def get_profile(self, ip: str) -> dict[str, str]:
        """Return the full flattened profile for an IP ({} if unknown)."""
        return _flatten(self._op(lambda: self.table.row(_b(ip))))

    def get_risk_score(self, ip: str) -> float:
        """Return the stored risk score for an IP (0.0 if absent)."""
        row = self._op(lambda: self.table.row(_b(ip), columns=[b"score:risk_score"]))
        raw = row.get(b"score:risk_score")
        try:
            return float(raw.decode()) if raw is not None else 0.0
        except (ValueError, AttributeError):
            return 0.0

    def flag_ip(self, ip: str, reason: str, request_count: Optional[int] = None) -> None:
        """Write an alert (auto-expires after the alerts-family TTL of 3600s)."""
        if request_count is None:
            request_count = int(self.get_profile(ip).get("req_count", 0) or 0)
        self._op(lambda: self.table.put(_b(ip), {
            _b("alerts:flagged_at"): _b(int(time.time())),
            _b("alerts:reason"): _b(reason),
            _b("alerts:request_count_at_flag"): _b(request_count),
        }))


def main() -> None:
    """Tiny self-test against the in-memory backend."""
    client = HBaseClient(use_fake=True)
    client.upsert_profile("1.2.3.4", {
        "req_count": 1200, "avg_interval": 0.5, "rate_404": 0.7,
        "ua_is_known_bot": 1, "risk_score": 0.93, "is_bot": 1,
        "model_version": "1.0.0", "first_seen": "2018-03-01T00:00:00",
    })
    client.flag_ip("1.2.3.4", reason="rate_404>0.5", request_count=1200)
    print("profile:", client.get_profile("1.2.3.4"))
    print("risk_score:", client.get_risk_score("1.2.3.4"))


if __name__ == "__main__":
    main()
