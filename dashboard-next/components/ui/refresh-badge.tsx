import { RefreshCw } from "lucide-react";

import { cn } from "@/lib/format";

export function RefreshBadge({
  isFetching,
  label = "Live refresh",
}: {
  isFetching?: boolean;
  label?: string;
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-ink/10 bg-panel/75 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.18em] text-graphite shadow-sm">
      <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin text-signal")} />
      {label}
    </span>
  );
}
