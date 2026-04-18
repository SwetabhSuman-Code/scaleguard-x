# ScaleGuard X — Enterprise Deployment Guide

**Version:** 1.1.0  
**Updated:** April 2026  
**Status:** Production-Ready

---

## Quick Start (5 minutes)

### Prerequisites
- Docker Desktop or Docker Engine (v20.10+)
- Docker Compose (v2.0+)
- At least 4GB RAM, 10GB disk space
- `.env` file (copy from `.env.example`)

### Launch
```bash
# 1. Clone and setup
git clone <repo-url>
cd scaleguard-x

# 2. Create .env from template
cp .env.example .env
# Edit .env to change POSTGRES_PASSWORD, GRAFANA_ADMIN_PASSWORD, etc.

# 3. Start all services
docker compose up --build

# 4. Access services
Dashboard:    http://localhost:3000
API Docs:     http://localhost:8000/docs
Prometheus:   http://localhost:9090
Grafana:      http://localhost:3001 (admin:password from .env)
Jaeger:       http://localhost:16686
```

---

## Architecture Overview

```
┌─────────────── Clients ────────────────┐
│  Dashboard  │  API Consumers  │  Alerts │
└─────────────────┬───────────────────────┘
                  │
        ┌─────────▼────────────┐
        │  API Gateway :8000   │  ← Main entry point
        │  (FastAPI)           │
        └─────────┬────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
PostgreSQL    Redis Stream   Jaeger
(Time-series) (Metrics queue) (Traces)
    │
    ├─ Prometheus :9090 (scrapes every 15s)
    │
    └─ Grafana :3001 (visualization)

Background Services:
  ├─ Metrics Agent       (collects metrics → Redis)
  ├─ Ingestion Service   (Redis → PostgreSQL)
  ├─ Anomaly Engine      (rule-based + ML detection)
  ├─ Prediction Engine   (ARIMA forecasting)
  ├─ Autoscaler         (scales workers via Docker)
  └─ Worker Cluster     (simulated app instances)
```

---

## Services & Ports

| Service | Port | HTTP | Purpose |
|---------|------|------|---------|
| **API Gateway** | 8000 | `/docs`, `/health`, `/api/*` | REST API, metrics query |
| **Dashboard** | 3000 | `/` | Web UI (React + Chart.js) |
| **Prometheus** | 9090 | `/metrics`, `/api/v1/*` | Metrics aggregation |
| **Grafana** | 3001 | `/` | Dashboard & alerts |
| **Jaeger** | 16686 | `/` | Distributed tracing |
| **PostgreSQL** | 5432 | — | Database (internal only) |
| **Redis** | 6379 | — | Message queue (internal only) |
| **Metrics Agent** | 9095 | `/metrics` | Metric export |
| **Anomaly Engine** | 9092 | `/metrics` | Anomaly detection + metrics |
| **Prediction Engine** | 9093 | `/metrics` | Forecasting + metrics |
| **Autoscaler** | 9094 | `/metrics` | Scaling decisions + metrics |
| **Ingestion Service** | 9091 | `/metrics` | Batch ingestion + metrics |

---

## Configuration

### Environment Variables
All configuration via `.env` file (never commit actual values):

```bash
# Database
POSTGRES_USER=scaleguard
POSTGRES_PASSWORD=your_secure_password  # Change this!
POSTGRES_DB=scaleguard

# Redis
REDIS_HOST=redis_queue
REDIS_PORT=6379

# Anomaly Thresholds
ANOMALY_CPU_THRESHOLD=85.0
ANOMALY_LATENCY_THRESHOLD=500.0
ANOMALY_MEMORY_THRESHOLD=90.0

# Autoscaler
AUTOSCALER_MIN_WORKERS=1
AUTOSCALER_MAX_WORKERS=8
AUTOSCALER_SCALE_UP_THRESHOLD=0.75
AUTOSCALER_SCALE_DOWN_THRESHOLD=0.35

# Grafana (change admin password!)
GRAFANA_ADMIN_PASSWORD=your_secure_password
```

### Config Files
- **`config/dev.yaml`** — Development settings
- **`config/staging.yaml`** — Staging/testing settings
- **`config/prod.yaml`** — Production settings

### Prometheus
**Location:** `infrastructure/prometheus/prometheus.yml`

Scraped targets (every 15 seconds):
- All service `/metrics` endpoints
- Prometheus self-check at `:9090/metrics`

To add customalerts, edit `infrastructure/prometheus/rules/` (when created)

---

## Data Retention & Cleanup

**Automatic Cleanup Schedule:** Daily at 02:00 UTC (configurable)

**Retention Policies:**
- **Metrics:** 30 days (hot) + compressed at 7 days
- **Anomalies:** 90 days
- **Predictions:** 7 days
- **Scaling Events:** 90 days
- **Alerts:** 60 days

**Manual Cleanup:**
```bash
# Run maintenance script
docker compose exec postgres_db psql -U scaleguard -d scaleguard \
  -f /docker-entrypoint-initdb.d/maintenance.sql
```

**Storage Growth:**
- Typical: 2-3 GB/month per 1000 metrics/sec
- Without retention: ~100 GB/year

---

## Monitoring & Observability

### 1. Logs (Structured JSON)
All logs output as JSON to stdout:
```bash
# View service logs
docker compose logs api_gateway | jq .level

# Filter by request_id
docker compose logs | jq 'select(.request_id=="abc123")'
```

### 2. Metrics (Prometheus)
```bash
# Query in Prometheus UI (http://localhost:9090)
scaleguard_metrics_ingested_total{service="ingestion_service"}
scaleguard_anomalies_detected_total
scaleguard_scaling_decisions_total{action="scale_up"}
```

