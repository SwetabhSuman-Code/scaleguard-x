import type { ReactNode } from "react";

import { cn } from "@/lib/format";

export function PanelCard({
  title,
  eyebrow,
  children,
  className,
  action,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={cn("panel rounded-[2rem] p-5", className)}>
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          {eyebrow ? (
            <p className="text-xs font-extrabold uppercase tracking-[0.22em] text-moss/60">
              {eyebrow}
            </p>
          ) : null}
          <h2 className="mt-1 font-display text-2xl font-black tracking-tight text-ink">{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
