"""
ScaleGuard X — API Gateway
Entry point for all dashboard/API consumers.
Exposes REST endpoints for:
  - metrics querying
  - anomaly listing
  - prediction listing
  - scaling history
  - worker registry
  - system control / health
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── env ─────────────────────────────────────────────────────────
load_dotenv()

PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER','scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD','scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST','localhost')}"
    f":{os.getenv('POSTGRES_PORT','5432')}"
    f"/{os.getenv('POSTGRES_DB','scaleguard')}"
)
REDIS_URL = f"redis://{os.getenv('REDIS_HOST','localhost')}:{os.getenv('REDIS_PORT','6379')}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [API-GW] %(levelname)s %(message)s")
log = logging.getLogger("api_gateway")

# ── App State ────────────────────────────────────────────────────
class AppState:
    db_pool: asyncpg.Pool = None
    redis: aioredis.Redis = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to Postgres and Redis on startup
    for attempt in range(10):
        try:
            state.db_pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)
            break
        except Exception as e:
            log.warning(f"Waiting for Postgres (attempt {attempt+1}): {e}")
            await asyncio.sleep(3)
    else:
        log.error("Could not connect to Postgres after 10 attempts")

    state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info("API Gateway started — DB and Redis connected")
    yield
    if state.db_pool:
        await state.db_pool.close()
    if state.redis:
        await state.redis.aclose()

app = FastAPI(
    title="ScaleGuard X — API Gateway",
    version="1.0.0",
    description="Central API for ScaleGuard X infrastructure monitoring platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# Pydantic response models
# ================================================================

class MetricPoint(BaseModel):
    node_id: str
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    latency_ms: float
    requests_per_sec: float
    disk_usage: float

class AnomalyRecord(BaseModel):
    id: int
    node_id: str
    detected_at: datetime
    anomaly_type: str
    metric_name: str
    metric_value: float
    threshold: Optional[float]
    anomaly_score: float
    description: Optional[str]

class PredictionRecord(BaseModel):
    id: int
    predicted_at: datetime
    horizon_minutes: int
    predicted_rps: float
    predicted_cpu: Optional[float]
    confidence: Optional[float]

class ScalingEvent(BaseModel):
    id: int
    triggered_at: datetime
    action: str
    prev_replicas: int
    new_replicas: int
    reason: Optional[str]

class AlertRecord(BaseModel):
    id: int
    raised_at: datetime
    severity: str
    node_id: Optional[str]
    alert_type: str
    message: str
    resolved: bool

class WorkerRecord(BaseModel):
    worker_id: str
    container_id: Optional[str]
    registered_at: datetime
    last_heartbeat: datetime
    status: str

class SystemStatus(BaseModel):
    status: str
    active_workers: int
    nodes_reporting: int
    latest_anomaly_score: float
    predicted_rps: float
    timestamp: datetime

# ================================================================
# Health check
# ================================================================

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "api_gateway", "timestamp": datetime.now(timezone.utc)}

# ================================================================
# METRICS
# ================================================================

@app.get("/api/metrics", response_model=List[MetricPoint], tags=["Metrics"])
async def get_metrics(
    node_id: Optional[str] = None,
    minutes: int = Query(default=30, ge=1, le=1440, description="How many minutes back"),
    limit: int = Query(default=500, le=5000),
):
    """Return recent metrics optionally filtered by node."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    async with state.db_pool.acquire() as con:
        if node_id:
            rows = await con.fetch(
                """SELECT node_id, timestamp, cpu_usage, memory_usage, latency_ms,
                          requests_per_sec, disk_usage
                   FROM metrics
                   WHERE node_id = $1 AND timestamp >= $2
                   ORDER BY timestamp DESC LIMIT $3""",
                node_id, since, limit,
            )
        else:
            rows = await con.fetch(
                """SELECT node_id, timestamp, cpu_usage, memory_usage, latency_ms,
                          requests_per_sec, disk_usage
                   FROM metrics
                   WHERE timestamp >= $1
                   ORDER BY timestamp DESC LIMIT $2""",
                since, limit,
            )
    return [MetricPoint(**dict(r)) for r in rows]


@app.get("/api/metrics/nodes", tags=["Metrics"])
async def get_active_nodes():
    """Return list of node IDs that have reported metrics in the last 5 minutes."""
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with state.db_pool.acquire() as con:
        rows = await con.fetch(
            "SELECT DISTINCT node_id FROM metrics WHERE timestamp >= $1", since
        )
    return {"nodes": [r["node_id"] for r in rows]}


