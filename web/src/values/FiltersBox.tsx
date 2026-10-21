// web/src/values/FiltersBox.tsx - "Filters at compare" (SPEC §06, kept from the old Rows section):
// which rows take part, on the common names, after types - applied when the run compares, unlike
// Rows to read, which cuts a side as it is read. Owned by the rows page (keys/).
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Icon } from "../ui/icons";
import { Button, CommitInput, ErrorNote, InfoTip } from "../ui/kit";
import { marks } from "../ui/marks";
import { errorText, type FilterRow, type FiltersView } from "../setup/api";
import { useFilters } from "../keys/summary";
import "../keys/keys.css";

export const FILTERS_KEY = ["setup-filters"];
const KEY = FILTERS_KEY;
const BLANK: FilterRow = { "Apply to": "Both", Column: "", Operator: "=", Value: "", Type: "auto" };

/** The filters that take part: a column picked. */
export const activeFilters = (f?: FiltersView) => (f?.rows ?? []).filter((r) => r.Column);

/** The Rows filters: which rows take part, on the common names. Kept on the server for the columns
 *  and names they were typed against; a filter that cannot be read is kept and said. */
export function FiltersBox() {
  const qc = useQueryClient();
  const q = useFilters();
  const [opened, setOpened] = useState(false);       // Add pressed on the one line: the grid shows, even with no column picked yet
  const [put, setPut] = useState<{ pending: boolean; error: unknown }>({ pending: false, error: null });
  const queue = useRef<Promise<void>>(Promise.resolve());
  const f = q.data;
  if (!f) return q.error ? <ErrorNote>{errorText(q.error)}</ErrorNote> : null;
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
  const grid = f.rows.length > 0 && (n > 0 || opened);
  const add = <Button size="sm" icon="plus" onClick={() => {
    // from the one line, a blank row the server holds already is the one to fill
    if (!grid) setOpened(true);
    if (grid || !f.rows.length) save((rows) => [...rows, BLANK]);
  }}>Add a filter</Button>;
  const errors = <>
    {f.error && <ErrorNote>{marks(f.error)}</ErrorNote>}
    {(q.error != null || put.error != null) && <ErrorNote>{errorText(q.error ?? put.error)}</ErrorNote>}
  </>;
  if (!grid) return (                                // none picked yet: one line, the grid after Add
    <div className="panel atcompare empty">
      <div className="panel-head">
        <h3>Filters at compare</h3>
        <span className="sub">No filter - every paired row takes part</span>
        <div className="actions">{add}</div>
      </div>
      {(f.error || q.error != null || put.error != null) && <div className="panel-body">{errors}</div>}
    </div>
  );
  return (
    <div className="panel atcompare">
      <div className="panel-head">
        <h3>Filters at compare</h3>
        <span className="sub">which rows take part</span>
        <InfoTip label="About Filters at compare" text="Which rows take part, on the common names." />
        {n > 0 && <div className="actions"><span className="pill ok"><i />{n} applied</span></div>}
      </div>
      <div className="panel-note">
        <span>{marks("Both sides, after types · exact match")}</span>
        <InfoTip label="About these filters" text="Values match exactly: Ignore case does not apply. To shrink a big file before it is read, use Rows to read above." />
      </div>
      <div className="tblwrap">
        <table className="tbl compact filters-tbl" aria-label="Filters">
          <thead><tr><th>Apply to</th><th>Column</th><th>Operator</th><th>Value</th><th>Type</th><th aria-label="Remove" /></tr></thead>
          <tbody>{f.rows.map((r, i) => (
            <tr key={i}>
              <td>{select(i, "Apply to", f.apply_to)}</td>
              <td>{select(i, "Column", ["", ...f.columns], true)}</td>
              <td>{select(i, "Operator", f.ops)}</td>
              <td><CommitInput className="in mono" aria-label={`Value, filter ${i + 1}`} value={r.Value} title="in / not in: comma separated. between: two values."
                               onDone={(v) => change(i, { Value: v })} /></td>
              <td>{select(i, "Type", f.types)}</td>
              <td><button type="button" className="icon-btn" aria-label={`Remove filter ${i + 1}`}
                          onClick={() => save((rows) => rows.filter((_, j) => j !== i))}><Icon name="x" size="sm" /></button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="panel-body filters-foot">
        <div>{add}</div>
        {errors}
      </div>
    </div>
  );
}
