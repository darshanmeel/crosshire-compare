// web/src/sources/SideCard.tsx - one side of the comparison (A or B), or the one table the Profile page
// reads (P), as a card (screens 01, 03, 04, 14, 15): badge, Name and status; the source choice; the
// upload, path or database box; delimiter, header, Rows to read and Advanced; Load; and once loaded a
// foot that says what was read with its first 10 rows a click away. The region is "File A" / "File B"
// / "File" - the e2e runs find the side by it.
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { Button, LinkButton, Pill, SideBadge, type Tone } from "../ui/kit";
import { marks } from "../ui/marks";
import { DatabaseBox } from "./DatabaseBox";
import { useSideForm } from "./formStore";
import { LoadedLine } from "./LoadedLine";
import { changedSinceLoad, loadTime, noteLoadTime, secs } from "./loadTime";
import { PathBox } from "./PathBox";
import { PreviewTable } from "./PreviewTable";
import { RowsToRead, rowsSummary } from "./RowsToRead";
import { SourceChoice } from "./SourceChoice";
import { UploadBox } from "./UploadBox";
import { useSources } from "./useSources";
import { pickOf, type Schema, type SideForm, type SideView, type Tag } from "./types";
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
  if (f.how === "database") return <>Fetch first; Load then reads what was fetched</>;
  if (tag === "A") return <>A file on this machine reads in place from <strong>Path on disk{meta.filepick ? " → Browse…" : ""}</strong></>;
  const kinds = Object.entries(meta.kinds ?? {}).filter(([k]) => k !== "folder").map(([, label]) => label);
  return kinds.length ? <>{kinds.join(", ")} under <strong>Database</strong></> : <>A database table under <strong>Database</strong></>;
}

export function SideCard({ tag, meta, compact = false }: { tag: Tag; meta: Meta; compact?: boolean }) {
  const id = useId();
  const single = tag === "P";
  const otherTag: Tag = tag === "A" ? "B" : "A";
  const qc = useQueryClient();
  const [f, set] = useSideForm(tag);
  const [other] = useSideForm(otherTag);
  const { data: src } = useSources();
  const view = src?.sides?.[tag];
  const pick = pickOf(f);
  const ready = picked(f, view);
  const schema = useQuery({
    queryKey: ["schema", tag, pick, view?.staged, view?.fetched?.at],
    queryFn: () => api.send<Schema>("POST", `/api/sources/${tag}/schema`, pick),
    enabled: ready,
  });
  const cols = ready ? (schema.data?.columns?.map((c) => c.name) ?? []) : [];
  const isCsv = (ready ? (schema.data?.kind ?? "csv") : "csv") === "csv";
  const [said, setSaid] = useState<{ warnings: string[]; error: string }>({ warnings: [], error: "" });
  const [open, setOpen] = useState<Open>(null);
  const [preview, setPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const asked = { ...pick, where: f.where, order_by: f.order_by, desc: f.desc, limit: f.limit, column_names: f.column_names, snapshot: f.snapshot };
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
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["preview", tag] });
    },
    onError: (e) => setSaid({ warnings: [], error: e instanceof ApiError ? e.detail : String(e) }),
  });

  const loaded = !!view?.loaded;
  const took = loadTime(tag, view);
  const [tone, status]: [Tone, string] = load.isPending || uploading ? ["run", "Loading"]
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
  const delimiter = isCsv && f.how !== "database" && <>
    <span className="row">
      <label className="lbl" htmlFor={`${id}-delim`}>Delimiter</label>
      <input id={`${id}-delim`} type="text" className="in tiny" aria-label="Delimiter" maxLength={3} value={f.delimiter}
             onChange={(e) => set({ delimiter: e.target.value })} />
    </span>
    <label className="check"><input type="checkbox" aria-label="First row is a header" checked={f.header}
                                    onChange={(e) => set({ header: e.target.checked })} />First row is a header</label>
  </>;
  const snapshot = (inline: boolean) => (
    <label className="check" title="Reads the rows once, keeps them as a compact Parquet file in the temp folder, and everything after reads that instead of the source again. Recommended for big files.">
      <input type="checkbox" aria-label="Snapshot the rows read to Parquet" checked={f.snapshot}
             onChange={(e) => set({ snapshot: e.target.checked })} />{inline ? "Snapshot to Parquet (read once)" : "Snapshot the rows read to Parquet"}
    </label>
  );
  const loadBtn = (small: boolean) => (
    <Button variant={small ? "default" : "dark"} size={small ? "sm" : "md"} className={small ? "load-again" : undefined}
            disabled={!cols.length || load.isPending} onClick={() => load.mutate()}>
      {load.isPending ? "Reading the rows…" : single ? "Load" : `Load ${tag}`}
    </Button>
  );
  const close = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
  const panels = <>
    {open === "rows" && (
      <div className="card-panel" id={`${id}-rows`} role="group" aria-label="Rows to read" onKeyDown={close}>
        <RowsToRead tag={tag} cols={cols} quickOps={src?.quick_ops ?? []} />
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
        {!dbInline && snapshot(false)}
      </div>
    )}
  </>;
  const newCols = cols.length > 0 && (!loaded || cols.join("\u0000") !== view!.columns.join("\u0000"));
  const dirty = loaded && (newCols || changedSinceLoad(tag, view, askedNow));   // Load comes back to the fore

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
      {f.how === "upload" && <UploadBox tag={tag} meta={meta} staged={view?.staged ?? ""} types={src?.upload_types ?? []} onBusy={setUploading} />}
      {f.how === "path" && <PathBox tag={tag} meta={meta} />}
      {f.how === "database" && <DatabaseBox tag={tag} meta={meta} />}
      {schema.error && <div className="note error">{(schema.error as Error).message}</div>}
      {ready && schema.data?.error && <div className="note error">{schema.data.error}</div>}
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
      {said.error && <div className="note error">{said.error}</div>}
      {said.warnings.map((w, i) => <div key={i} className="note warning">{marks(w)}</div>)}
      {loaded && view && (
        <LoadedLine tag={tag} view={view} box={f.name} otherBox={other.name} otherView={src?.sides?.[otherTag]}
                    preview={preview} onPreview={() => setPreview((p) => !p)} previewId={`${id}-preview`}
                    cols={compact && isCsv && f.how !== "database" ? `delimiter ${f.delimiter} · ${f.header ? "first row is a header" : "no header row"}` : undefined}>
          {compact ? <>{toggles}{loadBtn(true)}</> : !dirty && loadBtn(true)}
        </LoadedLine>
      )}
      {compact && panels}
      {preview && loaded && <div id={`${id}-preview`} className="preview-wrap"><PreviewTable tag={tag} /></div>}
    </section>
  );
}
