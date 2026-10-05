// web/src/profiling/ColumnDetail.tsx - one column of the profile (screen 16): back to all columns,
// previous / next, its statistics, its distribution (GET /api/profiling/hist), outliers, shapes,
// most and least frequent values and what determines it - all from the profile held.
import { Bar, Button, Chip, num, Panel, Seg, StatGrid } from "../ui/kit";
import { useState, type ReactNode } from "react";
import { setView } from "../shell/view";
import { castsOf, castType } from "./casts";
import { openColumn } from "./ColumnsTable";
import { SHOWN, strongest, TOP } from "./DepMatrix";
import { fmt, keyColumns, pct, rowsOf, statsOf, type Row } from "./frame";
import { FreqBars, splitFreq } from "./FreqSection";
import type { Frame, HistBin, Profile } from "./types";
import { useCasts, useFreq, useHist, useParts } from "./useProfiling";
import "./profiling.css";

const BINNED = ["number", "date", "timestamp"];

const C = ({ children }: { children: string }) => <code>{children}</code>;

function Distribution({ column, kind, made }: { column: string; kind: string; made: string }) {
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

type Point = { label: string; value: ReactNode; note?: ReactNode; tone?: "ok" | "warn" | "info" };

/** Findings as short points: a dot for the tone, what it is, the figure, one line on what it means. */
function Points({ name, items }: { name: string; items: Point[] }) {
  return (
    <ul className="prof-points" aria-label={name}>
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

const toNum = (v: unknown) => (v == null || v === "" ? NaN : Number(v));
/** Digits before the point, ignoring the sign. */
const intDigits = (x: number) => String(Math.floor(Math.abs(x))).length;
const share = (n: number, of: number) => (of > 0 ? (100 * n) / of : 0);

/** A shape read out: AA999 → "2 letters · 3 digits"; anything else is shown as itself. */
export function readShape(p: string) {
  return (p.match(/A+|9+|\s+|[^A9\s]+/g) ?? []).map((r) =>
    r[0] === "A" ? `${r.length} letter${r.length > 1 ? "s" : ""}`
    : r[0] === "9" ? `${r.length} digit${r.length > 1 ? "s" : ""}`
    : /^\s+$/.test(r) ? "space" : r === "." ? "point" : `"${r}"`).join(" · ");
}

/** Whole numbers that are (nearly) all different or very long read as a code, where a spread means nothing. */
function isCode(o: Row, st: Row) {
  const xs = [o.Lowest, o.Highest].map(toNum);
  if (xs.some((x) => Number.isNaN(x) || !Number.isInteger(x))) return false;
  return Number(st["Distinct % of filled"] ?? 0) >= 95 || intDigits(Math.max(...xs.map(Math.abs))) >= 9;
}

function Outliers({ o, kind, filled, st, made }: { o?: Row; kind: string; filled: number; st: Row; made: string }) {
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

function Shapes({ rows, kind, st }: { rows: Row[]; kind: string; st: Row }) {
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
                <span className="m" title={String(r.Pattern)}>{readShape(String(r.Pattern))} <span className="pc">e.g. {String(r.Example ?? "")}</span></span>
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
function CouldBe({ column, made }: { column: string; made: string }) {
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
function Parts({ column, kind, made }: { column: string; kind: string; made: string }) {
  const [n, setN] = useState<(typeof PART_N)[number]>("3");
  const groups = useParts(column, made, Number(n)).data?.groups ?? [];
  if (!groups.length) return null;
  const sub = kind === "number" ? "digits before and after the point, in bands of three"
    : kind === "text" ? "the most common first and last characters" : "when the values fall";
  return (
    <Panel title="Parts" sub={sub}
      actions={kind === "text" ? <Seg mini label="Characters" value={n} onChange={setN} options={PART_N.map((v) => ({ value: v, label: v }))} /> : undefined}>
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

function Frequent({ column, made, st }: { column: string; made: string; st: Row }) {
  const q = useFreq(column, made);
  const isNum = st.Type === "number";
  return (
    <Panel title="Most and least frequent" sub={`${num(st.Distinct as number)} distinct`}><div className="panel-body">
      {q.error ? <div className="note error">{(q.error as Error).message}</div>
        : !q.data ? <p className="caption">Reading…</p>
        : <FreqLists column={column} isNum={isNum} {...splitFreq(q.data.top, q.data.bottom)} />}
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

function Dependencies({ p, column }: { p: Profile; column: string }) {
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
  const { decides, decidedBy } = strongest(p.matrix, column);
  if (!deps.length && !keys.includes(column))
    items.push({ body: decidedBy[0]?.v >= SHOWN
      ? <>No column determines {column} on every row - the closest are under <em>Decides {column} most</em>.</>
      : <>No other column determines {column}.</> });
  const hits = (label: string, hs: { col: string; v: number }[]) => (
    <div className="dep-hits">
      <span className="eyebrow">{label}</span>
      {!hs.length ? <p className="caption">no other column</p> : <>
        <ul aria-label={label}>{hs.map((h) => (
          <li key={h.col} className={h.v < SHOWN ? "weak" : undefined}>
            <C>{h.col}</C><Bar pct={h.v} tone={h.v >= 100 ? "ok" : h.v < SHOWN ? "warn" : "accent"} label={`${num(h.v)}%`} />
          </li>))}
        </ul>
        {hs[0].v < SHOWN
          ? <p className="caption">all under {SHOWN}% - not conclusive, nothing here decides {column}</p>
          : hs.some((h) => h.v < SHOWN) && <p className="caption">the faint ones are under {SHOWN}% - not conclusive</p>}
      </>}
    </div>
  );
  return (
    <Panel title="Dependencies" sub="does another column determine this one?"><div className="panel-body">
      <ul className="bullets">{items.map((it, i) => <li key={i}><i className={it.ok ? "ok" : undefined} /><span>{it.body}</span></li>)}</ul>
      {p.matrix.rows.length > 0 && <>
        <p className="caption">How far one column decides another beyond chance - 0 unrelated, 100% every value with one value - the {TOP} strongest each way.</p>
        {hits(`${column} decides most`, decides)}
        {hits(`Decides ${column} most`, decidedBy)}
      </>}
    </div></Panel>
  );
}

export function ColumnDetail({ p, column, made, name, label }: { p: Profile; column: string; made: string; name: string; label: string }) {
  const all = rowsOf(p.stats).map((r) => String(r.Column));
  const i = all.indexOf(column);
  const st = statsOf(p, column)!;
  const kind = String(st.Type);
  const isNum = kind === "number";
  const o = rowsOf(p.outliers).find((r) => r.Column === column);
  const shapes = rowsOf(p.patterns).filter((r) => r.Column === column);
  const prev = i > 0 ? all[i - 1] : null;
  const next = i < all.length - 1 ? all[i + 1] : null;
  const has = (v: unknown) => v != null && v !== "";
  const stats = [
    { label: "Rows", value: num(st.Rows as number) },
    { label: "Nulls", value: <>{num(st.Nulls as number)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: <>{num(st.Distinct as number)} <span className="pc">· {pct(st["Distinct % of rows"])}</span></>,
      sub: `${pct(st["Distinct % of filled"])} of filled` },
    { label: "Min", value: fmt(st.Min, isNum) },
    ...(o && has(o.P25) ? [{ label: "Q1", value: fmt(o.P25, isNum) }] : []),
    ...(o && has(o.Median) ? [{ label: "Median", value: fmt(o.Median, isNum) }] : []),
    ...(has(st.Mean) ? [{ label: "Mean", value: fmt(st.Mean) }] : []),
    ...(o && has(o.P75) ? [{ label: "Q3", value: fmt(o.P75, isNum) }] : []),
    { label: "Max", value: fmt(st.Max, isNum) },
    ...(o && has(o["Std dev"]) ? [{ label: "Std dev", value: fmt(o["Std dev"]) }] : []),
    ...(has(st["Top value"]) ? [{ label: "Top value", value: fmt(st["Top value"], isNum), sub: pct(st["Top %"]) }] : []),
    ...(has(st["Min length"]) ? [{ label: "Min length", value: num(st["Min length"] as number), sub: "characters" }] : []),
    ...(has(st["Avg length"]) ? [{ label: "Avg length", value: fmt(st["Avg length"]), sub: "characters" }] : []),
    ...(has(st["Max length"]) ? [{ label: "Max length", value: num(st["Max length"] as number), sub: "characters" }] : []),
  ].filter((s) => s.value !== "");
  return (
    <>
      <div className="sec-head prof-colhead">
        <Button size="sm" icon="arrowl" onClick={() => setView({ column: null })}>All columns</Button>
        <h2 className="m">{column}</h2>
        <Chip>{kind}</Chip>
        <span className="sub">column {i + 1} of {all.length} · {name}{label ? ` · ${label}` : ""} · {num(st.Rows as number)} values</span>
        <div className="actions">
          <Button icon="arrowl" disabled={!prev} onClick={() => prev && openColumn(prev)}>Previous{prev && ` · ${prev}`}</Button>
          <Button iconAfter="arrow" disabled={!next} onClick={() => next && openColumn(next)}>Next{next && ` · ${next}`}</Button>
        </div>
      </div>
      <StatGrid stats={stats} />
      {/* the distribution across the page, then two panels to a row */}
      {BINNED.includes(kind) && <Distribution column={column} kind={kind} made={made} />}
      {(kind === "text" || kind === "number") && <CouldBe column={column} made={made} />}
      <Parts column={column} kind={kind} made={made} />
      <div className="prof-grid prof-col-grid">
        <Outliers o={o} kind={kind} filled={Number(st.Rows) - Number(st.Nulls)} st={st} made={made} />
        <Shapes rows={shapes} kind={kind} st={st} />
        <Frequent column={column} made={made} st={st} />
        <Dependencies p={p} column={column} />
      </div>
    </>
  );
}
