import { z } from "zod";

import { apiFetch } from "@/lib/fetcher";

const numberFromApi = z.coerce.number();
const nullableNumberFromApi = z.preprocess(
  (value) => (value === null || value === undefined ? undefined : value),
  z.coerce.number().optional(),
);

const healthSchema = z.object({
  status: z.string(),
  service: z.string(),
  timestamp: z.string(),
});

const statusSchema = z.object({
  status: z.string(),
  active_workers: numberFromApi,
  nodes_reporting: numberFromApi,
  latest_anomaly_score: numberFromApi,
  predicted_rps: numberFromApi,
  timestamp: z.string(),
});

const metricRowSchema = z.object({
  node_id: z.string(),
  timestamp: z.string(),
  cpu_usage: numberFromApi,
  memory_usage: numberFromApi,
  latency_ms: numberFromApi,
  requests_per_sec: numberFromApi,
  disk_usage: numberFromApi,
});

const metricSummarySchema = z.object({
  avg_cpu: numberFromApi,
  avg_mem: numberFromApi,
  avg_latency: numberFromApi,
  avg_rps: numberFromApi,
  node_count: numberFromApi,
});

const metricNodesSchema = z.object({
  nodes: z.array(z.string()),
});

const anomalySchema = z.object({
  id: numberFromApi,
  node_id: z.string(),
  detected_at: z.string(),
  anomaly_type: z.string(),
  metric_name: z.string(),
  metric_value: numberFromApi,
  threshold: nullableNumberFromApi.nullable(),
  anomaly_score: numberFromApi,
  description: z.string().nullable().optional(),
});

const predictionSchema = z.object({
  id: numberFromApi,
  predicted_at: z.string(),
  horizon_minutes: numberFromApi,
  predicted_rps: numberFromApi,
  predicted_cpu: nullableNumberFromApi.nullable(),
  confidence: nullableNumberFromApi.nullable(),
  lower_bound: nullableNumberFromApi.nullable(),
  upper_bound: nullableNumberFromApi.nullable(),
  spike_probability: nullableNumberFromApi.nullable(),
  model_name: z.string().nullable().optional(),
});

const scalingEventSchema = z.object({
  id: numberFromApi,
  triggered_at: z.string(),
  action: z.string(),
  prev_replicas: numberFromApi,
  new_replicas: numberFromApi,
  reason: z.string().nullable().optional(),
});

const alertSchema = z.object({
  id: numberFromApi,
  raised_at: z.string(),
  severity: z.string(),
  node_id: z.string().nullable().optional(),
  alert_type: z.string(),
  message: z.string(),
  resolved: z.boolean(),
});

const workerSchema = z.object({
  worker_id: z.string(),
  container_id: z.string().nullable().optional(),
  registered_at: z.string(),
  last_heartbeat: z.string(),
  status: z.string(),
});

async function fetchParsed<TSchema extends z.ZodTypeAny>(
  path: string,
  schema: TSchema,
): Promise<z.infer<TSchema>> {
  const json = await apiFetch<unknown>(path);
  return schema.parse(json);
}

function withParams(path: string, params: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });

  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function getHealth() {
  return fetchParsed("/health", healthSchema);
}

export function getStatus() {
  return fetchParsed("/api/status", statusSchema);
}

export function getMetricsSummary() {
  return fetchParsed("/api/metrics/summary", metricSummarySchema);
}

export function getMetricNodes() {
  return fetchParsed("/api/metrics/nodes", metricNodesSchema);
}

export function getMetrics(params: { nodeId?: string; minutes?: number; limit?: number } = {}) {
  return fetchParsed(
    withParams("/api/metrics", {
      node_id: params.nodeId,
      minutes: params.minutes ?? 30,
      limit: params.limit ?? 500,
    }),
    z.array(metricRowSchema),
  );
}

export function getAnomalies(params: { minutes?: number; limit?: number } = {}) {
  return fetchParsed(
    withParams("/api/anomalies", {
      minutes: params.minutes ?? 60,
      limit: params.limit ?? 100,
    }),
    z.array(anomalySchema),
  );
}

export function getPredictions(limit = 20) {
  return fetchParsed(withParams("/api/predictions", { limit }), z.array(predictionSchema));
}

export function getScalingEvents(limit = 50) {
  return fetchParsed(withParams("/api/scaling", { limit }), z.array(scalingEventSchema));
}

export function getAlerts(
  params: { minutes?: number; unresolvedOnly?: boolean; limit?: number } = {},
) {
  return fetchParsed(
    withParams("/api/alerts", {
      minutes: params.minutes ?? 60,
      unresolved_only: params.unresolvedOnly,
      limit: params.limit ?? 100,
    }),
    z.array(alertSchema),
  );
}

export function getWorkers() {
  return fetchParsed("/api/workers", z.array(workerSchema));
}
