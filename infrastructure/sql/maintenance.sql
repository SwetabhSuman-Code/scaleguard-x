-- ================================================================
-- ScaleGuard X — Database Maintenance Script
-- Issue #7: Data retention, compression, and index housekeeping
--
-- Schedule: nightly cron (02:00 UTC) via pg_cron or external scheduler
-- Target: DB size stable at ~50 GB, query latency < 100ms post-cleanup
-- ================================================================

-- ── 1. Delete metrics older than 30 days ─────────────────────────
-- Uses DELETE with a CTE to batch in chunks (prevents long lock holds on
-- large tables; adjust chunk_size for your throughput)
DO $$
DECLARE
    rows_deleted BIGINT := 0;
    total_deleted BIGINT := 0;
    chunk_size INT := 50000;
    cutoff TIMESTAMPTZ := NOW() - INTERVAL '30 days';
BEGIN
    RAISE NOTICE 'Starting metrics retention cleanup. Cutoff: %', cutoff;

    LOOP
        DELETE FROM metrics
        WHERE id IN (
            SELECT id FROM metrics
            WHERE timestamp < cutoff
            LIMIT chunk_size
        );

        GET DIAGNOSTICS rows_deleted = ROW_COUNT;
        total_deleted := total_deleted + rows_deleted;

        EXIT WHEN rows_deleted = 0;

        -- Brief pause between chunks to reduce I/O pressure
        PERFORM pg_sleep(0.05);
    END LOOP;

    RAISE NOTICE 'Metrics retention complete: % rows deleted', total_deleted;
END;
$$;

-- ── 2. Delete anomalies older than 90 days ────────────────────────
DELETE FROM anomalies
WHERE detected_at < NOW() - INTERVAL '90 days';

-- ── 3. Delete resolved alerts older than 60 days ─────────────────
DELETE FROM alerts
WHERE resolved = TRUE
  AND raised_at < NOW() - INTERVAL '60 days';

-- ── 4. Delete predictions older than 7 days ──────────────────────
DELETE FROM predictions
WHERE predicted_at < NOW() - INTERVAL '7 days';

-- ── 5. Delete scaling_events older than 90 days ──────────────────
DELETE FROM scaling_events
WHERE triggered_at < NOW() - INTERVAL '90 days';

-- ── 6. Update table statistics after mass delete ─────────────────
ANALYZE metrics;
ANALYZE anomalies;
ANALYZE alerts;
ANALYZE predictions;
ANALYZE scaling_events;

-- ── 7. TimescaleDB chunk compression (chunks older than 7 days) ───
-- Only runs if TimescaleDB extension is active
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'
    ) THEN
        -- Add compression policy if not already set
        BEGIN
            PERFORM add_compression_policy(
                'metrics',
                INTERVAL '7 days',
                if_not_exists => TRUE
            );
            RAISE NOTICE 'TimescaleDB compression policy ensured (7 days)';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Compression policy already set or error: %', SQLERRM;
        END;

        -- Manually compress any eligible uncompressed chunks now
        PERFORM compress_chunk(c.schema_name || '.' || c.table_name, if_not_compressed => TRUE)
        FROM timescaledb_information.chunks c
        WHERE c.hypertable_name = 'metrics'
          AND c.range_end < NOW() - INTERVAL '7 days'
          AND NOT c.is_compressed;

        RAISE NOTICE 'TimescaleDB chunk compression complete';
    ELSE
        RAISE NOTICE 'TimescaleDB not active — skipping compression step';
    END IF;
END;
$$;

-- ── 8. Reclaim dead tuple space ───────────────────────────────────
-- VACUUM ANALYZE is safe to run on a live system; does NOT block queries
VACUUM ANALYZE metrics;
VACUUM ANALYZE anomalies;

-- ── 9. Maintenance summary ────────────────────────────────────────
SELECT
    schemaname,
    relname                AS table_name,
    n_live_tup             AS live_rows,
    n_dead_tup             AS dead_rows,
    pg_size_pretty(pg_total_relation_size(schemaname || '.' || relname)) AS total_size,
    last_autovacuum,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('metrics', 'anomalies', 'alerts', 'predictions', 'scaling_events', 'workers')
ORDER BY pg_total_relation_size(schemaname || '.' || relname) DESC;
