export const TIME_RANGES = [
  { label: "15m", value: 15 },
  { label: "30m", value: 30 },
  { label: "60m", value: 60 },
  { label: "6h", value: 360 },
] as const;

export const POLL_INTERVALS = {
  health: 5_000,
  status: 5_000,
  summary: 5_000,
  metrics: 10_000,
  alerts: 10_000,
  anomalies: 10_000,
  scaling: 15_000,
  predictions: 15_000,
  workers: 15_000,
} as const;
