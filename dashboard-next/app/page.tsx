"use client";

import {
  Activity,
  AlertTriangle,
  Bell,
  BrainCircuit,
  Cpu,
  ServerCog,
} from "lucide-react";

import { MetricLineChart } from "@/components/charts/metric-line-chart";
import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { StatusBadge } from "@/components/ui/status-badge";
import { useAlerts } from "@/hooks/use-alerts";
import { useMetrics } from "@/hooks/use-metrics";
import { usePredictions } from "@/hooks/use-predictions";
import { useScalingEvents } from "@/hooks/use-scaling";
import { useMetricsSummary, useStatus } from "@/hooks/use-status";
import { actionLabel, formatDateTime, formatMs, formatNumber, formatRatioPercent } from "@/lib/format";

export default function OverviewPage() {
  const status = useStatus();
  const summary = useMetricsSummary();
  const metrics = useMetrics({ minutes: 15, limit: 300 });
  const alerts = useAlerts({ minutes: 360, unresolvedOnly: true, limit: 5 });
  const scaling = useScalingEvents(10);
  const predictions = usePredictions(10);

  const metricChartData = [...(metrics.data ?? [])].reverse().map((row) => ({
    timestamp: row.timestamp,
    requests_per_sec: row.requests_per_sec,
    latency_ms: row.latency_ms,
  }));

  const predictionChartData = [...(predictions.data ?? [])].reverse().map((prediction) => ({
    timestamp: prediction.predicted_at,
    predicted_rps: prediction.predicted_rps,
    lower_bound: prediction.lower_bound ?? null,
    upper_bound: prediction.upper_bound ?? null,
  }));

  const isFetching =
    status.isFetching ||
    summary.isFetching ||
    metrics.isFetching ||
    alerts.isFetching ||
    scaling.isFetching ||
    predictions.isFetching;

  return (
    <>
      <SectionHeader
        eyebrow="Operations cockpit"
        title="ScaleGuard X live dashboard"
        description="A Next.js console for the FastAPI observability backend: status, metrics, alerts, forecasts, and autoscaling evidence in one view."
        actions={<RefreshBadge isFetching={isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Platform"
          value={status.data?.status ? <StatusBadge status={status.data.status} /> : "Loading"}
          helper={status.data ? formatDateTime(status.data.timestamp) : "Waiting for /api/status"}
          icon={<Activity className="h-5 w-5" />}
          tone="good"
        />
        <StatCard
          label="Workers"
          value={formatNumber(status.data?.active_workers)}
          helper="active worker registry"
          icon={<ServerCog className="h-5 w-5" />}
          tone="neutral"
        />
        <StatCard
          label="Nodes"
          value={formatNumber(status.data?.nodes_reporting ?? summary.data?.node_count)}
          helper="reporting in the last window"
          icon={<Cpu className="h-5 w-5" />}
          tone="neutral"
        />
        <StatCard
          label="Predicted RPS"
          value={formatNumber(status.data?.predicted_rps, 1)}
          helper={`observed ${formatNumber(summary.data?.avg_rps, 1)} rps`}
          icon={<BrainCircuit className="h-5 w-5" />}
          tone="good"
        />
        <StatCard
          label="Open Alerts"
          value={formatNumber(alerts.data?.length)}
          helper={`anomaly score ${formatRatioPercent(status.data?.latest_anomaly_score, 0)}`}
          icon={<Bell className="h-5 w-5" />}
          tone={(alerts.data?.length ?? 0) > 0 ? "warn" : "good"}
        />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_0.9fr]">
        <PanelCard title="Traffic and latency" eyebrow="Last 15 minutes">
          {metrics.isLoading ? (
            <LoadingBlock label="Loading metrics" />
          ) : metrics.isError ? (
            <ErrorState error={metrics.error} />
          ) : (
            <MetricLineChart
              data={metricChartData}
              series={[
                { dataKey: "requests_per_sec", label: "Requests/sec", color: "#08b7a6" },
                { dataKey: "latency_ms", label: "Latency", color: "#f1a340", suffix: " ms" },
              ]}
            />
          )}
        </PanelCard>

        <PanelCard title="10-minute forecast" eyebrow="Prediction snapshot">
          {predictions.isLoading ? (
            <LoadingBlock label="Loading forecasts" />
          ) : predictions.isError ? (
            <ErrorState error={predictions.error} />
          ) : (
            <MetricLineChart
              data={predictionChartData}
              series={[
                { dataKey: "predicted_rps", label: "Predicted RPS", color: "#08b7a6" },
                { dataKey: "lower_bound", label: "Lower", color: "#6f7e72" },
                { dataKey: "upper_bound", label: "Upper", color: "#e85d4a" },
              ]}
            />
          )}
        </PanelCard>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <PanelCard title="Unresolved alerts" eyebrow="Needs attention">
          {alerts.isError ? (
            <ErrorState error={alerts.error} />
          ) : (
            <DataTable
              rows={alerts.data ?? []}
              getKey={(row) => row.id}
              emptyTitle="No unresolved alerts"
              columns={[
                { header: "Severity", render: (row) => <StatusBadge status={row.severity} /> },
                { header: "Type", render: (row) => row.alert_type },
                { header: "Node", render: (row) => row.node_id ?? "global" },
                { header: "Raised", render: (row) => formatDateTime(row.raised_at) },
              ]}
            />
          )}
        </PanelCard>

        <PanelCard title="Recent scaling activity" eyebrow="Autoscaler trail">
          {scaling.isError ? (
            <ErrorState error={scaling.error} />
          ) : (
            <DataTable
              rows={scaling.data ?? []}
              getKey={(row) => row.id}
              emptyTitle="No scaling events yet"
              columns={[
                { header: "Action", render: (row) => <StatusBadge status={actionLabel(row.action)} /> },
                { header: "Replicas", render: (row) => `${row.prev_replicas} -> ${row.new_replicas}` },
                { header: "Reason", render: (row) => row.reason ?? "policy decision" },
                { header: "Time", render: (row) => formatDateTime(row.triggered_at) },
              ]}
            />
          )}
        </PanelCard>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <StatCard label="Avg CPU" value={formatPercentValue(summary.data?.avg_cpu)} helper="5-minute aggregate" icon={<Cpu className="h-5 w-5" />} />
        <StatCard label="Avg memory" value={formatPercentValue(summary.data?.avg_mem)} helper="5-minute aggregate" icon={<Activity className="h-5 w-5" />} />
        <StatCard label="Avg latency" value={formatMs(summary.data?.avg_latency)} helper="5-minute aggregate" icon={<AlertTriangle className="h-5 w-5" />} />
      </div>
    </>
  );
}

function formatPercentValue(value: number | null | undefined) {
  return `${formatNumber(value, 1)}%`;
}
