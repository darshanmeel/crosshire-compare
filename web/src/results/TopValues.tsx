// web/src/results/TopValues.tsx - a column's values on the Summary's Columns table: per side a strip
// of its top three values, the rest and null as shares of all rows (a histogram for numbers and
// dates), and the detail a row opens - every side's top values as bars or a table.
import { useEffect, useRef, useState } from "react";
import { errorText } from "../api/client";
import { Loading, num, pctText, Seg } from "../ui/kit";
import { Failed } from "./Failed";
import { HIST_KINDS, axisMax, rankCls, useValues, type Basis, type HistSide, type ValueRow, type ValuesBody } from "./valuesApi";
import "./values.css";

const CLIP = 24;
const clip = (v: string) => (v.length > CLIP ? v.slice(0, CLIP - 1) + "…" : v);
const shown = (v: string | null) => (v == null ? "null" : v === "" ? "empty" : v);
const pct = (part: number, whole: number) => `${pctText(part, whole)}%`;
const dec = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
/** A bin edge or a median: a number with separators, a date or time as it reads. */
const edge = (v: number | string | null | undefined) =>
  v == null ? "-" : typeof v === "number" ? dec.format(v) : String(v).replace("T", " ");

/** One side's top three values, the other values and null, as shares of all rows, and a legend. */
export function StackStrip({ body, i = 0, side, column, name }: { body: ValuesBody; i?: number; side: "a" | "b"; column: string; name: string }) {
  const s = body.sides[i];
  const top = body.rows.filter((r) => r.value != null).slice(0, 3);
  const used = top.reduce((t, r) => t + r.n[i], 0);
  const other = Math.max(0, s.rows - used - s.nulls), more = s.distinct - top.length;
  const parts = [
    ...top.map((r, k) => ({ cls: rankCls(k), n: r.n[i], label: shown(r.value) })),
    { cls: "ro", n: other, label: `${num(more)} more` },
    { cls: "rnull", n: s.nulls, label: "null" },
  ].filter((p) => p.n > 0);
  const said = parts.map((p) => `${p.label} ${pct(p.n, s.rows)}`).join(", ");
  if (!s.rows) return <span className="dim vc-none">no rows</span>;
  if (s.top === 1 && s.distinct > 3) {          // a key or an id: no value repeats, so no top three to draw
    const line = `every value distinct · ${num(s.distinct)} values${s.nulls ? ` · null ${pct(s.nulls, s.rows)}` : ""}`;
    return (
      <div className="vc-strip">
        <div className={`vc-stack ${side}`} role="img" aria-label={`Top values of ${column} on ${name}: ${line}`}>
          <span className={`vc-seg ro ${side}`} style={{ width: `${(100 * (s.rows - s.nulls)) / s.rows}%` }} />
          {s.nulls > 0 && <span className={`vc-seg rnull ${side}`} style={{ width: `${(100 * s.nulls) / s.rows}%` }} />}
        </div>
        <ul className={`legend vc-legend ${side}`} aria-hidden="true"><li className="dim">{line}</li></ul>
      </div>
    );
  }
  return (
    <div className="vc-strip">
      <div className={`vc-stack ${side}`} role="img" aria-label={`Top values of ${column} on ${name}: ${said}`}>
        {parts.map((p, k) => <span key={k} className={`vc-seg ${p.cls} ${side}`} style={{ width: `${(100 * p.n) / s.rows}%` }} />)}
      </div>
      <ul className={`legend vc-legend ${side}`} aria-hidden="true">
        {top.map((r, k) => (
          <li key={k} title={r.value != null && r.value.length > CLIP ? r.value : undefined}>
            <i className={`vc-seg ${rankCls(k)} ${side}`} />{clip(shown(r.value))} <strong>{pct(r.n[i], s.rows)}</strong>
          </li>
        ))}
        {more > 0 && other > 0 && <li className="dim">+{num(more)} more {pct(other, s.rows)}</li>}
        {s.nulls > 0 && <li className="dim">null {pct(s.nulls, s.rows)}</li>}
      </ul>
    </div>
  );
}

