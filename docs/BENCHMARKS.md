# Benchmark Notes

This document records what has actually been measured in this repository and what still needs to be rerun after recent implementation changes.

## Available benchmark artifacts

Current checked-in JSON results under `benchmarks/results/`:

| Artifact | Status | Notes |
| --- | --- | --- |
| `latency_health_endpoint.json` | valid | Captures `/health` latency baseline |
| `memory_at_rest.json` | valid | Captures idle memory footprint of the benchmark process |
| `throughput_1k_metrics_per_sec.json` | valid | 60-second bulk-ingest run against the local Docker stack |
| `LOAD_TEST_GRADUAL_2026-04-19.md` | valid | 10-minute Locust gradual ramp with autoscaling evidence |
| `LOAD_TEST_SPIKE_2026-04-20.md` | valid | 5-minute Locust spike run with autoscaling evidence |
| `week2_scaling_events.csv` | valid | Exported Postgres scaling events for the week-2 load-test windows |

## Measured values

From `latency_health_endpoint.json`:

- p50: 1.86 ms
- p95: 2.61 ms
- p99: 3.21 ms
- p99.9: 3.87 ms

From `memory_at_rest.json`:

- initial RSS: 48.31 MB
- peak RSS: 48.33 MB
- final RSS: 48.33 MB
- growth over 10 seconds: 0.02 MB

From `throughput_1k_metrics_per_sec.json`:

- duration: 60.04 seconds
- batch size: 20 metrics/request
- achieved throughput: 999 metrics/sec
- total metrics sent: 60,000
- failed metrics: 0
- request rate: 49.97 requests/sec
- p50 latency: 51.58 ms
- p95 latency: 65.88 ms
- p99 latency: 96.05 ms

From `LOAD_TEST_GRADUAL_2026-04-19.md`:

- batch size: 5 metrics/request
- peak users: 150
- total requests: 65,228
- failures: 0
- average response time: 1,051.09 ms
- peak throughput: 198.70 req/sec
- estimated metrics ingested: 195,605
- scaling events during the test window: `2 -> 5 -> 8`

From `LOAD_TEST_SPIKE_2026-04-20.md`:

- batch size: 5 metrics/request
- peak users: 300
- total requests: 27,896
- failures: 0
- average response time: 2,848.27 ms
- peak throughput: 132.70 req/sec
- estimated metrics ingested: 83,965
- scaling events during the test window: `2 -> 5 -> 8`

## Throughput benchmark notes

- The throughput benchmark now targets `POST /api/metrics/bulk` when batch size is greater than 1.
- The checked-in 1K result measures metric throughput, not single-request throughput.
- The ingestion service container startup path was fixed so queued metrics now drain into Postgres during validation.
- `python scripts/validate_ingestion.py` currently passes with 100/100 metrics observed in Postgres for a unique validation run.

## Load test notes

- The week-2 Locust profile uses `FastHttpUser` and disables auth by default to keep the client from becoming the bottleneck before the API stack does.
- Both checked-in week-2 runs completed with zero request failures, which is the main availability signal.
- The mixed workload exposed an imbalance in the local stack: `POST /api/metrics/bulk` remained comparatively healthy while `GET /api/metrics` and `GET /api/status` degraded into multi-second p95/p99 latencies.
- Autoscaling evidence is recorded in Postgres `scaling_events`, not just in container logs, and both measured runs show the autoscaler moving from the 2-worker floor to the 8-worker cap.
- These artifacts are local Docker Compose measurements only. They are not AWS or production numbers.
- Visual summaries generated from the CSV artifacts live in `docs/images/week2_gradual_requests_per_second.svg`, `docs/images/week2_spike_requests_per_second.svg`, and `docs/images/week2_autoscaling_timeline.svg`.
- The full week-2 evidence summary lives in `docs/WEEK2_VALIDATION.md`.

## Rerun commands

Start the stack:

```bash
docker compose up -d --build
./scripts/wait-for-health.sh
python scripts/validate_ingestion.py
```

Then rerun:

```bash
python -m pytest benchmarks/test_latency.py::test_health_endpoint_latency -m benchmark -v
THROUGHPUT_BATCH_SIZE=20 python -m pytest benchmarks/test_throughput.py::test_throughput_1k_metrics_per_sec -m benchmark -v
python -m pytest benchmarks/test_memory_footprint.py::test_memory_at_rest -m benchmark -v
```

Generate week-2 evidence exports after the local stack has run the load tests:

```bash
python scripts/export_week2_evidence.py
```

## CI support

Benchmark regression support now has its own workflow:

- `.github/workflows/benchmark.yml`

That workflow brings up the minimal compose stack, waits for `/health`, runs a latency benchmark and a 1K throughput benchmark, and uploads the resulting JSON artifacts.

## Recommendation

Keep the README claim scoped to what has actually been measured:

- local Docker stack
- bulk ingestion path with 20 metrics/request
- validated Redis-to-Postgres pipeline

Do not generalize this artifact to cloud deployment or single-metric request throughput until those are benchmarked separately.
