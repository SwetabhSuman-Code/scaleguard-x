import { AlertTriangle, DatabaseZap } from "lucide-react";

export function LoadingBlock({ label = "Loading data" }: { label?: string }) {
  return (
    <div className="panel grid min-h-48 place-items-center rounded-[2rem] p-8 text-center">
      <div>
        <div className="mx-auto h-12 w-12 animate-pulse rounded-2xl bg-signal/25" />
        <p className="mt-4 text-sm font-extrabold uppercase tracking-[0.2em] text-graphite/60">
          {label}
        </p>
      </div>
    </div>
  );
}

export function EmptyState({
  title = "No data yet",
  message = "Start the backend stack or generate traffic to populate this view.",
}: {
  title?: string;
  message?: string;
}) {
  return (
    <div className="rounded-[2rem] border border-dashed border-ink/20 bg-panel/[0.55] p-8 text-center">
      <DatabaseZap className="mx-auto h-10 w-10 text-graphite/40" />
      <p className="mt-4 font-display text-2xl font-bold text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm font-semibold leading-6 text-graphite/[0.65]">
        {message}
      </p>
    </div>
  );
}

export function ErrorState({
  title = "Could not load data",
  error,
}: {
  title?: string;
  error?: unknown;
}) {
  const message = error instanceof Error ? error.message : "The API did not return usable data.";

  return (
    <div className="rounded-[2rem] border border-ember/30 bg-ember/10 p-6">
      <div className="flex gap-3">
        <AlertTriangle className="mt-1 h-5 w-5 shrink-0 text-ember" />
        <div>
          <p className="font-display text-xl font-bold text-ink">{title}</p>
          <p className="mt-2 text-sm font-semibold leading-6 text-graphite/70">{message}</p>
        </div>
      </div>
    </div>
  );
}
