// web/src/profiling/ColumnDetail.tsx - one column of the profile (screen 16): back to all columns,
// previous / next, its statistics, its distribution (GET /api/profiling/hist), outliers, shapes,
// most and least frequent values and what determines it - all from the profile held.
import { Bar, Button, Callout, Chip, num, Panel, StatGrid } from "../ui/kit";
import type { ReactNode } from "react";
import { setView } from "../shell/view";
import { openColumn } from "./ColumnsTable";
import { SHOWN, strongest, TOP } from "./DepMatrix";
import { fmt, keyColumns, pct, rowsOf, statsOf, type Row } from "./frame";
import { FreqBars, splitFreq } from "./FreqSection";
import type { Frame, HistBin, Profile } from "./types";
import { useFreq, useHist } from "./useProfiling";
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

function Outliers({ o, kind }: { o?: Row; kind: string }) {
  const isNum = kind === "number";
  if (!o) return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      <p className="caption">Outliers are looked for in number, date and timestamp columns.</p>
    </div></Panel>
  );
  const n = Number(o.Outliers ?? 0);
  const fence = `${fmt(o["Low fence"], isNum)} … ${fmt(o["High fence"], isNum)}`;
  const extra = [Number(o.Zeros) > 0 && `${num(Number(o.Zeros))} at zero`, Number(o.Negatives) > 0 && `${num(Number(o.Negatives))} negative`].filter(Boolean);
  const pcts = ["P1", "P5", "P25", "Median", "P75", "P95", "P99"].filter((k) => o[k] !== "" && o[k] != null);
  return (
    <Panel title="Outliers" sub="1.5 × IQR fence"><div className="panel-body">
      {n === 0
        ? <Callout tone="pos" icon="check"><strong>None.</strong> Every value sits inside {fence} (Q1 − 1.5 × IQR … Q3 + 1.5 × IQR).
            {isNum && (extra.length ? ` ${extra.join(", ")}.` : " Nothing at zero, nothing negative.")}</Callout>
        : <Callout tone="warn" icon="sparkle"><strong>{num(n)} value{n > 1 ? "s" : ""} ({pct(o["Outlier %"])})</strong> sit outside {fence}.
            Lowest {fmt(o.Lowest, isNum)}, highest {fmt(o.Highest, isNum)}.{extra.length > 0 && ` ${extra.join(", ")}.`}</Callout>}
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

function Shapes({ rows, kind }: { rows: Row[]; kind: string }) {
  const top = Math.max(1, ...rows.map((r) => Number(r.Count ?? 0)));
  const oneDec = kind === "number" ? rows.filter((r) => /\.9$/.test(String(r.Pattern))) : [];
  return (
    <Panel title="Shapes" sub="digits → 9, letters → A, as read from the file"><div className="panel-body">
      {rows.length
        ? <ul className="kv prof-kv" aria-label="Shapes">
            {rows.map((r, i) => (
              <li key={i}>
                <span className="m" title={`e.g. ${String(r.Example ?? "")}`}>{String(r.Pattern)} <span className="pc">e.g. {String(r.Example ?? "")}</span></span>
                <span className="bar"><i className="warn" style={{ width: `${(100 * Number(r.Count)) / top}%` }} /></span>
                <span className="v">{num(r.Count as number)} <span className="pc">· {pct(r["%"])}</span></span>
              </li>
            ))}
          </ul>
        : <p className="caption">No shapes - the three most common shapes are taken from text and number columns.</p>}
      {oneDec.length > 0 && (
        <Callout tone="warn" icon="sparkle"><strong>{num(oneDec.reduce((s, r) => s + Number(r.Count), 0))} values carry one decimal</strong> (a trailing zero
          dropped on export). Read as <em>number</em> they compare correctly; as <em>text</em> they would not.</Callout>
      )}
    </div></Panel>
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
      <div className="prof-grid prof-col-grid">
        <Outliers o={o} kind={kind} />
        <Shapes rows={shapes} kind={kind} />
        <Frequent column={column} made={made} st={st} />
        <Dependencies p={p} column={column} />
      </div>
    </>
  );
}
