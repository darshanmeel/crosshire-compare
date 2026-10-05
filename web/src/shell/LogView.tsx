// SPEC §13: the Log as a full-width page section, opened from the header's Log button.
import { useEffect, useRef, useState } from "react";
import type { LogEntry } from "../api/client";
import { Icon } from "../ui/icons";
import { Button, Callout, Pill, num } from "../ui/kit";
import { logText, useClearLog, useLog } from "./LogPanel";
import { setView } from "./view";
import "./log.css";

/** navigator.clipboard where the page may use it (https or localhost), else a hidden textarea and execCommand. */
async function copy(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* not allowed here - try the old way */ }
  try {
    const t = document.createElement("textarea");
    t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
    document.body.appendChild(t); t.select();
    const ok = document.execCommand("copy");
    t.remove();
    return ok;
  } catch { return false; }
}

function Entry({ e }: { e: LogEntry }) {
  return (
    <li className={`entry ${e.state}`}>
      <span className="at">{e.at}</span>
      <span className="kind">{e.kind}</span>
      <span className="l">
        <span className="head">{e.label}
          {e.state === "running" && <Pill tone="run">running</Pill>}
          {e.state === "error" && <Pill tone="neg">error</Pill>}
        </span>
        {e.lines.map((l, i) => <span key={i} className="sub">{l}</span>)}
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
  const entries = data?.entries ?? [];
  const n = entries.length;
  return (
    <section className="sec logview" aria-labelledby="log-title">
      <div className="sec-head">
        <h2 id="log-title" ref={head} tabIndex={-1}>Log</h2>
        <span className="sub">everything this session did, newest first · {num(n)} {n === 1 ? "entry" : "entries"}</span>
        <div className="actions row">
          <span className="copied" role="status">{copied === "yes" ? "Copied" : copied === "no" ? "Could not copy - select the text instead" : ""}</span>
          <Button disabled={n === 0} onClick={async () => setCopied((await copy(logText(entries))) ? "yes" : "no")}>Copy as text</Button>
          <Button disabled={n === 0 || clear.isPending} onClick={() => clear.mutate()}>Clear</Button>
          <Button icon="x" onClick={() => setView({ view: "setup" })}>Close</Button>
        </div>
      </div>
      {error && <div className="note error">{String((error as Error).message)}</div>}
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
