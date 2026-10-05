// web/src/profiling/ColumnDetail.tsx - one column of the profile (screen 16): back to all columns,
// previous / next, its statistics, its distribution (GET /api/profiling/hist), outliers, shapes,
// most and least frequent values and what determines it - all from the profile held.
import { Bar, Button, Chip, num, Panel, Seg } from "../ui/kit";
import { useState, type ReactNode } from "react";
import { setView } from "../shell/view";
import { castsOf, castType } from "./casts";
import { openColumn } from "./ColumnsTable";
import { SHOWN, strongest, TOP } from "./DepMatrix";
import { fmt, keyColumns, pct, rowsOf, statsOf, type Row } from "./frame";
import { FreqBars, splitFreq } from "./FreqSection";
import type { CastRow, Frame, HistBin, Profile } from "./types";
import { useCasts, useFreq, useHist, useParts, useSpelling } from "./useProfiling";
import { semantic } from "./column/Findings";
import { FlagView, useFlagForm } from "./column/FlagView";
import { KeyView } from "./column/KeyView";
import { NumberView, useNumberFormText } from "./column/NumberView";
import type { ColumnViewProps } from "./column/types";
import { TextView, textForm } from "./column/TextView";
import { WhenView } from "./column/WhenView";
import "./profiling.css";

const NEAR_KEY = 10;     // distinct % of rows from which a column is a near-key: it decides others by that alone
const READS_AS = 0.9;    // of the filled values: a column that reads as a date or a timestamp from this share

const C = ({ children }: { children: string }) => <code>{children}</code>;

export function Distribution({ column, kind, made }: { column: string; kind: string; made: string }) {
  const q = useHist(column, made);
  const isNum = kind === "number";
  const edge = (v: number | string) => (isNum ? fmt(Math.round(Number(v))) : String(v));
  let body;
  if (q.error) body = <div className="note error">{(q.error as Error).message}</div>;
  else if (!q.data) body = <p className="caption">Counting…</p>;
  else if (!q.data.bins.length) body = <p className="caption">No values to bin.</p>;
  else {
    const bins = q.data.bins;
    const span = isNum ? Math.abs(Number(bins[bins.length - 1].hi) - Number(bins[0].lo)) : 0;
    const whole = (v: number | string) => (span >= 100 ? fmt(Math.round(Number(v))) : fmt(v));
    const range = (b: HistBin) => (isNum ? `${whole(b.lo)} – ${whole(b.hi)}` : `${b.lo} – ${b.hi}`);
    const total = bins.reduce((s, b) => s + b.n, 0) || 1;
    const top = Math.max(1, ...bins.map((b) => b.n));
    const low = Math.min(...bins.map((b) => b.n));
    const empty = bins.filter((b) => b.n === 0).length;
    const half = Math.ceil(bins.length / 2);
    const ticks = bins.length > 1 ? [...bins.filter((_, i) => i % 2 === 0).map((b) => b.lo), bins[bins.length - 1].hi] : [bins[0].lo];
    const shape = empty ? `${empty} empty bin${empty > 1 ? "s" : ""} - the values leave a gap.`
      : bins.length > 1 && top <= low * 1.25 ? "Flat across the range - no cluster, no gap."
      : bins.length > 1 && top >= low * 4 ? `Clustered - the fullest bin holds ${num(top)} rows, the emptiest ${num(low)}.`
      : null;
    const cell = (b?: HistBin) => b
      ? <><td className="m">{range(b)}</td><td className="num m">{num(b.n)}</td><td className="num m dim">{((100 * b.n) / total).toFixed(1)}%</td></>
      : <><td /><td /><td /></>;
    body = (
      <>
        <div className="hist" role="img" aria-label={`Histogram of ${column}: ${bins.map((b) => `${range(b)} ${num(b.n)}`).join(", ")}`}>
          {bins.map((b, i) => <i key={i} style={{ height: `${(100 * b.n) / top}%` }} title={`${range(b)}: ${num(b.n)}`} />)}
        </div>
        <div className="hist-x">{ticks.map((t, i) => <span key={i}>{edge(t)}</span>)}</div>
        <div className="tblwrap">
          <table className="tbl compact prof-bins" aria-label={`Bins of ${column}`}>
            <thead><tr><th>Bin</th><th className="num">Rows</th><th className="num">Share</th><th className="b2">Bin</th><th className="num">Rows</th><th className="num">Share</th></tr></thead>
            <tbody>{bins.slice(0, half).map((b, i) => <tr key={i}>{cell(b)}{cell(bins[half + i])}</tr>)}</tbody>
          </table>
        </div>
        {shape && <p className="prof-said">{shape}</p>}
      </>
    );
  }
  return <Panel title="Distribution" sub="10 equal bins · rows per bin"><div className="panel-body">{body}</div></Panel>;
}