@app.get("/api/metrics/summary", tags=["Metrics"])
async def get_metrics_summary():
    """Latest average metrics across all nodes."""
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with state.db_pool.acquire() as con:
        row = await con.fetchrow(
            """SELECT AVG(cpu_usage) AS avg_cpu,
                      AVG(memory_usage) AS avg_mem,
                      AVG(latency_ms) AS avg_latency,
                      AVG(requests_per_sec) AS avg_rps,
                      COUNT(DISTINCT node_id) AS node_count
               FROM metrics WHERE timestamp >= $1""",
            since,
        )
    if not row:
        return {"avg_cpu": 0, "avg_mem": 0, "avg_latency": 0, "avg_rps": 0, "node_count": 0}
    return dict(row)

# ================================================================
# ANOMALIES
# ================================================================

@app.get("/api/anomalies", response_model=List[AnomalyRecord], tags=["Anomalies"])
async def get_anomalies(
    minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=100, le=1000),
):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    async with state.db_pool.acquire() as con:
        rows = await con.fetch(
            """SELECT id, node_id, detected_at, anomaly_type, metric_name,
                      metric_value, threshold, anomaly_score, description
               FROM anomalies WHERE detected_at >= $1
               ORDER BY detected_at DESC LIMIT $2""",
            since, limit,
        )
    return [AnomalyRecord(**dict(r)) for r in rows]

# ================================================================
# PREDICTIONS
# ================================================================

@app.get("/api/predictions", response_model=List[PredictionRecord], tags=["Predictions"])
async def get_predictions(limit: int = Query(default=20, le=100)):
    async with state.db_pool.acquire() as con:
        rows = await con.fetch(
            """SELECT id, predicted_at, horizon_minutes, predicted_rps, predicted_cpu, confidence
               FROM predictions ORDER BY predicted_at DESC LIMIT $1""",
            limit,
        )
    return [PredictionRecord(**dict(r)) for r in rows]

# ================================================================
# SCALING EVENTS
# ================================================================

@app.get("/api/scaling", response_model=List[ScalingEvent], tags=["Scaling"])
async def get_scaling_events(limit: int = Query(default=50, le=500)):
    async with state.db_pool.acquire() as con:
        rows = await con.fetch(
            """SELECT id, triggered_at, action, prev_replicas, new_replicas, reason
               FROM scaling_events ORDER BY triggered_at DESC LIMIT $1""",
            limit,
        )
    return [ScalingEvent(**dict(r)) for r in rows]

# ================================================================
# ALERTS
# ================================================================

@app.get("/api/alerts", response_model=List[AlertRecord], tags=["Alerts"])
async def get_alerts(
    minutes: int = Query(default=60),
    unresolved_only: bool = False,
    limit: int = Query(default=100, le=500),
):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    async with state.db_pool.acquire() as con:
        if unresolved_only:
            rows = await con.fetch(
                """SELECT id, raised_at, severity, node_id, alert_type, message, resolved
                   FROM alerts WHERE raised_at >= $1 AND resolved = FALSE
                   ORDER BY raised_at DESC LIMIT $2""",
                since, limit,
            )
        else:
            rows = await con.fetch(
                """SELECT id, raised_at, severity, node_id, alert_type, message, resolved
                   FROM alerts WHERE raised_at >= $1
                   ORDER BY raised_at DESC LIMIT $2""",
                since, limit,
            )
    return [AlertRecord(**dict(r)) for r in rows]

# ================================================================
# WORKERS
# ================================================================

@app.get("/api/workers", response_model=List[WorkerRecord], tags=["Workers"])
async def get_workers():
    async with state.db_pool.acquire() as con:
        rows = await con.fetch(
            """SELECT worker_id, container_id, registered_at, last_heartbeat, status
               FROM workers ORDER BY registered_at DESC"""
        )
    return [WorkerRecord(**dict(r)) for r in rows]

# ================================================================
# SYSTEM OVERVIEW
# ================================================================

@app.get("/api/status", response_model=SystemStatus, tags=["System"])
async def system_status():
    async with state.db_pool.acquire() as con:
        worker_count = await con.fetchval(
            "SELECT COUNT(*) FROM workers WHERE status='active'"
        )
        node_count = await con.fetchval(
            "SELECT COUNT(DISTINCT node_id) FROM metrics WHERE timestamp >= $1",
            datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        latest_anomaly = await con.fetchval(
            "SELECT MAX(anomaly_score) FROM anomalies WHERE detected_at >= $1",
            datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        latest_prediction = await con.fetchval(
            "SELECT predicted_rps FROM predictions ORDER BY predicted_at DESC LIMIT 1"
        )
    return SystemStatus(
        status="operational",
        active_workers=worker_count or 0,
        nodes_reporting=node_count or 0,
        latest_anomaly_score=round(float(latest_anomaly or 0), 3),
        predicted_rps=round(float(latest_prediction or 0), 2),
        timestamp=datetime.now(timezone.utc),
    )
