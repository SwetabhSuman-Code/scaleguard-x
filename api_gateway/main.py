"""
ScaleGuard X — API Gateway
Entry point for all dashboard/API consumers.

Upgrades (Phase 1):
  Fix #4 — Circuit breakers on DB and Redis connections
  Fix #5 — Structured JSON logging + request-ID middleware
  Fix #10 — Full FastAPI metadata, typed models, /docs ready
"""

from __future__ import annotations

import os
import asyncio
import uuid
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# ── Shared lib ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api_gateway.auth.jwt_handler import JWTConfig, JWTHandler
from api_gateway.auth.rbac import Permission, RBACManager
from api_gateway.middleware.rate_limiter import RateLimiter
from api_gateway.tracing.tracer import RequestTracer, Tracer, TracingConfig
from lib.circuit_breaker import (
    CircuitBreakerError,
    make_postgres_breaker,
    make_redis_breaker,
)
from lib.logging_config import (
    clear_log_context,
    get_logger,
    set_log_context,
    setup_json_logging,
)
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

load_dotenv()
setup_json_logging("api_gateway")
setup_metrics("api_gateway")
setup_metrics_server(port=9090)
log = get_logger("api_gateway")

# ── Config ────────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)
REDIS_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"

# ── Circuit breakers ──────────────────────────────────────────────
_pg_cb = make_postgres_breaker("api_gateway")
_redis_cb = make_redis_breaker("api_gateway")
_jwt_handler = JWTHandler(
    JWTConfig(
        secret_key=os.getenv(
            "JWT_SECRET_KEY",
            "scaleguard-dev-secret-change-me-32-chars",
        ),
        issuer=os.getenv("JWT_ISSUER", "scaleguard-api"),
        audience=os.getenv("JWT_AUDIENCE", "scaleguard-services"),
        expiration_minutes=int(os.getenv("JWT_EXPIRATION_MINUTES", "60")),
    )
)
_rbac = RBACManager()
_rate_limiter = RateLimiter()
_tracer = Tracer(
    TracingConfig(
        service_name="api_gateway",
        environment=os.getenv("APP_ENV", "development"),
    )
)
_request_tracer = RequestTracer(_tracer)


# ── App State ─────────────────────────────────────────────────────
class AppState:
    db_pool: Optional[asyncpg.Pool] = None
    redis: Optional[aioredis.Redis] = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to Postgres + Redis with exponential back-off."""
    for attempt in range(15):
        delay = min(2**attempt, 30)
        try:
            state.db_pool = await asyncpg.create_pool(
                PG_DSN,
                min_size=int(os.getenv("PG_POOL_MIN", 5)),
                max_size=int(os.getenv("PG_POOL_MAX", 20)),
            )
            log.info("postgres_connected", extra={"attempt": attempt + 1})
            break
        except Exception as exc:
            log.warning(
                "postgres_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            await asyncio.sleep(delay)
    else:
        log.error("postgres_connect_failed_after_retries")

    try:
        state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await state.redis.ping()
        log.info("redis_connected")
    except Exception as exc:
        log.warning("redis_connect_failed", extra={"error": str(exc)})
        state.redis = None

    log.info("api_gateway_ready")
    yield

    if state.db_pool:
        await state.db_pool.close()
    if state.redis:
        await state.redis.aclose()
    log.info("api_gateway_shutdown")


app = FastAPI(
    title="ScaleGuard X — API Gateway",
    version="1.1.0",
    description=(
        "Central REST API for the ScaleGuard X distributed infrastructure "
        "observability and auto-scaling platform. Exposes endpoints for metrics, "
        "anomalies, predictions, scaling events, workers, and system health."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request ID middleware ─────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """
    Inject a unique request_id into every log record for the duration
    of the request. Also returns it as the X-Request-ID response header.
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    set_log_context(request_id=request_id)
    try:
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        clear_log_context()


