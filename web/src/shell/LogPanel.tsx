// The session's Log (GET /api/log): every load, auto, compare, write and profile, newest first.
// useLog() is read by the header count, the rail, the running panel and the job followers; the
// page itself is LogView.tsx.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LogEntry } from "../api/client";

export type LogBody = { entries: LogEntry[]; last: Record<string, LogEntry> };

export function useLog() {
  return useQuery({
    queryKey: ["log"], queryFn: () => api.get<LogBody>("/api/log"),
    refetchInterval: (q) => (q.state.data?.entries?.some((e) => e.state === "running") ? 1000 : false),
  });
}

/** DELETE /api/log; the answer is the emptied Log, put straight into the cache. */
export function useClearLog() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => api.send<LogBody>("DELETE", "/api/log"), onSuccess: (d) => qc.setQueryData(["log"], d) });
}

/** The Log as plain text: one line per entry, its sub-lines indented under it. */
export function logText(entries: LogEntry[]): string {
  return entries.map((e) => [`${e.at}  ${e.kind}  ${e.label}`, ...e.lines.map((l) => `    ${l}`)].join("\n")).join("\n");
}
