// web/src/results/useSummary.ts - the run's Summary, read once and shared by the head and the tab.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Summary } from "./types";

export const useSummary = (runId: string) =>
  useQuery({ queryKey: ["results", runId, "summary"], staleTime: Infinity,
             queryFn: () => api.get<Summary>(`/api/results/${runId}/summary`) });
