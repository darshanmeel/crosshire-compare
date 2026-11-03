// web/src/profiling/KeyCombo.tsx - Check a key: any columns picked, checked as a key on every row
// (GET /api/profiling/keycombo) - rows, distinct, duplicate rows, null keys and the most repeated.
// The picks live in the pick store, so a key candidate can load itself here (loadKeyCombo).
import { useState } from "react";
import { errorText } from "../api/client";
import { NONE, usePick } from "../results/pickStore";
import { Button, ErrorNote, Loading, num, Panel, Pill, Seg } from "../ui/kit";
import { Icon } from "../ui/icons";
import { rowsOf } from "./frame";
import { FrameTable } from "./FrameTable";
import type { Profile } from "./types";
import { useKeyCombo } from "./useProfiling";

export const KEY_MAX = 10;
const PICKED = "keycombo-cols", ASKED = "keycombo-asked", NULLS = "keycombo-nulls";
type Nulls = "apart" | "same";

/** The picks and the columns last checked - shared with the key candidates' "check" buttons. */
export function useKeyComboPicks() {
  const [picked, setPicked] = usePick<string[]>(PICKED, NONE);
  const [asked, setAsked] = usePick<string[]>(ASKED, NONE);
  return { picked, setPicked, asked, setAsked, load: (cols: string[]) => { setPicked(cols); setAsked(cols); } };
}

export function KeyCombo({ p, made }: { p: Profile; made: string }) {
  const cols = rowsOf(p.stats).map((r) => String(r.Column));
  const { picked: all, setPicked, asked: was, setAsked } = useKeyComboPicks();
  const picked = all.filter((c) => cols.includes(c));             // a column the new profile lacks drops out
  const asked = was.filter((c) => cols.includes(c));
  const [nulls, setNulls] = usePick<Nulls>(NULLS, "apart");
  const q = useKeyCombo(asked, made, nulls);
  const [next, setNext] = useState("");                          // added by the Add button, not on change: arrow keys fire change
  const left = cols.filter((c) => !picked.includes(c));
  const same = JSON.stringify(picked) === JSON.stringify(asked);  // the result shows only for the columns on the chips
  const r = q.data;
  return (
    <Panel className="kcombo" title="Check a key" sub="any columns, on every row">
      <div className="panel-body">
        <div className="row" role="group" aria-label="Key columns to check">
          {picked.map((c) => (
            <span key={c} className="chip">{c}
              <button type="button" className="chip-x" aria-label={`Remove ${c}`}
                      onClick={() => setPicked(picked.filter((x) => x !== c))}><Icon name="x" size="sm" /></button>
            </span>
          ))}
          {picked.length < KEY_MAX && left.length > 0 && <>
            <select className="in mono" aria-label="Add a column" value={left.includes(next) ? next : ""} onChange={(e) => setNext(e.target.value)}>
              <option value="">Add a column…</option>
              {left.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <Button size="sm" icon="plus" disabled={!left.includes(next)} onClick={() => { setPicked([...picked, next]); setNext(""); }}>Add</Button>
          </>}
          <Seg<Nulls> mini label="Nulls in the key" value={nulls} onChange={setNulls}
               options={[{ value: "apart", label: "Null: each its own key" }, { value: "same", label: "Null = null" }]} />
          <Button size="sm" icon="key" disabled={!picked.length} onClick={() => same ? q.refetch() : setAsked(picked)}>Check</Button>
        </div>
        {asked.length > 0 && same && (q.error ? <ErrorNote>{errorText(q.error)}</ErrorNote>
          : !r ? <Loading>Checking…</Loading>
          : <>
              <p className="kcombo-line" role="status">
                <Pill tone={r.unique ? "ok" : "warn"}>{r.unique ? "Unique" : "Not unique"}</Pill>
                <span>{num(r.rows)} rows · {num(r.distinct)} distinct · {num(r.duplicate_rows)} duplicate rows · {num(r.null_keys)} with a null{nulls === "same" ? ", null = null" : ", each its own key"}</span>
              </p>
              {r.null_keys > 0 && (
                <p className="caption kcombo-cap">
                  Has nulls in {Object.entries(r.nulls_by_column ?? {}).map(([c, n]) => `${c} (${num(n)})`).join(" · ")}
                </p>
              )}
              {r.top.length > 0 && <>
                <p className="caption kcombo-cap">Most repeated</p>
                <FrameTable label="Most repeated" t={{ columns: ["Rows", ...r.columns], rows: r.top.map((t) => [t.n, ...t.values]) }} />
              </>}
            </>)}
      </div>
    </Panel>
  );
}