export type Point = { label: string; value: ReactNode; note?: ReactNode; tone?: "ok" | "warn" | "info" };

/** Findings as short points: a dot for the tone, what it is, the figure, one line on what it means. */
export function Points({ name, items, plain }: { name: string; items: Point[]; plain?: boolean }) {
  return (
    <ul className={plain ? "prof-points plain" : "prof-points"} aria-label={name}>
      {items.map((it) => (
        <li key={it.label} className={it.tone ?? "info"}>
          <span className="dot" aria-hidden="true" />
          <span className="l">{it.label}</span>
          <span className="v">{it.value}</span>
          {it.note && <span className="n">{it.note}</span>}
        </li>
      ))}
    </ul>
  );
}

export const toNum = (v: unknown) => (v == null || v === "" ? NaN : Number(v));
/** Digits before the point, ignoring the sign. */
const intDigits = (x: number) => String(Math.floor(Math.abs(x))).length;
export const share = (n: number, of: number) => (of > 0 ? (100 * n) / of : 0);

/** A shape read out: AA999 → "2 letters · 3 digits"; digit runs split by one mark read as one,
 *  99:99:99 → "2:2:2 digits"; a space and a point are said, any other mark shown as itself. */
export function readShape(p: string) {
  const runs = p.match(/A+|9+|\s+|[^A9\s]+/g) ?? [];
  const out: string[] = [];
  for (let i = 0; i < runs.length; i++) {
    const r = runs[i];
    if (r[0] === "9") {
      const lens = [r.length];
      let mark = "";
      while (/^[^A9\s.]$/.test(runs[i + 1] ?? "") && (!mark || runs[i + 1] === mark) && runs[i + 2]?.[0] === "9") {
        mark = runs[i + 1]; lens.push(runs[i + 2].length); i += 2;
      }
      out.push(lens.length > 1 ? `${lens.join(mark)} digits` : `${r.length} digit${r.length > 1 ? "s" : ""}`);
    } else out.push(r[0] === "A" ? `${r.length} letter${r.length > 1 ? "s" : ""}`
      : /^\s+$/.test(r) ? "space" : r === "." ? "point" : r);
  }
  return out.join(" · ");
}

/** Whole numbers that are (nearly) all different or very long read as a code, where a spread means nothing. */
function isCode(o: Row, st: Row) {
  const xs = [o.Lowest, o.Highest].map(toNum);
  if (xs.some((x) => Number.isNaN(x) || !Number.isInteger(x))) return false;
  return Number(st["Distinct % of filled"] ?? 0) >= 95 || intDigits(Math.max(...xs.map(Math.abs))) >= 9;
}

