# Contributing to ScaleGuard X

Thank you for contributing to ScaleGuard X! This guide will help you get started with development.

---

## Getting Started (10 minutes)

### 1. Clone & Setup
```bash
git clone https://github.com/yourusername/scaleguard-x.git
cd scaleguard-x

# Create .env for development
cp .env.example .env

# Create Python environment (optional but recommended)
# On macOS/Linux:
python3.11 -m venv venv
source venv/bin/activate

# On Windows:
# py -3.11 -m venv venv
# venv\Scripts\activate
```

### 2. Start Development Services
```bash
# Start all services
docker compose up --build

# In another terminal, run tests
pytest tests/ -m unit --cov=. --cov-fail-under=80
```

### 3. Verify it works
```bash
# Check all services are healthy
docker compose ps

# Check API is responding
curl http://localhost:8000/health

# View dashboard
open http://localhost:3000
```

---

## Code Standards

### Style Guide
- **Language:** Python 3.11+
- **Formatter:** `black` (100 char line width)
- **Linter:** `ruff` (catches errors)
- **Type Checker:** `mypy --strict`

### Before Committing
```bash
# Format code
black .

# Check for lint issues
ruff check .

# Run type checker
mypy api_gateway/main.py lib/

# Run tests
pytest tests/ -m unit --cov=.
```

### Auto-fix issues
```bash
# Format all code
black .

# Auto-fix ruff issues where possible
ruff check . --fix
```

---

## Testing

### Unit Tests
```bash
# Run all unit tests
pytest tests/ -m unit -v

# Run specific test file
pytest tests/test_logging.py -v

# Test with coverage
pytest tests/ --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

### Integration Tests
```bash
# Requires docker compose running
pytest tests/ -m integration -v

# These test services talking to real DB/Redis
```

### CI/CD Pipeline
Push to `main` or `develop` branch:
1. ✅ Code formatting check (`black`)
2. ✅ Lint check (`ruff`)
3. ✅ Type check (`mypy`)
4. ✅ Unit tests (pytest)
5. ✅ Build Docker images
6. ✅ Security scan (Trivy)

If any step fails, PR cannot merge. Fix locally and push again.

---

## Making Changes

### 1. Create a Branch
```bash
# Fix a bug
git checkout -b fix/issue-123-api-timeout

# Add feature
git checkout -b feat/worker-metrics-export

# Update docs
git checkout -b docs/add-runbook
```

### 2. Make Your Changes
- Keep commits atomic (one logical change per commit)
- Write clear commit messages: `feat: add worker health check endpoint`
- Update docstrings for new functions
- Add tests for new code

### 3. Local Verification
```bash
# Run full CI locally
black . && ruff check . && mypy . && pytest tests/ --cov=.

# If all pass, you're ready to push
git push origin feat/your-feature
```

### 4. Create Pull Request
- Reference issue number: "Fixes #123"
- Describe change in detail
- Include test coverage evidence
- Link to any relevant docs

---

## Project Structure

```
scaleguard-x/
├── api_gateway/            # FastAPI REST API
│   ├── main.py
│   └── requirements.txt
├── anomaly_engine/         # Rule-based + ML detection
├── prediction_engine/      # ARIMA forecasting
├── autoscaler/            # Docker auto-scaling
├── ingestion_service/     # Redis → Postgres pipeline
├── metrics_agent/         # System metrics collection
├── worker_cluster/        # Simulated workers
├── lib/                   # Shared utilities
│   ├── logging_config.py  # JSON logging
│   ├── circuit_breaker.py # Fault tolerance
│   └── prometheus_metrics.py  # Metrics export
├── infrastructure/        # Config files
│   ├── sql/              # Database schemas
│   ├── prometheus/       # Metrics scraping
│   └── grafana/          # Dashboards
├── config/               # Dev/staging/prod configs
├── tests/                # Unit & integration tests
├── docs/                 # Documentation
├── docker-compose.yml    # Orchestration
└── pyproject.toml        # Project metadata
```

---

## Common Development Tasks

### Add a New Metric
1. Define in `lib/prometheus_metrics.py`:
   ```python
   self.my_new_metric = Counter(
       'scaleguard_my_feature_total',
       'Description of metric',
       ['label1', 'label2']
   )
   ```

2. Use in your service:
   ```python
   from lib.prometheus_metrics import get_metrics
   metrics = get_metrics()
   metrics.my_new_metric.labels(label1="val1").inc()
   ```

3. Add to Prometheus config (`infrastructure/prometheus/prometheus.yml`)
4. Create Grafana panel to visualize

### Add a New API Endpoint
1. Add route in `api_gateway/main.py`:
   ```python
   @app.get("/api/features/{feature_id}")
   async def get_feature(feature_id: str) -> dict:
       async with _pg_cb:
           result = await state.db_pool.fetch(...)
       return {"feature_id": feature_id, "data": result}
   ```

2. Add test in `tests/test_api_gateway.py`
3. Document in `/docs/api_docs.md`
4. API docs auto-generate at `/docs`

### Add Circuit Breaker to New Service
```python
from lib.circuit_breaker import make_postgres_breaker

