// web/src/results/DownloadsTab.tsx - Results · Downloads (SPEC §12): every file of the run in one list
// with what it is, ticked for a download of several, the whole run as one zip, the paired rows and the
// Parquet copies on request, Tables as, saves to a folder, and how to run it again without the page.
import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { useSaveSettings } from "../compare/useCompare";
import { goToSection, setView } from "../shell/view";
import { Icon } from "../ui/icons";
import { Button, num } from "../ui/kit";
import { download, fileUrl, filesKey, size, useRunFiles, type FilesView } from "./detailApi";
import { Failed } from "./Failed";
import { FolderSave } from "./FolderSave";
import "./detail.css";

const FORMATS = [["csv", "CSV"], ["parquet", "Parquet"], ["both", "both"]] as const;
const ZIP_HELP = "Every file of this run in one archive - the paired rows written first when they are not on disk yet - next to the run folder";
const FORMAT_HELP = "Parquet: typed counts, a fraction of the size, straight into DuckDB, pandas or a warehouse. Applies to the next run; COMPARE_TABLE_FORMATS sets the default.";

type Row = { name: string; what: ReactNode; fact?: string; bytes?: number; off?: boolean; action?: ReactNode; pick?: boolean };

/** What each file of a run is, by its suffix - in the order the list shows them. */
function describe(suffix: string, NA: string, NB: string): { what: ReactNode; fact?: string; order: number; pick?: boolean } {
  const parquet = suffix.endsWith(".parquet");
  const base = parquet ? suffix.replace(/\.parquet$/, ".csv") : suffix;
  const known: Record<string, { what: ReactNode; fact?: string; order: number; pick?: boolean }> = {
    "report.html": { what: "Standalone report - the Report tab, as one file", fact: "opens anywhere", order: 0, pick: true },
    "summary.json": { what: "Every figure - counts, per-column match, key, timings, settings", fact: "machine-readable", order: 1, pick: true },
    "summary.csv": { what: "The same summary as a flat table", order: 2 },
    "cell_diffs.csv": { what: `Every differing cell - key, column, ${NA} value, ${NB} value`, order: 3, pick: true },
    "left_only.csv": { what: `Rows with no partner in ${NB}, as read`, order: 5 },
    "right_only.csv": { what: `Rows with no partner in ${NA}, as read`, order: 6 },
    "paired.csv": { what: `Every matched row, ${NA} beside ${NB}`, order: 7 },
    "config.json": { what: "Sources, pairs, steps, key, filters - reruns this exact comparison; never a password or the data", fact: "re-runnable", order: 8, pick: true },
    "columns.csv": { what: "Column metadata for both sides - names, detected types, roles", order: 9 },
    "profile.csv": { what: "Per-column statistics", order: 10 },
    "diff.html": { what: "The engine's own HTML report, as it produces it", fact: "opens anywhere", order: 11 },
  };
  const k = known[base];
  if (parquet) return { what: k ? <>Same as {base}, for DuckDB, pandas or a warehouse</> : "Parquet copy", order: (k?.order ?? 12) + 0.5 };
  return k ?? { what: "", order: 12 };
}

