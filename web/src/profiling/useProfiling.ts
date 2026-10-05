// web/src/profiling/useProfiling.ts
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CastsBody, FreqBody, HistBody, PartsBody, SpellingBody, ProfilingView, SaveDefaults } from "./types";

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

/** Text columns that could be read as a number, a date or a timestamp - one read of the table. */
export function useCasts(made: string) {
  return useQuery({ queryKey: ["profiling-casts", made], enabled: !!made, staleTime: Infinity,
                    queryFn: () => api.get<CastsBody>("/api/profiling/casts") });
}

/** One column taken apart: digits, years and months, or its first and last `n` characters. */
export function useParts(column: string, made: string, n: number, as = "") {
  return useQuery({ queryKey: ["profiling-parts", made, column, n, as], placeholderData: keepPreviousData,
                    queryFn: () => api.get<PartsBody>(`/api/profiling/parts?column=${encodeURIComponent(column)}&n=${n}${as ? `&as=${as}` : ""}`) });
}

/** A text column's spelling: distinct values, how many once case and outer spaces are ignored. */
export function useSpelling(column: string, made: string, on: boolean) {
  return useQuery({ queryKey: ["profiling-spelling", made, column], enabled: on, staleTime: Infinity,
                    queryFn: () => api.get<SpellingBody>(`/api/profiling/spelling?column=${encodeURIComponent(column)}`) });
}
