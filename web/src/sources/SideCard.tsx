// web/src/sources/SideCard.tsx - one side of the comparison (A or B), or the one table the Profile page
// reads (P), as a card (screens 01, 03, 04, 14, 15): badge, Name and status; the source choice; the
// upload, path or database box; delimiter, header, Rows to read and Advanced; Load; and once loaded a
// foot that says what was read with its first 10 rows a click away. The region is "File A" / "File B"
// / "File" - the e2e runs find the side by it.
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText, type Meta } from "../api/client";
import { Button, ErrorNote, LinkButton, Pill, SideBadge, type Tone } from "../ui/kit";
import { marks } from "../ui/marks";
import { DatabaseBox, FetchCap, useDbSide } from "./DatabaseBox";
import { getForm, setForm, useSideForm } from "./formStore";
import { LoadedLine } from "./LoadedLine";
import { boxAfterLoad } from "./names";
import { changedSinceLoad, loadTime, noteLoadTime, pickChangedSinceLoad, secs } from "./loadTime";
import { PathBox } from "./PathBox";
import { PreviewTable } from "./PreviewTable";
import { RowsToRead, rowsSummary } from "./RowsToRead";
import { SetAside } from "./SetAside";
import { SourceChoice } from "./SourceChoice";
import { UploadBox } from "./UploadBox";
import { useSources } from "./useSources";
import { loadBody, pickOf, type BadRows, type Quote, type Schema, type SideForm, type SideView, type Tag } from "./types";
import "./sources.css";

function picked(f: SideForm, view?: SideView): boolean {
  if (f.how === "upload") return !!view?.staged;
  if (f.how === "database") return !!view?.fetched;
  return !!(f.folder ? f.file.trim() : f.path.trim());
}

type Open = "rows" | "advanced" | null;

/** The line beside an empty card's Load button: where else a table can come from. */
function loadHint(tag: Tag, f: SideForm, meta: Meta): ReactNode {
  if (tag === "P") return <>then <strong>Profile</strong> — single-column figures first; combinations only when no column is unique by itself</>;
  if (f.how === "path") return <>Read where it lies, never copied — any size</>;
  if (f.how === "database") return <>Fetches the rows once, then reads them here</>;
  if (tag === "A") return <>A file on this machine reads in place from <strong>Path on disk{meta.filepick ? " → Browse…" : ""}</strong></>;
  const kinds = Object.entries(meta.kinds ?? {}).filter(([k]) => k !== "folder").map(([, label]) => label);
  return kinds.length ? <>{kinds.join(", ")} under <strong>Database</strong></> : <>A database table under <strong>Database</strong></>;
}

/** The compact card's foot: how the file was read, in place of its column names. */
function readSummary(f: SideForm, excel: boolean): string {      // the sheet, range and lines skipped are in the line above
  const head = f.header ? "first row is a header" : "no header row";
  return excel ? head : `delimiter ${f.delimiter} · ${head}`;
}

