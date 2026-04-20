"use client";

import { ArrowDownToLine, ArrowUpFromLine, Repeat2 } from "lucide-react";

import { MetricLineChart } from "@/components/charts/metric-line-chart";
import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { StatusBadge } from "@/components/ui/status-badge";
import { useScalingEvents } from "@/hooks/use-scaling";
import { actionLabel, formatDateTime, formatNumber } from "@/lib/format";

export default function ScalingPage() {
  const scaling = useScalingEvents(100);
  const rows = scaling.data ?? [];
  const scaleUps = rows.filter((row) => row.action === "scale_up").length;
  const scaleDowns = rows.filter((row) => row.action === "scale_down").length;
  const noChange = rows.filter((row) => row.action === "no_change").length;
  const chartData = [...rows].reverse().map((row) => ({
    timestamp: row.triggered_at,
    replicas: row.new_replicas,
    previous: row.prev_replicas,
  }));

  return (
    <>
      <SectionHeader
        eyebrow="Autoscaling"
        title="Scaling history"
        description="Follow autoscaler decisions, replica count changes, and the reasons attached to each action."
        actions={<RefreshBadge isFetching={scaling.isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Scale ups" value={formatNumber(scaleUps)} helper="capacity added" icon={<ArrowUpFromLine className="h-5 w-5" />} tone="good" />
        <StatCard label="Scale downs" value={formatNumber(scaleDowns)} helper="capacity released" icon={<ArrowDownToLine className="h-5 w-5" />} tone="neutral" />
        <StatCard label="No change" value={formatNumber(noChange)} helper="policy held steady" icon={<Repeat2 className="h-5 w-5" />} tone="warn" />
      </div>

      <div className="mt-5">
        <PanelCard title="Replica timeline" eyebrow="Newest events reconstructed">
          {scaling.isLoading ? (
            <LoadingBlock label="Loading scaling events" />
          ) : scaling.isError ? (
            <ErrorState error={scaling.error} />
          ) : (
            <MetricLineChart
              data={chartData}
              series={[
                { dataKey: "replicas", label: "New replicas", color: "#08b7a6" },
                { dataKey: "previous", label: "Previous", color: "#f1a340" },
              ]}
            />
          )}
        </PanelCard>
      </div>

      <div className="mt-5">
        <PanelCard title="Decision log" eyebrow={`${rows.length} events`}>
          {scaling.isLoading ? (
            <LoadingBlock label="Loading decision log" />
          ) : scaling.isError ? (
            <ErrorState error={scaling.error} />
          ) : (
            <DataTable
              rows={rows}
              getKey={(row) => row.id}
              emptyTitle="No autoscaling events yet"
              columns={[
                { header: "Time", render: (row) => formatDateTime(row.triggered_at) },
                { header: "Action", render: (row) => <StatusBadge status={actionLabel(row.action)} /> },
                { header: "Previous", render: (row) => row.prev_replicas },
                { header: "New", render: (row) => row.new_replicas },
                { header: "Reason", render: (row) => row.reason ?? "autoscaler policy" },
              ]}
            />
          )}
        </PanelCard>
      </div>
    </>
  );
}
