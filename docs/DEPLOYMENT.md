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
- API, ingestion, prediction, worker, and autoscaler ECS services
- an ECS-capable autoscaler path that updates the worker service desired count
- security groups and subnet-group wiring

Required Terraform inputs live in:

- [infrastructure/terraform/variables.tf](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/variables.tf)
- [infrastructure/terraform/outputs.tf](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/outputs.tf)
- [infrastructure/terraform/terraform.tfvars.example](/C:/Users/KIIT0001/Desktop/scaleguard-x/infrastructure/terraform/terraform.tfvars.example)

## Image build and push

Build the deployment image set locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_week2_images.ps1
```

After installing and configuring AWS CLI, tag and push to ECR:

```powershell
$accountId = aws sts get-caller-identity --query Account --output text
$region = "us-east-1"
$registry = "$accountId.dkr.ecr.$region.amazonaws.com"
aws ecr get-login-password --region $region | docker login --username AWS --password-stdin $registry
powershell -ExecutionPolicy Bypass -File scripts\build_week2_images.ps1 -Registry $registry -Push
```

The default prediction image uses ARIMA/EMA fallbacks so it can build reliably for pilot deployment. To include the optional Prophet/LSTM dependencies, build the prediction image with:

```powershell
docker build --build-arg INSTALL_ML_EXTRAS=true -t scaleguard-prediction:ml -f prediction_engine/Dockerfile .
```

## Pilot deployment flow

1. Build and publish container images for:
   - `api_gateway`
   - `ingestion_service`
   - `prediction_engine`
   - `worker_cluster`
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

## Week 2 local validation status

Local week-2 validation has been completed and documented in:

- [docs/WEEK2_VALIDATION.md](/C:/Users/KIIT0001/Desktop/scaleguard-x/docs/WEEK2_VALIDATION.md)
- [benchmarks/results/week2_scaling_events.csv](/C:/Users/KIIT0001/Desktop/scaleguard-x/benchmarks/results/week2_scaling_events.csv)

Terraform planning and ECR push were not run in this workspace because `terraform` and `aws` are not installed locally. Install those tools before running:

```powershell
cd infrastructure\terraform
copy terraform.tfvars.example terraform.tfvars
terraform init
terraform validate
terraform plan
```

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
