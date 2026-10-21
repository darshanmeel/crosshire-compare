// SPEC §13: the Log as a full-width page section, opened from the header's Log button.
import { useEffect, useRef, useState } from "react";
import type { LogEntry } from "../api/client";
import { copyText } from "../ui/copy";
import { Icon } from "../ui/icons";
import { Button, Callout, ErrorNote, num, Pill, plural } from "../ui/kit";
import { marks } from "../ui/marks";
import { logText, useClearLog, useLog } from "./LogPanel";
import { toggleLog } from "./view";
import "./log.css";

/** One entry: its headline in bold, then its lines. A job's lines are its progress trace, folded
 *  behind "n steps" once it has finished well; a note's lines (no time) are what it says, shown. */
function Entry({ e }: { e: LogEntry }) {
  const job = e.seconds != null || e.state === "running";
  const lines = e.lines.map((l, i) => <span key={i} className="sub">{marks(l)}</span>);
  return (
    <li className={`entry ${e.state}`}>
      <span className="at">{e.at}</span>
      <span className="kind">{e.kind}</span>
      <span className="l">
        <span className="head"><strong>{marks(e.label)}</strong>
          {e.state === "running" && <Pill tone="run">running</Pill>}
          {e.state === "error" && <Pill tone="neg">error</Pill>}
        </span>
        {job && lines.length > 0
          ? <details className="trace" open={e.state !== "done"}><summary>{plural(lines.length, "step")}<Icon name="chevron" size="sm" /></summary>{lines}</details>
          : lines}
      </span>
    </li>
  );
}

export function LogView() {
  const { data, error } = useLog();
  const clear = useClearLog();
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const head = useRef<HTMLHeadingElement>(null);
  useEffect(() => { head.current?.focus(); }, []);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(""), 2000); return () => clearTimeout(t); }, [copied]);
  const entries = [...(data?.entries ?? [])].reverse();     // the session's story in order: newest last
  const n = entries.length;
  return (
    <section className="sec logview" aria-labelledby="log-title">
      <div className="sec-head">
        <h2 id="log-title" ref={head} tabIndex={-1}>Log</h2>
        <span className="sub">everything this session did, newest last · {num(n)} {n === 1 ? "entry" : "entries"}</span>
        <div className="actions">
          <div className="row">
            <Button disabled={n === 0} onClick={async () => setCopied((await copyText(logText(entries))) ? "yes" : "no")}>Copy as text</Button>
            <Button disabled={n === 0 || clear.isPending} onClick={() => clear.mutate()}>Clear</Button>
            <Button icon="x" onClick={toggleLog}>Close</Button>
          </div>
          <span className="copied" role="status">{copied === "yes" ? "Copied" : copied === "no" ? "Could not copy - select the text instead" : ""}</span>
        </div>
      </div>
      {error && <ErrorNote>{String((error as Error).message)}</ErrorNote>}
      {n === 0
        ? <div className="panel log-empty">Nothing yet - every load, compare, write and profile lands here.</div>
        : <ol className="panel log" aria-label="Log entries">{entries.map((e) => <Entry key={e.id} e={e} />)}</ol>}
      <Callout icon="file">
        Entries stay for this session. Each compare also keeps its complete setup in the run folder's <code>config.json</code>, so any
        run here can be repeated: <code>python -m tablecmp.run config.json --out results</code>.
      </Callout>
    </section>
  );
}
