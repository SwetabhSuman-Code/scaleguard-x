"use client";

import { useQuery } from "@tanstack/react-query";

import { getWorkers } from "@/lib/api";
import { POLL_INTERVALS } from "@/lib/constants";

export function useWorkers() {
  return useQuery({
    queryKey: ["workers"],
    queryFn: getWorkers,
    refetchInterval: POLL_INTERVALS.workers,
  });
}
