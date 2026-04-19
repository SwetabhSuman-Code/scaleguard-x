# Load Testing Quick Reference — Copy & Paste Commands

## Prerequisites
```bash
# Install Locust
pip install locust

# Or ensure it's in requirements
pip install -r requirements-benchmark.txt

# Verify API is running
curl http://localhost:8000/health

# Verify Prometheus is running
curl http://localhost:9090/-/healthy
```

---

## Test 1: Gradual Load Ramp (Recommended First Test)
**Best for:** Realistic traffic growth, understanding system capacity

```bash
locust -f benchmarks/locustfile.py \
  -u 300 \
  -r 10 \
  -t 10m \
  --host http://localhost:8000 \
  --web
```

**Then open:** http://localhost:8089

**What to watch:**
- Request rate climbs from 0 → 3000 req/sec
- Latency should remain stable (< 200ms avg)
- Error rate stays at 0%
- In Grafana: CPU climbs linearly

**Duration:** ~10 minutes
**When done:** Press Ctrl+C to stop

---

## Test 2: Spike Test (Sudden Traffic)
**Best for:** Testing autoscaler response, cascading failure prevention

```bash
locust -f benchmarks/locustfile.py \
  -u 300 \
  -r 100 \
  -t 5m \
  --host http://localhost:8000 \
  --web
```

**What happens:**
- All 300 users spawn in ~3 seconds (instant load)
- Request rate jumps to 3000+ req/sec immediately
- Watch for latency spike and recovery
- Autoscaler should trigger within 30-60 seconds

**Key indicator:** After workers scale up, latency should return to baseline

---

## Test 3: Sustained Load (Endurance)
**Best for:** Finding memory leaks, connection pool issues, 24-hour readiness

```bash
locust -f benchmarks/locustfile.py \
  -u 100 \
  -r 5 \
  -t 15m \
  --host http://localhost:8000 \
  --web
```

**Watch for:**
- Memory usage staying flat (no leaks)
- Latency not degrading over time
- DB connections not creeping up
- No connection timeouts after 10+ minutes

---

## Test 4: Headless Mode (For CI/CD, Automated Runs)
**Best for:** Recording results to CSV, running in background

```bash
locust -f benchmarks/locustfile.py \
  -u 200 \
  -r 10 \
  -t 10m \
  --host http://localhost:8000 \
  --headless \
  --csv=benchmarks/results/load_test_$(date +%Y%m%d_%H%M%S)
```

**Output files created:**
- `load_test_1714060800_stats.csv` — Overall statistics
- `load_test_1714060800_stats_history.csv` — Per-minute breakdown
- `load_test_1714060800_failures.csv` — Failed requests

**No web UI** — Results go directly to CSV files

---

## Test 5: High Concurrency Stress Test
**Best for:** Finding absolute breaking point

```bash
locust -f benchmarks/locustfile.py \
  -u 500 \
  -r 50 \
  -t 5m \
  --host http://localhost:8000 \
  --web
```

**Expected:** System will struggle, errors should appear
**Use to:** Find max capacity and error recovery behavior

---

## Test 6: Low-Load Baseline (for comparison)
**Best for:** Establishing healthy baseline metrics

```bash
locust -f benchmarks/locustfile.py \
  -u 10 \
  -r 2 \
  -t 5m \
  --host http://localhost:8000 \
  --web
```

**Expected:** ~100 req/sec, latency < 50ms, 0% errors
**Use to:** Compare against load test results

---

## Prometheus Queries — Copy to http://localhost:9090

### Request Rate
```promql
rate(http_requests_total{job="api_gateway"}[1m])
```

### P95 Latency (in milliseconds)
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m])) * 1000
```

### Error Rate (%)
```promql
100 * (rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) / rate(http_requests_total{job="api_gateway"}[1m]))
```

### CPU Usage
```promql
rate(container_cpu_usage_seconds_total{name="scaleguard-api-gateway"}[1m]) * 100
```

### Memory Usage (MB)
```promql
container_memory_usage_bytes{name="scaleguard-api-gateway"} / 1024 / 1024
```

### Database Connections
```promql
pg_stat_activity_count{datname="scaleguard_db"}
```

---

## Docker Monitoring (While Tests Run)

### Real-time Container Stats
```bash
docker stats scaleguard-api-gateway scaleguard-postgres scaleguard-redis
```

### Watch Worker Scaling
```bash
watch -n 1 'docker compose ps | grep worker'
```

### Tail API Gateway Logs
```bash
docker compose logs -f api_gateway | grep -E "POST|ERROR|200|500"
```

### Check Metrics in Database
```bash
docker exec scaleguard-postgres psql -U scaleguard_user -d scaleguard_db \
  -c "SELECT COUNT(*) as total_metrics FROM metrics;"
