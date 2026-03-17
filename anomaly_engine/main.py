"""
ScaleGuard X — Anomaly Detection Engine
Two-layer anomaly detection running as a periodic background service:
  Layer 1:  Rule-based  (CPU > threshold, Latency > threshold, Memory > threshold)
  Layer 2:  ML-based    (Isolation Forest on rolling 60-minute window)
Detected anomalies are written to the `anomalies` table and to `alerts`.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import numpy as np
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest

load_dotenv()

# ── Config ───────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER','scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD','scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST','localhost')}"
    f":{os.getenv('POSTGRES_PORT','5432')}"
    f"/{os.getenv('POSTGRES_DB','scaleguard')}"
)

CPU_THRESH     = float(os.getenv("ANOMALY_CPU_THRESHOLD", 85.0))
LATENCY_THRESH = float(os.getenv("ANOMALY_LATENCY_THRESHOLD", 500.0))
MEM_THRESH     = float(os.getenv("ANOMALY_MEMORY_THRESHOLD", 90.0))
RUN_INTERVAL   = int(os.getenv("ANOMALY_RUN_INTERVAL", 10))  # seconds
WINDOW_MINUTES = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ANOMALY] %(levelname)s %(message)s",
)
log = logging.getLogger("anomaly_engine")

# ── DB Helpers ───────────────────────────────────────────────────
async def create_pool() -> asyncpg.Pool:
    for attempt in range(15):
        try:
            pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=6)
            log.info("Connected to Postgres")
            return pool
        except Exception as e:
            log.warning(f"Postgres not ready (attempt {attempt+1}): {e}")
            await asyncio.sleep(4)
    raise RuntimeError("Cannot connect to Postgres")


ANOMALY_INSERT = """
    INSERT INTO anomalies
        (node_id, detected_at, anomaly_type, metric_name, metric_value,
         threshold, anomaly_score, description)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

ALERT_INSERT = """
    INSERT INTO alerts (raised_at, severity, node_id, alert_type, message)
    VALUES ($1, $2, $3, $4, $5)
"""

async def record_anomaly(pool: asyncpg.Pool, **kwargs):
    async with pool.acquire() as con:
        await con.execute(
            ANOMALY_INSERT,
            kwargs["node_id"],
            kwargs["detected_at"],
            kwargs["anomaly_type"],
            kwargs["metric_name"],
            kwargs["metric_value"],
            kwargs.get("threshold"),
            kwargs["anomaly_score"],
            kwargs.get("description"),
        )
        severity = "critical" if kwargs["anomaly_score"] > 0.8 else "warning"
        await con.execute(
            ALERT_INSERT,
            kwargs["detected_at"],
            severity,
            kwargs["node_id"],
            kwargs["anomaly_type"],
            kwargs.get("description", "Anomaly detected"),
        )


# ================================================================
# Layer 1 — Rule-Based Detection
# ================================================================
async def rule_based_detection(pool: asyncpg.Pool):
    """
    Check the *latest* metric row per node against hard thresholds.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=2)
    async with pool.acquire() as con:
        rows = await con.fetch(
            """SELECT DISTINCT ON (node_id)
                      node_id, timestamp, cpu_usage, memory_usage, latency_ms
               FROM metrics
               WHERE timestamp >= $1
               ORDER BY node_id, timestamp DESC""",
            since,
        )

    now = datetime.now(timezone.utc)
    for row in rows:
        checks = [
            ("cpu",     row["cpu_usage"],    CPU_THRESH,     "High CPU usage"),
            ("memory",  row["memory_usage"], MEM_THRESH,     "High Memory usage"),
            ("latency", row["latency_ms"],   LATENCY_THRESH, "High Latency"),
        ]
        for metric, value, threshold, desc in checks:
            if value > threshold:
                excess_pct = (value - threshold) / threshold
                score = min(1.0, 0.5 + excess_pct)
                log.warning(
                    f"[Rule] node={row['node_id']} {metric}={value:.1f} > {threshold}"
                )
                await record_anomaly(
                    pool,
                    node_id      = row["node_id"],
                    detected_at  = now,
                    anomaly_type = "rule_based",
                    metric_name  = metric,
                    metric_value = value,
                    threshold    = threshold,
                    anomaly_score= round(score, 3),
                    description  = f"{desc}: {value:.1f} exceeds threshold {threshold}",
                )


# ================================================================
# Layer 2 — ML-Based Detection (Isolation Forest)
# ================================================================
async def ml_based_detection(pool: asyncpg.Pool):
    """
    For each node with enough data, fit an Isolation Forest on the last 60min
    and flag any recent points with a negative decision score.
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
    async with pool.acquire() as con:
        rows = await con.fetch(
            """SELECT node_id, timestamp, cpu_usage, memory_usage, latency_ms, requests_per_sec
               FROM metrics
               WHERE timestamp >= $1
               ORDER BY node_id, timestamp""",
            since,
        )

    if not rows:
        return

    # Group by node
    by_node: dict[str, list] = {}
    for r in rows:
        by_node.setdefault(r["node_id"], []).append(r)

    now = datetime.now(timezone.utc)
    recent_window = datetime.now(timezone.utc) - timedelta(minutes=2)

    for node_id, node_rows in by_node.items():
        if len(node_rows) < 30:
            continue  # not enough data to train

        features = np.array([
            [r["cpu_usage"], r["memory_usage"], r["latency_ms"], r["requests_per_sec"]]
            for r in node_rows
        ], dtype=np.float32)

        clf = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
        clf.fit(features)

        # Score only the last N recent points
        recent_rows = [r for r in node_rows if r["timestamp"] >= recent_window]
        if not recent_rows:
            continue

        recent_feats = np.array([
            [r["cpu_usage"], r["memory_usage"], r["latency_ms"], r["requests_per_sec"]]
            for r in recent_rows
        ], dtype=np.float32)

        scores   = clf.decision_function(recent_feats)   # negative = anomalous
        raw_pred = clf.predict(recent_feats)              # -1 = outlier

        for i, row in enumerate(recent_rows):
            if raw_pred[i] == -1:
                # Normalise score to [0,1] — more negative = higher severity
                anomaly_score = min(1.0, max(0.01, 0.5 - float(scores[i])))
                log.warning(
                    f"[ML] node={node_id} anomaly_score={anomaly_score:.3f} "
                    f"cpu={row['cpu_usage']} mem={row['memory_usage']}"
                )
                await record_anomaly(
                    pool,
                    node_id      = node_id,
                    detected_at  = now,
                    anomaly_type = "ml_based",
                    metric_name  = "composite",
                    metric_value = float(row["cpu_usage"]),
                    threshold    = None,
                    anomaly_score= round(anomaly_score, 3),
                    description  = (
                        f"Isolation Forest outlier detected on {node_id}: "
                        f"cpu={row['cpu_usage']:.1f}% mem={row['memory_usage']:.1f}% "
                        f"lat={row['latency_ms']:.1f}ms rps={row['requests_per_sec']:.1f}"
                    ),
                )


# ── Main loop ────────────────────────────────────────────────────
async def main():
    log.info(f"Anomaly Engine starting  interval={RUN_INTERVAL}s")
    pool = await create_pool()

    while True:
        try:
            await rule_based_detection(pool)
            await ml_based_detection(pool)
        except Exception as e:
            log.error(f"Anomaly detection cycle error: {e}", exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
