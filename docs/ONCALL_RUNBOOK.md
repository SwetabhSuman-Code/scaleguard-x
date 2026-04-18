# ScaleGuard X — On-Call Runbook

**For:** On-call engineers responding to incidents  
**Escalation:** L1 (read this) → L2 (contact service owner) → L3 (contact CTO)  
**SLA:** Page on-call within 5 minutes of alert

---

## Alert Index (What to Do When...)

### 🔴 CRITICAL — Respond Immediately

#### **Alert: "API Gateway Down" or "API Latency Spike"**

**Symptoms:** Dashboard doesn't load, `/api/*` endpoints timeout (> 5s)

**1-Minute Response:**
```bash
# Check if service is running
docker compose ps api_gateway  # Should show "healthy"

# If crashed, auto-restart happens (unless disabled)
docker compose logs api_gateway -n 50 | tail -50

# Check for obvious errors (OutOfMemory, panic, etc.)
```

**5-Minute Diagnosis:**
```bash
# SSH to prod host (or local if testing)

# 1. Is database reachable?
docker compose exec api_gateway \
  python -c "import asyncpg; print('DB OK')"

# 2. Is Redis working?
docker compose exec api_gateway \
  python -c "import redis; r = redis.Redis(); print(r.ping())"

# 3. Check service health endpoint
curl http://localhost:8000/health

# 4. View error rate in Prometheus
# Go to http://localhost:9090
# Query: rate(scaleguard_exceptions_total[5m])
```

**Action Plan:**
- **If DB down:** [See "Database Down" section below]
- **If Redis down:** [See "Redis Down" section below]
- **If service just crashed:** Restart with `docker compose restart api_gateway`
- **If still failing:** Roll back to previous version: `git checkout HEAD~1 && docker compose up -d --build`

**Escalate if:** Issue persists > 10 minutes

---

#### **Alert: "High Error Rate"** (> 5% errors)

**Symptoms:** Errors appear in logs, error count climbing in Prometheus

**60-Second Check:**
```bash
# See error types
docker compose logs api_gateway | grep ERROR | head -20

# Check if transient (e.g., Redis flaky) or persistent
docker compose exec redis_queue redis-cli ping  # Should return PONG

# View recent errors in Grafana
# Go to http://localhost:3001 → System Overview dashboard
# Look for "Errors/min" panel
```

**Common Causes & Fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `ConnectionRefusedError: postgres` | DB socket closed | Restart DB: `docker restart scaleguard-postgres` |
| `RedisConnectionError` | Redis OOM | Check: `redis-cli info memory`, restart if needed |
| `TimeoutError in autoscaler` | Docker socket permissions | Check: `ls -la /var/run/docker.sock` |
| `AssertionError in anomaly_engine` | Bad data in DB | Purge corrupted rows: `docker exec ... psql ... DELETE FROM anomalies WHERE metric_value < 0` |

---

#### **Alert: "Database Connection Pool Exhausted"**

**Symptoms:** New requests timeout, logs show "QueuePool limit of size 10 overflow" 

**Root Cause:** Too many concurrent queries, pool size too small

**Fix (choose one):**

**Option A: Increase pool size** (10 min downtime)
```bash
# Edit docker-compose.yml
PG_POOL_MAX=30  # Increase from 20 to 30

docker compose down
docker compose up -d --build
```

**Option B: Kill long-running queries** (no downtime)
```bash
# Find slow queries
docker compose exec postgres_db psql -U scaleguard -c \
  "SELECT pid, usename, state, query, now()-query_start FROM pg_stat_activity WHERE state != 'idle';"

# Kill specific query
docker compose exec postgres_db psql -U scaleguard -c \
  "SELECT pg_terminate_backend(PID);"
```

**Escalate if:** Happens repeatedly; may indicate schema needs optimization

---

#### **Alert: "Autoscaler Scaling Loop"** (spinning up/down workers rapidly)

**Symptoms:** Worker count fluctuates every 15 seconds, high CPU/network in autoscaler

**Root Cause:** Threshold tuned too tightly; load oscillates around boundary

