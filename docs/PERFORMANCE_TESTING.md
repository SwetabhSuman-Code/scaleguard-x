# ScaleGuard X — Performance Testing Guide

## Overview
This guide provides complete instructions for load testing your microservices system using Locust, monitoring with Prometheus, and validating system behavior through Grafana.

---

## Part 1: Run Locust Load Tests

### Prerequisites
```bash
pip install locust
# Or ensure it's in requirements-benchmark.txt
pip install -r requirements-benchmark.txt
```

### Test Scenario 1: Gradual Load Ramp (Recommended First Test)
**Simulates: Realistic traffic growth during business hours**

```bash
locust -f benchmarks/locustfile.py \
  -u 300 \
  -r 10 \
  -t 10m \
  --host http://localhost:8000 \
  --web
```

**What happens:**
- Starts with 0 users
- Adds 10 new users per second
- Reaches 300 users in ~30 seconds
- Holds 300 users for ~9.5 minutes
- Provides 10 minutes of sustained load metrics

**Open UI:** http://localhost:8089
- Watch "Current Users" graph climb to 300
- Monitor "Response Time" and "Failure Rate" in real-time
- Chart shows requests/second ramping up

---

### Test Scenario 2: Spike Test (Sudden Traffic)
**Simulates: Alert storms, cache purges, or viral traffic spike**

```bash
locust -f benchmarks/locustfile.py \
  -u 300 \
  -r 100 \
  -t 5m \
  --host http://localhost:8000 \
  --web
```

**What happens:**
- All 300 users spawn in ~3 seconds (aggressive)
- Immediate overload to test auto-scaling response
- Holds for 5 minutes
- Observe how system handles sudden 3000+ req/sec

**Expected in Grafana:**
- Rapid CPU spike (watch if autoscaler triggers)
- Request latency jumps 2-5x
- If system auto-scales, latency should recover

---

### Test Scenario 3: Sustained Load (Endurance Test)
**Simulates: Stable production load over hours**

```bash
locust -f benchmarks/locustfile.py \
  -u 100 \
  -r 5 \
  -t 15m \
  --host http://localhost:8000 \
  --web
```

**What happens:**
- 100 concurrent users
- ~1000 req/sec sustained
- Run for 15 minutes
- Check for memory leaks, connection pool exhaustion

**Watch for:**
- Latency degradation over time (memory leak indicator)
- Connection failures after 5-10 mins
- Database CPU creeping up

---

### Headless Mode (For CI/CD or Remote Runs)
**No web UI, outputs CSV for analysis**

```bash
locust -f benchmarks/locustfile.py \
  -u 200 \
  -r 10 \
  -t 10m \
  --host http://localhost:8000 \
  --headless \
  --csv=benchmarks/results/load_test_$(date +%Y%m%d_%H%M%S)
```

**Output files:**
- `load_test_1714060800_stats.csv` — Per-endpoint statistics
- `load_test_1714060800_stats_history.csv` — Statistics over time
- `load_test_1714060800_failures.csv` — Failed requests

---

## Part 2: Monitor in Real-Time with Prometheus Queries

### Open Prometheus UI
http://localhost:9090

### Key Queries to Run During Load Test

#### 1. Request Rate (requests/sec)
```promql
rate(http_requests_total{job="api_gateway"}[1m])
```
**What it shows:** How many requests/sec the API is processing
**Expected during test:** Should climb with user ramp (0 → ~3000 req/sec)

---

