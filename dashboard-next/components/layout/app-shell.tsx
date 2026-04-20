"use client";

import {
  Activity,
  AlertTriangle,
  Bell,
  BrainCircuit,
  Gauge,
  LayoutDashboard,
  Menu,
  ServerCog,
  TrendingUp,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";

import { StatusBadge } from "@/components/ui/status-badge";
import { useHealth } from "@/hooks/use-status";
import { cn } from "@/lib/format";

const navItems = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/metrics", label: "Metrics", icon: Activity },
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/predictions", label: "Predictions", icon: BrainCircuit },
  { href: "/scaling", label: "Scaling", icon: TrendingUp },
  { href: "/workers", label: "Workers", icon: ServerCog },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const health = useHealth();
  const healthStatus = health.data?.status ?? (health.isError ? "degraded" : "loading");

  return (
    <div className="min-h-screen">
      <div className="fixed inset-0 -z-10 bg-radial-grid" />
      <button
        className="fixed left-4 top-4 z-40 rounded-full border border-ink/10 bg-panel/90 p-3 shadow-panel backdrop-blur md:hidden"
        onClick={() => setOpen(true)}
        type="button"
        aria-label="Open navigation"
      >
        <Menu className="h-5 w-5" />
      </button>

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-72 border-r border-ink/10 bg-ink text-paper shadow-2xl transition-transform duration-300 md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-full flex-col p-5">
          <div className="flex items-start justify-between gap-3">
            <Link href="/" className="group" onClick={() => setOpen(false)}>
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-2xl bg-signal text-ink shadow-glow">
                  <Gauge className="h-6 w-6" />
                </div>
                <div>
                  <p className="font-display text-2xl font-black leading-none tracking-tight">
                    ScaleGuard
                  </p>
                  <p className="mt-1 text-xs uppercase tracking-[0.28em] text-paper/50">X console</p>
                </div>
              </div>
            </Link>
            <button
              className="rounded-full p-2 text-paper/70 hover:bg-white/10 md:hidden"
              onClick={() => setOpen(false)}
              type="button"
              aria-label="Close navigation"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="mt-8 rounded-3xl border border-white/10 bg-white/[0.07] p-4">
            <div className="text-xs uppercase tracking-[0.24em] text-paper/50">Backend</div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <StatusBadge status={healthStatus} />
              <span className="text-xs text-paper/50">polling /health</span>
            </div>
          </div>

          <nav className="mt-7 flex flex-1 flex-col gap-2">
            {navItems.map((item) => {
              const active = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-bold transition",
                    active
                      ? "bg-paper text-ink shadow-glow"
                      : "text-paper/70 hover:bg-white/10 hover:text-paper",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="rounded-3xl border border-white/10 bg-white/[0.07] p-4 text-sm text-paper/60">
            <p className="font-display text-lg font-bold text-paper">Operational story</p>
            <p className="mt-2">
              FastAPI services feed this live Next.js dashboard with metrics, forecasts, alerts,
              and autoscaling evidence.
            </p>
          </div>
        </div>
      </aside>

      <main className="min-h-screen px-4 py-6 md:ml-72 md:px-8 lg:px-10">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
