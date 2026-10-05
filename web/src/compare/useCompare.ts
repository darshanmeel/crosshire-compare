import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { SETUP_KEY } from "../setup/api";
import type { CompareSettings, CompareState } from "./types";

/** Where the comparison stands - polled while a Compare, Auto or config job runs. When one ends
 * every section reads again: Auto and a config change the column table under them. */
export function useCompareNow() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["compare"],
    queryFn: () => api.get<CompareState>("/api/compare"),
    refetchInterval: (query) => (query.state.data?.busy ? 1000 : false),
  });
  const wasBusy = useRef(false);
  const busy = !!q.data?.busy;
  useEffect(() => {
    if (wasBusy.current && !busy) qc.invalidateQueries();
    wasBusy.current = busy;
  }, [busy]);
  return q;
}

/** Any write that lands (a tick, a typed value, a Load, the Name boxes phase 3 PUTs) or a job
 * that ends can make the run stale - so the Compare state is read again after each. */
export function useCompareFreshness() {
  const qc = useQueryClient();
  useEffect(() => {
    const again = () => qc.invalidateQueries({ queryKey: ["compare"] });
    const offMutations = qc.getMutationCache().subscribe((ev) => {
      if (ev.type === "updated" && ev.action.type === "success") again();
    });
    const offQueries = qc.getQueryCache().subscribe((ev) => {
      const key = ev.query.queryKey[0];
      if (ev.type === "updated" && ev.action.type === "success" && (key === "log" || key === SETUP_KEY[0])) again();
    });
    return () => { offMutations(); offQueries(); };
  }, [qc]);
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<CompareSettings>) => api.send<CompareSettings>("PUT", "/api/compare/settings", patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["compare"] }),
  });
}
