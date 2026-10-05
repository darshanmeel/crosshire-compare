// web/src/profiling/FreqSection.tsx - Value frequencies (screen 15): one column at a time, picked
// in the head, its eight most frequent values as bars. The ten most and ten least frequent of any
// column are on its detail page (FreqBars, used there too).
import { Bar, LinkButton, num, Panel } from "../ui/kit";
import { fmt, pct, rowsOf, type Row } from "./frame";
import { openColumn } from "./ColumnsTable";
import { usePicks } from "./picks";
import type { Frame, FreqInfo, Profile } from "./types";
import { useFreq } from "./useProfiling";

/** The ten most and ten least frequent, without showing a value twice: with ten values or fewer
 *  the most frequent are all of them (rest null); with 11 to 19 the least frequent overlap them, so
 *  rest holds only the values not already shown, most to least, carrying on the same ranking. */
export function splitFreq(top: Frame, bottom: Frame): { top: Frame; rest: Frame | null; all: boolean } {
  const v = top.columns.indexOf("Value"), w = bottom.columns.indexOf("Value");
  const seen = new Set(top.rows.map((r) => String(r[v])));
  const rest = bottom.rows.filter((r) => !seen.has(String(r[w])));
  if (!rest.length) return { top, rest: null, all: true };
  if (rest.length === bottom.rows.length) return { top, rest: bottom, all: false };
  return { top, rest: { columns: bottom.columns, rows: [...rest].reverse() }, all: true };
}

/** Values with their count as bars, the longest bar the largest count (or `scale`, to carry one
 *  list's bars on from another's). */
export function FreqBars({ t, numeric, limit, label, scale, tone = "warn" }:
  { t: Frame; numeric: boolean; limit?: number; label: string; scale?: number; tone?: "warn" | "accent" }) {
  const rows: Row[] = rowsOf(t).slice(0, limit);
  const top = scale ?? Math.max(1, ...rows.map((r) => Number(r.Count ?? 0)));
  if (!rows.length) return <p className="caption">No values.</p>;
  return (
    <ul className="kv prof-kv" aria-label={label}>
      {rows.map((r, i) => (
        <li key={i}>
          <span className="m" title={String(r.Value)}>{fmt(r.Value, numeric)}</span>
          <Bar pct={(100 * Number(r.Count ?? 0)) / top} tone={tone} />
          <span className="v">{num(r.Count as number)} <span className="pc">· {pct(r["%"])}</span></span>
        </li>
      ))}
    </ul>
  );
}

/** The column the panel starts on: a picked one kept from before, else the column with the fewest
 *  values past a yes / no (the most telling bars), else the profile's own pick. */
function firstPick(p: Profile, freq: FreqInfo): string[] {
  const few = rowsOf(p.stats).filter((r) => freq.columns.includes(String(r.Column)) && Number(r.Distinct) > 2 && Number(r.Distinct) <= 50)
    .sort((a, b) => Number(a.Distinct) - Number(b.Distinct))[0];
  return few ? [String(few.Column)] : freq.picked.length ? freq.picked.slice(0, 1) : freq.columns.slice(0, 1);
}

export function FreqSection({ p, made }: { p: Profile; made: string }) {
  const freq = p.freq;
  const dflt = firstPick(p, freq);
  const [picked, setPicked] = usePicks(freq.columns, dflt);
  const column = picked[0] ?? dflt[0] ?? null;           // the one picked dropped out: the default again
  const q = useFreq(column, made);
  const st = rowsOf(p.stats).find((r) => r.Column === column);
  return (
    <Panel className="prof-freq" title="Value frequencies"
      sub={st ? `${num(st.Distinct as number)} distinct · all ${num(st.Rows as number)} rows` : undefined}
      actions={freq.columns.length > 0 && (
        <select className="sel type" aria-label="Value frequencies of" value={column ?? ""} onChange={(e) => setPicked([e.target.value])}>
          {freq.columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      )}>
      <div className="panel-body">
        {!column ? <p className="caption">No columns to list.</p>
          : q.error ? <div className="note error">{(q.error as Error).message}</div>
          : !q.data ? <p className="caption">Reading…</p>
          : <FreqBars t={q.data.top} numeric={st?.Type === "number"} limit={8} label={`Most frequent values of ${column}`} />}
        {column && <div><LinkButton iconAfter="arrow" onClick={() => openColumn(column)}>Most and least frequent of {column}</LinkButton></div>}
      </div>
    </Panel>
  );
}