/** A small histogram, with the lowest value, the median and the highest under it. */
export function Histo({ hist, side, column, name }: { hist: HistSide; side: "a" | "b"; column: string; name: string }) {
  const top = Math.max(1, ...hist.bins.map((b) => b.n));
  const lo = hist.bins[0]?.lo, hi = hist.bins[hist.bins.length - 1]?.hi;
  return (
    <div className="vc-strip">
      <div className={`vc-hist ${side}`} role="img" aria-label={`${column} on ${name}: ${edge(lo)} to ${edge(hi)}, median ${edge(hist.median)}`}>
        {hist.bins.map((b, k) => <i key={k} style={{ height: `${Math.max(b.n ? 4 : 0, (100 * b.n) / top)}%` }} title={`${edge(b.lo)} - ${edge(b.hi)}: ${num(b.n)}`} />)}
      </div>
      <div className="vc-hist-axis" aria-hidden="true"><span>{edge(lo)}</span><span>median {edge(hist.median)}</span><span>{edge(hi)}</span></div>
    </div>
  );
}

function SideTop({ runId, column, side, name, seen }: { runId: string; column: string; side: "a" | "b"; name: string; seen: boolean }) {
  const q = useValues(runId, { column, side, size: 3, basis: "nonnull", bins: 12 }, seen);
  const d = q.data;
  const h = d && HIST_KINDS.has(d.kind) ? d.hist.find((x) => x.side === side) : undefined;
  const why = q.error ? `Could not count the values: ${errorText(q.error)}` : "";
  return (
    <div className="vc-side">
      <span className={`sw ${side}`} title={name} />
      {q.error ? <span className="dim" title={why}>-<span className="sr-only">{why}</span></span>
        : !d ? <span className="vc-wait" aria-hidden="true" />
        : h && h.bins.length ? <Histo hist={h} side={side} column={column} name={name} />
        : <StackStrip body={d} side={side} column={column} name={name} />}
    </div>
  );
}

/** True once the element has come near the screen - so a wide pair counts only the columns looked at. */
function useSeen() {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (seen || !ref.current) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); }, { rootMargin: "300px 0px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [seen]);
  return [ref, seen] as const;
}

/** The two sides' top values of one column, A above B - counted when the row comes into view. */
export function TopCell({ runId, column, names }: { runId: string; column: string; names: [string, string] }) {
  const [ref, seen] = useSeen();
  return (
    <div className="vc-cell" ref={ref}>
      <SideTop runId={runId} column={column} side="a" name={names[0]} seen={seen} />
      <SideTop runId={runId} column={column} side="b" name={names[1]} seen={seen} />
    </div>
  );
}

/** Each value's place among one side's non-null values, most rows first - the strip's 1st, 2nd, 3rd. */
function sideRanks(rows: ValueRow[], i: number) {
  const named = rows.filter((r) => r.value != null && r.n[i] > 0);
  named.sort((x, y) => y.n[i] - x.n[i] || (x.value! < y.value! ? -1 : x.value! > y.value! ? 1 : 0));
  return new Map(named.map((r, k) => [r.rank, k]));
}

/** The key over the Columns table: what each shade of the strips means, on A and on B. */
export function RankKey() {
  const item = (cls: string, label: string) => (
    <li key={cls}><i className={`vc-seg ${cls} a`} /><i className={`vc-seg ${cls} b`} />{label}</li>
  );
  return <ul className="legend vc-key" aria-label="Top values key">{[item("r1", "1st"), item("r2", "2nd"), item("r3", "3rd"), item("ro", "other values"), item("rnull", "null")]}</ul>;
}

