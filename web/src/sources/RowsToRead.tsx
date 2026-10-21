// web/src/sources/RowsToRead.tsx - what the card's "Rows to read: …" opens: a quick filter builder,
// the WHERE, the order and the top N, applied as the side is read. The full editor is the Rows view.
import { useEffect, useId } from "react";
import { errorText } from "../api/client";
import { Button, ErrorNote, num } from "../ui/kit";
import { Tips } from "../ui/Tips";
import { useSideForm } from "./formStore";
import type { SideForm, Tag } from "./types";
import { useQuickClause } from "./useQuickClause";

/** The link's text: "all", or what cuts the rows ("filtered · top 1,000"). */
export function rowsSummary(f: SideForm): string {
  const parts = [f.where.trim() && "filtered", f.order_by.length > 0 && `by ${f.order_by.join(", ")}${f.desc ? " desc" : ""}`,
                 f.limit > 0 && `top ${num(f.limit)}`].filter(Boolean);
  return parts.length ? parts.join(" · ") : "all";
}

export function RowsToRead({ tag, cols, quickOps }: { tag: Tag; cols: string[]; quickOps: string[] }) {
  const id = useId();
  const [f, set] = useSideForm(tag);
  const q = useQuickClause(tag, cols);
  useEffect(() => {                 // another file now: its columns are not this one's (kept while none are known)
    const kept = f.order_by.filter((c) => cols.includes(c));
    if (cols.length && kept.length !== f.order_by.length) set({ order_by: kept });
  }, [cols.join("\u0000")]);
  return (
    <div className="rows-to-read">
      <Tips items={f.how === "database"
        ? ["On the fetched rows - to cut at the database, put a WHERE in the SQL", "Values are text: `hire_date >= '2026-07-20'`"]
        : ["As the file is read, on its own column names - :green[how a huge file is made small]", "Values are text: `hire_date >= '2026-07-20'`"]} />
      {cols.length > 0 && (
        <div className="quick">
          <label className="field"><span className="lbl">Column</span>
            <select className="in mono" aria-label="Column" value={q.col} onChange={(e) => q.setCol(e.target.value)}>{cols.map((c) => <option key={c}>{c}</option>)}</select>
          </label>
          <label className="field"><span className="lbl">Condition</span>
            <select className="in" aria-label="Condition" value={q.op} onChange={(e) => q.setOp(e.target.value)}>{quickOps.map((o) => <option key={o}>{o}</option>)}</select>
          </label>
          <label className="field"><span className="lbl">Value</span>
            <input type="text" className="in mono" aria-label="Value" disabled={q.noValue} placeholder="2026-07-20 · Finance · 100"
                   value={q.value} onChange={(e) => q.setValue(e.target.value)} />
          </label>
          <Button size="sm" icon="plus" disabled={q.add.isPending} onClick={() => q.add.mutate()}>Add to filter</Button>
        </div>
      )}
      {q.add.isError && <ErrorNote role="alert">{errorText(q.add.error)}</ErrorNote>}
      <label className="field"><span className="lbl">Filter (WHERE)</span>
        <textarea className="in mono" aria-label="Filter (WHERE)" rows={3} placeholder={"hire_date >= '2026-07-20'\nAND department = 'Finance'"}
                  value={f.where} onChange={(e) => set({ where: e.target.value })} />
      </label>
      <div className="quick">
        <label className="field"><span className="lbl">Order by</span>
          <select multiple className="in mono order" aria-label="Order by" value={f.order_by}
                  onChange={(e) => set({ order_by: Array.from(e.target.selectedOptions, (o) => o.value) })}>
            {cols.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <div className="field">
          <label className="check"><input type="checkbox" aria-label="Descending" disabled={!f.order_by.length}
                                          checked={f.desc} onChange={(e) => set({ desc: e.target.checked })} />Descending</label>
          <label className="lbl" htmlFor={`${id}-top`} title="Taken after the filter and the order, so 'order by date descending, top 100,000' is the latest 100,000 rows.">Top N rows</label>
          <input id={`${id}-top`} type="number" className="in mono cap" aria-label="Top N rows (0 = all)" min={0} max={500_000_000} step={10_000}
                 value={f.limit} onChange={(e) => set({ limit: Math.max(0, Number(e.target.value) || 0) })} />
          <span className="caption">0 reads every row</span>
        </div>
      </div>
    </div>
  );
}
