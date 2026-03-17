<div align="center">
  <h1>🛡️ ScaleGuard X</h1>
  <p><strong>Autonomous Infrastructure Monitoring & Auto-Scaling Platform</strong></p>
  
  [![Python version](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
  [![Docker](https://img.shields.io/badge/Docker-compose-2496ED.svg)](https://www.docker.com/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-00A69D.svg)](https://fastapi.tiangolo.com)
  [![React](https://img.shields.io/badge/React-18.x-61DAFB.svg)](https://react.dev)
  [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
</div>

---

A production-grade distributed observability system that collects real-time system metrics, detects anomalies via ML (Isolation Forest), predicts traffic spikes using time-series forecasting (ARIMA/EMA), and autonomously scales worker containers in response to predictive and reactive rules.

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Services & Ports](#services--ports)
- [Dashboard Features](#dashboard-features)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [How Autoscaling Works](#how-autoscaling-works)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Features

- **Real-time Telemetry:** Captures CPU, Memory, Latency, and RPS metrics continuously.
- **Machine Learning Anomaly Detection:** Utilizes Isolation Forest & Rule-based engines to identify degradation.
- **Predictive Scaling:** Forecasts 10-minute future load trends via ARIMA models.
- **Autonomous Docker Scaling:** Automatically provisions/deprovisions container replicas via Docker Socket.
- **High-Performance Ingestion:** Buffers metrics in Redis Streams and batches to PostgreSQL.
- **Premium Dashboard:** Real-time visual observability interface built with React & Vite.

## Architecture Overview

```mermaid
graph TD;
    Browser[Browser] -->|HTTP :3000| Dashboard[Dashboard (React/Nginx)];
    Dashboard -->|/api proxy| Gateway[API Gateway (FastAPI :8000)];
    Gateway -->|asyncpg read| DB[(PostgreSQL)];
    
    Ingestion[Ingestion Service] -->|Batch Write| DB;
    Queue[Redis Stream] -->|Read| Ingestion;
    
    Agent[Metrics Agent] -->|XADD| Queue;
    Workers[Worker Cluster] -->|Metrics| Queue;
    
    Anomaly[Anomaly Engine] -->|Write Anomalies| DB;
    Predict[Prediction Engine] -->|Write Forecasts| DB;
    
    Scaler[Autoscaler] -->|Read DB| DB;
    Scaler -->|Spawn/Kill| Workers;
    Scaler -.->|Docker Socket| DockerDaemon;
```

## Prerequisites

- **Docker Desktop** (v4.0+) / **Docker Engine** (20.10+)
- **Docker Compose** (v2.x plugins)

## Quick Start

1. **Clone the repository** (or navigate to the project directory)
   ```bash
   git clone https://github.com/yourusername/scaleguard-x.git
   cd scaleguard-x
   ```

2. **Build and start all services**
   ```bash
   docker compose up -d --build
   ```

3. **Access the application**
   - Dashboard: [http://localhost:3000](http://localhost:3000)
   - API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

4. **Stop the environment**
   ```bash
   docker compose down
   # To wipe the database/cache volumes: docker compose down -v
   ```

## Services & Ports

| Container | Port | Internal Role |
|-----------|------|---------------|
| `postgres_db` | `5432` | Time-series metrics & metadata store |
| `redis_queue` | `6379` | High-throughput Redis Streams message queue |
| `api_gateway` | `8000` | FastAPI REST API (+ Swagger UI) |
| `dashboard` | `3000` | React observability SPA (Nginx) |
| `metrics_agent` | — | Host node metric collector |
| `worker_cluster` | — | Simulated application workers (auto-scaled) |
| `ingestion_service` | — | Message broker pipeline (Redis → Postgres) |
| `anomaly_engine` | — | ML / Rule-based degradation detection |
| `prediction_engine` | — | Time-series forecasting worker |
| `autoscaler` | — | Docker-based scaling orchestration daemon |

## Dashboard Features

- **Live Telemetry Charts:** CPU / Memory / Latency / RPS refreshed every 5 seconds.
- **Anomaly Score Timeline:** Visual indicators overlapping exact rule/ML breach incidents.
- **Scaling History Visualization:** Bar charts depicting dynamic spawn/kill events.
- **Live Worker Registry:** Displays actively managed and running worker container replicas.
- **Alert Feed Tracking:** Centralized severity-tagged operational alerts.
- **KPI Badges:** High-level metrics for quick observability context.

## Configuration

Control the platform's behavior using the `.env` file at the repository root:

| Variable | Default Key | Description |
|---|---|---|
| `ANOMALY_CPU_THRESHOLD` | `85.0` | CPU % limit before triggering an alert |
| `ANOMALY_LATENCY_THRESHOLD` | `500.0` | Latency limit (ms) before triggering an alert |
| `PREDICTION_HORIZON_MINUTES`| `10` | Moving forecast horizon for resource predictions |
| `AUTOSCALER_MIN_WORKERS` | `1` | Core container floor |
| `AUTOSCALER_MAX_WORKERS` | `8` | Core container ceiling limit |
| `AUTOSCALER_SCALE_UP_THRESHOLD` | `0.75`| System utilization score triggering scale-up |
| `AUTOSCALER_SCALE_DOWN_THRESHOLD` | `0.35`| System utilization score triggering scale-down |
| `AGENT_INTERVAL` | `5` | Refresh rate (in seconds) for metric emission |

## API Endpoints

Explore the interactive API documentation at [`http://localhost:8000/docs`](http://localhost:8000/docs).

| Route | Method | Description |
|-------|--------|-------------|
| `/health` | `GET` | Upstream service connectivity health |
| `/api/status` | `GET` | Core system utilization parameters |
| `/api/metrics` | `GET` | Time-series raw metric export |
| `/api/anomalies` | `GET` | Historical ML/Rule breach log |
| `/api/predictions` | `GET` | Inferred resource loads |
| `/api/scaling` | `GET` | Docker scaling orchestration audit log |
| `/api/workers` | `GET` | Map of recognized dynamic replicas |

## How Autoscaling Works

The core `autoscaler` daemon pulses every 15 seconds, aggregating a blended `utilization` score:

`utilization = (0.6 * avg_cpu_fraction) + (0.4 * predicted_rps_fraction)`

- When `utilization > 0.75`: Spawns +1 worker container attached to the shared network.
- When `utilization < 0.35`: Gracefully halts -1 worker container.

The simulated active workers inject periodic noisy sine-wave stress spikes representing organic flash-crowds, forcing the controller to iteratively adapt and self-heal the environment.

## Project Structure

```text
scaleguard-x/
├── api_gateway/          # FastAPI entrypoint and route controllers
├── anomaly_engine/       # Scikit-Learn IsolationForest outlier detection
├── autoscaler/           # Docker unix-socket scaling manipulator
├── dashboard/            # React + Vite application shell
├── docs/                 # Extended markdown documentation and architecture notes
├── infrastructure/       # Init SQL schemas configuration
├── ingestion_service/    # Async Python Redis to Postgres ETL
├── metrics_agent/        # Psutil agent process
├── prediction_engine/    # Statsmodels ARIMA/EMA load planner
├── worker_cluster/       # Simulated load-injector nodes
├── docker-compose.yml    # Root deployment orchestration definition
└── .env                  # Environment configurations
```

## Contributing

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---
*Built as a reference implementation for autonomous microservice observability systems.*