@app.middleware("http")
async def security_and_observability_middleware(request: Request, call_next):
    """
    Attach tracing, optional JWT identity extraction, and role-aware rate
    limiting to every request without forcing auth for read-only demo flows.
    """
    request.state.trace_id = _request_tracer.start_request_trace(
        request.method,
        request.url.path,
        dict(request.headers),
    )

    auth_header = request.headers.get("Authorization", "")
    user: Dict[str, Any] = {"sub": "anonymous", "roles": ["guest"], "scopes": []}
    if auth_header:
        try:
            token = _jwt_handler.extract_token_from_header(auth_header)
            claims = _jwt_handler.validate_token(token)
            user = {
                "sub": claims.sub,
                "username": claims.username,
                "roles": claims.roles or ["guest"],
                "scopes": claims.scopes or [],
            }
        except Exception as exc:
            _tracer.end_trace()
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": f"Invalid token: {exc}"},
            )

    request.state.user = _serialize_user_for_state(user)
    identifier = str(user.get("sub") or (request.client.host if request.client else "anonymous"))
    role = list(user.get("roles", ["guest"]))[0]
    allowed, metadata = _rate_limiter.check_limit(identifier, role=role)
    if not allowed:
        _tracer.end_trace()
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Rate limit exceeded",
                "reset_after": metadata.get("reset_after"),
            },
        )

    try:
        response: Response = await call_next(request)
    except RuntimeError as exc:
        if str(exc) != "No response returned.":
            _tracer.end_trace()
            raise
        response = Response(status_code=499)
    response.headers["X-Trace-ID"] = request.state.trace_id
    _request_tracer.add_response_span(response.status_code, 0.0)
    _tracer.end_trace()
    return response


# ── DB helper ─────────────────────────────────────────────────────
async def _require_db() -> asyncpg.Pool:
    if state.db_pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return state.db_pool


def _metric_to_stream_entry(metric: "MetricIngestRequest", timestamp: datetime) -> Dict[str, str]:
    return {
        "node_id": metric.node_id,
        "timestamp": str(timestamp.timestamp()),
        "cpu_usage": str(metric.cpu_usage),
        "memory_usage": str(metric.memory_usage),
        "latency_ms": str(metric.latency_ms),
        "requests_per_sec": str(metric.requests_per_sec),
        "disk_usage": str(metric.disk_usage),
    }


# ================================================================
# Pydantic response models
# ================================================================


class MetricPoint(BaseModel):
    """A single metric sample from one node."""

    node_id: str
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    latency_ms: float
    requests_per_sec: float
    disk_usage: float


class AnomalyRecord(BaseModel):
    """An anomaly detected by rule-based or ML-based detection."""

    id: int
    node_id: str
    detected_at: datetime
    anomaly_type: str
    metric_name: str
    metric_value: float
    threshold: Optional[float] = None
    anomaly_score: float
    description: Optional[str] = None


class PredictionRecord(BaseModel):
    """A load forecast produced by the prediction engine."""

    id: int
    predicted_at: datetime
    horizon_minutes: int
    predicted_rps: float
    predicted_cpu: Optional[float] = None
    confidence: Optional[float] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    spike_probability: Optional[float] = None
    model_name: Optional[str] = None


class ScalingEvent(BaseModel):
    """A record of an autoscaling decision."""

    id: int
    triggered_at: datetime
    action: str
    prev_replicas: int
    new_replicas: int
    reason: Optional[str] = None


class AlertRecord(BaseModel):
    """An alert raised by the anomaly or rule engine."""

    id: int
    raised_at: datetime
    severity: str
    node_id: Optional[str] = None
    alert_type: str
    message: str
    resolved: bool


class WorkerRecord(BaseModel):
    """A registered worker container in the worker registry."""

    worker_id: str
    container_id: Optional[str] = None
    registered_at: datetime
    last_heartbeat: datetime
    status: str


class SystemStatus(BaseModel):
    """Aggregated system health snapshot."""

    status: str
    active_workers: int
    nodes_reporting: int
    latest_anomaly_score: float
    predicted_rps: float
    timestamp: datetime


class TokenRequest(BaseModel):
    """Simple development login payload used to mint JWTs."""

    username: str
    subject: Optional[str] = None
    role: str = "viewer"
    email: Optional[str] = None


