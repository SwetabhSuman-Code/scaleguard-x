# ScaleGuard X — API Reference

Base URL: `http://localhost:8000`

---

## System

### `GET /health`
Service health probe.

**Response:**
```json
{ "status": "ok", "service": "api_gateway", "timestamp": "2026-03-17T01:00:00Z" }
```

### `GET /api/status`
High-level platform overview.

**Response:**
```json
{
  "status": "operational",
  "active_workers": 3,
  "nodes_reporting": 4,
  "latest_anomaly_score": 0.612,
  "predicted_rps": 187.4,
  "timestamp": "2026-03-17T01:00:00Z"
}
```

---

## Metrics

### `GET /api/metrics`
Returns raw metric rows from the database.

| Param | Default | Description |
|---|---|---|
| `node_id` | *all* | Filter to a specific node |
| `minutes` | 30 | Lookback window (max 1440) |
| `limit` | 500 | Max rows returned (max 5000) |

**Response:** Array of metric objects:
```json
[{
  "node_id": "worker-abc",
  "timestamp": "2026-03-17T01:00:00Z",
  "cpu_usage": 72.5,
  "memory_usage": 55.1,
  "latency_ms": 42.3,
  "requests_per_sec": 214.0,
  "disk_usage": 40.2
}]
```

### `GET /api/metrics/nodes`
List all nodes that reported in the last 5 minutes.

### `GET /api/metrics/summary`
Average aggregated metrics across all nodes (last 5 min).

---

## Anomalies

### `GET /api/anomalies`
| Param | Default | Description |
|---|---|---|
| `minutes` | 60 | Lookback window |
| `limit` | 100 | Max results |

**Response:**
```json
[{
  "id": 1,
  "node_id": "worker-abc",
  "detected_at": "2026-03-17T01:00:00Z",
  "anomaly_type": "rule_based",
  "metric_name": "cpu",
  "metric_value": 91.2,
  "threshold": 85.0,
  "anomaly_score": 0.82,
  "description": "High CPU usage: 91.2 exceeds threshold 85.0"
}]
```

---

## Predictions

### `GET /api/predictions`
| Param | Default | Description |
|---|---|---|
| `limit` | 20 | Max results |

**Response:**
```json
[{
  "id": 1,
  "predicted_at": "2026-03-17T01:00:00Z",
  "horizon_minutes": 10,
  "predicted_rps": 245.8,
  "predicted_cpu": null,
  "confidence": 0.74
}]
```

---

## Scaling

### `GET /api/scaling`
Scaling history.
| Param | Default |
|---|---|
| `limit` | 50 |

**Response:**
```json
[{
  "id": 1,
  "triggered_at": "2026-03-17T01:00:00Z",
  "action": "scale_up",
  "prev_replicas": 2,
  "new_replicas": 3,
  "reason": "utilization=0.80 >= 0.75 (cpu=85.0%, rps=300.0)"
}]
```

---

## Alerts

### `GET /api/alerts`
| Param | Default | Description |
|---|---|---|
| `minutes` | 60 | Lookback |
| `unresolved_only` | false | Only open alerts |
| `limit` | 100 | Max results |

**Response:**
```json
[{
  "id": 1,
  "raised_at": "2026-03-17T01:00:00Z",
  "severity": "critical",
  "node_id": "worker-abc",
  "alert_type": "rule_based",
  "message": "High CPU usage: 91.2 exceeds threshold 85.0",
  "resolved": false
}]
```

---

## Workers

### `GET /api/workers`
All registered worker nodes.

**Response:**
```json
[{
  "worker_id": "worker-abc-123",
  "container_id": "a1b2c3d4",
  "registered_at": "2026-03-17T01:00:00Z",
  "last_heartbeat": "2026-03-17T01:01:00Z",
  "status": "active"
}]
```