export function Outliers({ o, kind, filled, st, made }: { o?: Row; kind: string; filled: number; st: Row; made: string }) {
  const isNum = kind === "number";
  const cast = useCasts(made).data?.columns?.find((x) => x.column === st.Column);
  const when = cast && ([cast.timestamp && "timestamp", cast.date && "date"] as const)
    .find((k) => k && cast[k]!.any >= 0.9 * cast.filled);
  if (!o) return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      <p className="caption">Outliers are looked for in number, date and timestamp columns.</p>
    </div></Panel>
  );
  if (isNum && when) return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      <Points name="Outlier findings" items={[
        { label: `Reads as a ${when}`, value: <>{fmt(o.Lowest, true)} … {fmt(o.Highest, true)}</>,
          note: `the digits of a ${when} - a fence on them means nothing; see Parts` }]} />
    </div></Panel>
  );
  if (isNum && isCode(o, st)) return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      <Points name="Outlier findings" items={[
        { label: "Reads like a code", value: <>{fmt(o.Lowest, true)} … {fmt(o.Highest, true)}</>,
          note: "whole numbers, nearly all different - an id, not a measure, so no fence" }]} />
    </div></Panel>
  );
  const n = Number(o.Outliers ?? 0);
  const op = Number(o["Outlier %"] ?? 0);
  const [lo, hi, low, high, q1, q3, p99] = [o["Low fence"], o["High fence"], o.Lowest, o.Highest, o.P25, o.P75, o.P99].map(toNum);
  const iqr = q3 - q1;
  const below = isNum ? low < lo : String(o.Lowest) < String(o["Low fence"]);
  const above = isNum ? high > hi : String(o.Highest) > String(o["High fence"]);
  const side = n === 0 ? "" : below && above ? "on both sides" : above ? "all on the high side" : "all on the low side";
  const items: Point[] = [
    { label: "Outside the fence", tone: n ? "warn" : "ok",
      value: n ? <Bar pct={op} tone="warn" label={<>{num(n)} <span className="pc">· {pct(op)}</span></>} /> : "none",
      note: n === 0 ? undefined : op >= 5 ? `${side} - too many for strays, the values run long` : `${side} - a few strays` },
    { label: "Fence", value: <>{fmt(o["Low fence"], isNum)} … {fmt(o["High fence"], isNum)}</>,
      note: isNum && !Number.isNaN(iqr) ? <>1.5 × IQR ({fmt(iqr)}) past Q1 and Q3</> : "1.5 × IQR past Q1 and Q3" },
    { label: "Lowest … highest", value: <>{fmt(o.Lowest, isNum)} … {fmt(o.Highest, isNum)}</>,
      tone: isNum && p99 > 0 && high / p99 >= 10 ? "warn" : undefined,
      note: isNum && p99 > 0 && high / p99 >= 10
        ? `${fmt(Math.round(high / p99))}× the P99 - a unit or entry error?`
        : isNum && !Number.isNaN(lo) && lo > 0 && low < 0 ? "the lowest is below zero" : undefined },
  ];
  if (isNum) {
    const z = Number(o.Zeros ?? 0), neg = Number(o.Negatives ?? 0);
    items.push(z || neg
      ? { label: "Zero · negative", value: <>{num(z)} <span className="pc">· {pct(share(z, filled))}</span> · {num(neg)} <span className="pc">· {pct(share(neg, filled))}</span></>,
          tone: share(z, filled) >= 5 ? "warn" : undefined,
          note: share(z, filled) >= 5 ? "many zeros - missing values?" : undefined }
      : { label: "Zero · negative", value: "none", tone: "ok" });
  }
  const pcts = ["P1", "P5", "P25", "Median", "P75", "P95", "P99"].filter((k) => o[k] !== "" && o[k] != null);
  return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      <Points name="Outlier findings" items={items} />
      {pcts.length > 0 && (
        <div className="tblwrap">
          <table className="tbl compact" aria-label="Percentiles">
            <thead><tr>{pcts.map((k) => <th key={k} className="num">{k}</th>)}</tr></thead>
            <tbody><tr>{pcts.map((k) => <td key={k} className="num m">{fmt(o[k], isNum)}</td>)}</tr></tbody>
          </table>
        </div>
      )}
    </div></Panel>
  );
}