#### 2. Request Latency (P95)
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m]))
```
**What it shows:** 95th percentile response time
**Healthy:** < 200ms under normal load
**Warning:** > 500ms = system struggling
**Spike test:** May jump to 1-2 seconds initially

---

#### 3. Error Rate
```promql
rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) / 
rate(http_requests_total{job="api_gateway"}[1m])
```
**What it shows:** % of requests returning 5xx errors
**Expected:** Should stay near 0%
**If > 1%:** API gateway is failing (database down? circuit breaker tripped?)

---

#### 4. API Gateway CPU Usage
```promql
container_cpu_usage_seconds_total{name="scaleguard-api-gateway"}
```
**What it shows:** API container CPU time
**Expected ramp:** Should increase linearly with load
**Watch for:** Sudden plateau = CPU-bound bottleneck

---

#### 5. Redis Queue Depth
```promql
redis_connected_clients{instance="redis_queue:6379"}
```
**What it shows:** Active Redis connections
**Expected:** Should stay constant (connection pooling)
**If > 50:** Connection leak in metrics ingestion

---

#### 6. PostgreSQL Connections
```promql
pg_stat_activity_count{datname="scaleguard_db"}
```
**What it shows:** Active database connections
**Expected:** 5-20 under normal load
**If > 50:** Connection pool exhaustion (possible memory leak)

---

#### 7. Metrics Ingested per Second
```promql
rate(metrics_ingested_total[1m])
```
**What it shows:** How many metrics/sec the system is actually processing
**Critical:** Should match request rate from query #1
**If lower:** Ingestion service is bottleneck (too slow)

---

#### 8. Autoscaler Decisions
```promql
autoscaler_scaling_events_total
```
**What it shows:** Number of times autoscaler triggered scale-up/down
**During spike test:** Should see 1-3 events as system reacts
**If 0:** Autoscaler not triggering (check logs)

---

## Part 3: Monitor in Grafana

### Open Grafana
http://localhost:3001
**Default:** admin / (your GRAFANA_ADMIN_PASSWORD from .env)

### Dashboards to Watch (Create if Missing)

#### Dashboard 1: System Health Overview
**Metrics to add:**
```
Panels to create:
1. "Request Rate" → rate(http_requests_total[1m])
2. "P95 Latency" → histogram_quantile(0.95, http_request_duration_seconds_bucket)
3. "Error Rate" → rate(http_requests_total{status=~"5.."}[1m])
4. "Active Users" → locust_user_count (from Locust prometheus exporter if enabled)
5. "DB Connections" → pg_stat_activity_count
6. "Redis Connections" → redis_connected_clients
```

**What to look for:**
- Error rate should stay near 0%
- Latency should remain stable (not creeping up)
- DB connections should not max out

---

#### Dashboard 2: Resource Usage
**Metrics:**
```
1. "API Gateway CPU" → container_cpu_usage_seconds_total
2. "API Gateway Memory" → container_memory_usage_bytes
3. "PostgreSQL CPU" → pg_stat_activity_cpu_seconds_total
4. "Redis Memory" → redis_memory_used_bytes
5. "Disk I/O" → node_disk_io_now
```

**Healthy pattern:**
- CPU climbs linearly with load, plateaus when saturated
- Memory stable (no leaks)
- Disk I/O spikes only at metrics flush points

---

#### Dashboard 3: Autoscaler Activity
**Metrics:**
```
1. "Worker Count" → worker_cluster_replicas
2. "Scaling Events" → autoscaler_scaling_events_total
3. "Forecast Load" → autoscaler_predicted_load
4. "Actual Load" → autoscaler_current_load
```

**During spike test:**
- Worker count should increase within 30-60 seconds
- Forecast should precede actual load spike
- System should scale before request latency degrades

---

## Part 4: Verify System Is Actually Processing Metrics

### Method 1: Check Database Growth
```sql
-- Run in PostgreSQL (e.g., from Adminer at localhost:8080)
SELECT COUNT(*) as total_metrics FROM metrics;
SELECT COUNT(*) as new_metrics FROM metrics WHERE created_at > NOW() - INTERVAL '1 minute';
```

**During load test:**
- `total_metrics` should grow by ~1000-3000 per minute
- `new_metrics` query should show incoming batch size

---

### Method 2: Check Redis Queue Depth
```bash
# SSH to container or use redis-cli
docker exec scaleguard-redis redis-cli LLEN metrics_stream
```

**What it means:**
- If queue depth climbs: Ingestion slower than arrival
- If stable/low: System keeping up
- If empty: Everything is processed

---

### Method 3: Query Ingested Metrics via API
```bash
curl -X GET "http://localhost:8000/api/metrics?limit=100" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Expected response:** Latest 100 metrics in descending timestamp order

---

### Method 4: Check Prometheus Scrape Success
```promql
# In Prometheus UI
up{job="api_gateway"}  # Should be 1 (healthy)
scrape_duration_seconds{job="api_gateway"}  # Should be <1s
```

---

## Part 5: Verify Autoscaler Behavior

### Pre-Spike State
```bash
docker compose ps | grep worker
# Should show: scaleguard-worker_cluster 2 running
```

### During Spike Test
```bash
# Watch worker count increase
watch -n 2 'docker compose ps | grep worker | wc -l'
```

**Expected behavior:**
1. Spike test starts (300 users, instant)
2. Request latency increases
3. Within 30-60 seconds: New workers spawn
4. Request latency returns to baseline
5. After test ends: Workers scale down (after 2-5 minutes)