_db_cb = make_postgres_breaker("my_service")

async def query_db():
    async with _db_cb:
        result = await db.fetch(...)
        return result
```

### Debug: Add Logging
```python
from lib.logging_config import get_logger

log = get_logger(__name__)

# Structured logging with context
log.info("request_received", extra={
    "user_id": user_id,
    "request_id": request_id,
    "path": "/api/metrics"
})
```

---

## Debugging in Development

### View Real-Time Logs
```bash
# Follow api_gateway logs
docker compose logs -f api_gateway

# Follow all services
docker compose logs -f

# See only errors
docker compose logs api_gateway | grep ERROR
```

### Access Database During Development
```bash
# Open psql interactive shell
docker compose exec postgres_db psql -U scaleguard -d scaleguard

# Example queries:
SELECT COUNT(*) FROM metrics;
SELECT * FROM anomalies ORDER BY detected_at DESC LIMIT 10;
SELECT * FROM predictions ORDER BY predicted_at DESC LIMIT 5;
```

### Modify Code & Auto-Reload
Most services restart automatically when code changes (in dev mode).

To force restart:
```bash
docker compose restart api_gateway
```

To rebuild with dependency changes:
```bash
docker compose up --build api_gateway
```

---

## Performance Profiling

### Profile CPU Usage
```bash
# Profile api_gateway
python -m cProfile -o out.prof api_gateway/main.py
pip install snakeviz
snakeviz out.prof
```

### Measure Query Performance
```bash
# Enable query logging (modify api_gateway)
log.info("db_query", extra={"duration_ms": elapsed_ms})

# View slowest queries in Prometheus
# Query: scaleguard_db_query_duration_seconds
```

---

## Documentation

### Update API Docs
- API docs auto-generate from FastAPI docstrings
- Update endpoint docstrings → `/docs` updates automatically

### Update Architecture Docs
- Edit `docs/architecture.md` for system design changes
- Edit `docs/DEPLOYMENT.md` for deployment instructions
- Edit `docs/ONCALL_RUNBOOK.md` for operational guides

### Update Config Docs
- Each YAML file has comments explaining options
- Keep `.env.example` in sync with supported variables

---

## Submitting Work

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

Fixes #<issue_number>
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `perf:` Performance improvement
- `tests:` Testing
- `docs:` Documentation
- `refactor:` Code restructuring (no feature change)
- `chore:` Build, deps, etc.

**Example:**
```
feat(anomaly-engine): add isolation forest ML detection

Implements two-layer anomaly detection:
- Layer 1: Rule-based (thresholds)
- Layer 2: ML-based (Isolation Forest)

Anomalies logged with anomaly_score for ranking.

Fixes #45
```

---

## Code Review Expectations

### What reviewers check
- ✅ Code follows style guide
- ✅ Tests cover new code (>80% coverage)
- ✅ Logging is structured JSON
- ✅ Error handling is present (circuit breaker, retries)
- ✅ No secrets in code
- ✅ Documentation updated
- ✅ Performance acceptable

### How to request review
Push to branch, create PR on GitHub. Reviewers notified automatically.

Respond to feedback promptly. Most PRs merge within 24-48 hours.

---

## Getting Help

- **Slack:** #scaleguard-x-dev channel
- **Issues:** GitHub Issues for bugs/features
- **Docs:** Read docs/ before asking
- **Pair:** Schedule pairing session with team

---

## Recognition

Contributors are added to:
- README.md "Contributors" section
- CHANGELOG.md release notes
- Thank you in commit messages

---

Happy coding! 🚀

