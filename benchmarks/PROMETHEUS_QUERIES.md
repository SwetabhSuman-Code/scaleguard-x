# Prometheus Queries for ScaleGuard X Performance Testing
# Copy-paste directly into Prometheus UI (http://localhost:9090)

# ====================================================================
# 1. REQUEST RATE (Requests per Second)
# ====================================================================
# Primary metric for throughput monitoring
rate(http_requests_total{job="api_gateway"}[1m])

# Breakdown by endpoint
rate(http_requests_total{job="api_gateway"}[1m]) by (endpoint)

# Breakdown by status code
rate(http_requests_total{job="api_gateway"}[1m]) by (status)


# ====================================================================
# 2. RESPONSE LATENCY (Request Duration)
# ====================================================================
# Average latency (mean)
avg(http_request_duration_seconds{job="api_gateway"})

# P50 (median)
histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m]))

# P95 (95th percentile) - Good indicator of user experience
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m]))

# P99 (99th percentile) - Worst case for most users
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m]))

# P99.9 (extremely slow requests)
histogram_quantile(0.999, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m]))

# Max latency
max(http_request_duration_seconds{job="api_gateway"})


# ====================================================================
# 3. ERROR RATE (Failures)
# ====================================================================
# Raw error count (5xx errors)
rate(http_requests_total{job="api_gateway",status=~"5.."}[1m])

# Error rate as percentage
100 * (
  rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) /
  rate(http_requests_total{job="api_gateway"}[1m])
)

# Errors by endpoint
rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) by (endpoint)

# Errors by status code
rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) by (status)


# ====================================================================
# 4. HTTP STATUS CODE BREAKDOWN
# ====================================================================
# 2xx (successful)
rate(http_requests_total{job="api_gateway",status=~"2.."}[1m])

# 4xx (client errors - bad requests)
rate(http_requests_total{job="api_gateway",status=~"4.."}[1m])

# 5xx (server errors)
rate(http_requests_total{job="api_gateway",status=~"5.."}[1m])


# ====================================================================
# 5. CPU & MEMORY USAGE
# ====================================================================
# API Gateway CPU usage
rate(container_cpu_usage_seconds_total{name="scaleguard-api-gateway"}[1m])

# API Gateway memory usage (bytes)
container_memory_usage_bytes{name="scaleguard-api-gateway"}

# API Gateway memory usage (MB)
container_memory_usage_bytes{name="scaleguard-api-gateway"} / 1024 / 1024

# PostgreSQL CPU
rate(container_cpu_usage_seconds_total{name="scaleguard-postgres"}[1m])

# PostgreSQL memory usage (MB)
container_memory_usage_bytes{name="scaleguard-postgres"} / 1024 / 1024

# Redis memory usage (MB)
redis_memory_used_bytes{instance="redis_queue:6379"} / 1024 / 1024


# ====================================================================
# 6. DATABASE METRICS
# ====================================================================
# Active database connections
pg_stat_activity_count{datname="scaleguard_db"}

# Database query duration
pg_slow_queries_total

# Database connection utilization (%)
100 * (pg_stat_activity_count{datname="scaleguard_db"} / pg_settings_max_connections)

# Cache hit ratio (if metrics_cache exists)
rate(metrics_cache_hits_total[1m]) / (rate(metrics_cache_hits_total[1m]) + rate(metrics_cache_misses_total[1m]))


# ====================================================================
# 7. REDIS METRICS
# ====================================================================
# Connected clients
redis_connected_clients{instance="redis_queue:6379"}

# Commands processed per second
rate(redis_commands_processed_total{instance="redis_queue:6379"}[1m])

# Memory usage
redis_memory_used_bytes{instance="redis_queue:6379"} / 1024 / 1024

# Key evictions (indicates memory pressure)
rate(redis_evicted_keys_total{instance="redis_queue:6379"}[1m])


# ====================================================================
# 8. METRICS INGESTION
# ====================================================================
# Metrics ingested per second
rate(metrics_ingested_total[1m])