---

### Autoscaler Logs
```bash
docker compose logs autoscaler -f
```

**Look for messages like:**
```
[INFO] Metrics available: 1200 req/sec
[INFO] Forecast: 1500 req/sec needed in 2 minutes
[INFO] Triggering scale up: 2 → 4 workers
[INFO] Waiting 60s for new workers to stabilize...
[INFO] Verified: New workers healthy, latency recovered
```

---

## Part 6: Expected Results for Resume/Documentation

### Result Template (Save After Each Test)

Create `benchmarks/results/TEST_RESULTS_YYYY-MM-DD.md`:

```markdown
# Load Test Results — [Test Type] — [Date]

## Test Configuration
- **Test Type:** Gradual Ramp | Spike | Sustained
- **Duration:** 10 minutes
- **Peak Users:** 300
- **Spawn Rate:** 10 users/sec
- **Total Requests:** 150,000
- **Unique Node IDs:** 50

## Key Metrics
| Metric | Result | Target | Status |
|--------|--------|--------|--------|
| Avg Response Time | 145 ms | < 200ms | ✅ Pass |
| P95 Latency | 280 ms | < 500ms | ✅ Pass |
| P99 Latency | 420 ms | < 1000ms | ✅ Pass |
| Error Rate | 0.02% | < 1% | ✅ Pass |
| Throughput | 2,500 req/sec | > 2,000 req/sec | ✅ Pass |
| Metrics Ingested | 150,000 | = requests | ✅ Pass |
| DB Connections Peak | 18 | < 50 | ✅ Pass |
| Memory Leak Detected | No | None | ✅ Pass |

## System Behavior
- **Autoscaler Response Time:** 45 seconds (Spike test)
- **Workers Scaled:** 2 → 4 → 2 (Spike test)
- **Database Performance:** Stable, no query timeouts
- **Cache Hit Rate:** 87% (if applicable)

## Resource Utilization
| Resource | Peak | Baseline | Headroom |
|----------|------|----------|----------|
| API CPU | 72% | 8% | Healthy |
| API Memory | 285 MB | 150 MB | Healthy |
| DB CPU | 45% | 5% | Healthy |
| DB Connections | 18/50 | 3/50 | Safe |

## Issues Found
- [List any errors, warnings, or anomalies]
- [None] ✅

## Recommendations
- System successfully handles 300 concurrent users
- Autoscaler responds quickly to spikes
- No memory leaks detected over 15 minute sustained test
- Ready for production

## Files
- Locust stats: `benchmarks/results/load_test_1714060800_stats.csv`
- Prometheus metrics: [Export from Prometheus UI]
- Grafana dashboard snapshots: [Screenshots]
```

---

## Quick Reference: Locust Web UI Metrics

When you open http://localhost:8089:

**Statistics Table:**
- **Name:** Endpoint name (e.g., POST /api/metrics)
- **# requests:** Total requests sent
- **# failures:** Number of failures
- **Median:** 50th percentile latency
- **95%:** 95th percentile latency
- **99%:** 99th percentile latency
- **Max:** Worst case latency
- **Avg (ms):** Average response time
- **Min:** Best case latency

**Charts:**
- **Total Request Rate:** req/sec over time
- **Response Times:** How latency changes as load increases
- **Failure Rate:** Should stay at 0%

---

## Troubleshooting During Tests

### Issue: "Connection refused" errors
```bash
# Check if API is running
curl http://localhost:8000/health
# If fails: docker compose up -d api_gateway
```

### Issue: "Timeout" errors increasing
- API is overloaded
- Check CPU: `docker stats scaleguard-api-gateway`
- Check if database is responding: `docker compose logs postgres_db`

### Issue: Autoscaler not scaling
```bash
# Check autoscaler logs
docker compose logs autoscaler | tail -20
# Check if metrics available
curl http://localhost:8000/api/metrics?limit=1
```

### Issue: Memory usage keeps growing
- Potential memory leak
- Check which container: `docker stats`
- Restart and re-test: `docker compose restart`

---

## Next Steps After Testing

1. **Document results** using template above
2. **Create Grafana snapshots** (Dashboard → Share → Snapshot)
3. **Export Locust CSV** for trend analysis
4. **Store in resume portfolio:**
   - Performance test results
   - Grafana screenshots
   - Autoscaling behavior proof
5. **Compare against industry benchmarks** (if targeting job applications)
