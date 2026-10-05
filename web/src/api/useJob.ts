// web/src/api/useJob.ts
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLog } from "../shell/LogPanel";
import { api, ApiError, type LogEntry } from "./client";

export const JOB_GONE = "The job is no longer known - check the Log, or start it again.";

const gone = (id: string): LogEntry =>
  ({ id, at: "", kind: "", label: "Could not follow the job", state: "error", seconds: null, lines: [JOB_GONE], page: "" });

/** Follow a job (phase 1's /api/jobs/{id}) until it ends; onEnd runs once with its last state.
 *  A job the server no longer knows (404) ends as an error that says so - it is not polled again. */
export function useJob(id: string | null, onEnd: (e: LogEntry) => void): LogEntry | undefined {
  const qc = useQueryClient();
  const ended = useRef<string | null>(null);
  const q = useQuery({
    queryKey: ["job", id], enabled: !!id, retry: false,
    queryFn: () => api.get<LogEntry>(`/api/jobs/${id}`),
    refetchInterval: (query) => {
      const err = query.state.error;
      if (err instanceof ApiError && err.status === 404) return false;
      return query.state.data?.state === "running" ? 1000 : false;
    },
  });
  const missing = q.error instanceof ApiError && q.error.status === 404;
  const entry = useMemo(() => (missing && id ? gone(id) : q.data), [missing, id, q.data]);
  useEffect(() => {
    if (entry && entry.state !== "running" && ended.current !== entry.id) {
      ended.current = entry.id;
      qc.invalidateQueries({ queryKey: ["log"] });
      onEnd(entry);
    }
  }, [entry]);
  return entry;
}

/** The running job of one kind on one page: the one this mount started, or - after leaving the page
 *  or closing the section - the one the Log says is still running (`slot` tells Fetch A from B). `busy` is true from the start
 *  until the job ends; `running` is its latest entry, for the run disc. */
export function useJobOfKind(kind: string, page: string, slot: string, onEnd: (e: LogEntry) => void) {
  const [mine, setMine] = useState<string | null>(null);
  const log = useLog().data;
  const resumed = log?.entries?.find((e) => e.state === "running" && e.kind === kind && e.page === page && (e.slot ?? "") === slot)?.id ?? null;
  const id = mine ?? resumed;
  const entry = useJob(id, (e) => { setMine(null); onEnd(e); });
  const busy = !!id && (!entry || entry.state === "running");
  return { follow: setMine, busy, running: busy ? entry : undefined };
}