**Fix:**
```bash
# View recent scaling decisions
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "SELECT triggered_at, action, prev_replicas, new_replicas FROM scaling_events ORDER BY triggered_at DESC LIMIT 20;"

# Adjust thresholds in .env
AUTOSCALER_SCALE_UP_THRESHOLD=0.80      # was 0.75 (more conservative)
AUTOSCALER_SCALE_DOWN_THRESHOLD=0.40    # was 0.35 (more conservative)

docker compose restart autoscaler
```

**Escalate if:** Still loops after adjustment; may need ML improvement

---

### 🟠 HIGH — Respond in 15 Minutes

#### **Alert: "Database Disk Space Low"** (< 10% free)

**Symptoms:** Write errors in logs, database growth rate accelerating

**Root Cause:** Retention policy not running or size exceeded

**Check space usage:**
```bash
# Docker volume size
docker volume inspect scaleguard-x_pg_data  # Check "Mountpoint"
du -sh /var/lib/docker/volumes/scaleguard-x_pg_data/_data/

# Inside database
docker compose exec postgres_db df -h /var/lib/postgresql/data
```

**If < 5% free:**
```bash
# Emergency: Delete 7-day-old metrics
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "DELETE FROM metrics WHERE timestamp < NOW() - INTERVAL '7 days';"

# Vacuum to reclaim space
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c "VACUUM FULL;"

# This may take 10-30 min; database will be slow
```

**Long-term fix:**
```bash
# Ensure maintenance script runs daily (check cron)
crontab -l | grep maintenance

# If missing, add:
0 2 * * * docker compose exec -T postgres_db psql -U scaleguard -d scaleguard -f /docker-entrypoint-initdb.d/maintenance.sql
```

---

#### **Alert: "Worker Cluster Empty"** (0 workers running)

**Symptoms:** No metrics from workers, scaling events show replicas=0

**Diagnosis:**
```bash
# Check worker containers
docker compose ps worker_cluster

# If containers exist but unhealthy:
docker compose logs worker_cluster -n 50

# If containers don't exist, autoscaler likely deleted them
# Check autoscaler logs
docker compose logs autoscaler | grep "terminate\|spawn"
```

**Recovery:**
```bash
# Force spawn 2 workers
curl -X POST http://localhost:8000/api/admin/workers/spawn \
  -d '{"count": 2}' \
  -H "Content-Type: application/json"

# Or manually:
docker compose up -d --scale worker_cluster=2
```

---

### 🟡 MEDIUM — Respond in 1 Hour

#### **Alert: "Slow Queries"** (p99 latency > 1s)

**Root Cause:** Missing index, table scan on large table, or general load

**Diagnose:**
```bash
# Find slow queries
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "SELECT query, mean_time, calls FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# Check index usage (should be low for queries using indexes)
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "SELECT schemaname, tablename, indexname FROM pg_indexes WHERE schemaname='public';"
```

**Add missing index:**
```bash
# Example: metrics query on (node_id, timestamp)
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "CREATE INDEX CONCURRENTLY idx_metrics_node_id_ts ON metrics(node_id, timestamp DESC);"

# CONCURRENTLY means it doesn't lock during creation
```

---

#### **Alert: "Anomaly Detection Not Running"**

**Symptoms:** No new anomalies in past hour, prediction engine logs show waiting

**Check:**
```bash
# Is service running?
docker compose ps anomaly_engine  # Should be "Up"

# Any errors?
docker compose logs anomaly_engine -n 100 | grep -i error

# Metrics still being collected?
docker compose logs metrics_agent | grep "xadd\|requests_per_sec" | tail -5

# Database has metrics?
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "SELECT COUNT(*) as count, MAX(timestamp) as latest FROM metrics;"
```

**If no metrics in DB:**
- Check metrics_agent: `docker compose logs metrics_agent`
- Check ingestion service: `docker compose logs ingestion_service`
- Redis stream has data? `docker compose exec redis_queue redis-cli XLEN metrics_stream`

**If metrics high but no anomalies:**
- May be normal (requires anomalous conditions)
- Force test: Create spike in anomaly_engine config, restart

---

#### **Alert: "Grafana Dashboard Blank"**

