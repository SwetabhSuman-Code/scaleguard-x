"use client";

import { BrainCircuit, Gauge, LineChart as LineChartIcon, Radar } from "lucide-react";

import { MetricLineChart } from "@/components/charts/metric-line-chart";
import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { usePredictions } from "@/hooks/use-predictions";
import { useMetricsSummary, useStatus } from "@/hooks/use-status";
import { formatDateTime, formatNumber, formatRatioPercent } from "@/lib/format";

export default function PredictionsPage() {
  const predictions = usePredictions(50);
  const summary = useMetricsSummary();
  const status = useStatus();
  const rows = predictions.data ?? [];
  const latest = rows[0];
  const chartData = [...rows].reverse().map((row) => ({
    timestamp: row.predicted_at,
    predicted_rps: row.predicted_rps,
    lower_bound: row.lower_bound ?? null,
    upper_bound: row.upper_bound ?? null,
    predicted_cpu: row.predicted_cpu ?? null,
  }));

  return (
    <>
      <SectionHeader
        eyebrow="Forecasting"
        title="Predictions"
        description="Compare current observed throughput against the prediction engine's latest RPS and CPU forecasts."
        actions={<RefreshBadge isFetching={predictions.isFetching || summary.isFetching || status.isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Observed RPS" value={formatNumber(summary.data?.avg_rps, 1)} helper="current 5-minute average" icon={<Gauge className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Predicted RPS" value={formatNumber(status.data?.predicted_rps ?? latest?.predicted_rps, 1)} helper={`${latest?.horizon_minutes ?? 0} minute horizon`} icon={<BrainCircuit className="h-5 w-5" />} tone="good" />
        <StatCard label="Confidence" value={formatRatioPercent(latest?.confidence ?? 0, 0)} helper={latest?.model_name ?? "forecast model"} icon={<LineChartIcon className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Spike risk" value={formatRatioPercent(latest?.spike_probability ?? 0, 0)} helper="latest predicted probability" icon={<Radar className="h-5 w-5" />} tone={(latest?.spike_probability ?? 0) > 0.5 ? "warn" : "good"} />
      </div>

      <div className="mt-5">
        <PanelCard title="Forecast band" eyebrow="RPS with confidence bounds">
          {predictions.isLoading ? (
            <LoadingBlock label="Loading forecasts" />
          ) : predictions.isError ? (
            <ErrorState error={predictions.error} />
          ) : (
            <MetricLineChart
              data={chartData}
              series={[
                { dataKey: "predicted_rps", label: "Predicted RPS", color: "#08b7a6" },
                { dataKey: "lower_bound", label: "Lower bound", color: "#6f7e72" },
                { dataKey: "upper_bound", label: "Upper bound", color: "#e85d4a" },
              ]}
            />
          )}
        </PanelCard>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <PanelCard title="Predicted CPU" eyebrow="Capacity pressure">
          {predictions.isLoading ? (
            <LoadingBlock label="Loading CPU forecast" />
          ) : predictions.isError ? (
            <ErrorState error={predictions.error} />
          ) : (
            <MetricLineChart
              data={chartData}
              series={[{ dataKey: "predicted_cpu", label: "Predicted CPU", color: "#f1a340", suffix: "%" }]}
            />
          )}
        </PanelCard>

        <PanelCard title="Prediction records" eyebrow={`${rows.length} recent rows`}>
          {predictions.isLoading ? (
            <LoadingBlock label="Loading records" />
          ) : predictions.isError ? (
            <ErrorState error={predictions.error} />
          ) : (
            <DataTable
              rows={rows.slice(0, 15)}
              getKey={(row) => row.id}
              emptyTitle="No predictions yet"
              columns={[
                { header: "Predicted at", render: (row) => formatDateTime(row.predicted_at) },
                { header: "Horizon", render: (row) => `${row.horizon_minutes}m` },
                { header: "RPS", render: (row) => formatNumber(row.predicted_rps, 1) },
                { header: "CPU", render: (row) => (row.predicted_cpu === null || row.predicted_cpu === undefined ? "-" : `${formatNumber(row.predicted_cpu, 1)}%`) },
                { header: "Confidence", render: (row) => formatRatioPercent(row.confidence ?? 0, 0) },
                { header: "Model", render: (row) => row.model_name ?? "unknown" },
              ]}
            />
          )}
        </PanelCard>
      </div>
    </>
  );
}
