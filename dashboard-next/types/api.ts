export interface HealthResponse {
  status: string;
  service: string;
  timestamp: string;
}

export interface StatusResponse {
  status: string;
  active_workers: number;
  nodes_reporting: number;
  latest_anomaly_score: number;
  predicted_rps: number;
  timestamp: string;
}

export interface MetricRow {
  node_id: string;
  timestamp: string;
  cpu_usage: number;
  memory_usage: number;
  latency_ms: number;
  requests_per_sec: number;
  disk_usage: number;
}

export interface MetricsSummary {
  avg_cpu: number;
  avg_mem: number;
  avg_latency: number;
  avg_rps: number;
  node_count: number;
}

export interface MetricNodesResponse {
  nodes: string[];
}

export interface Anomaly {
  id: number;
  node_id: string;
  detected_at: string;
  anomaly_type: string;
  metric_name: string;
  metric_value: number;
  threshold?: number | null;
  anomaly_score: number;
  description?: string | null;
}

export interface Prediction {
  id: number;
  predicted_at: string;
  horizon_minutes: number;
  predicted_rps: number;
  predicted_cpu?: number | null;
  confidence?: number | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  spike_probability?: number | null;
  model_name?: string | null;
}

export interface ScalingEvent {
  id: number;
  triggered_at: string;
  action: string;
  prev_replicas: number;
  new_replicas: number;
  reason?: string | null;
}

export interface Alert {
  id: number;
  raised_at: string;
  severity: string;
  node_id?: string | null;
  alert_type: string;
  message: string;
  resolved: boolean;
}

export interface Worker {
  worker_id: string;
  container_id?: string | null;
  registered_at: string;
  last_heartbeat: string;
  status: string;
}

export type TimeRangeMinutes = 15 | 30 | 60 | 360;
