// web/src/values/FiltersBox.tsx - "Filters at compare" (SPEC §06, kept from the old Rows section):
// which rows take part, on the common names, after types - applied when the run compares, unlike
// Rows to read, which cuts a side as it is read. Owned by the rows page (keys/).
import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Icon } from "../ui/icons";
import { Button } from "../ui/kit";
import { marks } from "../ui/marks";
import { errorText, type FilterRow, type FiltersView } from "../setup/api";
import "../keys/keys.css";

export const FILTERS_KEY = ["setup-filters"];
const KEY = FILTERS_KEY;
const BLANK: FilterRow = { "Apply to": "Both", Column: "", Operator: "=", Value: "", Type: "auto" };

/** The filters that take part: a column picked. */
export const activeFilters = (f?: FiltersView) => (f?.rows ?? []).filter((r) => r.Column);

function ValueCell({ value, label, onDone }: { value: string; label: string; onDone: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [was, setWas] = useState(value);
  if (value !== was) { setWas(value); setDraft(value); }
  return <input type="text" className="in mono" aria-label={label} value={draft} title="in / not in: comma separated. between: two values."
                onChange={(e) => setDraft(e.target.value)} onBlur={() => { if (draft !== value) onDone(draft); }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />;
}

/** The Rows filters: which rows take part, on the common names. Kept on the server for the columns
 *  and names they were typed against; a filter that cannot be read is kept and said. */
export function FiltersBox() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => api.get<FiltersView>("/api/setup/filters") });
  const [put, setPut] = useState<{ pending: boolean; error: unknown }>({ pending: false, error: null });
  const queue = useRef<Promise<void>>(Promise.resolve());
  const f = q.data;
  if (!f) return q.error ? <div className="note error">{errorText(q.error)}</div> : null;
  /** Each change is worked out from the latest filters when its turn comes, and sent with their version: two quick
   *  changes (a typed value, then an Operator) are sent one after the other, never from the same old rows. */
  const save = (next: (rows: FilterRow[]) => FilterRow[]) => {
    queue.current = queue.current.then(async () => {
      const held = qc.getQueryData<FiltersView>(KEY) ?? f;
      setPut({ pending: true, error: null });
      try {
        qc.setQueryData(KEY, await api.send<FiltersView>("PUT", "/api/setup/filters", { rows: next(held.rows), rev: held.rev }));
        setPut({ pending: false, error: null });
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) await qc.invalidateQueries({ queryKey: KEY });   // changed since: shown as it is now
        setPut({ pending: false, error: e });
      }
    });
  };
  const change = (i: number, patch: Partial<FilterRow>) => save((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const select = (i: number, key: keyof FilterRow, options: string[], mono = false) => (
    <select className={mono ? "in mono" : "in"} aria-label={`${key}, filter ${i + 1}`} value={f.rows[i][key]} onChange={(e) => change(i, { [key]: e.target.value })}>
      {options.map((o) => <option key={o} value={o}>{o || "pick…"}</option>)}
    </select>
  );
  const n = activeFilters(f).length;
  return (
    <div className="panel atcompare">
      <div className="panel-head">
        <h3>Filters at compare</h3>
        <span className="sub">Filters - which rows take part, on the common names</span>
        <div className="actions"><span className={`pill ${n ? "ok" : "idle"}`}><i />{n ? `${n} applied` : "none"}</span></div>
      </div>
      <div className="panel-note">
        <span>{marks("Both sides, after types · values match exactly (*Ignore case* does not apply) · to shrink a big file before it is read: **Rows to read** above")}</span>
      </div>
      {f.rows.length > 0 && (
        <div className="tblwrap">
          <table className="tbl compact filters-tbl" aria-label="Filters">
            <thead><tr><th>Apply to</th><th>Column</th><th>Operator</th><th>Value</th><th>Type</th><th aria-label="Remove" /></tr></thead>
            <tbody>{f.rows.map((r, i) => (
              <tr key={i}>
                <td>{select(i, "Apply to", f.apply_to)}</td>
                <td>{select(i, "Column", ["", ...f.columns], true)}</td>
                <td>{select(i, "Operator", f.ops)}</td>
                <td><ValueCell value={r.Value} label={`Value, filter ${i + 1}`} onDone={(v) => change(i, { Value: v })} /></td>
                <td>{select(i, "Type", f.types)}</td>
                <td><button type="button" className="icon-btn" aria-label={`Remove filter ${i + 1}`}
                            onClick={() => save((rows) => rows.filter((_, j) => j !== i))}><Icon name="x" size="sm" /></button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <div className="panel-body filters-foot">
        <div><Button size="sm" icon="plus" onClick={() => save((rows) => [...rows, BLANK])}>Add a filter</Button></div>
        {f.error && <div className="note error">{marks(f.error)}</div>}
        {(q.error != null || put.error != null) && <div className="note error">{errorText(q.error ?? put.error)}</div>}
      </div>
    </div>
  );
}
