# Load Test Results - April 20, 2026

## Summary
- Batch size: 5
- Peak users: 300
- Total requests: 27896
- Failures: 0
- Average response time: 2848.27 ms
- P95 latency: 8700 ms
- P99 latency: 10000 ms
- Sustained throughput: 93.55 req/sec
- Peak throughput: 132.70 req/sec

## Endpoints
- GET /api/metrics: 5496 requests, 0 failures, p95 9800 ms, p99 13000 ms
- POST /api/metrics/bulk: 16793 requests, 0 failures, p95 500 ms, p99 1400 ms
- GET /api/status: 5607 requests, 0 failures, p95 9300 ms, p99 12000 ms

## Pipeline Impact
- Estimated metrics ingested: 83965

## Scaling Events
- 2026-04-19 18:36:33.711703+00: scale_up 2 -> 5 (PID: -3.00, Prophet: +0.00, LSTM: +0.00; cpu=76.9; predicted_rps=0.0; upper_util=0.0; spike_probability=0.00; model=none)
- 2026-04-19 18:36:54.68571+00: scale_up 5 -> 8 (PID: -3.00, Prophet: +0.00, LSTM: +0.00; cpu=77.6; predicted_rps=0.0; upper_util=0.0; spike_probability=0.00; model=none)