```

---

## Grafana Dashboards

**Open:** http://localhost:3001
**Login:** admin / (your GRAFANA_ADMIN_PASSWORD)

### Panels to Create/Check
1. **Request Rate**
   - Query: `rate(http_requests_total{job="api_gateway"}[1m])`
   - Type: Graph
   - Expected: 0 → peak → 0 (follows test shape)

2. **P95 Latency**
   - Query: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) * 1000`
   - Type: Graph
   - Expected: Flat line (should not increase with load)

3. **Error Rate**
   - Query: `100 * (rate(http_requests_total{status=~"5.."}[1m]) / rate(http_requests_total[1m]))`
   - Type: Graph
   - Expected: Flat at 0

4. **CPU Usage**
   - Query: `rate(container_cpu_usage_seconds_total{name="scaleguard-api-gateway"}[1m]) * 100`
   - Type: Graph
   - Expected: Linear climb with load

5. **Memory Usage**
   - Query: `container_memory_usage_bytes{name="scaleguard-api-gateway"} / 1024 / 1024`
   - Type: Graph
   - Expected: Flat line (no leaks)

---

## Post-Test Analysis

### 1. Export Locust Results
```bash
# CSV files are in:
cat benchmarks/results/load_test_*_stats.csv

# Copy to spreadsheet for analysis
```

### 2. Export Prometheus Metrics
```bash
# In Prometheus UI:
# 1. Run query
# 2. Click "Graph"
# 3. Set time range to test duration
# 4. Screenshot or export
```

### 3. Create Grafana Snapshots
```
In Grafana:
Dashboard → Share → Snapshot → Create
(Creates shareable snapshot link)
```

### 4. Fill Results Template
```bash
# Copy template from: benchmarks/TEST_RESULTS_TEMPLATE.md
# Fill in values from test
# Save as: benchmarks/results/TEST_RESULTS_[TYPE]_[DATE].md
```

---

## Troubleshooting During Tests

### Error: "Connection refused"
```bash
# API not running
curl http://localhost:8000/health
docker compose up -d api_gateway
```

### Error: "Timeout" errors increasing
```bash
# API overloaded, check CPU
docker stats scaleguard-api-gateway

# May need to restart
docker compose restart api_gateway
```

### Error: "Failed to bind to port 8089"
```bash
# Locust UI port in use
# Either:
locust -f benchmarks/locustfile.py --web-port 9999 ...  # Use different port
# Or:
lsof -i :8089
kill -9 <PID>
```

### Error: "Database connection pool exhausted"
```bash
# Too many concurrent DB connections
# Check PostgreSQL
docker compose logs postgres_db
docker stats scaleguard-postgres

# Reduce users or restart DB
docker compose restart postgres_db
```

### Autoscaler not scaling
```bash
# Check autoscaler logs
docker compose logs autoscaler | tail -50

# Verify it can see metrics
curl http://localhost:8000/api/metrics?limit=1

# Check if workers exist
docker compose ps | grep worker
```

---

## Save & Share Results

### For Resume Portfolio
```bash
# Create results file
cp benchmarks/TEST_RESULTS_TEMPLATE.md \
   benchmarks/results/TEST_RESULTS_GRADUAL_$(date +%Y%m%d).md

# Fill in values
# Edit in editor

# Add to Git
git add benchmarks/results/TEST_RESULTS_*.md
git commit -m "Add load test results"
git push origin main
```

### Screenshot Portfolio
```
Directory: benchmarks/results/screenshots/

Include:
1. Locust Statistics Table (final state)
2. Grafana Dashboard (peak load)
3. Request Rate Chart
4. Latency Chart
5. CPU Usage Chart
6. Autoscaler scaling events
```

---

## Example Results Summary (For Resume)

```
✅ PERFORMANCE TEST SUMMARY — ScaleGuard X Microservices

Gradual Load Test (300 concurrent users):
- Throughput: 2,847 requests/sec
- P95 Latency: 289 ms
- Error Rate: 0.03%
- Autoscaler Response: 45 seconds

Spike Test (instant 300 users):
- Peak Throughput: 3,124 requests/sec
- Latency Recovery: 52 seconds after scale-up
- Workers Scaled: 2 → 4 automatically

Sustained Load Test (100 users, 15 min):
- No memory leaks detected
- Database connections: 18/50 (safe)
- Zero connection timeouts

✅ System production-ready for 2000+ req/sec sustained
✅ Auto-scaling responds within 1 minute
✅ No cascading failures under test conditions
```

---

## Next Steps

1. [ ] Run Test 1 (Gradual Ramp)
2. [ ] Monitor in Prometheus & Grafana
3. [ ] Run Test 2 (Spike)
4. [ ] Check autoscaler logs
5. [ ] Run Test 3 (Sustained)
6. [ ] Export results to CSV
7. [ ] Fill TEST_RESULTS_TEMPLATE.md
8. [ ] Save screenshots
9. [ ] Commit to GitHub
10. [ ] Add to resume portfolio