class MetricIngestRequest(BaseModel):
    """Metric sample accepted by the API ingestion endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    node_id: str = "api-client"
    cpu_usage: float = Field(validation_alias=AliasChoices("cpu_usage", "cpu"))
    memory_usage: float = Field(validation_alias=AliasChoices("memory_usage", "memory"))
    latency_ms: float = Field(validation_alias=AliasChoices("latency_ms", "latency"))
    requests_per_sec: float = Field(validation_alias=AliasChoices("requests_per_sec", "rps"))
    disk_usage: float = Field(
        default=0.0,
        validation_alias=AliasChoices("disk_usage", "disk"),
    )
    timestamp: Optional[datetime] = None


class MetricBatchIngestRequest(BaseModel):
    """Batch of metric samples accepted by the bulk ingestion endpoint."""

    metrics: List[MetricIngestRequest] = Field(min_length=1, max_length=1000)


def _serialize_user_for_state(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sub": user.get("sub", "anonymous"),
        "username": user.get("username"),
        "roles": user.get("roles", ["guest"]),
        "scopes": user.get("scopes", []),
    }


def _current_user(request: Request) -> Dict[str, Any]:
    return getattr(request.state, "user", {"sub": "anonymous", "roles": ["guest"]})


def _require_permission(request: Request, permission: Permission) -> Dict[str, Any]:
    user = _current_user(request)
    access = _rbac.evaluate_access(
        str(user.get("sub", "anonymous")),
        list(user.get("roles", ["guest"])),
        permission,
    )
    if not access.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission.value}",
        )
    return user


async def _enqueue_metrics(metrics: List[MetricIngestRequest]) -> Optional[List[str]]:
    if state.redis is None:
        return None

    stream_key = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
    stream_entries = [
        _metric_to_stream_entry(metric, metric.timestamp or datetime.now(timezone.utc))
        for metric in metrics
    ]

    try:
        async with _redis_cb:
            if len(stream_entries) == 1:
                message_id = await state.redis.xadd(stream_key, stream_entries[0])
                return [message_id]

            async with state.redis.pipeline(transaction=False) as pipe:
                for entry in stream_entries:
                    pipe.xadd(stream_key, entry)
                message_ids = await pipe.execute()
            return [str(message_id) for message_id in message_ids]
    except CircuitBreakerError:
        log.warning("metrics_enqueue_circuit_open")
    except Exception as exc:
        log.warning(
            "metrics_enqueue_failed",
            extra={"error": str(exc), "count": len(stream_entries)},
        )
    return None


async def _store_metrics(metrics: List[MetricIngestRequest]) -> None:
    pool = await _require_db()
    rows = [
        (
            metric.node_id,
            metric.timestamp or datetime.now(timezone.utc),
            metric.cpu_usage,
            metric.memory_usage,
            metric.latency_ms,
            metric.requests_per_sec,
            metric.disk_usage,
        )
        for metric in metrics
    ]

    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.executemany(
                    """INSERT INTO metrics
                       (node_id, timestamp, cpu_usage, memory_usage, latency_ms,
                        requests_per_sec, disk_usage)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    rows,
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ================================================================
# Health
# ================================================================


@app.get(
    "/health",
    tags=["System"],
    summary="Health check",
    description="Returns a simple OK response. Used by Docker and load balancers.",
)
async def health():
    """Liveness probe — always returns 200 if the process is alive."""
    return {
        "status": "ok",
        "service": "api_gateway",
        "timestamp": datetime.now(timezone.utc),
    }


# ================================================================
# Auth
# ================================================================


@app.post("/api/auth/token", tags=["Auth"], summary="Issue a development JWT")
async def create_token(payload: TokenRequest) -> Dict[str, Any]:
    role = payload.role if payload.role in _rbac.roles else "viewer"
    subject = payload.subject or payload.username
    token_data = _jwt_handler.generate_token(
        subject=subject,
        username=payload.username,
        email=payload.email,
        roles=[role],
        scopes=[permission.value for permission in _rbac.get_user_permissions([role])],
    )
    refresh_token = _jwt_handler.generate_refresh_token(subject, username=payload.username)
    return {
        **token_data,
        "refresh_token": refresh_token,
        "role": role,
    }


# ================================================================
# METRICS
# ================================================================


