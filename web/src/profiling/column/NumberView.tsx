// web/src/profiling/column/NumberView.tsx - a number column's page below its header (screen 20): its
// statistics, a skew banner, the distribution in equal-width, log or percentile bins, outliers, its form
// (digits, places, round lots - GET /api/profiling/numform), most and least frequent, dependencies.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Callout, num, Panel, Seg, StatGrid } from "../../ui/kit";
import { CouldBe, Dependencies, Frequent, Outliers, Points, share, toNum, type Point } from "../ColumnDetail";
import { fmt, pct, rowsOf } from "../frame";
import { useHist } from "../useProfiling";
import type { ColumnViewProps } from "./types";
import "./number.css";

export type LogBin = { label: string; lo: number; hi: number; n: number };
export type NumForm = {
  column: string; filled: number; zeros: number; negatives: number; log_bins: LogBin[];
  before: { label: string; n: number }[]; places: { min: number; max: number }; fits: string;
  round_lots: number[]; top: { value: number; n: number }[]; once: number[];
};

const SKEW = 5;          // mean at least this many times the median: heavily skewed
const ONE_BIN = 0.9;     // share of rows in one equal-width bin from which the bins say nothing
type Mode = "equal" | "log" | "pct";
const MODES: { value: Mode; label: string }[] = [
  { value: "equal", label: "Equal width" }, { value: "log", label: "Log" }, { value: "pct", label: "Percentile" }];
const STRIP = [["Min", "P1", 1], ["P1", "P5", 4], ["P5", "P25", 20], ["P25", "Median", 25],
  ["Median", "P75", 25], ["P75", "P95", 20], ["P95", "P99", 4], ["P99", "Max", 1]] as const;

const dash = (s: string) => s.replace(/(\d)-(\d)/g, "$1 - $2");
const has = (v: unknown) => v != null && v !== "";

function useNumForm(column: string, made: string) {
  return useQuery({ queryKey: ["profiling-numform", made, column], enabled: !!made, staleTime: Infinity,
    queryFn: () => api.get<NumForm>(`/api/profiling/numform?column=${encodeURIComponent(column)}`) });
}

type Shown = { label: string; n?: number; share: number };

