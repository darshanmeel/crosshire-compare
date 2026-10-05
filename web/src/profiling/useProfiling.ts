// web/src/profiling/useProfiling.ts
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FreqBody, HistBody, ProfilingView, SaveDefaults } from "./types";

/** The held profile as the page draws it - it does not depend on the Name. */
export function useProfiling(enabled: boolean) {
  return useQuery({ queryKey: ["profiling"], enabled, queryFn: () => api.get<ProfilingView>("/api/profiling") });
}

/** The file name and save folder the Name gives; the last answer stays while a new one is asked for. */
export function useSaveDefaults(name: string, made: string) {
  return useQuery({ queryKey: ["profiling-defaults", name, made], enabled: !!made, placeholderData: keepPreviousData,
                    queryFn: () => api.get<SaveDefaults>(`/api/profiling/defaults?name=${encodeURIComponent(name)}`) });
}

/** One column's ten most and ten least frequent values - measured already, sent when asked for. */
export function useFreq(column: string | null, made: string) {
  return useQuery({ queryKey: ["profiling-freq", made, column], enabled: !!column,
                    queryFn: () => api.get<FreqBody>(`/api/profiling/freq?column=${encodeURIComponent(column!)}`) });
}

/** One number, date or timestamp column in ten equal bins (GET /api/profiling/hist). */
export function useHist(column: string | null, made: string, enabled = true) {
  return useQuery({ queryKey: ["profiling-hist", made, column], enabled: !!column && enabled,
                    queryFn: () => api.get<HistBody>(`/api/profiling/hist?column=${encodeURIComponent(column!)}&bins=10`) });
}
