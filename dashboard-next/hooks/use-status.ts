"use client";

import { useQuery } from "@tanstack/react-query";

import { getHealth, getMetricsSummary, getStatus } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: POLL_INTERVALS.health,
  });
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: getStatus,
    refetchInterval: POLL_INTERVALS.status,
  });
}

export function useMetricsSummary() {
  return useQuery({
    queryKey: ["metrics-summary"],
    queryFn: getMetricsSummary,
    refetchInterval: POLL_INTERVALS.summary,
  });
}
