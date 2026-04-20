"use client";

import { useQuery } from "@tanstack/react-query";

import { getAlerts } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useAlerts(
  params: { minutes?: number; unresolvedOnly?: boolean; limit?: number } = {},
) {
  return useQuery({
    queryKey: ["alerts", params],
    queryFn: () => getAlerts(params),
    refetchInterval: POLL_INTERVALS.alerts,
  });
}
