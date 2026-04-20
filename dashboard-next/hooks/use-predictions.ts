"use client";

import { useQuery } from "@tanstack/react-query";

import { getPredictions } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function usePredictions(limit = 20) {
  return useQuery({
    queryKey: ["predictions", limit],
    queryFn: () => getPredictions(limit),
    refetchInterval: POLL_INTERVALS.predictions,
  });
}