/** Every side's top ten values of a column, as bars on one axis or as a table. */
export function ValueDetail({ runId, column, names }: { runId: string; column: string; names: [string, string] }) {
  const [basis, setBasis] = useState<Basis>("all");
  const [view, setView] = useState<"chart" | "table">("chart");
  const q = useValues(runId, { column, side: "both", size: 10, basis });
  const d = q.data;
  const [NA, NB] = names;
  // the body's own basis: while the other basis loads, the last body stays on screen
  const whole = (i: number) => (d ? d.sides[i].rows - (d.basis === "nonnull" ? d.sides[i].nulls : 0) : 0);
  const share = (r: { n: number[] }, i: number) => (whole(i) ? (100 * r.n[i]) / whole(i) : 0);
  const max = d ? axisMax(Math.max(0, ...d.rows.flatMap((r) => [share(r, 0), share(r, 1)]))) : 100;
  const last = d?.rows[d.rows.length - 1];
  const ranks = d ? [sideRanks(d.rows, 0), sideRanks(d.rows, 1)] : [];
  const tone = (r: ValueRow, i: number) => (r.value == null ? "rnull" : rankCls(ranks[i].get(r.rank) ?? 3));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const tick = (t: number) => (ticks.every(Number.isInteger) ? `${t}%` : `${t.toFixed(2)}%`);
  const cell = (r: { n: number[] }, i: number) => <>{num(r.n[i])} · <strong>{pct(r.n[i], whole(i))}</strong></>;
  return (
    <div className="vc-detail-body">
      <div className="vc-detail-head">
        <div>
          <h3>{column}</h3>
          {d && <span className="sub">{num(d.sides[0].distinct)} distinct in {NA} · {num(d.sides[1].distinct)} in {NB} · nulls {num(d.sides[0].nulls)} / {num(d.sides[1].nulls)}</span>}
        </div>
        <span className="grow" />
        <Seg label="Percent of" value={basis} onChange={setBasis}
             options={[{ value: "all", label: "% of all rows" }, { value: "nonnull", label: "% of non-null" }]} />
        <Seg label="Show values as" value={view} onChange={setView}
             options={[{ value: "chart", label: "Chart", icon: "bars" }, { value: "table", label: "Table", icon: "table" }]} />
      </div>
      {q.error && <Failed error={q.error} />}
      {!d && !q.error && <Loading>Counting values…</Loading>}
      {d && view === "chart" && (
        <div className="vc-list" role="list" aria-label={`Top values of ${column}`}>
          <div className="vc-row vc-axis" aria-hidden="true">
            <span>Value</span>
            <span className="vc-ticks">{ticks.map((t) => <b key={t} style={{ left: `${(100 * t) / max}%` }}>{tick(t)}</b>)}</span>
            <span className="num">Rows · %</span>
          </div>
          {d.rows.map((r) => (
            <div className="vc-row" role="listitem" key={r.rank}>
              <span className={r.value == null ? "m vc-null" : "m"} title={r.value ?? undefined}>{clip(shown(r.value))}</span>
              <span className="vc-bars">
                {[0, 1].map((i) => (
                  <span key={i} className="vc-share">
                    <i className={`vc-seg ${tone(r, i)} ${"ab"[i]}`} style={{ width: `${Math.min(100, (100 * share(r, i)) / max)}%` }} />
                  </span>
                ))}
              </span>
              <span className="num vc-nums">{[0, 1].map((i) => <span key={i}><span className={`sw ${"ab"[i]}`} /><span>{cell(r, i)}</span></span>)}</span>
            </div>
          ))}
        </div>
      )}
      {d && view === "table" && (
        <div className="tblwrap">
          <table className="tbl compact" aria-label={`Values of ${column}`}>
            <thead><tr><th>Value</th><th className="num">{NA} rows</th><th className="num">{NA} %</th><th className="num">{NB} rows</th><th className="num">{NB} %</th></tr></thead>
            <tbody>{d.rows.map((r) => (
              <tr key={r.rank}>
                <td className="m">{r.value == null ? <em className="vc-null">null</em> : shown(r.value)}</td>
                <td className="num m">{num(r.n[0])}</td><td className="num m">{pct(r.n[0], whole(0))}</td>
                <td className="num m">{num(r.n[1])}</td><td className="num m">{pct(r.n[1], whole(1))}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {d && last && (
        <p className="caption">
          Top {num(d.rows.length)} of {num(d.values)} values cover {pct(last.cum[0], whole(0))} of {NA} rows and {pct(last.cum[1], whole(1))} of {NB} rows
          {d.basis === "nonnull" ? " with a value" : ""}.{view === "chart" && ` Axis scaled to ${max}%.`}
        </p>
      )}
    </div>
  );
}
