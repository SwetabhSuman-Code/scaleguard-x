"use client";

import { Clock, RadioTower, ServerCog } from "lucide-react";

import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { StatusBadge } from "@/components/ui/status-badge";
import { useMetricNodes } from "@/hooks/use-metrics";
import { useWorkers } from "@/hooks/use-workers";
import { ageLabel, formatDateTime, formatNumber } from "@/lib/format";

export default function WorkersPage() {
  const workers = useWorkers();
  const nodes = useMetricNodes();
  const rows = workers.data ?? [];
  const activeWorkers = rows.filter((row) => row.status.toLowerCase() === "active").length;
  const recentHeartbeats = rows.filter((row) => {
    const heartbeat = new Date(row.last_heartbeat).getTime();
    return Number.isFinite(heartbeat) && Date.now() - heartbeat < 120_000;
  }).length;

  return (
    <>
      <SectionHeader
        eyebrow="Runtime"
        title="Workers and nodes"
        description="See registered workers, heartbeat recency, and metric-reporting node IDs from the backend registry."
        actions={<RefreshBadge isFetching={workers.isFetching || nodes.isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Registered workers" value={formatNumber(rows.length)} helper="known worker records" icon={<ServerCog className="h-5 w-5" />} tone="neutral" />
        <StatCard label="Active workers" value={formatNumber(activeWorkers)} helper="status is active" icon={<RadioTower className="h-5 w-5" />} tone={activeWorkers > 0 ? "good" : "warn"} />
        <StatCard label="Fresh heartbeats" value={formatNumber(recentHeartbeats)} helper="within the last 2 minutes" icon={<Clock className="h-5 w-5" />} tone={recentHeartbeats === rows.length && rows.length > 0 ? "good" : "warn"} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <PanelCard title="Worker registry" eyebrow={`${rows.length} records`}>
          {workers.isLoading ? (
            <LoadingBlock label="Loading workers" />
          ) : workers.isError ? (
            <ErrorState error={workers.error} />
          ) : (
            <DataTable
              rows={rows}
              getKey={(row) => row.worker_id}
              emptyTitle="No workers registered"
              columns={[
                { header: "Worker", render: (row) => row.worker_id },
                { header: "Status", render: (row) => <StatusBadge status={row.status} /> },
                { header: "Container", render: (row) => row.container_id ?? "-" },
                { header: "Registered", render: (row) => formatDateTime(row.registered_at) },
                { header: "Heartbeat", render: (row) => ageLabel(row.last_heartbeat) },
              ]}
            />
          )}
        </PanelCard>

        <PanelCard title="Reporting nodes" eyebrow="Metrics source IDs">
          {nodes.isLoading ? (
            <LoadingBlock label="Loading nodes" />
          ) : nodes.isError ? (
            <ErrorState error={nodes.error} />
          ) : (
            <div className="flex flex-wrap gap-3">
              {(nodes.data?.nodes ?? []).length === 0 ? (
                <p className="text-sm font-semibold text-graphite/[0.65]">
                  No nodes have reported in the last 5 minutes.
                </p>
              ) : (
                nodes.data?.nodes.map((node) => (
                  <span
                    key={node}
                    className="rounded-full border border-ink/10 bg-ink px-4 py-2 text-sm font-extrabold text-paper"
                  >
                    {node}
                  </span>
                ))
              )}
            </div>
          )}
        </PanelCard>
      </div>
    </>
  );
}
