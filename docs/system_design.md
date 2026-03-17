# ScaleGuard X — System Design Document

## Design Principles

1. **Separation of Concerns** — Each microservice owns exactly one domain. No service writes to another service's primary data store directly.
2. **Asynchronous Everything** — Ingestion is non-blocking. Analytics engines run on independent schedules.
3. **Backpressure via Queuing** — Redis Streams buffer spikes so that Postgres isn't overwhelmed by direct writes.
4. **Graceful Degradation** — All services retry on startup and log warnings rather than crashing when dependencies are temporarily unavailable.
5. **Environment-Driven Config** — All thresholds, intervals, and connection strings are environment variables, not hardcoded.

---

## Database Design

### `metrics` table (time-series core)
- Every 5 seconds × N nodes → high write rate
- TimescaleDB hypertable recommended for automatic chunk partitioning
- Index on `(node_id, timestamp DESC)` for efficient per-node windowed queries

### `anomalies` table
- Written by the anomaly_engine after each 10s detection cycle
- Serves both API consumers and alerting

### `predictions` table
- Written by prediction_engine every 30s
- Autoscaler reads the latest row; API gateway exposes history

### `scaling_events` table
- Append-only audit log of every autoscaling decision
- Enables post-hoc analysis and dashboard display

### `alerts` table
- Raised by anomaly_engine alongside anomaly records
- Severity: `info | warning | critical`
- `resolved` flag for future alert resolution support

### `workers` table
- Soft registry synced by autoscaler every 15s from Docker API
- Persists worker identity across container restarts

---

## Anomaly Detection Design

### Layer 1 — Rule-Based (O(n) per node)
- Checks the latest metric row per node
- Deterministic, low latency, human-understandable thresholds
- Generates `anomaly_type=rule_based` records

### Layer 2 — Isolation Forest (O(n log n) per node)
- Trains on 60-minute rolling window (min 30 samples)
- `contamination=0.05` → expects ~5% of points to be anomalous
- Scores are normalized to `[0,1]`; higher = more anomalous
- Generates `anomaly_type=ml_based` records
- Re-trains every cycle (simple enough to be fast, but in production would cache the model)

---

## Prediction Engine Design

### Data: per-minute RPS averages over 60 minutes
- Group by `date_trunc('minute', timestamp)` to get one RPS sample per minute
- Provides ~60 points as ARIMA input

### Model: ARIMA(2,1,2)
- Order `(2,1,2)` captures short-term autocorrelation and a first-difference for trend
- `statsmodels` ARIMA with `warnings` suppressed for noisy convergence messages
- **Fallback**: Exponential Moving Average (α=0.3) + linear trend, confidence 0.6

### Output
- `predicted_rps` for the next `PREDICTION_HORIZON_MINUTES` (default 10)
- `confidence` from ARIMA 80% confidence interval width

---

## Autoscaling Design

### Utilization Formula
```
utilization = 0.6 × (avg_cpu / 100) + 0.4 × min(1, predicted_rps / 300)
```
- Weighted combination of CPU reality and predicted load
- RPS baseline of 300 is tunable via threshold env vars

### Decision Logic
| Condition | Action |
|---|---|
| `utilization >= UP_THRESH (0.75)` AND `workers < MAX` | +1 worker |
| `utilization <= DOWN_THRESH (0.35)` AND `workers > MIN` | -1 worker |
| Otherwise | No change |

### Docker Integration
- Scale-up: `docker_client.containers.run(image, detach=True, network=..., labels=...)`
- Scale-down: Stop + remove the newest dynamic container (label: `scaleguard.dynamic=true`)
- Worker registry sync: Cross-reference running containers to update `workers` table

---

## Message Queue Design

### Redis Streams
- Stream key: `metrics_stream`
- Producers: metrics_agent, worker_cluster nodes (XADD)
- Consumer: ingestion_service (XREADGROUP with group `ingestion_group`)
- Acknowledged with XACK after confirmed Postgres write
- Messages not ACK'd are retained in PEL for redelivery → no data loss on ingestion crash

---

## Scalability Considerations

| Bottleneck | Current Design | Production Enhancement |
|---|---|---|
| Postgres write throughput | Batch executemany | TimescaleDB + connection pooling (PgBouncer) |
| Redis throughput | Single stream | Multiple stream partitions by node group |
| Anomaly engine | Single process, per-node | Distributed workers with Celery |
| ARIMA fitting | Single process | Cache model object, retrain only on staleness |
| API Gateway | 2 uvicorn workers | Behind load balancer with more replicas |