@app.post(
    "/api/metrics",
    tags=["Metrics"],
    summary="Ingest a metric sample",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_metric(payload: MetricIngestRequest, request: Request) -> Dict[str, Any]:
    message_ids = await _enqueue_metrics([payload])
    if message_ids:
        return {
            "status": "queued",
            "message_id": message_ids[0],
            "trace_id": getattr(request.state, "trace_id", None),
        }

    await _store_metrics([payload])

    return {
        "status": "stored",
        "trace_id": getattr(request.state, "trace_id", None),
    }


@app.post(
    "/api/metrics/bulk",
    tags=["Metrics"],
    summary="Ingest a batch of metric samples",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_metrics_bulk(
    payload: MetricBatchIngestRequest,
    request: Request,
) -> Dict[str, Any]:
    message_ids = await _enqueue_metrics(payload.metrics)
    if message_ids:
        return {
            "status": "queued",
            "count": len(payload.metrics),
            "message_count": len(message_ids),
            "first_message_id": message_ids[0],
            "last_message_id": message_ids[-1],
            "trace_id": getattr(request.state, "trace_id", None),
        }

    await _store_metrics(payload.metrics)
    return {
        "status": "stored",
        "count": len(payload.metrics),
        "trace_id": getattr(request.state, "trace_id", None),
    }


@app.get(
    "/api/metrics",
    response_model=List[MetricPoint],
    tags=["Metrics"],
    summary="Retrieve recent metrics",
)
async def get_metrics(
    node_id: Optional[str] = Query(default=None, description="Filter by node ID"),
    minutes: int = Query(default=30, ge=1, le=1440, description="Lookback window in minutes"),
    limit: int = Query(default=500, le=5000, description="Maximum rows returned"),
) -> List[MetricPoint]:
    """
    Return time-series metric samples, optionally filtered by node.
    Results are ordered newest-first.
    """
    pool = await _require_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                if node_id:
                    rows = await con.fetch(
                        """SELECT node_id, timestamp, cpu_usage, memory_usage, latency_ms,
                                  requests_per_sec, disk_usage
                           FROM metrics
                           WHERE node_id = $1 AND timestamp >= $2
                           ORDER BY timestamp DESC LIMIT $3""",
                        node_id,
                        since,
                        limit,
                    )
                else:
                    rows = await con.fetch(
                        """SELECT node_id, timestamp, cpu_usage, memory_usage, latency_ms,
                                  requests_per_sec, disk_usage
                           FROM metrics
                           WHERE timestamp >= $1
                           ORDER BY timestamp DESC LIMIT $2""",
                        since,
                        limit,
                    )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [MetricPoint(**dict(r)) for r in rows]


@app.get("/api/metrics/nodes", tags=["Metrics"], summary="List active nodes")
async def get_active_nodes():
    """Return list of node IDs that have reported metrics in the last 5 minutes."""
    pool = await _require_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    "SELECT DISTINCT node_id FROM metrics WHERE timestamp >= $1", since
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"nodes": [r["node_id"] for r in rows]}


@app.get("/api/metrics/summary", tags=["Metrics"], summary="Latest aggregate metrics")
async def get_metrics_summary():
    """Latest average metrics across all nodes (5-minute window)."""
    pool = await _require_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                row = await con.fetchrow(
                    """SELECT AVG(cpu_usage)        AS avg_cpu,
                              AVG(memory_usage)     AS avg_mem,
                              AVG(latency_ms)       AS avg_latency,
                              AVG(requests_per_sec) AS avg_rps,
                              COUNT(DISTINCT node_id) AS node_count
                       FROM metrics WHERE timestamp >= $1""",
                    since,
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not row:
        return {
            "avg_cpu": 0,
            "avg_mem": 0,
            "avg_latency": 0,
            "avg_rps": 0,
            "node_count": 0,
        }
    return dict(row)


# ================================================================
# ANOMALIES
# ================================================================


@app.get(
    "/api/anomalies",
    response_model=List[AnomalyRecord],
    tags=["Anomalies"],
    summary="List detected anomalies",
)
async def get_anomalies(
    minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=100, le=1000),
) -> List[AnomalyRecord]:
    """Return anomalies detected within the specified lookback window."""
    pool = await _require_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT id, node_id, detected_at, anomaly_type, metric_name,
                              metric_value, threshold, anomaly_score, description
                       FROM anomalies WHERE detected_at >= $1
                       ORDER BY detected_at DESC LIMIT $2""",
                    since,
                    limit,
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [AnomalyRecord(**dict(r)) for r in rows]


# ================================================================
# PREDICTIONS
# ================================================================


@app.get(
    "/api/predictions",
    response_model=List[PredictionRecord],
    tags=["Predictions"],
    summary="Latest load predictions",
)
async def get_predictions(
    limit: int = Query(default=20, le=100),
) -> List[PredictionRecord]:
    """Return the most recent RPS/CPU load predictions from the prediction engine."""
    pool = await _require_db()
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT id, predicted_at, horizon_minutes, predicted_rps,
                              predicted_cpu, confidence, lower_bound, upper_bound,
                              spike_probability, model_name
                       FROM predictions ORDER BY predicted_at DESC LIMIT $1""",
                    limit,
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [PredictionRecord(**dict(r)) for r in rows]


# ================================================================
# SCALING EVENTS
# ================================================================


@app.get(
    "/api/scaling",
    response_model=List[ScalingEvent],
    tags=["Scaling"],
    summary="Autoscaling event history",
)
async def get_scaling_events(
    limit: int = Query(default=50, le=500),
) -> List[ScalingEvent]:
    """Return autoscaling decisions (scale_up, scale_down, no_change)."""
    pool = await _require_db()
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT id, triggered_at, action, prev_replicas, new_replicas, reason
                       FROM scaling_events ORDER BY triggered_at DESC LIMIT $1""",
                    limit,
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [ScalingEvent(**dict(r)) for r in rows]


# ================================================================
# ALERTS
# ================================================================


@app.get(
    "/api/alerts",
    response_model=List[AlertRecord],
    tags=["Alerts"],
    summary="List alerts",
)
async def get_alerts(
    minutes: int = Query(default=60),
    unresolved_only: bool = Query(default=False, description="Only return open alerts"),
    limit: int = Query(default=100, le=500),
) -> List[AlertRecord]:
    """Return alerts, optionally filtering to only unresolved ones."""
    pool = await _require_db()
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                if unresolved_only:
                    rows = await con.fetch(
                        """SELECT id, raised_at, severity, node_id, alert_type, message, resolved
                           FROM alerts WHERE raised_at >= $1 AND resolved = FALSE
                           ORDER BY raised_at DESC LIMIT $2""",
                        since,
                        limit,
                    )
                else:
                    rows = await con.fetch(
                        """SELECT id, raised_at, severity, node_id, alert_type, message, resolved
                           FROM alerts WHERE raised_at >= $1
                           ORDER BY raised_at DESC LIMIT $2""",
                        since,
                        limit,
                    )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [AlertRecord(**dict(r)) for r in rows]


# ================================================================
# WORKERS
# ================================================================


@app.get(
    "/api/workers",
    response_model=List[WorkerRecord],
    tags=["Workers"],
    summary="Worker registry",
)
async def get_workers() -> List[WorkerRecord]:
    """Return all registered worker containers and their current status."""
    pool = await _require_db()
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT worker_id, container_id, registered_at, last_heartbeat, status
                       FROM workers ORDER BY registered_at DESC"""
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [WorkerRecord(**dict(r)) for r in rows]


# ================================================================
# SYSTEM OVERVIEW
# ================================================================


@app.get(
    "/api/status",
    response_model=SystemStatus,
    tags=["System"],
    summary="System health snapshot",
)
async def system_status() -> SystemStatus:
    """Aggregated system health: worker count, reporting nodes, latest anomaly + prediction."""
    pool = await _require_db()
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
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
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return SystemStatus(
        status="operational",
        active_workers=int(worker_count or 0),
        nodes_reporting=int(node_count or 0),
        latest_anomaly_score=round(float(latest_anomaly or 0), 3),
        predicted_rps=round(float(latest_prediction or 0), 2),
        timestamp=datetime.now(timezone.utc),
    )


@app.post(
    "/api/scaling/manual",
    tags=["Scaling"],
    summary="Create a manual scaling request",
)
async def manual_scale(target: int, request: Request) -> Dict[str, Any]:
    user = _require_permission(request, Permission.SCALING_EXECUTE)
    if target < 1:
        raise HTTPException(status_code=400, detail="target must be >= 1")

    pool = await _require_db()
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                previous = await con.fetchval("SELECT COUNT(*) FROM workers WHERE status='active'")
                await con.execute(
                    """INSERT INTO scaling_events
                           (triggered_at, action, prev_replicas, new_replicas, reason)
                       VALUES ($1, $2, $3, $4, $5)""",
                    datetime.now(timezone.utc),
                    "manual_scale",
                    int(previous or 0),
                    target,
                    f"manual request by {user.get('sub', 'anonymous')}",
                )
    except CircuitBreakerError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "status": "accepted",
        "requested_target": target,
        "requested_by": user.get("sub", "anonymous"),
    }