export function Shapes({ rows, kind, st }: { rows: Row[]; kind: string; st: Row }) {
  const top = Math.max(1, ...rows.map((r) => Number(r.Count ?? 0)));
  const items: Point[] = [];
  if (kind === "number" && rows.length) {
    const parts = rows.map((r) => String(r.Pattern).replace(/^-/, "").split("."));
    const places = parts.map((p) => (p[1] ?? "").length);
    const most = parts[0][0].length;
    const longest = Math.max(...[st.Min, st.Max].map(toNum).filter((x) => !Number.isNaN(x)).map(intDigits), ...parts.map((p) => p[0].length));
    const scale = Math.max(...places);
    items.push({ label: "Digits before the point", value: most === longest ? `${longest}` : `${most} mostly, up to ${longest}`,
      tone: longest - most >= 3 ? "warn" : undefined,
      note: longest - most >= 3 ? "a few far longer - a unit or entry error?" : undefined });
    items.push({ label: "Places after the point", value: Math.min(...places) === scale ? `${scale}` : `${Math.min(...places)} to ${scale}`,
      note: <>fits <code>DECIMAL({longest + scale}, {scale})</code></> });
    const one = rows.filter((r) => /\.9$/.test(String(r.Pattern))).reduce((s, r) => s + Number(r.Count), 0);
    if (one && scale > 1)
      items.push({ label: "One decimal", value: <>{num(one)} <span className="pc">· {pct(share(one, Number(st.Rows) - Number(st.Nulls)))}</span></>,
        note: "fine - a dropped trailing zero (10.10 → 10.1)" });
  } else if (kind === "text" && rows.length) {
    const covered = rows.reduce((s, r) => s + Number(r["%"] ?? 0), 0);
    items.push(rows.length === 1 && covered >= 99.995
      ? { label: "One shape", value: "every value", tone: "ok", note: "a fixed format" }
      : { label: "Top shapes cover", value: pct(Math.min(100, covered)), tone: covered < 90 ? "warn" : undefined,
          note: covered < 90 ? "the rest vary in length or format" : undefined });
  }
  return (
    <Panel title="Shapes" sub="digits → 9, letters → A, as read from the file"><div className="panel-body">
      {rows.length
        ? <ul className="kv prof-kv prof-shapes" aria-label="Shapes">
            {rows.map((r, i) => (
              <li key={i}>
                <span className="m" title={String(r.Pattern)}>{readShape(String(r.Pattern))}<span className="eg">e.g. {String(r.Example ?? "")}</span></span>
                <span className="bar"><i className="warn" style={{ width: `${(100 * Number(r.Count)) / top}%` }} /></span>
                <span className="v">{num(r.Count as number)} <span className="pc">· {pct(r["%"])}</span></span>
              </li>
            ))}
          </ul>
        : <p className="caption">No shapes - the three most common shapes are taken from text and number columns.</p>}
      {items.length > 0 && <Points name="Shape findings" items={items} />}
    </div></Panel>
  );
}

/** A text or number column whose values would read as a number, a date or a timestamp: how many, and as what. */
export function CouldBe({ column, made }: { column: string; made: string }) {
  const r = useCasts(made).data?.columns?.find((x) => x.column === column);
  if (!r) return null;
  const items: Point[] = castsOf(r).map(({ kind, hit }) => {
    const { type, form } = castType(kind, hit);
    const left = r.filled - hit.any;
    return { label: kind[0].toUpperCase() + kind.slice(1), tone: left ? "warn" : "ok",
      value: <Bar pct={share(hit.any, r.filled)} tone={left ? "warn" : "ok"} label={<>{num(hit.any)} <span className="pc">· {pct(share(hit.any, r.filled))}</span></>} />,
      note: <><code>{type}</code>{form && <> · <code>{form}</code></>}{left ? ` · ${num(left)} would not convert` : " · every value"}</> };
  });
  return (
    <Panel title="Could be read as" sub={`read as ${r.kind} - of ${num(r.filled)} filled values`}><div className="panel-body">
      <Points name="Could be read as" items={items} />
    </div></Panel>
  );
}

const PART_N = ["1", "2", "3", "4", "5"] as const;

/** The column taken apart: a number's digits before and after the point, a date's years, months
 *  and weekdays (and hours), text's first and last few characters. */
