import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { SETUP_KEY } from "../setup/api";
import { getView, setView } from "../shell/view";
import { startedQuietly } from "./actions";
import type { CompareSettings, CompareState } from "./types";

/** Where the comparison stands - polled while a Compare, Auto or config job runs. */
export function useCompareNow() {
  return useQuery({
    queryKey: ["compare"],
    queryFn: () => api.get<CompareState>("/api/compare"),
    refetchInterval: (query) => (query.state.data?.busy ? 1000 : false),
  });
}

/** Any write that lands (a tick, a typed value, a Load, the Name boxes phase 3 PUTs) or a job
 * that ends can make the run stale - so the Compare state is read again after each.
 * When a Compare, Auto or config run ends - seen busy, or a new run id that came in while not busy
 * (a fast run on small files) - every section reads again: Auto and a config change the column table
 * under them. A run that ends with a result opens the results, unless the person is in an editor or
 * reading the results, or the run was a re-run on every change. Only App mounts this. */
export function useCompareFreshness() {
  const qc = useQueryClient();
  const st = useCompareNow().data;
  const seen = useRef<{ busy: boolean; run: string | null } | null>(null);
  useEffect(() => {
    if (!st) return;
    const was = seen.current, run = st.run?.id ?? null;
    seen.current = { busy: st.busy, run };
    if (!was || st.busy || !(was.busy || (run && run !== was.run))) return;
    qc.invalidateQueries();
    const { view } = getView();
    if (run && (view === "config" || (view === "setup" && !startedQuietly()))) setView({ view: "results", tab: "summary" });
  }, [st?.busy, st?.run?.id]);
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
