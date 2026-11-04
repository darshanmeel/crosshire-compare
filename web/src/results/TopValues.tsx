// web/src/results/TopValues.tsx - a column's values on the Summary's Columns table: per side a strip
// of its top five values, the rest and null as shares of all rows (a histogram for numbers and
// dates), and the detail a row opens - the top ten as bars, every value as a paged table (also
// Profile by bucket's view of a column, on one bucket's rows).
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { errorText } from "../api/client";
import { Loading, num, pctText, Seg } from "../ui/kit";
import { Pager } from "./DistinctValues";
import { Failed } from "./Failed";
import { HIST_KINDS, axisMax, useValues, type Basis, type HistSide, type Side, type Subset, type ValueRow, type ValuesBody } from "./valuesApi";
import "./values.css";

const CLIP = 24;
const TOP = 5;                                         // values the strip names
/** A value's shade by its place: the first five their own, the rest the other values' grey. */
const topCls = (i: number) => (i < TOP ? `r${i + 1}` : "ro");
const clip = (v: string) => (v.length > CLIP ? v.slice(0, CLIP - 1) + "…" : v);
const shown = (v: string | null) => (v == null ? "null" : v === "" ? "empty" : v);
const pct = (part: number, whole: number) => `${pctText(part, whole)}%`;
const dec = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
/** A bin edge or a median: a number with separators, a date or time as it reads. */
const edge = (v: number | string | null | undefined) =>
  v == null ? "-" : typeof v === "number" ? dec.format(v) : String(v).replace("T", " ");

/** One side's top five values, the other values and null, as shares of all rows, and a legend. */
export function StackStrip({ body, i = 0, side, column, name }: { body: ValuesBody; i?: number; side: "a" | "b"; column: string; name: string }) {
  const s = body.sides[i];
  const top = body.rows.filter((r) => r.value != null).slice(0, TOP);
  const used = top.reduce((t, r) => t + r.n[i], 0);
  const other = Math.max(0, s.rows - used - s.nulls), more = s.distinct - top.length;
  const parts = [
    ...top.map((r, k) => ({ cls: topCls(k), n: r.n[i], label: shown(r.value) })),
    { cls: "ro", n: other, label: `${num(more)} more` },
    { cls: "rnull", n: s.nulls, label: "null" },
  ].filter((p) => p.n > 0);
  const said = parts.map((p) => `${p.label} ${pct(p.n, s.rows)}`).join(", ");
  if (!s.rows) return <span className="dim vc-none">no rows</span>;
  if (s.top === 1 && s.distinct > TOP) {        // a key or an id: no value repeats, so no top five to draw
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
            <i className={`vc-seg ${topCls(k)} ${side}`} />{clip(shown(r.value))} <strong>{pct(r.n[i], s.rows)}</strong>
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
  const q = useValues(runId, { column, side, size: TOP, basis: "nonnull", bins: 12 }, seen);
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

/** Each value's place among one side's non-null values, most rows first - the strip's 1st to 5th. */
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
  return <ul className="legend vc-key" aria-label="Top values key">{[item("r1", "1st"), item("r2", "2nd"), item("r3", "3rd"), item("r4", "4th"), item("r5", "5th"), item("ro", "other values"), item("rnull", "null")]}</ul>;
}

/** Every side's top ten values of a column as bars on one axis, and every value as a paged table -
 *  over all rows, or a bucket's rows (`subset`); `sides` narrows it to the one side a set of rows has.
 *  `where` (the bucket) goes into its names, so a bucket's column is told apart from the Summary's. */
export function ValueDetail({ runId, column, names, subset, sides = ["a", "b"], title, where }: {
  runId: string; column: string; names: [string, string]; subset?: Subset; sides?: ("a" | "b")[]; title?: ReactNode; where?: string;
}) {
  const of = where ? `${column} in ${where}` : column;
  const [basis, setBasis] = useState<Basis>("all");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [page, setPage] = useState(1);                 // the all-values table's page
  const side: Side = sides.length > 1 ? "both" : sides[0];
  const q = useValues(runId, { column, subset, side, size: 10, basis });
  const d = q.data;
  const ix = sides.map((_, i) => i);
  const nm = (i: number) => names[sides[i] === "a" ? 0 : 1];
  // the body's own basis: while the other basis loads, the last body stays on screen
  const whole = (i: number) => (d ? d.sides[i].rows - (d.basis === "nonnull" ? d.sides[i].nulls : 0) : 0);
  const share = (r: { n: number[] }, i: number) => (whole(i) ? (100 * r.n[i]) / whole(i) : 0);
  const max = d ? axisMax(Math.max(0, ...d.rows.flatMap((r) => ix.map((i) => share(r, i))))) : 100;
  const last = d?.rows[d.rows.length - 1];
  const ranks = d ? ix.map((i) => sideRanks(d.rows, i)) : [];
  const tone = (r: ValueRow, i: number) => (r.value == null ? "rnull" : topCls(ranks[i].get(r.rank) ?? TOP));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * max);
  const tick = (t: number) => (ticks.every(Number.isInteger) ? `${t}%` : `${t.toFixed(2)}%`);
  const cell = (r: { n: number[] }, i: number) => <>{num(r.n[i])} · <strong>{pct(r.n[i], whole(i))}</strong></>;
  return (
    <div className="vc-detail-body">
      <div className="vc-detail-head">
        <div>
          <h3>{title ?? column}</h3>
          {d && <span className="sub">{ix.map((i) => `${num(d.sides[i].distinct)} distinct in ${nm(i)}`).join(" · ")} · nulls {ix.map((i) => num(d.sides[i].nulls)).join(" / ")}</span>}
        </div>
        <span className="grow" />
        <Seg label={where ? `Percent of for ${of}` : "Percent of"} value={basis} onChange={(b) => { setBasis(b); setPage(1); }}
             options={[{ value: "all", label: "% of all rows" }, { value: "nonnull", label: "% of non-null" }]} />
        <Seg label={where ? `Show values as for ${of}` : "Show values as"} value={view} onChange={setView}
             options={[{ value: "chart", label: "Chart", icon: "bars" }, { value: "table", label: "Table", icon: "table" }]} />
      </div>
      {q.error && <Failed error={q.error} />}
      {!d && !q.error && <Loading>Counting values…</Loading>}
      {d && view === "chart" && (
        <div className="vc-list" role="list" aria-label={`Top values of ${of}`}>
          <div className="vc-row vc-axis" aria-hidden="true">
            <span>Value</span>
            <span className="vc-ticks">{ticks.map((t) => <b key={t} style={{ left: `${(100 * t) / max}%` }}>{tick(t)}</b>)}</span>
            <span className="num">Rows · %</span>
          </div>
          {d.rows.map((r) => (
            <div className="vc-row" role="listitem" key={r.rank}>
              <span className={r.value == null ? "m vc-null" : "m"} title={r.value ?? undefined}>{clip(shown(r.value))}</span>
              <span className="vc-bars">
                {ix.map((i) => (
                  <span key={i} className="vc-share">
                    <i className={`vc-seg ${tone(r, i)} ${sides[i]}`} style={{ width: `${Math.min(100, (100 * share(r, i)) / max)}%` }} />
                  </span>
                ))}
              </span>
              <span className="num vc-nums">{ix.map((i) => <span key={i}><span className={`sw ${sides[i]}`} /><span>{cell(r, i)}</span></span>)}</span>
            </div>
          ))}
        </div>
      )}
      {d && last && view === "chart" && (
        <p className="caption">
          Top {num(d.rows.length)} of {num(d.values)} values cover {ix.map((i) => `${pct(last.cum[i], whole(i))} of ${nm(i)} rows`).join(" and ")}
          {d.basis === "nonnull" ? " with a value" : ""}. Axis scaled to {max}%.
        </p>
      )}
      <AllValues runId={runId} column={column} of={of} subset={subset} sides={sides} names={ix.map(nm)} basis={basis} page={page} setPage={setPage} quiet={!!q.error} />
    </div>
  );
}