### 3. Traces (Jaeger)
```
http://localhost:16686
- Click "Service" dropdown → select service
- Filter by operation, duration, status
- Follow full request flow across services
```

### 4. Dashboards (Grafana)
Pre-built dashboards:
- **System Overview** — CPU, Memory, Disk, Network trends
- **Autoscaling Events** — Worker count, scaling decisions, utilization
- **Anomaly Detection** — Anomalies/hour, ML vs rule-based, false positive rate

---

## Common Operations

### Check Service Health
```bash
# All services should show "healthy"
docker compose ps

# Detailed health for database
docker compose logs postgres_db | tail -20
```

### View Metrics in Real-Time
```bash
# Watch metrics as they arrive
watch -n 1 'curl -s http://localhost:9090/api/v1/query?query=scaleguard_metrics_ingested_total | jq .data.result[0].value[1]'
```

### Scale Workers Manually
```bash
# View current workers
curl http://localhost:8000/api/workers

# Trigger manual scale
curl -X POST http://localhost:8000/api/workers/scale \
  -d '{"target_count": 5}' \
  -H "Content-Type: application/json"
```

### Restart a Service
```bash
# Restart API Gateway
docker compose restart api_gateway

# View logs during restart
docker compose logs -f api_gateway
```

### Database Backup
```bash
# Manual backup
docker compose exec postgres_db pg_dump -U scaleguard scaleguard > backup.sql

# Restore from backup
docker compose exec -T postgres_db psql -U scaleguard scaleguard < backup.sql
```

---

## Security Best Practices

### 1. Secrets Management
✅ **DO:**
- Store passwords in `.env` (git-ignored)
- Use strong passwords (min 16 chars, mixed case + numbers)
- Rotate passwords every 90 days
- Use different passwords for dev/staging/prod

❌ **DON'T:**
- Commit `.env` to git
- Use default passwords in production
- Store secrets in logs
- Expose metrics endpoints to internet

### 2. Network Security
```bash
# Limit external access (production)
# Proxy only dashboard (:3000) and API (:8000) through firewall

# Example firewall rules:
#   :3000 → Dashboard (enable)
#   :8000 → API (enable)
#   :9090 → Prometheus (disable, internal only)
#   :3001 → Grafana (disable, internal only)
```

### 3. Container Security
```bash
# Build as non-root user (already configured in Dockerfile)
docker compose exec api_gateway whoami
# Should print: nobody or similar (not root)

# Scan images for vulnerabilities
trivy image scaleguard-x-api_gateway
```

### 4. Database Security
```bash
# PostgreSQL only listens internally (default)
# External connections require SSH tunnel:
ssh -L 5432:postgres_db:5432 user@prod-host
psql -h localhost -U scaleguard -d scaleguard
```

---

## Production Checklist

### Pre-Deployment
- [ ] Change all default passwords (.env)
- [ ] Configure firewall (allow only :3000, :8000 externally)
- [ ] Set up automated backups (daily to S3)
- [ ] Enable monitoring alerts in Grafana
- [ ] Test database restore procedure
- [ ] Document runbooks for on-call team

### Post-Deployment
- [ ] Verify 99.9% uptime SLA for 2 weeks
- [ ] Monitor error rate (should be < 1%)
- [ ] Check database size growth (should ~2-3 GB/month)
- [ ] Review logs daily for anomalies
- [ ] Run monthly disaster recovery drill

### Ongoing
- [ ] Weekly backup verification (restore to test DB)
- [ ] Monthly security audit
- [ ] Quarterly performance review ( p99 latency under 500ms)
- [ ] Annual penetration testing

---

## Troubleshooting

### Service won't start
```bash
# Check logs
docker compose logs <service_name>

# Common issues:
# 1. Port already in use → `lsof -i :8000` and kill process
# 2. Database not ready → wait 30s and retry
# 3. Memory limit → increase Docker memory allocation
```

### Metrics not showing
```bash
# Check Prometheus is scraping
curl http://localhost:9090/api/v1/targets

# Verify service metrics endpoint
curl http://localhost:9090/metrics  # API Gateway
curl http://localhost:9091/metrics  # Ingestion
curl http://localhost:9092/metrics  # Anomaly Engine
# etc.

# Check all services are running with `docker compose ps`
```

### High latency (> 500ms)
```bash
# Check database performance
docker compose exec postgres_db psql -U scaleguard -d scaleguard \
  -c "SELECT query, calls, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# Check if autoscaler is keeping up with load
curl http://localhost:8000/api/scaling-events | jq '. | length'

# Review slow queries in logs:
docker compose logs ingestion_service | grep "db_query_duration"
```

### OOM (Out of Memory) errors
```bash
# Check memory usage
docker compose stats

# Reduce load or increase allocation:
# Edit docker-compose.yml: deploy.resources.limits.memory: 2g

# Restart with increased memory
docker compose down
docker-compose up -d --build
```

---

## Support & Documentation

### Additional Resources
- **Architecture:** `docs/architecture.md`
- **API Reference:** http://localhost:8000/docs (when running)
- **System Design:** `docs/system_design.md`
- **Configuration:** `config/*.yaml` (commented)

### Community & Support
- GitHub Issues: Report bugs and request features
- Discussions: Ask questions and share ideas
- Wiki: Community-contributed runbooks

---

## License & Attribution

**License:** MIT  
**Contributors:** Engineering team, Community

This platform is inspired by production observability stacks (Prometheus, Grafana, Kubernetes) and combines the best practices from Google's SRE methodology, AWS Well-Architected Framework, and CNCF specifications.