# Metrics processing latency
histogram_quantile(0.95, rate(metrics_processing_duration_seconds_bucket[5m]))

# Ingestion queue depth (if tracked)
metrics_queue_depth

# Failed ingestion attempts
rate(metrics_ingestion_failures_total[1m])


# ====================================================================
# 9. AUTOSCALER METRICS
# ====================================================================
# Current worker count
worker_cluster_replicas

# Scale-up events
rate(autoscaler_scale_up_events_total[5m])

# Scale-down events
rate(autoscaler_scale_down_events_total[5m])

# Total scaling events
rate(autoscaler_scaling_events_total[5m])

# Predicted load (forecast)
autoscaler_predicted_load_next_5m

# Actual current load
autoscaler_current_load

# Time to respond to spike (if available)
autoscaler_response_time_seconds


# ====================================================================
# 10. CIRCUIT BREAKER STATUS
# ====================================================================
# Circuit breaker trips (indicates cascading failures)
rate(circuit_breaker_trips_total[5m])

# Open circuits (0 = healthy, 1 = circuit open/failing)
circuit_breaker_status{name="metrics_store"}

# Circuit breaker recovery attempts
rate(circuit_breaker_recovery_attempts_total[5m])


# ====================================================================
# 11. COMBINED PERFORMANCE DASHBOARD QUERIES
# ====================================================================
# Apdex Score (0-1, >0.94 is healthy)
# Measures: (satisfactory responses + 0.5 * tolerable) / total
# Satisfactory < 200ms, Tolerable < 1s
(
  rate(http_requests_total{job="api_gateway",le="0.2"}[5m]) +
  0.5 * rate(http_requests_total{job="api_gateway",le="1"}[5m])
) / rate(http_requests_total{job="api_gateway"}[5m])

# Golden Signals (USE Method)
# 1. Utilization: CPU usage
rate(container_cpu_usage_seconds_total{name="scaleguard-api-gateway"}[1m])

# 2. Saturation: Request queue depth
http_requests_in_flight{job="api_gateway"}

# 3. Errors: Error rate
100 * (
  rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) /
  rate(http_requests_total{job="api_gateway"}[1m])
)


# ====================================================================
# 12. SLOW QUERY DETECTION
# ====================================================================
# Requests slower than 500ms
rate(http_requests_total{job="api_gateway",le="0.5"}[5m]) == 0

# Requests slower than 1 second
rate(http_requests_total{job="api_gateway",le="1"}[5m])

# Spike in latency (compare to 1h ago)
rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m]) > 
(rate(http_request_duration_seconds_sum[5m] offset 1h) / rate(http_request_duration_seconds_count[5m] offset 1h)) * 1.5


# ====================================================================
# 13. ALERT THRESHOLDS (Set these as Prometheus Alerts)
# ====================================================================
# Alert: High error rate
ALERT HighErrorRate
  IF (rate(http_requests_total{status=~"5.."}[1m]) / rate(http_requests_total[1m])) > 0.05
  FOR 2m

# Alert: High latency
ALERT HighLatency
  IF histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
  FOR 5m

# Alert: Database connection exhaustion
ALERT DBConnectionExhaustion
  IF pg_stat_activity_count{datname="scaleguard_db"} > 40
  FOR 1m

# Alert: Memory leak
ALERT MemoryLeak
  IF rate(container_memory_usage_bytes{name="scaleguard-api-gateway"}[10m]) > 0
  FOR 15m


# ====================================================================
# QUICK START: Copy All 3 Main Queries Below
# ====================================================================

# PASTE THESE THREE INTO SEPARATE PANELS FOR MAIN DASHBOARD:

# Panel 1: Request Rate (req/sec)
rate(http_requests_total{job="api_gateway"}[1m])

# Panel 2: P95 Latency (milliseconds)
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="api_gateway"}[5m])) * 1000

# Panel 3: Error Rate (%)
100 * (rate(http_requests_total{job="api_gateway",status=~"5.."}[1m]) / rate(http_requests_total{job="api_gateway"}[1m]))
