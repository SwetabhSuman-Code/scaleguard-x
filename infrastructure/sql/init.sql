-- ================================================================
-- ScaleGuard X  –  Database Schema
-- ================================================================

-- --------------- Enable TimescaleDB extension if available -------
-- (Gracefully skip on plain Postgres)
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB not available, using standard Postgres. This is fine.';
END;
$$;

-- ================================================================
-- 1. METRICS TABLE
-- ================================================================
CREATE TABLE IF NOT EXISTS metrics (
    id               BIGSERIAL,
    node_id          VARCHAR(128)   NOT NULL,
    timestamp        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    cpu_usage        DOUBLE PRECISION NOT NULL,
    memory_usage     DOUBLE PRECISION NOT NULL,
    latency_ms       DOUBLE PRECISION NOT NULL,
    requests_per_sec DOUBLE PRECISION NOT NULL,
    disk_usage       DOUBLE PRECISION NOT NULL,
    CONSTRAINT metrics_pkey PRIMARY KEY (id, timestamp)
);

-- Index for fast node + time range queries
CREATE INDEX IF NOT EXISTS idx_metrics_node_time
    ON metrics (node_id, timestamp DESC);

-- Convert to TimescaleDB hypertable (skip if extension absent)
DO $$
BEGIN
    PERFORM create_hypertable('metrics', 'timestamp',
        if_not_exists => TRUE,
        migrate_data   => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping hypertable creation: %', SQLERRM;
END;
$$;

-- ================================================================
-- 2. ANOMALIES TABLE
-- ================================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id            BIGSERIAL PRIMARY KEY,
    node_id       VARCHAR(128)   NOT NULL,
    detected_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    anomaly_type  VARCHAR(64)    NOT NULL,   -- 'rule_based' | 'ml_based'
    metric_name   VARCHAR(64)    NOT NULL,   -- 'cpu' | 'memory' | 'latency' | 'composite'
    metric_value  DOUBLE PRECISION NOT NULL,
    threshold     DOUBLE PRECISION,
    anomaly_score DOUBLE PRECISION NOT NULL, -- 0..1
    description   TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomalies_node_time
    ON anomalies (node_id, detected_at DESC);

-- ================================================================
-- 3. PREDICTIONS TABLE
-- ================================================================
CREATE TABLE IF NOT EXISTS predictions (
    id                BIGSERIAL PRIMARY KEY,
    predicted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    horizon_minutes   INT         NOT NULL,
    predicted_rps     DOUBLE PRECISION NOT NULL,
    predicted_cpu     DOUBLE PRECISION,
    confidence        DOUBLE PRECISION,
    lower_bound       DOUBLE PRECISION,
    upper_bound       DOUBLE PRECISION,
    spike_probability DOUBLE PRECISION,
    model_name        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_predictions_time
    ON predictions (predicted_at DESC);

ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS lower_bound DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS upper_bound DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS spike_probability DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS model_name VARCHAR(64);

-- ================================================================
-- 4. SCALING_EVENTS TABLE
-- ================================================================
CREATE TABLE IF NOT EXISTS scaling_events (
    id            BIGSERIAL PRIMARY KEY,
    triggered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action        VARCHAR(32)  NOT NULL,  -- 'scale_up' | 'scale_down' | 'no_change'
    prev_replicas INT         NOT NULL,
    new_replicas  INT         NOT NULL,
    reason        TEXT
);

CREATE INDEX IF NOT EXISTS idx_scaling_events_time
    ON scaling_events (triggered_at DESC);

-- ================================================================
-- 5. ALERTS TABLE
-- ================================================================
CREATE TABLE IF NOT EXISTS alerts (
    id           BIGSERIAL PRIMARY KEY,
    raised_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity     VARCHAR(16)  NOT NULL,  -- 'info' | 'warning' | 'critical'
    node_id      VARCHAR(128),
    alert_type   VARCHAR(64)  NOT NULL,
    message      TEXT         NOT NULL,
    resolved     BOOLEAN      NOT NULL DEFAULT FALSE,
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_time
    ON alerts (raised_at DESC);

-- ================================================================
-- 6. WORKERS TABLE   (registry of live worker containers)
-- ================================================================
CREATE TABLE IF NOT EXISTS workers (
    id             BIGSERIAL PRIMARY KEY,
    worker_id      VARCHAR(128) UNIQUE NOT NULL,
    container_id   VARCHAR(128),
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status         VARCHAR(32)  NOT NULL DEFAULT 'active'   -- active | idle | terminated
);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON workers (status);
