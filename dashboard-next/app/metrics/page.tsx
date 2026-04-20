"use client";

import { Activity, Gauge, HardDrive, MemoryStick, Network } from "lucide-react";
import { useState } from "react";

import { MetricLineChart } from "@/components/charts/metric-line-chart";
import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { useMetricNodes, useMetrics } from "@/hooks/use-metrics";
import { useMetricsSummary } from "@/hooks/use-status";
import { TIME_RANGES } from "@/lib/constants";
import { cn, formatDateTime, formatMs, formatNumber } from "@/lib/format";
import type { TimeRangeMinutes } from "@/types/api";

export default function MetricsPage() {
  const [minutes, setMinutes] = useState<TimeRangeMinutes>(30);
  const [nodeId, setNodeId] = useState("");
  const nodes = useMetricNodes();
  const metrics = useMetrics({ nodeId: nodeId || undefined, minutes, limit: 1000 });
  const summary = useMetricsSummary();

  const chartData = [...(metrics.data ?? [])].reverse().map((row) => ({
    timestamp: row.timestamp,
    cpu_usage: row.cpu_usage,
    memory_usage: row.memory_usage,
    latency_ms: row.latency_ms,
    requests_per_sec: row.requests_per_sec,
    disk_usage: row.disk_usage,
  }));

  const latestRows = (metrics.data ?? []).slice(0, 15);

  return (
    <>
      <SectionHeader
        eyebrow="Telemetry"
        title="Metrics explorer"
        description="Filter live metric samples by node and time window, then inspect request rate, latency, CPU, memory, and disk usage."
        actions={<RefreshBadge isFetching={metrics.isFetching || summary.isFetching} />}
      />

      <div className="panel mb-5 rounded-[2rem] p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {TIME_RANGES.map((range) => (
              <button
                key={range.value}
                type="button"
                className={cn(
                  "rounded-full border px-4 py-2 text-sm font-extrabold transition",
                  minutes === range.value
                    ? "border-ink bg-ink text-paper"
                    : "border-ink/10 bg-panel text-graphite hover:border-ink/30",
                )}
                onClick={() => setMinutes(range.value)}
              >
                {range.label}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-3 text-sm font-extrabold text-graphite">
            Node
            <select
              className="rounded-full border border-ink/10 bg-panel px-4 py-2 font-bold outline-none focus-ring"
              value={nodeId}
              onChange={(event) => setNodeId(event.target.value)}
            >
              <option value="">All nodes</option>
              {(nodes.data?.nodes ?? []).map((node) => (
                <option key={node} value={node}>
                  {node}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Avg RPS" value={formatNumber(summary.data?.avg_rps, 1)} helper="5-minute aggregate" icon={<Network className="h-5 w-5" />} tone="good" />
        <StatCard label="Avg latency" value={formatMs(summary.data?.avg_latency)} helper="latest aggregate" icon={<Gauge className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Avg CPU" value={`${formatNumber(summary.data?.avg_cpu, 1)}%`} helper="across reporting nodes" icon={<Activity className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Avg memory" value={`${formatNumber(summary.data?.avg_mem, 1)}%`} helper="across reporting nodes" icon={<MemoryStick className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Nodes" value={formatNumber(summary.data?.node_count)} helper="active in 5 minutes" icon={<HardDrive className="h-5 w-5" />} tone="neutral" />
      </div>

      {metrics.isError ? (
        <div className="mt-5">
          <ErrorState error={metrics.error} />
        </div>
      ) : metrics.isLoading ? (
        <div className="mt-5">
          <LoadingBlock label="Loading metric samples" />
        </div>
      ) : (
        <>
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <PanelCard title="Requests/sec" eyebrow={`${minutes} minute window`}>
              <MetricLineChart
                data={chartData}
                series={[{ dataKey: "requests_per_sec", label: "Requests/sec", color: "#08b7a6" }]}
              />
            </PanelCard>
            <PanelCard title="Latency" eyebrow="API and worker response">
              <MetricLineChart
                data={chartData}
                series={[{ dataKey: "latency_ms", label: "Latency", color: "#f1a340", suffix: " ms" }]}
              />
            </PanelCard>
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <PanelCard title="CPU and memory" eyebrow="Node pressure">
              <MetricLineChart
                data={chartData}
                series={[
                  { dataKey: "cpu_usage", label: "CPU", color: "#e85d4a", suffix: "%" },
                  { dataKey: "memory_usage", label: "Memory", color: "#08b7a6", suffix: "%" },
                ]}
              />
            </PanelCard>
            <PanelCard title="Disk usage" eyebrow="Storage headroom">
              <MetricLineChart
                data={chartData}
                series={[{ dataKey: "disk_usage", label: "Disk", color: "#36493b", suffix: "%" }]}
              />
            </PanelCard>
          </div>

          <div className="mt-5">
            <PanelCard title="Latest metric rows" eyebrow="Raw samples">
              <DataTable
                rows={latestRows}
                getKey={(row, index) => `${row.node_id}-${row.timestamp}-${index}`}
                emptyTitle="No metrics in this window"
                columns={[
                  { header: "Time", render: (row) => formatDateTime(row.timestamp) },
                  { header: "Node", render: (row) => row.node_id },
                  { header: "RPS", render: (row) => formatNumber(row.requests_per_sec, 1) },
                  { header: "Latency", render: (row) => formatMs(row.latency_ms) },
                  { header: "CPU", render: (row) => `${formatNumber(row.cpu_usage, 1)}%` },
                  { header: "Memory", render: (row) => `${formatNumber(row.memory_usage, 1)}%` },
                  { header: "Disk", render: (row) => `${formatNumber(row.disk_usage, 1)}%` },
                ]}
              />
            </PanelCard>
          </div>
        </>
      )}
    </>
  );
}