export function DownloadsTab({ run, limit }: { run: RunView; limit: number }) {
  const qc = useQueryClient();
  const f = useRunFiles(run.id, limit);
  const settings = useSaveSettings();
  const put = (d: FilesView) => qc.setQueryData(filesKey(run.id, limit), d);
  const act = useMutation({
    mutationFn: (what: "paired" | "zip" | "parquet") => api.send<FilesView>("POST", `/api/results/${run.id}/${what}`),
    onSuccess: (d, what) => { put(d); if (what === "zip" && d.zip) download(fileUrl(run.id, d.zip.name), d.zip.name); },
  });
  const [picked, setPicked] = useState<Set<string> | null>(null);
  if (f.error) return <div className="rd"><Failed error={f.error} /></div>;
  const d = f.data;
  if (!d) return <div className="rd"><p className="caption">Reading…</p></div>;
  const busy = act.isPending ? act.variables : null;
  const [NA, NB] = run.names;
  const pair = run.pair;
  const suffix = (name: string) => (name.startsWith(`${pair}__`) ? name.slice(pair.length + 2) : name);

  const listed = [...d.files, ...(d.config ? [{ name: d.config.name, label: "Config", bytes: d.config.bytes }] : [])];
  const rows: (Row & { order: number })[] = listed.map((x) => {
    const k = describe(suffix(x.name), NA, NB);
    return { name: x.name, what: k.what || x.label, fact: k.fact, bytes: x.bytes, order: k.order, pick: k.pick };
  });
  if (!d.paired) {
    rows.push({ name: `${pair}__paired.csv`, order: 7, off: true, what: <>Every matched row, {NA} beside {NB} - written when asked for; <em>slower than the comparison was</em> on a wide pair</>,
                action: <Button size="sm" disabled={!!busy} onClick={() => act.mutate("paired")}>{busy === "paired" ? "Writing the paired rows…" : "Write the paired rows"}</Button> });
  }
  if (!listed.some((x) => suffix(x.name) === "profile.csv")) {
    rows.push({ name: `${pair}__profile.csv`, order: 10, off: true, fact: "not in this run",
                what: <>Per-column statistics - only when <em>Profile by bucket</em> or Profile ran</> });
  }
  rows.sort((a, b) => a.order - b.order);
  const ready = rows.filter((r) => !r.off).map((r) => r.name);
  const chosen = picked ?? new Set(rows.filter((r) => r.pick && !r.off).map((r) => r.name));
  const sel = ready.filter((n) => chosen.has(n));
  const toggle = (name: string, on: boolean) => {
    const s = new Set(chosen);
    if (on) s.add(name); else s.delete(name);
    setPicked(s);
  };
  const getSelected = () => sel.forEach((n, i) => setTimeout(() => download(fileUrl(run.id, n), n), i * 250));
  const command = `python -m tablecmp.run ${d.config?.name ?? `${pair}__config.json`} \\\n  --left <new ${NA} file> --right <new ${NB} file> --out results`;

  return (
    <div className="rd">
      <div className="toolbar rd-dl-bar">
        <FolderSave runId={run.id} what="all" field="Run folder" label="Save everything to folder" folder={d.save_folder} onSaved={put} />
        <Button disabled={sel.length === 0} onClick={getSelected}>Download selected · {num(sel.length)}</Button>
        {d.zip
          ? <a className="btn primary" href={fileUrl(run.id, d.zip.name)} download><Icon name="zip" />Download {d.zip.name} · {size(d.zip.bytes)}</a>
          : <Button variant="primary" icon="zip" title={ZIP_HELP} disabled={!!busy} onClick={() => act.mutate("zip")}>
              {busy === "zip" ? (d.paired ? "Zipping the run folder…" : "Writing the paired rows and zipping…") : "Everything as one zip"}
            </Button>}
      </div>
      {act.error && <Failed error={act.error} />}

      <section className="panel" aria-label="Files in this run">
        <div className="panel-head">
          <h3>Files in this run</h3>
          <span className="sub">{num(ready.length)} on disk · complete results, not just the rows displayed · tick what you want, or take the zip</span>
        </div>
        <ul className="files rd-files">
          {rows.map((r) => (
            <li key={r.name} className={r.off ? "off" : undefined}>
              <input type="checkbox" aria-label={`Select ${r.name}`} disabled={r.off} checked={!r.off && chosen.has(r.name)}
                     onChange={(e) => toggle(r.name, e.target.checked)} />
              <span className="f">
                <Icon name="file" size="sm" />
                {r.off ? <span>{r.name}</span> : <a href={fileUrl(run.id, r.name)} download>{r.name}</a>}
              </span>
              <span className="d">{r.what}</span>
              <span className="r">{r.action ?? [r.fact, r.bytes != null ? size(r.bytes) : ""].filter(Boolean).join(" · ")}</span>
            </li>
          ))}
        </ul>
        <div className="panel-foot">
          <div className="rd-formats" role="radiogroup" aria-label="Tables as" title={FORMAT_HELP}>
            <span className="lbl">Tables as</span>
            {FORMATS.map(([v, text]) => (
              <label key={v} className="check">
                <input type="radio" name={`out_fmt_${run.id}`} checked={d.out_fmt === v}
                       onChange={() => settings.mutate({ out_fmt: v }, {
                         onSuccess: () => qc.invalidateQueries({ queryKey: ["results", run.id, "files"] }),
                       })} />
                {text}
              </label>
            ))}
          </div>
          <span className="caption">applies to the next run</span>
          <span className="grow" />
          {d.out_fmt !== "csv" && !d.parquet && (
            <Button size="sm" disabled={!!busy} onClick={() => act.mutate("parquet")}>
              {busy === "parquet" ? "Writing Parquet…" : "Write Parquet copies for this run"}
            </Button>
          )}
        </div>
      </section>

      <div className="two">
        <div className="callout rd-callout">
          <div className="rd-col">
            <strong>Run it again without the UI</strong>
            <span>The config file reproduces this comparison headless - in CI, on a schedule, or for a batch of pairs with <code>--pairs pairs.csv</code>.</span>
            <pre className="rd-cmd"><code>{command}</code></pre>
            {d.config && (
              <>
                <span className="row">
                  <a className="btn sm" href={fileUrl(run.id, d.config.name)} download><Icon name="download" />Download config</a>
                </span>
                <FolderSave runId={run.id} what="config" field="Config to" label="Save config to folder" folder={d.save_folder} />
              </>
            )}
          </div>
        </div>
        <div className="callout rd-callout">
          <div className="rd-col">
            <strong>Keep the setup, not the data</strong>
            <span>Save mapping under Columns stores just the pairs and steps - load it next month against the new files and press Compare.</span>
            <span className="row">
              <Button size="sm" onClick={() => goToSection("columns")}>Save mapping</Button>
              <Button size="sm" onClick={() => setView({ view: "config" })}>Run from config</Button>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
