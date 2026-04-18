# ScaleGuard X Deployment Guide

This guide describes how to take ScaleGuard X from a local docker-compose stack to a pilot cloud deployment. It is intentionally written as a pilot guide, not a blanket claim that the repository is already production-proven.

## What this guide covers

- local stack bring-up for functional validation
- AWS ECS Fargate deployment scaffolding via Terraform
- post-deploy smoke checks and benchmark reruns
- what still needs manual validation before calling a deployment production-ready

## Local validation first

1. Copy `.env.example` to `.env`.
2. Set strong values for:
   - `POSTGRES_PASSWORD`
   - `GRAFANA_ADMIN_PASSWORD`
   - `JWT_SECRET_KEY`
3. Start the stack with `docker compose up -d --build`.
4. Confirm:
   - `http://localhost:8000/health`
   - `http://localhost:8000/docs`
   - `http://localhost:3000`
   - `http://localhost:16686`

## Pilot cloud target

The repository now includes an AWS-oriented Terraform scaffold under [infrastructure/terraform/main.tf](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/main.tf). The scaffold provisions:

- ECS cluster with Fargate services
- HTTPS Application Load Balancer
- RDS PostgreSQL
- ElastiCache Redis
- CloudWatch log groups
- security groups and subnet-group wiring

Required Terraform inputs live in:

- [infrastructure/terraform/variables.tf](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/variables.tf)
- [infrastructure/terraform/outputs.tf](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/outputs.tf)

## Pilot deployment flow

1. Build and publish container images for:
   - `api_gateway`
   - `ingestion_service`
   - `prediction_engine`
   - `autoscaler`
2. Provide image URIs, VPC/subnet IDs, ACM certificate ARN, DB password, and JWT secret to Terraform.
3. Apply the Terraform stack.
4. Point `SCALEGUARD_PRODUCTION_URL` at the ALB hostname or your DNS front door.
5. Run the production smoke tests with:

```bash
pytest tests/production/test_deployment.py -v
```

## Post-deploy verification

Minimum checks after every pilot deployment:

- `GET /health` returns healthy or explicitly degraded dependencies
- `POST /api/auth/token` returns a valid token payload
- `POST /api/metrics` accepts benchmark-compatible metric payloads
- anonymous callers cannot trigger `POST /api/scaling/manual`
- every request returns `X-Request-ID` and `X-Trace-ID`
- Prometheus can scrape the API metrics endpoint

## Benchmark reruns

Once a live stack is up, rerun the benchmark suite before publishing any throughput numbers:

```bash
pytest benchmarks/test_latency.py::test_health_endpoint_latency -m benchmark -v
pytest benchmarks/test_throughput.py::test_throughput_1k_metrics_per_sec -m benchmark -v
```

The repository includes a dedicated GitHub workflow for this path:

- [.github/workflows/benchmark.yml](/C:/Users/KIIT0001/Desktop/scaleguard-x/.github/workflows/benchmark.yml)

## What is still manual

Even with the Terraform scaffold and smoke tests in place, the following are still manual validation steps:

- real TLS, DNS, and certificate ownership
- secret rotation and secure storage
- backup and restore drills
- load testing with sustained traffic and observed autoscaling
- incident handling and on-call exercise
- competitive benchmarking against external tools in equivalent environments

## Recommended evidence before calling it production-ready

- a successful production smoke-test run
- at least one valid ingestion throughput benchmark result
- one recorded chaos drill
- one backup/restore drill
- one written incident or postmortem report
