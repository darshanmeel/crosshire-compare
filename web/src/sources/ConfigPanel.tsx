// web/src/sources/ConfigPanel.tsx - Run from a saved config (SPEC §17): the Config card (upload or
// path, what it holds), This run (run it, or go to the setup), and the Batch panel (a pairs.csv
// previewed and the command that runs it). POST /api/sources/config loads it all as a job and the
// server compares when both sides opened; App switches to the results when that compare ends.
import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type LogEntry, type Meta } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import { Icon } from "../ui/icons";
import { Button, Dropzone, Panel, Pill, Seg } from "../ui/kit";
import { setView } from "../shell/view";
import { arg, readConf, readPairs, summarise, type ConfSummary, type PairRow } from "./configRead";
import { setForm, takeConfig } from "./formStore";
import { NoteLine } from "./NoteLine";
import { useSources } from "./useSources";
import "./config.css";

/** Once per loaded config (its counter n), its boxes go into both side forms. Mount it where it is
 *  always drawn, so the forms fill even when the config page was left before the load ended. */
export function useConfigSync() {
  const cfg = useSources().data?.config;
  useEffect(() => {
    if (cfg && takeConfig(cfg.n)) { setForm("A", cfg.boxes.A); setForm("B", cfg.boxes.B); }
  }, [cfg?.n]);
}
export function ConfigSync() { useConfigSync(); return null; }

const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/api/meta"), staleTime: Infinity });

type Picked = { text: string; filename: string; sum?: ConfSummary; error?: string };

function Summary({ s }: { s: ConfSummary }) {
  return (
    <div className="card-foot cfg-sum">
      <span><strong>Sources</strong> {s.sources}</span>
      <span><strong>Pairs</strong> {s.pairList}</span>
      <span><strong>Steps</strong> {s.steps}</span>
      <span><strong>Rows</strong> {s.rows}</span>
    </div>
  );
}

function Batch({ config }: { config: string }) {
  const [pairs, setPairs] = useState<{ name: string; rows: PairRow[] } | null>(null);
  const [err, setErr] = useState("");
  const pick = async (f: File) => {
    const r = readPairs(await f.text());
    if (r.error) { setErr(`${f.name}: ${r.error}`); setPairs(null); } else { setErr(""); setPairs({ name: f.name, rows: r.rows! }); }
  };
  const named = pairs?.rows.some((r) => r.name_left || r.name_right);
  const cmd = `python -m tablecmp.run ${arg(config)} --pairs ${arg(pairs?.name ?? "pairs.csv")} --out results`;
  return (
    <section aria-labelledby="cfg-batch">
      <Panel className="cfg-batch"
        title={<span id="cfg-batch">Batch · many pairs, one config</span>}
        sub="a pairs.csv with one line per left / right file - each pair gets its own run folder"
        foot={<>
          <code className="cmd">{cmd}</code>
          <span className="grow" />
          <label className="btn cfg-pick">
            <Icon name="upload" />Load a pairs.csv
            <input type="file" accept=".csv,text/csv" aria-label="Pairs file" onChange={(e) => { const f = e.target.files?.[0]; if (f) pick(f); e.target.value = ""; }} />
          </label>
        </>}>
        {err && <div className="panel-note"><div className="note error">{err}</div></div>}
        {pairs ? (
          <div className="tblwrap">
            <table className="tbl compact" aria-label={`Pairs in ${pairs.name}`}>
              <thead><tr><th>left</th><th>right</th>{named && <><th>name_left</th><th>name_right</th></>}</tr></thead>
              <tbody>
                {pairs.rows.map((r, i) => (
                  <tr key={i}><td className="m">{r.left}</td><td className="m">{r.right}</td>{named && <><td className="m">{r.name_left}</td><td className="m">{r.name_right}</td></>}</tr>
                ))}
                {pairs.rows.length === 0 && <tr><td colSpan={named ? 4 : 2} className="dim">No pairs in the file.</td></tr>}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="panel-note">
            <span>Columns <code>left</code>, <code>right</code> and, if you like, <code>name_left</code>, <code>name_right</code>. Load one to check it here;
            the run itself is the command below.</span>
          </div>
        )}
      </Panel>
    </section>
  );
}