export function Parts({ column, kind, made, as }: { column: string; kind: string; made: string; as: string }) {
  const [n, setN] = useState<(typeof PART_N)[number]>("3");
  const q = useParts(column, made, Number(n), as === kind ? "" : as).data;
  const groups = q?.groups ?? [];
  if (!groups.length) return null;
  const when = q?.reads_as;
  const sub = when === "number" ? "read as a number - digits before and after the point, in bands of three"
    : when ? `read as a ${when} - when the values fall`
    : kind === "number" ? "digits before and after the point, in bands of three"
    : kind === "text" ? "the most common first and last characters" : "when the values fall";
  return (
    <Panel title="Parts" sub={sub}
      actions={kind === "text" && !when ? <Seg mini label="Characters" value={n} onChange={setN} options={PART_N.map((v) => ({ value: v, label: v }))} /> : undefined}>
      <div className="panel-body"><div className="prof-parts">
        {groups.map((g) => {
          const top = Math.max(1, ...g.rows.map((r) => r.n));
          const all = g.total;
          return (
            <div key={g.title}>
              <h4 className="eyebrow">{g.title}</h4>
              <ul className="kv prof-kv" aria-label={g.title}>
                {g.rows.map((r) => (
                  <li key={r.label}>
                    <span className="m" title={r.label}>{r.label === "" ? "(blank)" : r.label}</span>
                    <span className="bar"><i style={{ width: `${(100 * r.n) / top}%` }} /></span>
                    <span className="v">{num(r.n)} <span className="pc">· {pct(share(r.n, all))}</span></span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div></div>
    </Panel>
  );
}

export function Frequent({ column, made, st, title = "Most and least frequent", sub, children }:
  { column: string; made: string; st: Row; title?: string; sub?: string; children?: ReactNode }) {
  const q = useFreq(column, made);
  const isNum = st.Type === "number";
  return (
    <Panel title={title} sub={sub ?? `${num(st.Distinct as number)} distinct`}><div className="panel-body">
      {q.error ? <div className="note error">{(q.error as Error).message}</div>
        : !q.data ? <p className="caption">Reading…</p>
        : <FreqLists column={column} isNum={isNum} {...splitFreq(q.data.top, q.data.bottom)} />}
      {children}
    </div></Panel>
  );
}

/** The sections left out for this column, and why - so nothing goes missing without a word. */
export function NotShown({ items }: { items: { label: string; why: string }[] }) {
  if (!items.length) return null;
  return (
    <Panel title="Not shown for this column" sub="sections that only help with other kinds of data"><div className="panel-body">
      <Points name="Not shown for this column" plain items={items.map((it) => ({ label: it.label, value: it.why }))} />
    </div></Panel>
  );
}

/** Over 20 values: the ten most and the ten least frequent. Ten or fewer: every value, once.
 *  In between: the ten most frequent, then the rest in another colour, its bars on the same scale. */
function FreqLists({ column, isNum, top, rest, all }: { column: string; isNum: boolean; top: Frame; rest: Frame | null; all: boolean }) {
  if (!rest) return (<>
    <span className="eyebrow">Every value · most to least frequent</span>
    <FreqBars t={top} numeric={isNum} label={`Most frequent values of ${column}`} />
  </>);
  const scale = Math.max(1, ...top.rows.map((r) => Number(r[top.columns.indexOf("Count")] ?? 0)));
  return (<>
    <span className="eyebrow">Most frequent</span>
    <FreqBars t={top} numeric={isNum} label={`Most frequent values of ${column}`} />
    <span className="eyebrow accent freq-rest">{all ? `The other ${rest.rows.length} · down to the least frequent` : "Least frequent"}</span>
    <FreqBars t={rest} numeric={isNum} label={`Least frequent values of ${column}`} scale={all ? scale : undefined} tone={all ? "accent" : "warn"} />
  </>);
}

export function Dependencies({ p, column }: { p: Profile; column: string }) {
  const keys = keyColumns(p);
  const deps = rowsOf(p.deps).filter((r) => r.Determines === column || r.Determined === column);
  const corr = rowsOf(p.corr).filter((r) => r["Column A"] === column || r["Column B"] === column);
  const items: { ok?: boolean; body: ReactNode }[] = [];
  if (keys.includes(column))
    items.push({ ok: true, body: <><C>{column}</C> is {keys.length > 1 ? "part of the key" : "the key"} - it determines every other column</> });
  else if (keys.length)
    items.push({ ok: true, body: <>{keys.map((k, i) => <span key={k}>{i > 0 && " + "}<C>{k}</C></span>)} → <C>{column}</C> - trivially, {keys.join(" + ")} is the key</> });
  for (const r of deps)
    items.push({ body: <><C>{String(r.Determines)}</C> {r.Kind === "one-to-one" ? "↔" : "→"} <C>{String(r.Determined)}</C> - {String(r.Kind)}{r.Distinct != null && r.Distinct !== "" ? ` · ${num(r.Distinct as number)} distinct` : ""}</> });
  for (const r of corr)
    items.push({ body: <><C>{String(r["Column A"])}</C> and <C>{String(r["Column B"])}</C> are correlated - r = {fmt(r.r)}</> });
  const all = strongest(p.matrix, column, Infinity);
  const decides = all.decides.slice(0, TOP), decidedBy = all.decidedBy.slice(0, TOP);
  const near = (col: string) => Number(statsOf(p, col)?.["Distinct % of rows"] ?? 0) >= NEAR_KEY;
  const real = all.decidedBy.filter((h) => !near(h.col));     // the verdict looks past the five shown
  if (!deps.length && !keys.includes(column))
    items.push({ body: real[0]?.v >= SHOWN
      ? <>No column determines {column} on every row - the closest are under <em>Decides {column} most</em>.</>
      : <>No other column determines {column}.</> });
  const unmeasured = !p.matrix.rows.some((r) => r[0] === column);
  const distinct = Number(statsOf(p, column)?.Distinct ?? 0), rows = Number(statsOf(p, column)?.Rows ?? 0);
  // why a column has no row of its own: near-unique, constant, or past the columns the matrix covers
  const why = distinct * 2 > rows
    ? `not measured - ${num(distinct)} distinct values, more than half the rows, so ${column} decides nearly every column by that alone`
    : distinct <= 1 ? `not measured - ${column} holds ${distinct ? "one value" : "no values"}, so it decides nothing`
    : "not measured - past the columns the matrix covers";
  // near-keys only matter among the columns that decide this one: an id decides it by being near-unique
  const hits = (label: string, hs: { col: string; v: number }[], self = false, rest = 0) => {
    const nk = (col: string) => !self && near(col);
    const faint = (h: { col: string; v: number }) => h.v < SHOWN || nk(h.col);
    const more = rest ? ` · ${num(rest)} more, lower` : "";
    return (
    <div className="dep-hits">
      <span className="eyebrow">{label}</span>
      {!hs.length ? <p className="caption">{self && unmeasured ? why : "no other column"}</p> : <>
        <ul aria-label={label}>{hs.map((h) => (
          <li key={h.col} className={faint(h) ? "weak" : undefined}>
            <span className="dep-col"><C>{h.col}</C>{nk(h.col) && <span className="near">near-key · {pct(statsOf(p, h.col)?.["Distinct % of rows"])} distinct</span>}</span><Bar pct={h.v} tone={h.v >= 100 ? "ok" : h.v < SHOWN ? "warn" : "accent"} label={`${num(h.v)}%`} />
          </li>))}
        </ul>
        {hs.every(faint)
          ? <p className="caption">{hs.some((h) => nk(h.col)) ? `near-keys aside, all under ${SHOWN}%` : `all under ${SHOWN}%`} - not conclusive{more}</p>
          : hs.some(faint) ? <p className="caption">the faint ones are under {SHOWN}%{hs.some((h) => nk(h.col)) ? " or near-keys" : ""} - not conclusive{more}</p>
          : more && <p className="caption">{more.slice(3)}</p>}
      </>}
    </div>
    );
  };
  return (
    <Panel title="Dependencies" sub="does another column determine this one?"><div className="panel-body">
      <ul className="bullets">{items.map((it, i) => <li key={i}><i className={it.ok ? "ok" : undefined} /><span>{it.body}</span></li>)}</ul>
      {p.matrix.rows.length > 0 && <>
        <p className="caption">How far one column decides another beyond chance - 0 unrelated, 100% every value with one value - the {TOP} strongest each way. A near-key (an id) decides nearly everything by being near-unique, so it is faint and never the verdict.</p>
        {hits(`Decides ${column} most`, decidedBy, false, all.decidedBy.length - decidedBy.length)}
        {hits(`${column} decides most`, decides, true, all.decides.length - decides.length)}
      </>}
    </div></Panel>
  );
}

/** The types a column could be read as: its own, then any its values take, the fullest first. */
function readings(kind: string, cast?: CastRow) {
  return [kind, ...(cast ? castsOf(cast).map((c) => c.kind) : []).filter((k) => k !== kind)];
}

export function ColumnDetail({ p, column, made, name, label }: { p: Profile; column: string; made: string; name: string; label: string }) {
  const all = rowsOf(p.stats).map((r) => String(r.Column));
  const i = all.indexOf(column);
  const st = statsOf(p, column)!;
  const kind = String(st.Type);
  const isNum = kind === "number";
  const isText = kind === "text";
  const shapes = rowsOf(p.patterns).filter((r) => r.Column === column);
  const prev = i > 0 ? all[i - 1] : null;
  const next = i < all.length - 1 ? all[i + 1] : null;
  const cast = useCasts(made).data?.columns?.find((x) => x.column === column);
  const when = cast ? (["timestamp", "date"] as const).find((k) => cast[k] && cast[k]!.any >= READS_AS * cast.filled) ?? "" : "";
  // read as: the column's own type unless its values read as a date or a timestamp; a pick holds for this column only
  const [pick, setPick] = useState<{ column: string; as: string } | null>(null);
  const as = pick?.column === column ? pick.as : when || kind;
  const asWhen = as === "date" || as === "timestamp";
  const keys = keyColumns(p);
  const opts = readings(kind, cast);
  // beside the reading: the format a date or a timestamp is read in, a number's places, a text key's leading zeros
  const hit = (as === "date" || as === "timestamp" || as === "number") && as !== kind ? cast?.[as] : undefined;
  const places = isNum && shapes.length ? Math.max(...shapes.map((r) => (String(r.Pattern).split(".")[1] ?? "").length)) : -1;
  const read = hit && castType(as as "date" | "timestamp" | "number", hit);
  // the same queries the column's page makes, so each is asked once: a number's places and the
  // DECIMAL it fits, a flag's spellings, a text column's case and space variants
  const numForm = useNumberFormText(column, made, isNum && as === "number");
  const flagForm = useFlagForm(column, made, kind === "boolean");
  const spell = useSpelling(column, made, isText && as === "text").data;
  const isKey = keys.length === 1 && keys[0] === column;
  const form = read ? (read.form ? `${read.type} · ${read.form}` : read.type)
    : numForm || flagForm
    || (places === 0 ? "whole" : places > 0 ? `${places} place${places > 1 ? "s" : ""}` : "")
    || (isText && isKey ? "keep leading zeros" : isText && as === "text" ? textForm(st, spell) : "");
  const view: ColumnViewProps = { p, column, made, st, as, cast };
  // a page per kind of column: the key, a date or a timestamp (or text read as one), a number, a flag, text
  const body = keys.length === 1 && keys[0] === column ? <KeyView {...view} />
    : asWhen ? <WhenView {...view} />
    : kind === "number" ? <NumberView {...view} />
    : kind === "boolean" ? <FlagView {...view} />
    : <TextView {...view} />;
  return (
    <>
      <div className="sec-head prof-colhead">
        <Button size="sm" icon="arrowl" onClick={() => setView({ column: null })}>All columns</Button>
        <h2 className="m">{column}</h2>
        {keys.length === 1 && keys[0] === column && <Chip tone="key">key</Chip>}
        {opts.length > 1
          ? <label className="prof-readas"><span>read as</span>
              <select className="sel" value={as} onChange={(e) => setPick({ column, as: e.target.value })}>
                {opts.map((k) => <option key={k} value={k}>{k}{k === kind ? " - as profiled" : ""}</option>)}
              </select>
              {form && <code className="readas-form">{form}</code>}
            </label>
          : <span className="prof-readas"><span>read as</span><Chip>{kind}</Chip>{form && <code className="readas-form">{form}</code>}</span>}
        <span className="prof-sem" title="what the column most likely holds - a guess from its name, type and values">
          {semantic(column, as, Number(st.Distinct), Number(st.Rows), keys.length === 1 && keys[0] === column, shapes[0] ? String(shapes[0].Pattern) : "")}</span>
        <span className="sub">column {i + 1} of {all.length} · {name}{label ? ` · ${label}` : ""}</span>
        <div className="actions">
          <Button icon="arrowl" disabled={!prev} onClick={() => prev && openColumn(prev)}>Previous{prev && ` · ${prev}`}</Button>
          <Button iconAfter="arrow" disabled={!next} onClick={() => next && openColumn(next)}>Next{next && ` · ${next}`}</Button>
        </div>
      </div>
      {body}
    </>
  );
}
