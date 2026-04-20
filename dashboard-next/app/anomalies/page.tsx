"use client";

import { AlertTriangle, Gauge, Search } from "lucide-react";
import { useState } from "react";

import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { StatusBadge } from "@/components/ui/status-badge";
import { useAnomalies } from "@/hooks/use-anomalies";
import { TIME_RANGES } from "@/lib/constants";
import { anomalyTone, cn, formatDateTime, formatNumber, formatRatioPercent } from "@/lib/format";
import type { TimeRangeMinutes } from "@/types/api";

export default function AnomaliesPage() {
  const [minutes, setMinutes] = useState<TimeRangeMinutes>(60);
  const [nodeFilter, setNodeFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const anomalies = useAnomalies({ minutes, limit: 250 });

  const rows = anomalies.data ?? [];
  const nodeOptions = Array.from(new Set(rows.map((row) => row.node_id))).sort();
  const typeOptions = Array.from(new Set(rows.map((row) => row.anomaly_type))).sort();
  const filteredRows = rows.filter((row) => {
    const matchesNode = !nodeFilter || row.node_id === nodeFilter;
    const matchesType = !typeFilter || row.anomaly_type === typeFilter;
    return matchesNode && matchesType;
  });
  const criticalCount = rows.filter((row) => anomalyTone(row.anomaly_score) === "bad").length;
  const maxScore = rows.reduce((max, row) => Math.max(max, row.anomaly_score), 0);

  return (
    <>
      <SectionHeader
        eyebrow="Detection"
        title="Anomaly feed"
        description="Inspect detected outliers with node, metric, threshold, and score context from the anomaly engine."
        actions={<RefreshBadge isFetching={anomalies.isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Anomalies" value={formatNumber(rows.length)} helper={`${minutes} minute window`} icon={<AlertTriangle className="h-5 w-5" />} tone={rows.length > 0 ? "warn" : "good"} />
        <StatCard label="Critical scores" value={formatNumber(criticalCount)} helper="score at or above 0.8" icon={<Gauge className="h-5 w-5" />} tone={criticalCount > 0 ? "bad" : "good"} />
        <StatCard label="Max score" value={formatRatioPercent(maxScore, 0)} helper="highest active anomaly score" icon={<Search className="h-5 w-5" />} tone={maxScore >= 0.8 ? "bad" : maxScore >= 0.5 ? "warn" : "good"} />
      </div>

      <div className="panel my-5 rounded-[2rem] p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
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
          <div className="flex flex-wrap gap-3">
            <select
              className="rounded-full border border-ink/10 bg-panel px-4 py-2 text-sm font-bold outline-none focus-ring"
              value={nodeFilter}
              onChange={(event) => setNodeFilter(event.target.value)}
            >
              <option value="">All nodes</option>
              {nodeOptions.map((node) => (
                <option key={node} value={node}>
                  {node}
                </option>
              ))}
            </select>
            <select
              className="rounded-full border border-ink/10 bg-panel px-4 py-2 text-sm font-bold outline-none focus-ring"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
            >
              <option value="">All types</option>
              {typeOptions.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <PanelCard title="Detected anomalies" eyebrow={`${filteredRows.length} visible rows`}>
        {anomalies.isLoading ? (
          <LoadingBlock label="Loading anomalies" />
        ) : anomalies.isError ? (
          <ErrorState error={anomalies.error} />
        ) : (
          <DataTable
            rows={filteredRows}
            getKey={(row) => row.id}
            emptyTitle="No anomalies found"
            columns={[
              { header: "Severity", render: (row) => <StatusBadge status={anomalyTone(row.anomaly_score)} /> },
              { header: "Detected", render: (row) => formatDateTime(row.detected_at) },
              { header: "Node", render: (row) => row.node_id },
              { header: "Metric", render: (row) => row.metric_name },
              { header: "Value", render: (row) => formatNumber(row.metric_value, 2) },
              { header: "Threshold", render: (row) => (row.threshold === null || row.threshold === undefined ? "-" : formatNumber(row.threshold, 2)) },
              { header: "Score", render: (row) => formatRatioPercent(row.anomaly_score, 0) },
              { header: "Description", render: (row) => row.description ?? row.anomaly_type },
            ]}
          />
        )}
      </PanelCard>
    </>
  );
}
