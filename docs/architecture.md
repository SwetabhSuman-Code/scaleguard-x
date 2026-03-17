# ScaleGuard X — System Architecture

## Overview

ScaleGuard X is a distributed infrastructure observability and autonomous scaling platform modeled after real-world Kubernetes monitoring stacks (Prometheus + Grafana + KEDA). The system ingests metrics from distributed nodes, runs multi-layer anomaly detection, forecasts future load with ML, and automatically adjusts compute resources.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         External Clients                             │
│                    (Browser / API Consumers)                         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP :3000
                    ┌───────▼───────┐
                    │   Dashboard   │   React + Chart.js  (Nginx)
                    │  (Frontend)   │
                    └───────┬───────┘
                            │ /api/* proxy  HTTP :8000
                    ┌───────▼───────┐
                    │  API Gateway  │   FastAPI REST API
                    │   :8000       │
                    └───┬───┬───┬───┘
               reads    │   │   │   reads
          ┌─────────────┘   │   └──────────────┐
          │                 │                  │
   ┌──────▼──────┐  ┌───────▼────────┐  ┌─────▼───────┐
   │  anomalies  │  │  predictions   │  │   metrics   │
   │   (Postgres)│  │   (Postgres)   │  │  (Postgres) │
   └──────▲──────┘  └───────▲────────┘  └─────▲───────┘
          │                 │                  │
   ┌──────┴──────┐  ┌───────┴────────┐  ┌─────┴───────┐
   │   Anomaly   │  │   Prediction   │  │  Ingestion  │
   │   Engine    │  │    Engine      │  │   Service   │
   └─────────────┘  └────────────────┘  └─────▲───────┘
                                               │ XREADGROUP
                                        ┌──────┴──────────┐
                                        │   Redis Stream  │
                                        │  metrics_stream │
                                        └──────▲──▲───────┘
                                        XADD   │  │ XADD
                                   ┌───────────┘  └───────────┐
                             ┌─────┴──────┐           ┌───────┴──────┐
                             │  Metrics   │           │   Worker     │
                             │   Agent    │           │  Cluster     │
                             │ (psutil)   │           │  (N replicas)│
                             └────────────┘           └──────────────┘
                                                             ▲
                                                             │ spawn/kill
                                                      ┌──────┴──────┐
                                                      │  Autoscaler │
                                                      │(Docker SDK) │
                                                      └─────────────┘
```

---

## Service Responsibilities

| Service | Technology | Role |
|---|---|---|
| `postgres_db` | PostgreSQL 16 | Persistent storage for all time-series metrics, anomalies, predictions, scaling events |
| `redis_queue` | Redis 7 | High-throughput message queue via Redis Streams |
| `api_gateway` | FastAPI + asyncpg | Unified REST API; serves dashboard and external consumers |
| `ingestion_service` | Python + asyncpg | Consumer group reader on Redis Stream; batch-inserts to Postgres |
| `metrics_agent` | Python + psutil | Collects real host metrics every 5s, publishes to Redis Stream |
| `worker_cluster` | Python (replicated) | Simulated backend workers with realistic sinusoidal load patterns |
| `anomaly_engine` | scikit-learn | Rule-based + Isolation Forest anomaly detection every 10s |
| `prediction_engine` | statsmodels ARIMA | 10-minute-ahead RPS forecast using 60-min history every 30s |
| `autoscaler` | Python + Docker SDK | Reads predictions+CPU, adjusts worker container count every 15s |
| `dashboard` | React + Chart.js + Nginx | Real-time monitoring UI served via Nginx |

---

## Data Flow

### Metrics Ingestion Path
```
Node (psutil/simulated)
  → XADD metrics_stream              [Redis Streams]
    → ingestion_service XREADGROUP   [Consumer group, batch read]
      → Postgres metrics table       [asyncpg executemany]
```

### Anomaly Detection Path
```
Postgres metrics (last 2 min)
  → rule_based_detection()           [CPU/Mem/Latency thresholds]
  → ml_based_detection()             [Isolation Forest on 60min window]
    → Postgres anomalies table
    → Postgres alerts table
```

### Autoscaling Path
```
Postgres predictions (latest predicted_rps)
  + Postgres metrics (avg cpu last 2 min)
    → utilization score = 0.6*cpu + 0.4*rps_fraction
      → if utilization > 0.75: docker containers run() [spawn worker]
      → if utilization < 0.35: container.stop()+remove() [kill worker]
        → Postgres scaling_events table
```

---

## Inter-Service Communication

- **Agents → Redis**: XADD (fire-and-forget, no back-pressure)
- **Ingestion → Postgres**: Consumer group XREADGROUP, batch executemany
- **Analytics Engines → Postgres**: Direct asyncpg read/write
- **Autoscaler → Docker Engine**: Unix socket `/var/run/docker.sock`
- **Dashboard → API Gateway**: HTTP REST (proxied via Nginx)
- **API Gateway → Postgres**: asyncpg connection pool

---

## Fault Tolerance

- All services retry Postgres/Redis connection up to 15× with exponential-ish backoff
- Ingestion uses consumer groups — messages are not lost if service restarts (redelivered from PEL)
- Autoscaler safely handles Docker socket unavailability (dry-run mode)
- ARIMA falls back to EMA if fitting fails
- All services have `restart: unless-stopped` in compose
