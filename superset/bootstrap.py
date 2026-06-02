"""Auto-configure Apache Superset for the BotSentry dashboard.

Idempotent — every step looks up by name before creating, so it is safe to
re-run. Builds, in order:

1. Login + CSRF handshake.
2. Database connection (``BotSentryEvents``) -> the shared SQLite event log.
3. Dataset (``bot_events``) with ``timestamp`` marked temporal (epoch_s).
4. Charts (KPIs, throughput line, top-IP table, bot/human pie) each with a
   ``query_context`` so they render immediately in Superset 3.x.
5. A dashboard (``BotSentry — Live Operations``) laying them out in a grid.

Run:
    python -m superset.bootstrap --superset-url http://localhost:8088 \\
        --username admin --password admin \\
        --db-uri 'sqlite:////app/data/bot_events.db'
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger("superset_bootstrap")

DB_NAME = "BotSentryEvents"
DATASET_NAME = "bot_events"
DASHBOARD_TITLE = "BotSentry — Live Operations"
TEMPORAL_COL = "timestamp"


class SupersetClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.access_token: str | None = None
        self.csrf_token: str | None = None
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        data = None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.csrf_token and method != "GET":
            headers["X-CSRFToken"] = self.csrf_token
            headers["Referer"] = self.base
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=30) as resp:
                payload = resp.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            log.error("%s %s -> HTTP %d: %s", method, path, exc.code, err_body[:300])
            raise

    def wait_for_ready(self, attempts: int = 60, delay: float = 5.0) -> None:
        for i in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(f"{self.base}/health", timeout=5) as r:
                    if r.status == 200:
                        log.info("Superset healthy (attempt %d).", i)
                        return
            except (urllib.error.URLError, ConnectionResetError, TimeoutError) as exc:
                log.info("Waiting for Superset (%d/%d): %s", i, attempts, exc)
            time.sleep(delay)
        raise RuntimeError(f"Superset did not come up after {attempts * delay:.0f}s")

    def login(self, username: str, password: str) -> None:
        resp = self._request("POST", "/api/v1/security/login", {
            "username": username, "password": password,
            "provider": "db", "refresh": False,
        })
        self.access_token = resp["access_token"]
        log.info("Authenticated as %s.", username)
        self.csrf_token = self._request("GET", "/api/v1/security/csrf_token/").get("result")

    def find_database(self, name: str) -> int | None:
        resp = self._request("GET", "/api/v1/database/?q=(page_size:100)")
        for item in resp.get("result", []):
            if item.get("database_name") == name:
                return int(item["id"])
        return None

    def create_database(self, name: str, sqlalchemy_uri: str) -> int:
        existing = self.find_database(name)
        if existing is not None:
            log.info("Database %s exists (id=%d).", name, existing)
            return existing
        resp = self._request("POST", "/api/v1/database/", {
            "database_name": name, "sqlalchemy_uri": sqlalchemy_uri,
            "expose_in_sqllab": True, "allow_dml": False,
        })
        log.info("Created database %s (id=%d).", name, resp["id"])
        return int(resp["id"])

    def find_dataset(self, table_name: str) -> int | None:
        resp = self._request("GET", "/api/v1/dataset/?q=(page_size:100)")
        for item in resp.get("result", []):
            if item.get("table_name") == table_name:
                return int(item["id"])
        return None

    def create_dataset(self, db_id: int, table_name: str, schema: str = "main") -> int:
        existing = self.find_dataset(table_name)
        if existing is not None:
            log.info("Dataset %s exists (id=%d).", table_name, existing)
            return existing
        resp = self._request("POST", "/api/v1/dataset/",
                             {"database": db_id, "schema": schema, "table_name": table_name})
        log.info("Created dataset %s (id=%d).", table_name, resp["id"])
        return int(resp["id"])

    def mark_temporal(self, dataset_id: int, column_name: str, date_format: str = "epoch_s") -> None:
        ds = self._request("GET", f"/api/v1/dataset/{dataset_id}")["result"]
        new_cols = []
        for c in ds["columns"]:
            entry = {"column_name": c["column_name"], "type": c.get("type")}
            if c["column_name"] == column_name:
                entry["is_dttm"] = True
                entry["python_date_format"] = date_format
            else:
                entry["is_dttm"] = False
            new_cols.append(entry)
        self._request("PUT", f"/api/v1/dataset/{dataset_id}?override_columns=true",
                      {"columns": new_cols})
        log.info("Marked %s temporal (format=%s).", column_name, date_format)

    def find_chart(self, name: str) -> int | None:
        resp = self._request("GET", "/api/v1/chart/?q=(page_size:200)")
        for item in resp.get("result", []):
            if item.get("slice_name") == name:
                return int(item["id"])
        return None

    def upsert_chart(self, name: str, datasource_id: int, viz_type: str,
                     params: dict, query_context: dict) -> int:
        body = {
            "slice_name": name, "viz_type": viz_type,
            "datasource_id": datasource_id, "datasource_type": "table",
            "params": json.dumps(params), "query_context": json.dumps(query_context),
        }
        existing = self.find_chart(name)
        if existing is not None:
            self._request("PUT", f"/api/v1/chart/{existing}", body)
            log.info("Updated chart %s (id=%d).", name, existing)
            return existing
        resp = self._request("POST", "/api/v1/chart/", body)
        log.info("Created chart %s (id=%d).", name, resp["id"])
        return int(resp["id"])

    def find_dashboard(self, title: str) -> int | None:
        resp = self._request("GET", "/api/v1/dashboard/?q=(page_size:100)")
        for item in resp.get("result", []):
            if item.get("dashboard_title") == title:
                return int(item["id"])
        return None

    def upsert_dashboard(self, title: str, position_json: dict, published: bool = True) -> int:
        body = {"dashboard_title": title,
                "position_json": json.dumps(position_json), "published": published}
        existing = self.find_dashboard(title)
        if existing is not None:
            self._request("PUT", f"/api/v1/dashboard/{existing}", body)
            return existing
        resp = self._request("POST", "/api/v1/dashboard/", body)
        log.info("Created dashboard %r (id=%d).", title, resp["id"])
        return int(resp["id"])

    def attach_chart_to_dashboard(self, chart_id: int, dashboard_id: int) -> None:
        self._request("PUT", f"/api/v1/chart/{chart_id}", {"dashboards": [dashboard_id]})


def sql_metric(label: str, sql: str) -> dict:
    return {"label": label, "expressionType": "SQL", "sqlExpression": sql}


COUNT_STAR = sql_metric("COUNT(*)", "COUNT(*)")
TIME_RANGE = "No filter"  # simulated events span the last ~2h


def base_query_context(ds_id: int, columns: list, metrics: list,
                       filters: list | None = None, row_limit: int = 10000,
                       orderby: list | None = None) -> dict:
    return {
        "datasource": {"id": ds_id, "type": "table"},
        "force": False,
        "queries": [{
            "time_range": TIME_RANGE,
            "filters": filters or [],
            "extras": {"having": "", "where": ""},
            "columns": columns,
            "metrics": metrics,
            "row_limit": row_limit,
            "orderby": orderby or [],
            "is_timeseries": False,
        }],
        "form_data": {"datasource": f"{ds_id}__table", "time_range": TIME_RANGE},
        "result_format": "json",
        "result_type": "full",
    }


def kpi(name: str, metric: dict, subheader: str, fmt: str) -> dict:
    return {
        "name": name, "viz_type": "big_number_total",
        "params": {"viz_type": "big_number_total", "metric": metric,
                   "subheader": subheader, "y_axis_format": fmt, "time_range": TIME_RANGE},
        "query_context": base_query_context(0, [], [metric]),  # ds_id patched below
        "_metric": metric,
    }


def chart_definitions(ds_id: int) -> list[dict]:
    bot_pct = sql_metric("Bot %", "AVG(CAST(is_bot AS REAL)) * 100")
    avg_risk = sql_metric("Avg risk", "AVG(risk_score)")
    bot_hits = sql_metric("Bot hits", "SUM(is_bot)")

    charts = [
        {**kpi("Bot percentage", bot_pct, "% of scored requests classified as bots", ".1f"),
         "layout": {"row": 0, "col_start": 0, "width": 4, "height": 30}},
        {**kpi("Total events", COUNT_STAR, "scored requests in the event log", "SMART_NUMBER"),
         "layout": {"row": 0, "col_start": 4, "width": 4, "height": 30}},
        {**kpi("Average risk score", avg_risk, "mean ML risk score", ".3f"),
         "layout": {"row": 0, "col_start": 8, "width": 4, "height": 30}},
        # Throughput over time, split bot vs human.
        {
            "name": "Request throughput (human vs bot)",
            "viz_type": "echarts_timeseries_line",
            "params": {
                "viz_type": "echarts_timeseries_line",
                "granularity_sqla": TEMPORAL_COL, "time_grain_sqla": "PT10M",
                "metrics": [COUNT_STAR], "groupby": ["is_bot"],
                "row_limit": 5000, "show_legend": True,
                "x_axis_title": "time", "y_axis_title": "requests",
                "time_range": TIME_RANGE,
            },
            "query_context": {
                "datasource": {"id": ds_id, "type": "table"}, "force": False,
                "queries": [{
                    "granularity": TEMPORAL_COL, "time_range": TIME_RANGE,
                    "filters": [], "extras": {"having": "", "where": "", "time_grain_sqla": "PT10M"},
                    "columns": ["is_bot"], "metrics": [COUNT_STAR],
                    "row_limit": 5000, "is_timeseries": True,
                }],
                "form_data": {"viz_type": "echarts_timeseries_line",
                              "datasource": f"{ds_id}__table", "time_range": TIME_RANGE,
                              "granularity_sqla": TEMPORAL_COL, "time_grain_sqla": "PT10M"},
                "result_format": "json", "result_type": "full",
            },
            "layout": {"row": 1, "col_start": 0, "width": 8, "height": 50},
        },
        # Bot vs human pie.
        {
            "name": "Bot vs human",
            "viz_type": "pie",
            "params": {"viz_type": "pie", "groupby": ["is_bot"], "metric": COUNT_STAR,
                       "row_limit": 10, "show_legend": True, "donut": True, "time_range": TIME_RANGE},
            "query_context": base_query_context(ds_id, ["is_bot"], [COUNT_STAR],
                                                row_limit=10, orderby=[[COUNT_STAR, False]]),
            "layout": {"row": 1, "col_start": 8, "width": 4, "height": 50},
        },
        # Top offending IPs.
        {
            "name": "Top flagged IPs",
            "viz_type": "table",
            "params": {"viz_type": "table", "query_mode": "aggregate", "groupby": ["ip"],
                       "metrics": [COUNT_STAR, bot_hits, avg_risk],
                       "row_limit": 20, "order_desc": True, "time_range": TIME_RANGE},
            "query_context": base_query_context(
                ds_id, ["ip"], [COUNT_STAR, bot_hits, avg_risk],
                filters=[{"col": "is_bot", "op": "==", "val": "1"}],
                row_limit=20, orderby=[[COUNT_STAR, False]]),
            "layout": {"row": 2, "col_start": 0, "width": 12, "height": 50},
        },
    ]
    # Patch the ds_id into the KPI query_contexts built before we had it.
    for c in charts:
        if c["viz_type"] == "big_number_total":
            c["query_context"] = base_query_context(ds_id, [], [c["_metric"]])
    return charts


def build_position_json(chart_specs: list[tuple[int, str, dict]]) -> dict:
    rows: dict[int, list] = {}
    for cid, name, layout in chart_specs:
        rows.setdefault(layout["row"], []).append((cid, name, layout))
    position: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
    }
    for row_idx in sorted(rows):
        row_id = f"ROW-{row_idx}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {"type": "ROW", "id": row_id,
                            "parents": ["ROOT_ID", "GRID_ID"], "children": [],
                            "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for cid, name, layout in sorted(rows[row_idx], key=lambda c: c[2]["col_start"]):
            node = f"CHART-{cid}"
            position[row_id]["children"].append(node)
            position[node] = {"type": "CHART", "id": node,
                              "parents": ["ROOT_ID", "GRID_ID", row_id], "children": [],
                              "meta": {"chartId": cid, "sliceName": name,
                                       "width": layout["width"], "height": layout["height"],
                                       "uuid": f"chart-{cid}"}}
    return position


def bootstrap(client: SupersetClient, db_uri: str) -> None:
    db_id = client.create_database(DB_NAME, db_uri)
    ds_id = client.create_dataset(db_id, DATASET_NAME)
    client.mark_temporal(ds_id, TEMPORAL_COL, "epoch_s")

    specs: list[tuple[int, str, dict]] = []
    for chart in chart_definitions(ds_id):
        try:
            cid = client.upsert_chart(chart["name"], ds_id, chart["viz_type"],
                                      chart["params"], chart["query_context"])
            specs.append((cid, chart["name"], chart["layout"]))
        except urllib.error.HTTPError as exc:
            log.error("Skipping chart %r (HTTP %d).", chart["name"], exc.code)

    if not specs:
        log.warning("No charts created — skipping dashboard.")
        return
    dash_id = client.upsert_dashboard(DASHBOARD_TITLE, build_position_json(specs))
    for chart_id, name, _ in specs:
        client.attach_chart_to_dashboard(chart_id, dash_id)
    log.info("Dashboard %r ready with %d charts.", DASHBOARD_TITLE, len(specs))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(description="Bootstrap Superset for BotSentry.")
    parser.add_argument("--superset-url", default="http://localhost:8088")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--db-uri", default="sqlite:////app/data/bot_events.db")
    parser.add_argument("--wait-attempts", type=int, default=60)
    parser.add_argument("--wait-delay", type=float, default=5.0)
    args = parser.parse_args()

    client = SupersetClient(args.superset_url)
    client.wait_for_ready(args.wait_attempts, args.wait_delay)
    client.login(args.username, args.password)
    bootstrap(client, args.db_uri)
    log.info("Done. Open %s -> Dashboards -> %r.", args.superset_url, DASHBOARD_TITLE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
