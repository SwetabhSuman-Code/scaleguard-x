import type { ReactNode } from "react";

import { cn } from "@/lib/format";

export function StatCard({
  label,
  value,
  helper,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  helper?: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const toneClass = {
    neutral: "bg-graphite/[0.08] text-graphite",
    good: "bg-signal/[0.15] text-ink",
    warn: "bg-amber/[0.18] text-ink",
    bad: "bg-ember/[0.15] text-ink",
  };

  return (
    <article className="panel rounded-[2rem] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-extrabold uppercase tracking-[0.22em] text-graphite/[0.55]">
            {label}
          </p>
          <div className="mt-3 font-display text-4xl font-black tracking-tight text-ink">
            {value}
          </div>
        </div>
        {icon ? (
          <div className={cn("grid h-12 w-12 place-items-center rounded-2xl", toneClass[tone])}>
            {icon}
          </div>
        ) : null}
      </div>
      {helper ? <p className="mt-4 text-sm font-semibold text-graphite/[0.65]">{helper}</p> : null}
    </article>
  );
}
