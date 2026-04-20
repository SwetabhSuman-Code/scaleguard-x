import { format, formatDistanceToNow } from "date-fns";

export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export function formatNumber(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "0";
  }

  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits,
  }).format(value);
}

export function formatMs(value: number | null | undefined): string {
  return `${formatNumber(value, 1)} ms`;
}

export function formatPercent(value: number | null | undefined, maximumFractionDigits = 1): string {
  return `${formatNumber(value, maximumFractionDigits)}%`;
}

export function formatRatioPercent(
  value: number | null | undefined,
  maximumFractionDigits = 0,
): string {
  return `${formatNumber((value ?? 0) * 100, maximumFractionDigits)}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "Unknown";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return format(date, "MMM d, HH:mm:ss");
}

export function formatShortTime(value: string | null | undefined): string {
  if (!value) {
    return "--:--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }

  return format(date, "HH:mm:ss");
}

export function ageLabel(value: string | null | undefined): string {
  if (!value) {
    return "unknown";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "unknown";
  }

  return formatDistanceToNow(date, { addSuffix: true });
}

export function actionLabel(action: string): string {
  return action.replaceAll("_", " ");
}

export function severityTone(severity: string): "good" | "warn" | "bad" | "neutral" {
  const normalized = severity.toLowerCase();
  if (["critical", "error", "high", "bad"].includes(normalized)) {
    return "bad";
  }
  if (["warning", "warn", "medium"].includes(normalized)) {
    return "warn";
  }
  if (["ok", "healthy", "operational", "active", "resolved", "info", "low"].includes(normalized)) {
    return "good";
  }
  return "neutral";
}

export function anomalyTone(score: number): "good" | "warn" | "bad" {
  if (score >= 0.8) {
    return "bad";
  }
  if (score >= 0.5) {
    return "warn";
  }
  return "good";
}
