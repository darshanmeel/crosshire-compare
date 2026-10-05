// web/src/compare/RunningPanel.tsx - SPEC §07: while a Compare, Auto or config job runs, the panel
// at the top of the setup says what it is doing. Built only on what the job reports (its Log entry):
// every line it has said so far is a done task, the newest one is the running task. The job does not
// say how many steps it has, so there is no "of m" and the bar is indeterminate. The API has no
// cancel, so there is no Cancel button.
import { useEffect, useState } from "react";
import type { LogEntry } from "../api/client";
import { useLog } from "../shell/LogPanel";
import { Icon } from "../ui/icons";
import { marks } from "../ui/marks";
import { useCompareNow } from "./useCompare";
import "./running.css";

const KINDS = new Set(["Compare", "Auto", "Config"]);

/** The newest Compare, Auto or config job still running - a Key search or Profile meanwhile is not it. */
export function useRunningJob(): LogEntry | undefined {
  return useLog().data?.entries?.find((e) => e.state === "running" && KINDS.has(e.kind));
}

// When this page first saw each job: the elapsed time counts from here, client-side, and survives the
// panel being drawn again (a view switch) while the job runs.
const firstSeen = new Map<string, number>();

function useElapsed(id: string): number {
  if (!firstSeen.has(id)) firstSeen.set(id, Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [id]);
  return Math.max(0, (now - firstSeen.get(id)!) / 1000);
}

export function RunningPanel() {
  const busy = useCompareNow().data?.busy;
  const job = useRunningJob();
  return busy && job ? <Running job={job} /> : null;
}

/** The running panel for any job: what it said so far as steps, the newest running, and the time.
 *  The Profile page draws it too, titled "Profiling…". */
export function Running({ job, title = "Working it out…" }: { job: LogEntry; title?: string }) {
  const secs = useElapsed(job.id);
  const lines = job.lines;
  const current = lines.length ? lines[lines.length - 1] : job.label;
  return (
    <section className="runbox running run-panel" aria-label="Progress">
      <div className="disc" aria-hidden="true"><Icon name="sparkle" /></div>
      <div className="run-body">
        <div className="run-head">
          <h2>{title}</h2>
          <span className="line run-now" role="status" aria-live="polite">{marks(current)}</span>
          <span className="grow" />
          <span className="line run-meta">
            {lines.length > 0 && <>step {lines.length} · </>}
            <span className="run-secs">{secs.toFixed(1)}s</span>
          </span>
        </div>
        {lines.length === 0 && <div className="run-label">{job.label}</div>}
        <div className="progress indeterminate" aria-hidden="true"><i /></div>
        {lines.length > 0 && (
          <ol className="tasks" aria-label="Steps so far">
            {lines.map((l, i) => {
              const now = i === lines.length - 1;
              return (
                <li key={i} className={now ? "run" : "done"}>
                  <span className="n">{now ? <i /> : <Icon name="check" size="sm" />}</span>
                  <span><span className="run-sr">{now ? "Running: " : "Done: "}</span>{marks(l)}</span>
                  <span className="t">{now ? "running" : ""}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
