"use client";

import { useQuery } from "@tanstack/react-query";

import { getScalingEvents } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useScalingEvents(limit = 50) {
  return useQuery({
    queryKey: ["scaling-events", limit],
    queryFn: () => getScalingEvents(limit),
    refetchInterval: POLL_INTERVALS.scaling,
  });
}
