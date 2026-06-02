-- ===========================================================================
-- Superset chart definitions for the bot-detection pipeline (Phase 7)
-- ===========================================================================
-- Two data sources are registered in Superset:
--   (A) SQLite  : sqlite:////app/data/bot_events.db   (live event log)
--   (B) DuckDB  : duckdb:////app/data/analytics.duckdb (reads Parquet features)
--
-- In Superset: Data > Databases > + Database, add both connection strings,
-- then create a "Virtual Dataset" for each query below and build the chart of
-- the indicated type on top of it.
--
-- Notes on the SQLite event log: `timestamp` is a REAL UNIX epoch (seconds);
-- `is_bot` is 0/1; `risk_score` is in [0,1].
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- DuckDB bootstrap (run once in the DuckDB database to expose Parquet + JSON)
-- ---------------------------------------------------------------------------
-- Register the partitioned Parquet feature table as a view:
CREATE VIEW IF NOT EXISTS features AS
    SELECT * FROM read_parquet('/app/data/parquet/features.parquet/**/*.parquet',
                               hive_partitioning = 1);

-- Materialise feature importances from the training metrics JSON into a table
-- (Chart 6 reads this). DuckDB parses the {feature: importance} object as a
-- STRUCT; we unpivot it to (feature, importance) rows.
CREATE TABLE IF NOT EXISTS feature_importances AS
    SELECT k AS feature, CAST(v AS DOUBLE) AS importance
    FROM (
        SELECT unnest(map_keys(fi)) AS k, unnest(map_values(fi)) AS v
        FROM (
            SELECT CAST(feature_importances AS MAP(VARCHAR, DOUBLE)) AS fi
            FROM read_json_auto('/app/data/../models/metrics.json')
        )
    );


-- ===========================================================================
-- CHART 1 — Requests throughput over time   (Time-series Line, 5-min buckets)
-- Source: (A) SQLite bot_events
-- ===========================================================================
SELECT
    datetime((CAST(timestamp / 300 AS INTEGER)) * 300, 'unixepoch') AS bucket_5min,
    COUNT(*)                                                        AS requests
FROM bot_events
GROUP BY bucket_5min
ORDER BY bucket_5min;


-- ===========================================================================
-- CHART 2 — Bot vs human ratio over time     (Stacked Area)
-- Source: (A) SQLite bot_events
-- ===========================================================================
SELECT
    datetime((CAST(timestamp / 300 AS INTEGER)) * 300, 'unixepoch') AS bucket_5min,
    SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END)                     AS bots,
    SUM(CASE WHEN is_bot = 0 THEN 1 ELSE 0 END)                     AS humans
FROM bot_events
GROUP BY bucket_5min
ORDER BY bucket_5min;


-- ===========================================================================
-- CHART 3 — Top 20 flagged IPs by request count   (Bar, horizontal)
-- Source: (A) SQLite bot_events
-- ===========================================================================
SELECT
    ip,
    COUNT(*)            AS req_count,
    MAX(risk_score)     AS max_risk
FROM bot_events
WHERE is_bot = 1
GROUP BY ip
ORDER BY req_count DESC
LIMIT 20;


-- ===========================================================================
-- CHART 4 — Risk score distribution   (Histogram, 20 bins)
-- Source: (A) SQLite bot_events
-- (Superset's native Histogram viz can also bin the raw risk_score column;
--  this pre-bins into 20 buckets of width 0.05 for a plain Bar chart.)
-- ===========================================================================
SELECT
    (CAST(risk_score * 20 AS INTEGER) / 20.0) AS risk_bin,
    COUNT(*)                                  AS n
FROM bot_events
WHERE risk_score IS NOT NULL
GROUP BY risk_bin
ORDER BY risk_bin;


-- ===========================================================================
-- CHART 5 — Path density heatmap   (Heatmap: hour-of-day x day-of-week)
-- Source: (A) SQLite bot_events
-- dow: 0=Sunday .. 6=Saturday ; hour: 0..23
-- ===========================================================================
SELECT
    CAST(strftime('%w', datetime(timestamp, 'unixepoch')) AS INTEGER) AS day_of_week,
    CAST(strftime('%H', datetime(timestamp, 'unixepoch')) AS INTEGER) AS hour_of_day,
    COUNT(*)                                                          AS requests
FROM bot_events
GROUP BY day_of_week, hour_of_day
ORDER BY day_of_week, hour_of_day;


-- ===========================================================================
-- CHART 6 — Feature importances   (Bar, horizontal)
-- Source: (B) DuckDB feature_importances table (loaded above from metrics.json)
-- ===========================================================================
SELECT
    feature,
    importance
FROM feature_importances
ORDER BY importance DESC;


-- ===========================================================================
-- CHART 7 — Alert replay timeline   (Scatter: time x IP, colour = risk_score)
-- Source: (A) SQLite bot_events
-- Plot ts on X, ip on Y (or as series), bubble/colour by risk_score.
-- ===========================================================================
SELECT
    datetime(timestamp, 'unixepoch') AS ts,
    ip,
    risk_score,
    is_bot,
    path
FROM bot_events
WHERE is_bot = 1
ORDER BY ts;