**Symptoms:** Dashboard loads but all charts show "No data"

**Fix:**
```bash
# Is Prometheus scraping data?
curl http://localhost:9090/api/v1/targets | jq '.data | length'
# Should show multiple targets ("state": "up")

# Query Prometheus directly
curl 'http://localhost:9090/api/v1/query?query=up'
# Should show metric values

# Restart Grafana
docker compose restart grafana

# Refresh browser (hard refresh: Ctrl+Shift+R)
```

---

### 🟢 LOW — Respond in 8 Hours

#### **Alert: "Prediction Engine Forecast Error High"** (MAPE > 30%)

**Symptoms:** Predictions consistently off, scaling decisions suboptimal

**Diagnosis:**
```bash
# Query latest MAPE
curl 'http://localhost:9090/api/v1/query?query=scaleguard_prediction_error_mape'

# View predictions vs actual in database
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "SELECT predicted_at, predicted_rps FROM predictions ORDER BY predicted_at DESC LIMIT 20;"
```

**Long-term fix:**
- May need more historical data (requires 2-4 weeks baseline)
- Consider switching ARIMA to EMA: edit `prediction_engine/main.py`
- Document in runbook for future reference

---

## Database Operations

### **Backup Database**
```bash
# Manual on-demand backup
docker compose exec postgres_db \
  pg_dump -U scaleguard scaleguard > backup_$(date +%Y%m%d_%H%M%S).sql

# Automated (add to cron)
# 0 3 * * * docker compose exec -T postgres_db pg_dump -U scaleguard scaleguard | gzip > /backups/pg_$(date +\%Y\%m\%d).sql.gz
```

### **Restore Database**
```bash
# From backup file
docker compose exec -T postgres_db psql -U scaleguard scaleguard < backup.sql

# Verify restore
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c "SELECT COUNT(*) FROM metrics;"
```

### **Analyze Query Plans**
```bash
# See how DB executes a query
docker compose exec postgres_db psql -U scaleguard -d scaleguard -c \
  "EXPLAIN ANALYZE SELECT * FROM metrics WHERE node_id = 'host-agent-1' ORDER BY timestamp DESC LIMIT 100;"

# High "Seq Scan" = missing index; Consider adding one
```

---

## Network Troubleshooting

### **Test Service Connectivity**
```bash
# From host to container
curl http://api_gateway:8000/health

# From container to container
docker compose exec api_gateway curl http://postgres_db:5432 -v

# If connection refused: Services may not be on same network
docker network ls
docker network inspect scaleguard-x_default
```

### **Find Port Conflicts**
```bash
# Linux/Mac
lsof -i :8000
lsof -i :3000

# If port in use, kill or change docker-compose.yml port mapping
kill <PID>
```

---

## Escalation Contacts

**L1 (You):** Follow this runbook, restart services, basic diagnostics

**L2 (Service Owner):** 
- Backend team lead (for API/scaling issues)
- DB Administrator (for database performance)
- DevOps (for Docker/network issues)

**L3 (CTO/Architect):**
- Required for: Architecture changes, security incidents, SLA violations
- Contact: [Contact info]

**Resolution SLA:**
- **Severity 1 (Down):** 15 min response, 1 hour resolution
- **Severity 2 (Degraded):** 1 hour response, 4 hour resolution
- **Severity 3 (Warning):** 8 hour response, 2 day resolution

---

## Testing This Runbook

**Monthly Drill** (every 1st Monday):
1. Simulate database crash: `docker compose stop postgres_db`
2. Walk through restoration steps
3. Measure time to recovery
4. Document lessons learned
5. Update runbook if needed

**Quarterly Simulation** (every quarter):
1. Simulate API Gateway failure
2. Verify monitoring alerts fire
3. Test escalation notification chain
4. Measure MTTR (Mean Time To Recover)
5. Target: < 15 minutes to full recovery

---

## Document Updates

**Runbook Version:** 1.1  
**Last Updated:** April 2026  
**Next Review:** July 2026  

Maintained by: On-call rotation  
Contact with updates: #scaleguard-x-oncall Slack channel

