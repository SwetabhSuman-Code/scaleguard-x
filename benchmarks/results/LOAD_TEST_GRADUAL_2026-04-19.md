# Load Test Results - April 20, 2026

## Summary
- Batch size: 5
- Peak users: 150
- Total requests: 65228
- Failures: 0
- Average response time: 1051.09 ms
- P95 latency: 3800 ms
- P99 latency: 4800 ms
- Sustained throughput: 109.04 req/sec
- Peak throughput: 198.70 req/sec

## Endpoints
- GET /api/metrics: 12991 requests, 0 failures, p95 4100 ms, p99 5000 ms
- POST /api/metrics/bulk: 39121 requests, 0 failures, p95 400 ms, p99 680 ms
- GET /api/status: 13116 requests, 0 failures, p95 4600 ms, p99 5500 ms

## Pipeline Impact
- Estimated metrics ingested: 195605

## Scaling Events
- 2026-04-19 18:19:47.437433+00: scale_up 2 -> 5 (PID: -3.00, Prophet: +0.00, LSTM: +0.00; cpu=77.6; predicted_rps=0.0; upper_util=0.0; spike_probability=0.00; model=none)
- 2026-04-19 18:20:07.962888+00: scale_up 5 -> 8 (PID: -3.00, Prophet: +0.00, LSTM: +0.00; cpu=77.8; predicted_rps=0.0; upper_util=0.0; spike_probability=0.00; model=none)