export function ConfigPanel() {
  const qc = useQueryClient();
  const id = useId();
  const meta = useMeta().data;
  const { data: src } = useSources();
  const [how, setHow] = useState<"upload" | "path">("upload");
  const [path, setPath] = useState("");
  const [file, setFile] = useState<Picked | null>(null);
  const [err, setErr] = useState("");
  const [ran, setRan] = useState<"" | "done" | "error">("");
  useConfigSync();

  const start = useMutation({
    mutationFn: (b: { text?: string; path?: string }) => api.send<LogEntry>("POST", "/api/sources/config", b),
    onSuccess: (e) => { setErr(""); setRan(""); follow(e.id); qc.invalidateQueries({ queryKey: ["log"] }); },
    onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)),
  });
  const { follow, busy } = useJobOfKind("Config", "Compare", "", (e) => {
    if (e.state === "error") { setErr(e.lines.at(-1) ?? e.label); setRan("error"); } else setRan("done");
    ["sources", "preview", "db"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  });
  const browse = useMutation({
    mutationFn: () => api.send<{ path: string; file: string }>("POST", "/api/sources/browse", { start: path, folder: "" }),
    onSuccess: (r) => { setErr(""); if (r.path) setPath(r.path); },
    onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)),
  });

  const read = async (f: File) => {
    const text = await f.text();
    const r = readConf(text);
    setFile({ text, filename: f.name, sum: r.conf && summarise(r.conf), error: r.error });
  };
  const ready = how === "upload" ? !!file && !file.error : !!path.trim();
  const working = busy || start.isPending;
  const run = () => start.mutate(how === "upload" ? { text: file!.text } : { path: path.trim().replace(/^"|"$/g, "") });
  const sum = how === "upload" ? file?.sum : undefined;
  const cfgName = how === "upload" ? file?.filename ?? "config.json" : path.trim().replace(/^"|"$/g, "") || "config.json";

  const pill = working ? <Pill tone="run">Loading the config…</Pill>
    : ran === "error" ? <Pill tone="neg">Not loaded</Pill>
    : ran === "done" ? <Pill tone="ok">Loaded</Pill>
    : how === "upload" && file?.error ? <Pill tone="neg">Not a config</Pill>
    : sum ? <Pill tone="ok">Read · {sum.pairs} pair{sum.pairs === 1 ? "" : "s"}{sum.keys.length ? ` · key ${sum.keys.join(", ")}` : ""}</Pill>
    : <Pill tone="idle">{how === "path" && path.trim() ? "Read when it runs" : "Nothing picked"}</Pill>;

  return (
    <div className="cfg">
      <div className="two">
        <section className="card" aria-label="Config">
          <div className="card-head">
            <span className="side-badge k" aria-hidden="true"><Icon name="file" /></span>
            <h3>Config</h3>
            <span className="grow" />
            <span role="status">{pill}</span>
          </div>
          <Seg label="Where the config is" value={how} onChange={(v) => { setHow(v); setRan(""); setErr(""); }}
               options={[{ label: "Upload", value: "upload" }, { label: "Path on disk", value: "path" }]} />
          {how === "upload" ? (
            <>
              <Dropzone accept=".json,application/json" label="Config file" onFile={read}
                        title={file ? <span className="m">{file.filename}</span> : "Drop a config.json here"}
                        hint="the one a run writes (Downloads tab)" />
              {file?.error && <div className="note error">{file.filename}: {file.error}</div>}
            </>
          ) : (
            <div className="row">
              <label className="lbl w" htmlFor={`${id}-path`}>Path</label>
              <input id={`${id}-path`} type="text" className="in mono grow" placeholder="C:\runs\HR_compare_Payroll__config.json"
                     value={path} onChange={(e) => { setPath(e.target.value); setRan(""); }}
                     onKeyDown={(e) => { if (e.key === "Enter" && ready && !working) run(); }} />
              {meta?.filepick && <Button onClick={() => browse.mutate()} disabled={browse.isPending}>{browse.isPending ? "Waiting…" : "Browse…"}</Button>}
            </div>
          )}
          {sum && <Summary s={sum} />}
        </section>

        <section className="card" aria-label="This run">
          <div className="card-head">
            <span className="side-badge k" aria-hidden="true"><Icon name="refresh" /></span>
            <h3>This run</h3>
            <span className="grow" />
            <span className="cfg-sub">reads the files the config names</span>
          </div>
          <p className="cfg-text">Both sides open, the columns, steps, key and rows settings come back as they were, then it compares. Change anything after in the setup.</p>
          <div className="row">
            <Button variant="primary" icon="play" disabled={!ready || working} onClick={run}>{working ? "Loading the config…" : "Run this config"}</Button>
            <Button onClick={() => setView({ view: "setup" })}>Open in the setup instead</Button>
          </div>
          {err && <div className="note error" role="alert">{err}</div>}
          {!working && src?.config?.said.map((n, i) => <NoteLine key={i} note={n} />)}
          <div className="cfg-other">
            <span className="lbl">Other files, same setup</span>
            <code className="cmd">python -m tablecmp.run {arg(cfgName)} --left &lt;file A&gt; --right &lt;file B&gt; --out results</code>
          </div>
        </section>
      </div>
      <Batch config={cfgName} />
    </div>
  );
}
