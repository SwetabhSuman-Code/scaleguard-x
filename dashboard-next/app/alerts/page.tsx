"use client";

import { Bell, CircleCheck, Siren } from "lucide-react";
import { useState } from "react";

import { PanelCard } from "@/components/dashboard/panel-card";
import { DataTable } from "@/components/tables/data-table";
import { RefreshBadge } from "@/components/ui/refresh-badge";
import { SectionHeader } from "@/components/ui/section-header";
import { StatCard } from "@/components/ui/stat-card";
import { ErrorState, LoadingBlock } from "@/components/ui/state-blocks";
import { StatusBadge } from "@/components/ui/status-badge";
import { useAlerts } from "@/hooks/use-alerts";
import { cn, formatDateTime, formatNumber, severityTone } from "@/lib/format";

const tabs = ["all", "critical", "warning", "info"] as const;

export default function AlertsPage() {
  const [unresolvedOnly, setUnresolvedOnly] = useState(true);
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("all");
  const alerts = useAlerts({ minutes: 360, unresolvedOnly, limit: 250 });

  const rows = alerts.data ?? [];
  const filteredRows = rows.filter((row) => activeTab === "all" || row.severity.toLowerCase() === activeTab);
  const unresolved = rows.filter((row) => !row.resolved).length;
  const critical = rows.filter((row) => severityTone(row.severity) === "bad").length;

  return (
    <>
      <SectionHeader
        eyebrow="Incident view"
        title="Alerts"
        description="Track unresolved and historical alerts with severity tabs and recent feed context."
        actions={<RefreshBadge isFetching={alerts.isFetching} />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Visible alerts" value={formatNumber(filteredRows.length)} helper={unresolvedOnly ? "unresolved only" : "all alerts"} icon={<Bell className="h-5 w-5" />} tone={filteredRows.length > 0 ? "warn" : "good"} />
        <StatCard label="Unresolved" value={formatNumber(unresolved)} helper="open action items" icon={<Siren className="h-5 w-5" />} tone={unresolved > 0 ? "bad" : "good"} />
        <StatCard label="Critical" value={formatNumber(critical)} helper="high severity rows" icon={<CircleCheck className="h-5 w-5" />} tone={critical > 0 ? "bad" : "good"} />
      </div>

      <div className="panel my-5 rounded-[2rem] p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                className={cn(
                  "rounded-full border px-4 py-2 text-sm font-extrabold capitalize transition",
                  activeTab === tab
                    ? "border-ink bg-ink text-paper"
                    : "border-ink/10 bg-panel text-graphite hover:border-ink/30",
                )}
                onClick={() => setActiveTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-3 text-sm font-extrabold text-graphite">
            <input
              type="checkbox"
              checked={unresolvedOnly}
              onChange={(event) => setUnresolvedOnly(event.target.checked)}
              className="h-4 w-4 accent-ink"
            />
            Unresolved only
          </label>
        </div>
      </div>

      <PanelCard title="Alert feed" eyebrow={`${filteredRows.length} rows`}>
        {alerts.isLoading ? (
          <LoadingBlock label="Loading alerts" />
        ) : alerts.isError ? (
          <ErrorState error={alerts.error} />
        ) : (
          <DataTable
            rows={filteredRows}
            getKey={(row) => row.id}
            emptyTitle="No alerts in this view"
            columns={[
              { header: "Severity", render: (row) => <StatusBadge status={row.severity} /> },
              { header: "Status", render: (row) => <StatusBadge status={row.resolved ? "resolved" : "open"} /> },
              { header: "Raised", render: (row) => formatDateTime(row.raised_at) },
              { header: "Node", render: (row) => row.node_id ?? "global" },
              { header: "Type", render: (row) => row.alert_type },
              { header: "Message", render: (row) => row.message },
            ]}
          />
        )}
      </PanelCard>
    </>
  );
}