export function SideCard({ tag, meta, compact = false, extra }: { tag: Tag; meta: Meta; compact?: boolean; extra?: ReactNode }) {
  const id = useId();
  const single = tag === "P";
  const otherTag: Tag = tag === "A" ? "B" : "A";
  const qc = useQueryClient();
  const [f, set] = useSideForm(tag);
  const [other] = useSideForm(otherTag);
  const { data: src } = useSources();
  const view = src?.sides?.[tag];
  const pickNow = JSON.stringify(pickOf(f));
  const [keyPick, setKeyPick] = useState(pickNow);        // the schema is asked 300 ms after the last keystroke
  useEffect(() => { const t = setTimeout(() => setKeyPick(pickNow), 300); return () => clearTimeout(t); }, [pickNow]);
  const ready = picked(f, view);
  const schema = useQuery({
    queryKey: ["schema", tag, keyPick, view?.staged, view?.fetched?.at],
    queryFn: () => api.send<Schema>("POST", `/api/sources/${tag}/schema`, JSON.parse(keyPick)),
    enabled: ready && keyPick === pickNow,                // not for a pick already typed over
    placeholderData: keepPreviousData,
  });
  const peek = ready ? (schema.data?.columns?.map((c) => c.name) ?? []) : [];
  // an Excel column list reads the first rows only and Load the whole sheet: a wider row lower
  // down adds header-less columns (columnN) at the end - then the loaded list is the true one,
  // as long as the card still points at the sheet and range that were loaded
  const wider = schema.data?.kind === "excel" && !!view?.loaded && peek.length > 0 && peek.length < view.columns.length
                && peek.every((c, i) => c === view.columns[i]) && view.columns.slice(peek.length).every((c) => /^column\d+$/.test(c))
                && (view.sheet ?? "") === (f.sheet || schema.data?.sheet || "") && (view.cell_range ?? "") === f.cell_range
                && !!view.stop_at_blank === f.stop_at_blank;
  const cols = wider ? view!.columns : peek;
  const kind = (ready ? schema.data?.kind : undefined) ?? view?.kind ?? "csv";
  const isCsv = kind === "csv";
  const isExcel = kind === "excel";
  const sheets = ready ? (schema.data?.sheets ?? []) : [];
  const hidden = ready ? (schema.data?.hidden ?? []) : [];
  const sheetRead = f.sheet || schema.data?.sheet || sheets[0] || "";
  const [said, setSaid] = useState<{ warnings: string[]; error: string }>({ warnings: [], error: "" });
  const [open, setOpen] = useState<Open>(null);
  const [preview, setPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const asked = loadBody(f);
  const askedNow = JSON.stringify(asked);
  const load = useMutation({
    mutationFn: async () => {
      const t0 = performance.now();
      const r = await api.send<{ side: SideView; warnings: string[] }>("POST", `/api/sources/${tag}/load`, { ...asked, name: f.name });
      if (r.side) noteLoadTime(tag, r.side, (performance.now() - t0) / 1000, askedNow);
      return r;
    },
    onSuccess: (r) => {
      setSaid({ warnings: r.warnings, error: "" });
      if (r.side) {                                       // a box left at Left / Right takes the loaded name
        const box = boxAfterLoad(tag, getForm(tag).name, r.side);
        if (box !== getForm(tag).name) setForm(tag, { name: box });
      }
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["preview", tag] });
      qc.removeQueries({ queryKey: ["values", tag] });      // the value lists were of the side before
    },
    onError: (e) => setSaid({ warnings: [], error: errorText(e) }),
  });
  const loadNow = useRef(() => load.mutate());
  loadNow.current = () => load.mutate();
  const db = useDbSide(tag, f.how === "database", () => loadNow.current());
  const needFetch = f.how === "database" && !db.plan?.held;   // Load fetches first, then reads the fetch

  const loaded = !!view?.loaded;
  const took = loadTime(tag, view);
  const [tone, status]: [Tone, string] = load.isPending || uploading || db.fetching ? ["run", "Loading"]
    : said.error ? ["neg", "Error"]
    : loaded ? ["ok", took != null ? `Loaded · ${secs(took)}` : "Loaded"]
    : ["idle", "Not loaded"];
  const title = single ? "File" : `File ${tag}`;
  const toggle = (o: Exclude<Open, null>) => setOpen((now) => (now === o ? null : o));
  const dbInline = f.how === "database" && !compact;      // the snapshot tick sits in the options row (screen 03)

  const choice = <SourceChoice tag={tag} value={f.how} onChange={(h) => set({ how: h })} />;
  const toggles = <>
    <LinkButton iconAfter="chevron" aria-expanded={open === "rows"} aria-controls={`${id}-rows`} onClick={() => toggle("rows")}
                className={open === "rows" ? "open" : undefined}>Rows to read: {rowsSummary(f)}</LinkButton>
    <LinkButton iconAfter="chevron" aria-expanded={open === "advanced"} aria-controls={`${id}-adv`} onClick={() => toggle("advanced")}
                className={open === "advanced" ? "open" : undefined}>Advanced</LinkButton>
  </>;
  const header = <label className="check"><input type="checkbox" aria-label="First row is a header" checked={f.header}
                                                 onChange={(e) => set({ header: e.target.checked })} />First row is a header</label>;
  // how the file is read, where the delimiter sat: a CSV's delimiter, header and lines to skip; an
  // Excel file's sheet, where the table starts, header and whether it ends at its first empty row
  const delimiter = f.how !== "database" && (isCsv ? <>
    <span className="row">
      <label className="lbl" htmlFor={`${id}-delim`}>Delimiter</label>
      <input id={`${id}-delim`} type="text" className="in tiny" aria-label="Delimiter" maxLength={3} value={f.delimiter}
             onChange={(e) => set({ delimiter: e.target.value })} />
    </span>
    {header}
    <span className="row" title="Lines above the header row - a title or notes - that are not part of the table">
      <label className="lbl" htmlFor={`${id}-skip`}>Skip lines at top</label>
      <input id={`${id}-skip`} type="number" className="in skip" min={0} step={1} inputMode="numeric" value={f.skip_rows}
             onChange={(e) => set({ skip_rows: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} />
    </span>
  </> : isExcel ? <>
    <span className="row">
      <label className="lbl" htmlFor={`${id}-sheet`}>Sheet</label>
      <select id={`${id}-sheet`} className="in sheet" value={sheetRead} onChange={(e) => set({ sheet: e.target.value })}>
        {sheetRead && !sheets.includes(sheetRead) && <option value={sheetRead}>{sheetRead}</option>}
        {sheets.map((n) => <option key={n} value={n}>{hidden.includes(n) ? `${n} (hidden)` : n}</option>)}
      </select>
    </span>
    <span className="row" title="Top-left cell of the header row, or a full range">
      <label className="lbl" htmlFor={`${id}-range`}>Table starts at</label>
      <input id={`${id}-range`} type="text" className="in mono range" placeholder="A1 or B4:H500" maxLength={30}
             spellCheck={false} value={f.cell_range} onChange={(e) => set({ cell_range: e.target.value })} />
    </span>
    {header}
    <label className="check" title="For notes or totals under the table">
      <input type="checkbox" checked={f.stop_at_blank} onChange={(e) => set({ stop_at_blank: e.target.checked })} />Stop at the first empty row
    </label>
  </> : null);
  const snapshot = (inline: boolean) => (
    <label className="check" title="Reads the rows once, keeps them as a compact Parquet file in the temp folder, and everything after reads that instead of the source again. Recommended for big files.">
      <input type="checkbox" aria-label="Snapshot the rows read to Parquet" checked={f.snapshot}
             onChange={(e) => set({ snapshot: e.target.checked })} />{inline ? "Snapshot to Parquet (read once)" : "Snapshot the rows read to Parquet"}
    </label>
  );
  const loadBtn = (small: boolean, again = false) => (
    <Button variant={small || again ? "default" : "dark"} size={small ? "sm" : "md"} className={small ? "load-again" : undefined}
            aria-label={again ? (single ? "Load" : `Load ${tag}`) : undefined}
            disabled={needFetch ? !db.plan?.sql || db.fetching : !cols.length || load.isPending}
            onClick={() => (needFetch ? db.start.mutate() : load.mutate())}>
      {db.fetching ? db.line : load.isPending ? "Reading the rows…" : single ? "Load" : `Load ${tag}`}{again && !db.fetching && !load.isPending && " again"}
    </Button>
  );
  const close = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
  const newCols = cols.length > 0 && (!loaded || cols.join("\u0000") !== view!.columns.join("\u0000"));
  const dirty = loaded && (newCols || changedSinceLoad(tag, view, askedNow));   // Load comes back to the fore
  // the values on offer would be the loaded file's, not this one's (renamed columns differ from the file's by design)
  const stale = (newCols && !f.column_names.trim()) || pickChangedSinceLoad(tag, view, askedNow);
  const panels = <>
    {open === "rows" && (
      <div className="card-panel" id={`${id}-rows`} role="group" aria-label="Rows to read" onKeyDown={close}>
        <RowsToRead tag={tag} cols={cols} quickOps={src?.quick_ops ?? []} stale={stale} />
      </div>
    )}
    {open === "advanced" && (
      <div className="card-panel" id={`${id}-adv`} role="group" aria-label="Advanced" onKeyDown={close}>
        {compact && delimiter && <div className="row spread">{delimiter}</div>}
        <label className="field" title="Use this when the header row is missing names.">
          <span className="lbl">Column names - comma separated, overrides the header row</span>
          <textarea className="in mono" aria-label="Column names" rows={2} placeholder="emp_id, first_name, dept_name, ..."
                    value={f.column_names} onChange={(e) => set({ column_names: e.target.value })} />
        </label>
        {isCsv && f.how !== "database" && (
          <div className="row spread">
            <span className="row">
              <label className="lbl" htmlFor={`${id}-quote`}>Quote character</label>
              <select id={`${id}-quote`} className="in" value={f.quote} onChange={(e) => set({ quote: e.target.value as Quote })}>
                <option value={'"'}>" (double)</option><option value="'">' (single)</option><option value="">none</option>
              </select>
            </span>
            <span className="row" title="A row with fewer or more fields than the header">
              <label className="lbl" htmlFor={`${id}-bad`}>Rows with too few or too many fields</label>
              <select id={`${id}-bad`} className="in" value={f.bad_rows} onChange={(e) => set({ bad_rows: e.target.value as BadRows })}>
                <option value="keep">Keep - missing fields empty, extra ones as extra columns</option>
                <option value="set_aside">Set aside - leave them out and list them</option>
              </select>
            </span>
          </div>
        )}
        {f.how === "database" && <FetchCap tag={tag} db={db} />}
        {!dbInline && snapshot(false)}
        {!compact && loaded && !dirty && <div className="row">{loadBtn(false, true)}</div>}
      </div>
    )}
  </>;

  return (
    <section className={["card", "side-card", compact && "compact"].filter(Boolean).join(" ")} aria-label={title}>
      <div className="card-head">
        <SideBadge side={tag} />
        <label className="lbl" htmlFor={`${id}-name`}>Name</label>
        <input id={`${id}-name`} type="text" className="in name" aria-label="Name" value={f.name}
               title={single ? src?.name_help?.table : src?.name_help?.side} onChange={(e) => set({ name: e.target.value })} />
        {compact && choice}
        <span className="grow" />
        <Pill tone={tone} role="status">{status}</Pill>
      </div>
      {!compact && choice}
      {f.how === "upload" && <UploadBox tag={tag} staged={view?.staged ?? ""} types={src?.upload_types ?? []} onBusy={setUploading}
                                   uploaded={loaded && !view!.is_database && !!view!.staged && view!.label === view!.staged} />}
      {f.how === "path" && <PathBox tag={tag} meta={meta} />}
      {f.how === "database" && <DatabaseBox tag={tag} db={db} />}
      {schema.error && <ErrorNote>{(schema.error as Error).message}</ErrorNote>}
      {ready && schema.data?.error && <ErrorNote>{schema.data.error}</ErrorNote>}
      {newCols && (
        <p className="caption cols-found">{cols.length} columns: {cols.slice(0, 12).join(", ")}{cols.length > 12 ? ` … +${cols.length - 12} more` : ""}</p>
      )}
      {!compact && <>
        <div className="row spread opts">
          {delimiter}
          {dbInline && snapshot(true)}
          <span className="grow" />
          {toggles}
        </div>
        {panels}
        {(!loaded || dirty) && (
          <div className="row load-row">
            {loadBtn(false)}
            <span className="hint">{loaded ? <>The choices above changed since the last Load</> : loadHint(tag, f, meta)}</span>
          </div>
        )}
      </>}
      {said.error && <ErrorNote>{said.error}</ErrorNote>}
      {said.warnings.map((w, i) => <div key={i} className="note warning">{marks(w)}</div>)}
      {loaded && view && (
        <LoadedLine tag={tag} view={view} sheet={isExcel ? sheetRead : ""} box={f.name} otherBox={other.name} otherView={src?.sides?.[otherTag]}
                    preview={preview} onPreview={() => setPreview((p) => !p)} previewId={`${id}-preview`}
                    cols={compact && f.how !== "database" && (isCsv || isExcel) ? readSummary(f, isExcel) : undefined}>
          {compact && <>{toggles}{loadBtn(true)}{extra}</>}
        </LoadedLine>
      )}
      {loaded && view?.set_aside && <SetAside tag={tag} info={view.set_aside} />}
      {compact && panels}
      {preview && loaded && <div id={`${id}-preview`} className="preview-wrap"><PreviewTable tag={tag} /></div>}
    </section>
  );
}
