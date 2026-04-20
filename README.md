# ScaleGuard X

ScaleGuard X is a learning-focused infrastructure monitoring and autoscaling platform built as a multi-service Python project. It demonstrates how metrics ingestion, anomaly detection, forecasting, autoscaling, tracing, and dashboards can fit together in one system without pretending to be a drop-in replacement for Kubernetes, Datadog, or a managed APM stack.

## Current status

This repository now includes the implementation work for the first four roadmap phases:

- Phase 1: benchmark harnesses, result capture, and CI benchmark workflow scaffolding
- Phase 2: Prophet and LSTM model paths in the prediction engine with ARIMA/EMA fallbacks
- Phase 3: predictive autoscaling with PID control and multi-step scaling decisions
- Phase 4: JWT token issuance, RBAC checks, rate limiting, and request tracing in the API gateway

What it does not include yet is hard proof that every production claim has been validated in a real cloud environment. The code is moving in that direction, but several week 9-12 items still require an actual pilot deployment, real traffic, and external tool benchmarking.

## What works in this repo

- FastAPI API gateway with `/health`, `/api/metrics`, token issuance, manual scaling requests, and read APIs
- Redis-backed metric ingestion with database fallback
- Prediction engine with Prophet plus LSTM spike detection when warm-up data exists
- Predictive autoscaler that reads stored forecasts and can scale by more than one worker at a time
- Structured logging, circuit breakers, Prometheus metrics, and request tracing support
- Grafana dashboards, Prometheus config, docker-compose stack, and ECS Terraform scaffolding
- Unit and integration coverage for auth, middleware, tracing, PID control, predictive scaling, and prediction helpers

## Measured results

Measured benchmark artifacts currently checked into the repo:

| Metric | Result | Source |
| --- | --- | --- |
| `/health` latency p50 | 1.86 ms | `benchmarks/results/latency_health_endpoint.json` |
| `/health` latency p99 | 3.21 ms | `benchmarks/results/latency_health_endpoint.json` |
| Idle memory peak | 48.33 MB | `benchmarks/results/memory_at_rest.json` |
| Ingestion throughput | 999 metrics/sec | `benchmarks/results/throughput_1k_metrics_per_sec.json` |
| Ingestion throughput p99 | 96.05 ms | `benchmarks/results/throughput_1k_metrics_per_sec.json` |
| Ingestion success rate | 100% | `benchmarks/results/throughput_1k_metrics_per_sec.json` |
| Gradual load test peak users | 150 users | `benchmarks/results/LOAD_TEST_GRADUAL_2026-04-19.md` |
| Gradual load test failures | 0 / 65,228 requests | `benchmarks/results/LOAD_TEST_GRADUAL_2026-04-19.md` |
| Gradual load test peak throughput | 198.70 req/sec | `benchmarks/results/LOAD_TEST_GRADUAL_2026-04-19.md` |
| Spike load test peak users | 300 users | `benchmarks/results/LOAD_TEST_SPIKE_2026-04-20.md` |
| Spike load test failures | 0 / 27,896 requests | `benchmarks/results/LOAD_TEST_SPIKE_2026-04-20.md` |
| Spike load test peak throughput | 132.70 req/sec | `benchmarks/results/LOAD_TEST_SPIKE_2026-04-20.md` |
| Autoscaling evidence | `2 -> 5 -> 8` workers in gradual and spike runs | `benchmarks/results/week2_scaling_events.csv` |

Notes:
- The throughput benchmark uses `POST /api/metrics/bulk` with batches of 20 metrics per request, which is how the local Docker stack reached the measured 999 metrics/sec result.
- End-to-end pipeline validation currently passes with `python scripts/validate_ingestion.py`, which sent 100 metrics and observed 100 rows stored in Postgres for that run.
- The week-2 Locust runs use `POST /api/metrics/bulk` with batches of 5 metrics per request and a mixed workload that also hits `GET /api/metrics` and `GET /api/status`.

## Week 2 load testing

Local week-2 validation now includes two measured Locust runs against the Docker Compose stack:

| Test | Result | Source |
| --- | --- | --- |
| Gradual ramp | 150 peak users, 65,228 requests, 0 failures, 198.70 req/sec peak | `benchmarks/results/LOAD_TEST_GRADUAL_2026-04-19.md` |
| Gradual autoscaling | `2 -> 5 -> 8` workers during the test window | `benchmarks/results/LOAD_TEST_GRADUAL_2026-04-19.md` |
| Spike test | 300 peak users, 27,896 requests, 0 failures, 132.70 req/sec peak | `benchmarks/results/LOAD_TEST_SPIKE_2026-04-20.md` |
| Spike autoscaling | `2 -> 5 -> 8` workers during the test window | `benchmarks/results/LOAD_TEST_SPIKE_2026-04-20.md` |

What these week-2 runs show:

