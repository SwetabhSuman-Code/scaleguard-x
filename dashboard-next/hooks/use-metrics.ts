"use client";

import { useQuery } from "@tanstack/react-query";

import { getMetricNodes, getMetrics } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useMetrics(params: { nodeId?: string; minutes?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: ["metrics", params],
    queryFn: () => getMetrics(params),
    refetchInterval: POLL_INTERVALS.metrics,
  });
}

export function useMetricNodes() {
  return useQuery({
    queryKey: ["metric-nodes"],
    queryFn: getMetricNodes,
    refetchInterval: POLL_INTERVALS.summary,
  });
}