const PAGE = 25;

/** Every value of a column with its rows and % on each side, a page at a time, scrolling inside the panel. */
function AllValues({ runId, column, of, subset, sides, names, basis, page, setPage, quiet }: {
  runId: string; column: string; of: string; subset?: Subset; sides: ("a" | "b")[]; names: string[]; basis: Basis;
  page: number; setPage: (p: number) => void; quiet: boolean;
}) {
  const q = useValues(runId, { column, subset, side: sides.length > 1 ? "both" : sides[0], basis, page, size: PAGE });
  const d = q.data;
  const ix = sides.map((_, i) => i);
  const whole = (i: number) => (d ? d.sides[i].rows - (d.basis === "nonnull" ? d.sides[i].nulls : 0) : 0);
  const pages = d ? Math.max(1, Math.ceil(d.values / PAGE)) : 1;
  const from = d ? (d.page - 1) * d.size + 1 : 0;
  if (q.error) return quiet ? null : <Failed error={q.error} />;     // the detail above already said it failed
  if (!d) return <Loading>Counting values…</Loading>;
  return (
    <div className="vc-all">
      <div className="tblwrap vc-all-scroll">
        <table className="tbl compact" aria-label={`Values of ${of}`} aria-busy={q.isFetching}>
          <thead><tr><th>Value</th>{ix.map((i) => <Fragment key={i}><th className="num">{names[i]} rows</th><th className="num">{names[i]} %</th></Fragment>)}</tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.rank}>
              <td className="m vc-val" title={r.value ?? "null"}>{r.value == null ? <em className="vc-null">null</em> : shown(r.value)}</td>
              {ix.map((i) => <Fragment key={i}><td className="num m">{num(r.n[i])}</td><td className="num m">{pct(r.n[i], whole(i))}</td></Fragment>)}
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="vc-all-foot">
        <span>{d.rows.length ? <>Values <strong>{num(from)}–{num(from + d.rows.length - 1)}</strong> of {num(d.values)}</> : "No values."}</span>
        <span className="grow" />
        {pages > 1 && <Pager page={page} pages={pages} setPage={setPage} label={`Pages of ${of}`} />}
      </div>
    </div>
  );
}
