# Bot Detection for Web Servers

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Apache Spark](https://img.shields.io/badge/Apache%20Spark-3.4%2B-E25A1C?logo=apachespark&logoColor=white)](https://spark.apache.org/)
[![HBase](https://img.shields.io/badge/HBase-Thrift-D22128?logo=apache&logoColor=white)](https://hbase.apache.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

End-to-end **web-robot detection** pipeline over the Zenodo *Web robot
detection* dataset (`search.lib.auth.gr` access logs):

**Spark ETL → ML training → HBase profile store → FastAPI scoring service →
SQLite live event log → Superset dashboards → an interactive Next.js front
end** — all orchestrated with Docker Compose.

> Trained and verified on the **full 4,091,155-request / 26,966-IP** dataset
> (Feb 28 – Mar 27 2018): 2,309 IPs labelled robot (8.6%).

---

## Table of contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Quick start (local, no Docker)](#quick-start-local-no-docker)
- [Quick start (Docker)](#quick-start-docker)
- [Features computed per IP](#features-computed-per-ip-phase-2)
- [ML training](#ml-training-phase-3)
- [HBase schema](#hbase-schema-phase-4--table-bot_profiles-row-key--ip)
- [API reference](#api-phase-5)
- [SQLite event log](#sqlite-event-log-phase-6--bot_events)
- [Superset dashboards](#superset-phase-7)
- [Web UI](#web-ui-nextjs)
- [Configuration / secrets](#configuration--secrets)
- [Smoke tests](#smoke-tests)

---

## Overview

This project takes raw web-server access logs, turns them into per-IP
behavioural features, trains models that distinguish bots from humans, and
serves real-time risk scores through an API and an interactive dashboard:

- **Spark / pandas ETL** — stream a 3.2 GB raw JSON dump into per-IP feature
  tables (Parquet + CSV), no JVM required.
- **ML models** — RandomForest vs GradientBoosting, both a live behavioural
  model and an honest ground-truth benchmark (recall 0.976 @ precision 0.889,
  AUC 0.995).
- **HBase profile store** — per-IP stats, scores, and alerts with TTL'd alert
  records, via a happybase Thrift client (with an in-memory fake mode).
- **FastAPI scoring service** — `/api/check`, `/api/score`, bulk scoring,
  CIDR-aware rate limiting, and an IP allowlist.
- **SQLite live event log** — every scored request, with session and CIDR
  derivation, queryable for analytics.
- **Superset dashboards** — 7 charts over live SQLite events and Parquet
  features via DuckDB.
- **Next.js web console** — overview, detection playground, admin dashboard,
  and model insights, all backed by the live API.

## Architecture

```
Access logs (public_v2.json)
        │
        ▼
  Spark / pandas ETL  ──────────────►  features.parquet / features.csv
        │
        ▼
  ML training (RandomForest / GradientBoosting)
        │
        ▼
  HBase profile store  ◄──────────────  FastAPI scoring service
        │                                       │
        ▼                                       ▼
  Alerts (TTL'd)                    SQLite event log (bot_events)
                                                 │
                              ┌──────────────────┴───────────────────┐
                              ▼                                       ▼
                      Superset dashboards               Next.js web console
                                                  (overview / playground /
                                                   dashboard / model insights)
```

## Project structure

```
BDT_2/
├── data/raw/              # Zenodo dataset (public_v2.json) + derived NDJSON
├── data/parquet/          # Spark/ETL output: features.parquet + features.csv
├── models/                # best_model.pkl, metrics.json, threshold.txt
├── spark/
│   ├── prepare_data.py    # stream the 3.2 GB single-object JSON -> NDJSON
│   ├── etl.py             # PySpark feature ETL (needs a JVM)
│   ├── etl_pandas.py      # no-JVM reference ETL (identical schema)
│   └── etl_stream.py      # memory-bounded streaming ETL for the full dump
├── ml/
│   ├── train.py           # RandomForest vs GradientBoosting, recall-optimised
│   └── scorer.py          # runtime model loader/scorer (shared by the API)
├── hbase/client.py        # happybase wrapper for the bot_profiles table
├── db/event_log.py        # SQLite bot_events log (session_id + cidr derivation)
├── api/
│   ├── server.py          # FastAPI: check/score/bulk + CIDR rate limit + allowlist
│   └── analytics.py       # dashboard queries (DuckDB/Parquet) + traffic simulator
├── config/allowlist.txt   # known-good IPs (skip scoring)
├── superset/setup.sql     # 7 chart-defining SQL queries
├── web/                    # Next.js 16 + TS front end (overview/playground/dashboard/model)
├── Dockerfile              # FastAPI serving image
├── docker-compose.yml      # spark master+worker, hbase, fastapi, superset, web
└── requirements.txt
```

## Requirements

- Python 3.10+
- For `spark/etl.py`: a JVM (Java 8/11/17) + PySpark 3.4+. **If you have no
  JVM, use `spark/etl_pandas.py`** — it produces an identical `features.csv`
  and partitioned Parquet so the rest of the pipeline runs unchanged.
- Docker (for the full stack).
- Node.js 18+ (for the web UI).

```bash
pip install -r requirements.txt
```

## Quick start (local, no Docker)

```bash
# 1. Build the feature table from the full 3.2 GB dump.
#    etl_stream.py reads the raw single-object JSON in one memory-bounded pass
#    (no JVM, no giant intermediate file) — this is what produced the shipped
#    features on the full 4M-request dataset (~70s):
python spark/etl_stream.py --input data/raw/public_v2.json --output data/parquet

#    Alternatives (same output schema):
#    - Spark (needs Java):  prepare_data.py -> spark-submit spark/etl.py
#    - small pandas path:   spark/etl_pandas.py

# 2. Train models.
#    (a) per-IP behavioural model used for live serving (heuristic labels):
python ml/train.py --features data/parquet/features.csv --models-dir models
#    (b) honest ground-truth benchmark on the official Zenodo ROBOT labels
#        (simple_features ⋈ semantic_features on ID):
python ml/train_groundtruth.py --raw-dir data/raw --models-dir models

# 3. Serve the API (HBASE_FAKE=1 = in-memory profile store, no HBase needed).
HBASE_FAKE=1 uvicorn api.server:app --host 0.0.0.0 --port 8000

# 4. Run the web UI (separate terminal).
cd web && npm install && npm run dev      # http://localhost:3000
```

## Quick start (Docker)

```bash
cp .env.example .env        # then edit secrets (Superset key/password)
docker compose up --build   # brings up hbase + thrift sidecar + fastapi + web + superset
```

| Service  | URL                     |
|----------|-------------------------|
| Web UI   | http://localhost:3000   |
| FastAPI  | http://localhost:8000   |
| Superset | http://localhost:8088   |
| HBase UI | http://localhost:16010  |

Services & images (chosen to match what runs reliably on this host):

- **hbase** — `bde2020/hbase-standalone` (embedded ZooKeeper on :2181).
- **hbase-thrift** — same image, sidecar running `scripts/hbase-thrift-init.sh`;
  it waits for the master, then `hbase thrift start`. happybase connects here on
  :9090 (buffered transport). `fastapi` waits for this to become healthy.
- **fastapi** — built from `Dockerfile`. **Trained models are baked into the
  image** (not bind-mounted) so the import-time model load never races a lazy
  host mount; `data/` and `config/` are mounted. Rebuild after retraining.
- **web** — `web/Dockerfile`, Next.js standalone server on :3000.
- **superset** — `apache/superset:3.1.0` with `superset/superset_config.py`.
- **spark-etl** — opt-in, `apache/spark`. Run the full Spark ETL on demand:
  `docker compose --profile etl run --rm spark-etl`.

> **Port note:** an earlier version of this project may still be running
> (`bd-hbase`, `bd-hbase-thrift`, `bd-app`, `bd-superset`) and holds the same
> ports (8000/9090/2181/16010/8088). Stop it first:
> `docker rm -f bd-app bd-hbase-thrift bd-hbase bd-superset`.

Verified end-to-end: the API image builds, runs, loads the trained model
(`model_ready: true`), connects to the live HBase Thrift gateway
(`hbase_status: connected`), and a `/api/check` write was read straight back
out of HBase via happybase on :9090.

## Features computed per IP (Phase 2)

Temporal/behavioural: `req_count, avg_interval, std_interval, min_interval,
requests_per_hour, session_count, avg_session_length`
(a session boundary is an inter-arrival gap > 1800 s).
Content: `unique_paths_ratio, error_rate, rate_404, avg_bytes`.
User-Agent: `ua_is_known_bot, ua_is_browser, ua_entropy` (Shannon entropy).

**Label (`is_robot`)**: uses a ground-truth column from the dataset when
present, otherwise falls back to `ua_is_known_bot OR rate_404 > 0.5`.

> Note on labels: the raw `public_v2.json` has no per-request ground truth, so
> the heuristic label is used by default. Because that heuristic partly relies
> on `ua_is_known_bot` (also a feature), reported CV scores on heuristic labels
> can look near-perfect. To train on real ground truth, join the Zenodo
> `simple_features`/`semantic_features` `ROBOT` column by session ID and feed
> the ETL a dataset that carries an `is_robot`/`robot` column — the ETL and
> trainer already prefer it automatically.

## ML training (Phase 3)

RandomForest (`n_estimators=200, class_weight='balanced'`) vs
GradientBoosting (`n_estimators=200, learning_rate=0.05`), evaluated with
`StratifiedKFold(5)`. Reports precision/recall/F1/AUC-ROC. The decision
threshold is swept over `0.30–0.70` and chosen to **maximise recall subject to
precision ≥ 0.80** (missing a bot costs more than a false positive); the best
model is selected by recall.

Two models are produced:

1. **Per-IP behavioural model** (`ml/train.py` → `best_model.pkl`,
   `metrics.json`, `threshold.txt`). Trains on the 14 features computable live
   from raw logs per IP, so it powers the API/playground. Labels are heuristic,
   which overlaps the UA features (near-perfect CV — not real generalisation).

2. **Ground-truth benchmark** (`ml/train_groundtruth.py` →
   `groundtruth_model.pkl`, `groundtruth_metrics.json`,
   `groundtruth_threshold.txt`). Trains on the official Zenodo
   `simple_features` ⋈ `semantic_features` (per session, joined on `ID`)
   against the real `ROBOT` label — a genuine, non-circular benchmark.
   On the full 67,352-session set: **RandomForest recall 0.976 @ precision
   0.889, AUC 0.995**. The API surfaces this at `/api/model/groundtruth` and
   the UI shows it as the headline model.

## HBase schema (Phase 4) — table `bot_profiles`, row key = IP

| Family   | Columns | Notes |
|----------|---------|-------|
| `stats`  | the 12 numeric features | |
| `meta`   | `first_seen, last_seen, ua_is_known_bot, ua_is_browser` | |
| `score`  | `risk_score, is_bot, threshold_used, model_version` | |
| `alerts` | `flagged_at, reason, request_count_at_flag` | **TTL 3600 s** |

API: `upsert_profile`, `bulk_upsert`, `get_profile`, `get_risk_score`,
`flag_ip`. Connection via `HBASE_HOST/HBASE_PORT`; set `HBASE_FAKE=1` for an
in-memory backend.

## API (Phase 5)

| Method/Path        | Purpose |
|--------------------|---------|
| `POST /api/check`  | score `{ip, useragent, path}` → `{ip, risk_score, is_bot, reason, session_count}` |
| `GET  /api/score?ip=` | firewall/WAF lookup → `{ip, risk_score, flagged, last_seen, req_count}` |
| `POST /api/bulk-score` | `{ips:[...]}` → `[{ip, risk_score, is_bot}, ...]` |
| `GET  /api/stats`  | totals, bot ratio, top-10 flagged IPs |
| `GET  /api/health` | model version, HBase status, uptime |
| `GET  /api/analytics/overview` | dataset-wide rollup (IPs, requests, bot ratio, AUC) |
| `GET  /api/analytics/top-bots` | top flagged IPs by request count |
| `GET  /api/analytics/risk-distribution` | population by request-rate, bot vs human |
| `GET  /api/analytics/scatter` | sampled IPs for the behavioural scatter |
| `GET  /api/model/metrics` · `/api/model/feature-importances` | training results |
| `GET  /api/events/timeseries` · `/api/events/heatmap` | live event-log aggregates |
| `POST /api/simulate` | replay real IPs through the scorer to populate live charts |

Rate limiting (slowapi, on the caller's source address; honours
`X-Forwarded-For`): **100 req/min per exact IP** and **500 req/min per /24
CIDR block**. IPs in `config/allowlist.txt` skip both rate limiting and
scoring. HBase reads are cached for 60 s via `functools.lru_cache`.

## SQLite event log (Phase 6) — `bot_events`

Columns `id, ip, timestamp, path, useragent, risk_score, is_bot, status_code,
bytes_sent, session_id, cidr_block` with indexes on `timestamp, ip, path,
is_bot`. `session_id = MD5(ip + floor(timestamp/1800))`,
`cidr_block = first three octets + '.0/24'`.

## Superset (Phase 7)

`superset/setup.sql` defines 7 charts over two sources — SQLite `bot_events`
(live) and Parquet features via the DuckDB engine: throughput, bot-vs-human
ratio, top-20 flagged IPs, risk-score histogram, path-density heatmap, feature
importances (from `metrics.json`), and an alert-replay scatter.

## Web UI (Next.js)

An interactive console in [`web/`](web/) (Next.js 16, TypeScript, Tailwind,
Recharts, Framer Motion) built to demo the project to evaluators. Four routes:

- **Overview** — hero, live dataset stats, an animated architecture pipeline,
  and a bot-vs-human behavioural scatter (request-rate × UA entropy).
- **Detection Playground** — send a live request (IP / User-Agent / path) and
  watch an animated risk gauge + verdict; one-click presets (Googlebot, Chrome,
  Python scraper, curl) and a bulk-scoring table.
- **Admin Dashboard** — auto-refreshing throughput, bot-vs-human stacked area,
  top flagged IPs, population-by-rate distribution, and an hour×weekday activity
  heatmap. A **Simulate traffic** button replays real IPs through the scorer so
  the live charts fill in on demand.
- **Model Insights** — RF vs GBT comparison table, chosen threshold, and the
  feature-importance ranking.

```bash
cd web
npm install
npm run dev            # http://localhost:3000  (API expected on :8000)
```

The API base URL is configurable via `web/.env.local`
(`NEXT_PUBLIC_API_BASE`, default `http://localhost:8000`). The FastAPI server
enables permissive CORS so the dev server can call it directly.

## Configuration / secrets

All configuration is via environment variables (see `.env.example`): no
credentials are hardcoded. Superset requires `SUPERSET_SECRET_KEY` and
`SUPERSET_ADMIN_PASSWORD` to be set or it refuses to start.

## Smoke tests

Each module is runnable standalone:
`python spark/prepare_data.py …`, `python spark/etl_pandas.py …`,
`python ml/train.py`, `python hbase/client.py`, `python db/event_log.py`, and
`uvicorn api.server:app`. See the commands above.