export function NumberView({ p, column, made, st }: ColumnViewProps) {
  const o = rowsOf(p.outliers).find((r) => r.Column === column);
  const filled = Number(st.Rows) - Number(st.Nulls);
  const got = useNumForm(column, made).data;
  const form = got && Array.isArray(got.log_bins) ? got : undefined;     // an answer of another shape reads as none
  const hist = useHist(column, made).data;
  const median = toNum(o?.Median), mean = toNum(st.Mean);
  const times = median > 0 && mean >= SKEW * median ? mean / median : 0;
  const bins = hist?.bins ?? [];
  const binTotal = bins.reduce((s, b) => s + b.n, 0);
  const fullest = Math.max(0, ...bins.map((b) => b.n));
  const oneBin = bins.length > 1 && binTotal > 0 && fullest >= ONE_BIN * binTotal;
  const skewed = times > 0 || oneBin;
  const [pick, setPick] = useState<Mode | null>(null);
  const mode: Mode = pick ?? (skewed ? "log" : "equal");

  const z = Number(o?.Zeros ?? 0), neg = Number(o?.Negatives ?? 0);
  const top = form?.top[0];
  const stats = [
    { label: "Rows", value: num(st.Rows as number) },
    { label: "Nulls", value: <>{num(st.Nulls as number)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: num(st.Distinct as number), sub: `${pct(st["Distinct % of rows"])} of rows` },
    { label: "Min", value: fmt(st.Min) },
    ...(o && has(o.P25) ? [{ label: "Q1", value: fmt(o.P25) }] : []),
    ...(o && has(o.Median) ? [{ label: "Median", value: fmt(o.Median) }] : []),
    ...(has(st.Mean) ? [{ label: "Mean", value: times ? <span className="warn-t">{fmt(st.Mean)}</span> : fmt(st.Mean),
      sub: times ? `${fmt(Math.round(times))}× the median` : undefined }] : []),
    ...(o && has(o.P75) ? [{ label: "Q3", value: fmt(o.P75) }] : []),
    { label: "Max", value: fmt(st.Max) },
    ...(o && has(o["Std dev"]) ? [{ label: "Std dev", value: fmt(o["Std dev"]) }] : []),
    ...(has(st["Top value"]) ? [{ label: "Top value", value: fmt(st["Top value"]),
      sub: top && String(top.value) === String(toNum(st["Top value"])) ? `${num(top.n)} · ${pct(st["Top %"])}` : pct(st["Top %"]) }] : []),
    ...(o ? [{ label: "Zero · negative",
      value: z || neg ? <>{num(z)} · {num(neg)}</> : <span className="ok-t">none</span>,
      sub: z || neg ? `${pct(share(z, filled))} · ${pct(share(neg, filled))}` : undefined }] : []),
  ].filter((s) => s.value !== "");

  const banner = skewed ? (
    <Callout tone="warn" icon="sparkle">
      <strong>Heavily skewed.</strong> Half the values are {fmt(o?.Median)} or less; the mean is {fmt(st.Mean)}
      {times ? `, ${fmt(Math.round(times))}× the median` : ""}
      {o && has(o.P99) && has(st.Max) ? `; the top 1% runs from ${fmt(o.P99)} to ${fmt(st.Max)}` : ""}.{" "}
      {oneBin ? `Equal-width bins put ${pct(share(fullest, binTotal))} of rows in one bar, so the` : "The"} distribution below uses <strong>log bins</strong>.
    </Callout>
  ) : bins.length > 1 && binTotal > 0 && fullest <= (2 * binTotal) / bins.length ? (
    <Callout tone="pos" icon="check">
      <strong>Spread evenly.</strong> No equal-width bin holds more than {pct(share(fullest, binTotal))} of rows; the mean is {fmt(st.Mean)}, the median {fmt(o?.Median)}.
    </Callout>
  ) : null;

  // the bins of the mode picked, and one line on why
  let shown: Shown[] | null = null;
  let caption = "";
  if (mode === "equal" && hist) {
    const span = bins.length ? Math.abs(Number(bins[bins.length - 1].hi) - Number(bins[0].lo)) : 0;
    const edge = (v: number | string) => (span >= 100 ? fmt(Math.round(Number(v))) : fmt(v));
    shown = bins.map((b) => ({ label: `${edge(b.lo)} - ${edge(b.hi)}`, n: b.n, share: share(b.n, binTotal) }));
    const empty = bins.filter((b) => b.n === 0).length;
    caption = oneBin ? `${pct(share(fullest, binTotal))} of rows fall in one of ${bins.length} bins${empty ? `, ${empty} empty` : ""} - Log shows the spread.`
      : `${bins.length} bins of equal width from the lowest to the highest value${empty ? `, ${empty} empty` : ""}.`;
  } else if (mode === "log" && form) {
    shown = form.log_bins.map((b) => ({ label: b.label, n: b.n, share: share(b.n, form.filled) }));
    caption = oneBin
      ? `Equal width was tried first: ${bins.filter((b) => b.n === 0).length} of ${bins.length} bins empty and ${pct(share(fullest, binTotal))} of rows in the fullest - so rows are counted per order of magnitude.`
      : "Rows per order of magnitude of the value - each bin ten times wider than the one before.";
  } else if (mode === "pct" && o) {
    const val = (k: string) => (k === "Min" ? st.Min : k === "Max" ? st.Max : o[k]);
    shown = STRIP.filter(([a, b]) => has(val(a)) && has(val(b)))
      .map(([a, b, s]) => ({ label: `${a} - ${b} · ${fmt(val(a))} - ${fmt(val(b))}`, share: s }));
    caption = "The P1 … P99 strip as bins - each holds a fixed share of the rows; the narrower its range, the denser the values.";
  }
  const barTop = Math.max(1e-9, ...(shown ?? []).map((b) => b.share));
  const half = shown ? Math.ceil(shown.length / 2) : 0;
  const cell = (b?: Shown) => b
    ? <><td className="m">{b.label}</td><td className="num m">{b.n === undefined ? "" : num(b.n)}</td><td className="num m dim">{pct(b.share)}</td></>
    : <><td /><td /><td /></>;

  const dist = (
    <Panel title="Distribution" sub={mode === "log" ? "rows per order of magnitude" : mode === "pct" ? "rows between percentiles" : `${bins.length || 10} equal bins · rows per bin`}
      actions={<Seg mini label="Bins" value={mode} onChange={setPick} options={MODES} />}>
      <div className="panel-body">
        {!shown ? <p className="caption">{mode === "pct" ? "No percentiles for this column." : "Counting…"}</p>
          : !shown.length ? <p className="caption">No values to bin.</p>
          : <>
            {mode !== "pct" && <>
              <div className="hist num-hist" role="img" aria-label={`Histogram of ${column}: ${shown.map((b) => `${b.label} ${num(b.n ?? 0)}`).join(", ")}`}>
                {shown.map((b, i) => <i key={i} style={{ height: `${(100 * b.share) / barTop}%` }} title={`${b.label}: ${num(b.n ?? 0)}`} />)}
              </div>
              <div className="num-hist-x" aria-hidden="true">{shown.map((b, i) => <span key={i} title={b.label}>{mode === "log" ? b.label : b.label.split(" - ")[0]}</span>)}</div>
            </>}
            <div className="tblwrap">
              <table className="tbl compact prof-bins" aria-label={`Bins of ${column}`}>
                <thead><tr><th>Bin</th><th className="num">Rows</th><th className="num">Share</th><th className="b2">Bin</th><th className="num">Rows</th><th className="num">Share</th></tr></thead>
                <tbody>{shown.slice(0, half).map((b, i) => <tr key={i}>{cell(b)}{cell(shown![half + i])}</tr>)}</tbody>
              </table>
            </div>
          </>}
        {caption && <p className="caption">{caption}</p>}
      </div>
    </Panel>
  );

  return (
    <>
      <StatGrid stats={stats} />
      {banner}
      <div className="prof-grid prof-col-grid">
        <div className="prof-stack">
          {dist}
          <Outliers o={o} kind="number" filled={filled} st={st} made={made} />
        </div>
        <div className="prof-stack">
          <Form form={form} />
          <CouldBe column={column} made={made} />
          <Frequent column={column} made={made} st={st}>
            {form && form.once.length > 0 && (
              <p className="caption num-once">Seen once{form.once.length === 10 ? ", the lowest ten" : ""}: <span className="m">{form.once.map((v) => fmt(v)).join(" · ")}</span></p>
            )}
          </Frequent>
          <Dependencies p={p} column={column} />
        </div>
      </div>
    </>
  );
}

/** Digits before the point, places after it and the DECIMAL they fit, round lots among the most frequent. */
function Form({ form }: { form?: NumForm }) {
  if (!form) return <Panel title="Form" sub="digits, decimals, round numbers"><div className="panel-body"><p className="caption">Reading…</p></div></Panel>;
  const top = Math.max(1, ...form.before.map((r) => r.n));
  const { min, max } = form.places;
  const items: Point[] = [{ label: "Places after the point", tone: "ok",
    value: min === max ? `${max} · every value` : `${min} to ${max}`,
    note: <>{max === 0 ? "whole numbers - " : ""}fits <code>{form.fits}</code></> }];
  if (form.round_lots.length) {
    const step = form.round_lots.every((v) => v % 1000 === 0) ? 1000 : 100;
    items.push({ label: "Round lots", tone: "warn", value: form.round_lots.map((v) => fmt(v)).join(" · "),
      note: `${form.round_lots.length} of the ${form.top.length} most frequent values are whole multiples of ${num(step)}` });
  }
  return (
    <Panel title="Form" sub="digits, decimals, round numbers"><div className="panel-body">
      {form.filled === 0 ? <p className="caption">No values.</p> : <>
        <h4 className="eyebrow">Digits before the point</h4>
        <ul className="kv prof-kv" aria-label="Digits before the point">
          {form.before.map((r) => (
            <li key={r.label}>
              <span className="m">{dash(r.label)}</span>
              <span className="bar"><i style={{ width: `${(100 * r.n) / top}%` }} /></span>
              <span className="v">{num(r.n)} <span className="pc">· {pct(share(r.n, form.filled))}</span></span>
            </li>
          ))}
        </ul>
        <Points name="Form findings" items={items} />
      </>}
    </div></Panel>
  );
}
