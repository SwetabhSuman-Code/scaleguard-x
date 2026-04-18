# Benchmark Notes

This document records what has actually been measured in this repository and what still needs to be rerun after recent implementation changes.

## Available benchmark artifacts

Current checked-in JSON results under `benchmarks/results/`:

| Artifact | Status | Notes |
| --- | --- | --- |
| `latency_health_endpoint.json` | valid | Captures `/health` latency baseline |
| `memory_at_rest.json` | valid | Captures idle memory footprint of the benchmark process |
| `throughput_1k_metrics_per_sec.json` | invalidated | Earlier run recorded zero successful writes |

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

## Why the throughput result is not publishable

The repository previously stored a failed 1K throughput run with:

- achieved throughput: 0 metrics/sec
- failed attempts: 18,400
- success flag: false

That result is useful as a historical debugging artifact, but it should not be used as a product claim. The API ingestion path has since been updated to accept the benchmark payload shape and to enqueue metrics through Redis or store them directly in Postgres when Redis is unavailable. Throughput must be rerun against a live stack before any new capacity claim is made.

## Rerun commands

Start the stack:

```bash
docker compose up -d --build
```

Then rerun:

```bash
pytest benchmarks/test_latency.py::test_health_endpoint_latency -m benchmark -v
pytest benchmarks/test_throughput.py::test_throughput_1k_metrics_per_sec -m benchmark -v
pytest benchmarks/test_memory_footprint.py::test_memory_at_rest -m benchmark -v
```

## CI support

Benchmark regression support now has its own workflow:

- `.github/workflows/benchmark.yml`

That workflow brings up the minimal compose stack, waits for `/health`, runs a latency benchmark and a 1K throughput benchmark, and uploads the resulting JSON artifacts.

## Recommendation

Do not advertise any ingestion throughput number until:

- the benchmark workflow passes at least once
- the results are archived
- the README is updated with the new measured figure
