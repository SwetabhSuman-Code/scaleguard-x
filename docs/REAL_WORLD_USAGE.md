# Real-World Usage Notes

This repository does not yet include a claimed 30-day production case study. What it now includes is a practical pilot path and a checklist for turning a deployment into an evidence-backed case study.

## What is implemented

- cloud deployment scaffold for AWS ECS Fargate
- production smoke tests gated by `SCALEGUARD_PRODUCTION_URL`
- benchmark rerun workflow
- on-call runbook and local observability stack

## What still needs real-world validation

- sustained ingestion throughput in a deployed environment
- end-to-end autoscaling reaction time under real traffic
- backup and restore timing
- behavior during dependency outages
- operational cost over time

## Pilot checklist

Before calling a pilot successful, collect the following:

- deployment date and environment details
- instance sizes and task counts
- valid benchmark results from the deployed environment
- one chaos drill result
- one restore drill result
- one incident summary, even if low severity

## Suggested case-study template

Use this template after a real pilot run:

### Environment

- region:
- ECS task sizes:
- API desired count:
- prediction desired count:
- autoscaler desired count:
- database tier:
- redis tier:

### Measured results

- `/health` p99:
- ingestion throughput:
- autoscale reaction time:
- average worker utilization:
- monthly infrastructure cost:

### Incidents

- date:
- trigger:
- impact:
- mitigation:
- follow-up action:

### What worked

- 

### What broke first

- 

### Next changes before a wider rollout

- 
