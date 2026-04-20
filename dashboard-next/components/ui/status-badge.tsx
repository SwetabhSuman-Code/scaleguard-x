import { cn, severityTone } from "@/lib/format";

const toneClass = {
  good: "border-signal/25 bg-signal/[0.12] text-ink",
  warn: "border-amber/[0.35] bg-amber/[0.15] text-ink",
  bad: "border-ember/[0.35] bg-ember/[0.15] text-ink",
  neutral: "border-ink/[0.15] bg-ink/[0.08] text-ink",
};

const dotClass = {
  good: "bg-signal",
  warn: "bg-amber",
  bad: "bg-ember",
  neutral: "bg-graphite/[0.45]",
};

function normalizeStatus(status: string): string {
  if (status.toLowerCase() === "ok") {
    return "healthy";
  }

  return status.replaceAll("_", " ");
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized === "loading" ? "neutral" : severityTone(normalized);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-extrabold uppercase tracking-[0.18em]",
        toneClass[tone],
        className,
      )}
    >
      <span className={cn("h-2 w-2 rounded-full", dotClass[tone])} />
      {normalizeStatus(status)}
    </span>
  );
}