- the write-heavy ingest path stays available under both gradual and spike traffic
- the autoscaler reacts quickly enough to move from the 2-worker floor to the 8-worker cap in local testing
- the current read endpoints are the bottleneck under load, with multi-second p95 and p99 latencies in both runs

That means week 2 produced real autoscaling evidence, but it also surfaced the next honest target for week 3 and beyond: improving `GET /api/metrics` and `GET /api/status` performance rather than pretending the whole stack is balanced already.

Week-2 evidence bundle:

- [docs/WEEK2_VALIDATION.md](docs/WEEK2_VALIDATION.md)
- [benchmarks/results/week2_scaling_events.csv](benchmarks/results/week2_scaling_events.csv)
- [docs/images/week2_autoscaling_timeline.svg](docs/images/week2_autoscaling_timeline.svg)
- [docs/images/week2_gradual_requests_per_second.svg](docs/images/week2_gradual_requests_per_second.svg)
- [docs/images/week2_spike_requests_per_second.svg](docs/images/week2_spike_requests_per_second.svg)

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for details and rerun instructions.

## Architecture

```mermaid
graph TD
    Dashboard["Dashboard"] --> Gateway["API Gateway"]
    Gateway --> Postgres["PostgreSQL"]
    Gateway --> Redis["Redis"]
    Agent["Metrics Agent"] --> Redis
    Workers["Worker Cluster"] --> Redis
    Redis --> Ingestion["Ingestion Service"]
    Ingestion --> Postgres
    Postgres --> Prediction["Prediction Engine"]
    Postgres --> Anomaly["Anomaly Engine"]
    Postgres --> Autoscaler["Autoscaler"]
    Autoscaler --> Workers
    Gateway -. traces .-> Jaeger["Jaeger"]
    Gateway -. metrics .-> Prometheus["Prometheus"]
    Prometheus --> Grafana["Grafana"]
```

## Running locally

1. Copy `.env.example` to `.env`.
2. Set strong values for `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, and `JWT_SECRET_KEY`.
3. Start the stack with `docker compose up -d --build`.
4. Wait for the API to come up with `./scripts/wait-for-health.sh`.
5. Validate the ingestion pipeline with `python scripts/validate_ingestion.py`.
6. Open:
   - Dashboard: `http://localhost:3000`
   - API docs: `http://localhost:8000/docs`
   - Prometheus: `http://localhost:9090`
   - Grafana: `http://localhost:3001`
   - Jaeger: `http://localhost:16686`

## Benchmarks and validation

- Benchmark code lives in `benchmarks/`
- Benchmark CI workflow lives in `.github/workflows/benchmark.yml`
- Competitive-analysis helper script lives in `benchmarks/competitive_analysis.py`
- Production smoke tests live in `tests/production/test_deployment.py`
- Chaos-focused service tests live in `tests/chaos/test_failure_modes.py`

## Deployment path

AWS delivery is represented as a pilot deployment scaffold, not a claimed production rollout:

- Terraform scaffold: [infrastructure/terraform/main.tf](infrastructure/terraform/main.tf)
- Terraform variables example: [infrastructure/terraform/terraform.tfvars.example](infrastructure/terraform/terraform.tfvars.example)
- Deployment guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Real-world validation notes: [docs/REAL_WORLD_USAGE.md](docs/REAL_WORLD_USAGE.md)

The Terraform config targets AWS ECS Fargate with RDS PostgreSQL, ElastiCache Redis, an HTTPS ALB, and CloudWatch logs. The autoscaler now has an ECS backend that updates the worker service desired count in AWS, while the local Docker backend remains available for Compose validation. Terraform planning and ECR push were not executed in this workspace because `terraform` and `aws` are not installed here.

## Honest positioning

Use ScaleGuard X when:

- you want to learn how monitoring and autoscaling components fit together
- you want to inspect and modify the forecasting and scaling logic directly
- you need a portfolio project that shows distributed-systems and observability patterns

Do not use ScaleGuard X as-is when:

- you need proven, high-volume production throughput numbers
- you need HA, multi-region, audited security controls, or vendor support
- you need managed alerting, mature incident tooling, or large-scale autoscaling guarantees

## Documentation

- [docs/BENCHMARKS.md](docs/BENCHMARKS.md)
- [docs/WEEK2_VALIDATION.md](docs/WEEK2_VALIDATION.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/REAL_WORLD_USAGE.md](docs/REAL_WORLD_USAGE.md)
- [docs/ONCALL_RUNBOOK.md](docs/ONCALL_RUNBOOK.md)
- [docs/api_docs.md](docs/api_docs.md)

## Development notes

- Python configuration lives in [pyproject.toml](pyproject.toml)
- Main services live in `api_gateway/`, `prediction_engine/`, `autoscaler/`, `ingestion_service/`, `anomaly_engine/`, and `metrics_agent/`
- The most meaningful verification right now is the targeted unit and integration suites, plus rerunning benchmarks against a live stack
