"use client";

import { useQuery } from "@tanstack/react-query";

import { getAnomalies } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useAnomalies(params: { minutes?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: ["anomalies", params],
    queryFn: () => getAnomalies(params),
    refetchInterval: POLL_INTERVALS.anomalies,
  });
}
