// web/src/profiling/column/NumberView.tsx - a number column's page below its header (screen 27): the
// findings, its statistics, a skew callout, the distribution in equal-width, log or percentile bins,
// outliers, its form taken apart (digits, places, round lots - GET /api/profiling/numform and
// /api/profiling/parts), most and least frequent, dependencies.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Bar, Callout, num, Panel, Seg, StatGrid } from "../../ui/kit";
import { CouldBe, Dependencies, NotShown, Outliers, Points, share, toNum, type Point } from "../ColumnDetail";
import { FreqBars, splitFreq } from "../FreqSection";
import { fmt, pct, rowsOf, type Row } from "../frame";
import type { PartGroup } from "../types";
import { useFreq, useHist, useParts } from "../useProfiling";
import { Findings, type Finding } from "./Findings";
import type { ColumnViewProps } from "./types";
import "./number.css";

export type LogBin = { label: string; lo: number; hi: number; n: number };
export type NumForm = {
  column: string; filled: number; zeros: number; negatives: number; log_bins: LogBin[];
  before: { label: string; n: number }[]; places: { min: number; max: number }; fits: string;
  round_lots: number[]; lot_step?: number; top: { value: number; n: number }[]; once: number[];
};

const SKEW = 5;          // mean at least this many times the median: heavily skewed
const ONE_BIN = 0.9;     // share of rows in one equal-width bin from which the bins say nothing
const LONG = 5;          // % of values past the fence from which they are a long tail, not strays
const EXTREME = 10;      // the highest this many times the P99: an extreme value
const READS_AS = 0.9;    // of the filled values: a number that reads as a date or a timestamp from this share
type Mode = "equal" | "log" | "pct";
const MODES: { value: Mode; label: string }[] = [
  { value: "equal", label: "Equal width" }, { value: "log", label: "Log" }, { value: "pct", label: "Percentile" }];
const STRIP = [["Min", "P1", 1], ["P1", "P5", 4], ["P5", "P25", 20], ["P25", "Median", 25],
  ["Median", "P75", 25], ["P75", "P95", 20], ["P95", "P99", 4], ["P99", "Max", 1]] as const;

const dash = (s: string) => s.replace(/(\d)-(\d)/g, "$1 - $2");
const has = (v: unknown) => v != null && v !== "";
/** DECIMAL(8, 0) as the header and the findings write it: DECIMAL(8,0). */
const tight = (fits: string) => fits.replace(/,\s+/g, ",");

export function useNumForm(column: string, made: string, enabled = true) {
  return useQuery({ queryKey: ["profiling-numform", made, column], enabled: !!made && enabled, staleTime: Infinity,
    queryFn: () => api.get<NumForm>(`/api/profiling/numform?column=${encodeURIComponent(column)}`) });
}

/** The form next to "read as" in the column's header: "whole · fits DECIMAL(8,0)",
 *  "2 places · fits DECIMAL(10,2)", "0 to 4 places · fits DECIMAL(9,4)" - "" until it is known. */
export function numberFormText(form?: Pick<NumForm, "filled" | "places" | "fits"> | null): string {
  if (!form || !form.filled || !form.fits) return "";
  const { min, max } = form.places;
  const places = max === 0 ? "whole" : min === max ? `${max} place${max === 1 ? "" : "s"}` : `${min} to ${max} places`;
  return `${places} · fits ${tight(form.fits)}`;
}

/** numberFormText for a column, read from the same query the page uses (so asked for once). */
export function useNumberFormText(column: string, made: string, enabled = true): string {
  const got = useNumForm(column, made, enabled).data;
  return numberFormText(got && Array.isArray(got.log_bins) ? got : undefined);
}

/** A number column whose digits read as dates or timestamps, or that reads like a code: no fence there. */
function noFence(o: Row, st: Row, cast: ColumnViewProps["cast"]) {
  if (cast && [cast.date, cast.timestamp].some((h) => h && h.any >= READS_AS * cast.filled)) return true;
  const xs = [o.Lowest, o.Highest].map(toNum);
  if (xs.some((x) => Number.isNaN(x) || !Number.isInteger(x))) return false;
  return Number(st["Distinct % of filled"] ?? 0) >= 95 || String(Math.floor(Math.max(...xs.map(Math.abs)))).length >= 9;
}

type Shown = { label: string; n?: number; share: number };

export function NumberView({ p, column, made, st, cast }: ColumnViewProps) {
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
  const fullAt = bins.findIndex((b) => b.n === fullest);
  const empty = bins.filter((b) => b.n === 0).length;
  const oneBin = bins.length > 1 && binTotal > 0 && fullest >= ONE_BIN * binTotal;
  const mostEmpty = bins.length > 1 && binTotal > 0 && empty > bins.length / 2;
  const skewed = times > 0 || oneBin;
  const [pick, setPick] = useState<Mode | null>(null);
  const mode: Mode = pick ?? (skewed || mostEmpty ? "log" : "equal");

  const z = Number(o?.Zeros ?? form?.zeros ?? 0), neg = Number(o?.Negatives ?? form?.negatives ?? 0);
  const nulls = Number(st.Nulls ?? 0);
  const p99 = toNum(o?.P99), high = toNum(o?.Highest ?? st.Max);
  const extreme = p99 > 0 && high / p99 >= EXTREME ? high / p99 : 0;
  const fenced = o && !noFence(o, st, cast);
  const out = Number(o?.Outliers ?? 0), outPct = Number(o?.["Outlier %"] ?? 0);
  const below = toNum(o?.Lowest) < toNum(o?.["Low fence"]), above = toNum(o?.Highest) > toNum(o?.["High fence"]);
  const side = below && above ? "both sides" : above ? "all high" : "all low";
  const longTail = fenced && out > 0 && outPct >= LONG;
  const lotEnd = (form?.lot_step ?? (form?.round_lots.every((v) => v % 1000 === 0) ? 1000 : 100)) === 1000 ? "000" : "00";

  // the findings row: one pill per thing worth knowing, each a measured fact
  const findings: Finding[] = [];
  if (times) findings.push({ tone: "warn", label: "Skewed", detail: `mean ${fmt(Math.round(times))}× the median` });
  if (longTail) findings.push({ tone: "warn", label: "Long tail", detail: `${pct(outPct)} past the IQR fence, ${side}` });
  if (fenced && extreme) findings.push({ tone: "neg", label: "Extreme value", detail: `${fmt(o?.Highest ?? st.Max)} · ${fmt(Math.round(extreme))}× the P99` });
  if (form && form.round_lots.length) findings.push({ tone: "info", label: "Round lots",
    detail: `${form.round_lots.length} of the top ${form.top.length} end in ${lotEnd}` });
  if (form && form.filled && form.fits) findings.push(form.places.max === 0
    ? { tone: "info", label: "Whole numbers", detail: `fits ${tight(form.fits)}` }
    : { tone: "info", label: "Decimals", detail: numberFormText(form) });
  const none = [["nulls", nulls], ["zeros", z], ["negatives", neg]].filter(([, n]) => n === 0).map(([w]) => `no ${w}`);
  if (none.length) findings.push({ tone: "pos", label: none.join(" · ").replace(/^n/, "N") });
  if (nulls) findings.push({ tone: "info", label: "Nulls", detail: `${num(nulls)} · ${pct(st["Null %"])}` });
  if (z) findings.push({ tone: "info", label: "Zeros", detail: `${num(z)} · ${pct(share(z, filled))}` });
  if (neg) findings.push({ tone: "info", label: "Negatives", detail: `${num(neg)} · ${pct(share(neg, filled))}` });

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
    ...(o || form ? [{ label: "Zero · negative",
      value: z || neg ? <>{num(z)} · {num(neg)}</> : <span className="ok-t">none</span>,
      sub: z || neg ? `${pct(share(z, filled))} · ${pct(share(neg, filled))}` : undefined }] : []),
  ].filter((s) => s.value !== "");

  const banner = skewed ? (
    <Callout tone="warn" icon="sparkle">
      <strong>Heavily skewed.</strong> {o && has(o.Median) ? `Half the values are ${fmt(o.Median)} or less; the` : "The"} mean is {fmt(st.Mean)}
      {times ? `, ${fmt(Math.round(times))}× the median` : ""}
      {o && has(o.P99) && has(st.Max) ? `; the top 1% runs from ${fmt(o.P99)} to ${fmt(st.Max)}` : ""}.{" "}
      {oneBin ? `Equal-width bins put ${pct(share(fullest, binTotal))} of rows in one bar, so the` : "The"} distribution below uses <strong>log bins</strong>.
      {longTail ? ` The ${pct(outPct)} past the fence are a long tail, not a few strays - see Outliers.` : ""}
    </Callout>
  ) : bins.length > 1 && binTotal > 0 && fullest <= (2 * binTotal) / bins.length ? (
    <Callout tone="pos" icon="check">
      <strong>Spread evenly.</strong> No equal-width bin holds more than {pct(share(fullest, binTotal))} of rows; the mean is {fmt(st.Mean)}{o && has(o.Median) ? `, the median ${fmt(o.Median)}` : ""}.
    </Callout>
  ) : null;

  // the bins of the mode picked, and one line on why
  let shown: Shown[] | null = null;
  let caption = "";
  const where = fullAt === 0 ? "the first" : fullAt === bins.length - 1 ? "the last" : "one";
  if (mode === "equal" && hist) {
    const span = bins.length ? Math.abs(Number(bins[bins.length - 1].hi) - Number(bins[0].lo)) : 0;
    const edge = (v: number | string) => (span >= 100 ? fmt(Math.round(Number(v))) : fmt(v));
    shown = bins.map((b) => ({ label: `${edge(b.lo)} - ${edge(b.hi)}`, n: b.n, share: share(b.n, binTotal) }));
    caption = oneBin ? `${pct(share(fullest, binTotal))} of rows fall in one of ${bins.length} bins${empty ? `, ${empty} empty` : ""} - Log shows the spread.`
      : mostEmpty ? `${empty} of ${bins.length} bins empty - Log shows the spread.`
      : `${bins.length} bins of equal width from the lowest to the highest value${empty ? `, ${empty} empty` : ""}.`;
  } else if (mode === "log" && form) {
    shown = form.log_bins.map((b) => ({ label: b.label, n: b.n, share: share(b.n, form.filled) }));
    caption = oneBin || mostEmpty
      ? `Equal width was tried first: ${empty} of ${bins.length} bins empty and ${pct(share(fullest, binTotal))} of rows in ${where} - switched to log bins. Percentile shows the P1 … P99 strip as bins.`
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
  const axis = (b: Shown, i: number) => {
    if (mode !== "log") return b.label.split(" - ")[0];
    const last = i === shown!.length - 1 && /^[\d,]+ - [\d,.]+$/.test(b.label);
    return last ? `${b.label.split(" - ")[0]} +` : b.label;
  };

  const dist = (
    <Panel title="Distribution" sub={mode === "log" ? "rows per order of magnitude" : mode === "pct" ? "rows between percentiles" : `${bins.length || 10} equal bins · rows per bin`}
      actions={<Seg mini label="Bins" value={mode} onChange={setPick} options={MODES} />}>
      <div className="panel-body">
        {!shown ? <p className="caption">{mode === "pct" ? "No percentiles for this column." : "Counting…"}</p>
          : !shown.length ? <p className="caption">No values to bin.</p>
          : <>
            {mode !== "pct" ? <>
              <div className="hist num-hist" role="img" aria-label={`Histogram of ${column}: ${shown.map((b) => `${b.label} ${num(b.n ?? 0)}`).join(", ")}`}>
                {shown.map((b, i) => <i key={i} style={{ height: `${(100 * b.share) / barTop}%` }} title={`${b.label}: ${num(b.n ?? 0)}`} />)}
              </div>
              <div className="num-hist-x" aria-hidden="true">{shown.map((b, i) => <span key={i} title={b.label}>{axis(b, i)}</span>)}</div>
            </> : (
              <div className="num-strip" role="img" aria-label={`Percentile strip of ${column}: ${shown.map((b) => b.label).join(", ")}`}>
                {shown.map((b, i) => (
                  <span key={i} style={{ flexGrow: b.share }} title={b.label}>
                    <em>{b.label.split(" · ")[1]?.split(" - ")[0]}</em>
                  </span>
                ))}
              </div>
            )}
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
      <Findings items={findings} label={`Findings for ${column}`} />
      <StatGrid stats={stats} />
      {banner}
      <div className="prof-grid prof-col-grid">
        <div className="prof-stack">
          {dist}
          <Outliers o={o} kind="number" filled={filled} st={st} made={made} />
        </div>
        <div className="prof-stack">
          <FormParts column={column} made={made} form={form} lotEnd={lotEnd} />
          <CouldBe column={column} made={made} />
          <NumFrequent column={column} made={made} st={st} />
          <Dependencies p={p} column={column} />
          <NotShown items={[{ label: "Shapes", why: "a number's shape is its digits before and after the point - see Form · parts" }]} />
        </div>
      </div>
    </>
  );
}

/** One group of /parts as bars: a label, a bar on the largest, the count and its share. */
function PartBars({ g, label = g.title }: { g: PartGroup; label?: string }) {
  const top = Math.max(1, ...g.rows.map((r) => r.n));
  return (
    <ul className="kv prof-kv" aria-label={label}>
      {g.rows.map((r) => (
        <li key={r.label}>
          <span className="m">{dash(r.label)}</span>
          <Bar pct={(100 * r.n) / top} tone="warn" />
          <span className="v">{num(r.n)} <span className="pc">· {pct(share(r.n, g.total))}</span></span>
        </li>
      ))}
    </ul>
  );
}

/** The column taken apart: digits before the point (GET /api/profiling/parts), places after it and the
 *  DECIMAL they fit, the before · after combinations when there is more than one, round lots among the
 *  most frequent (GET /api/profiling/numform). */
function FormParts({ column, made, form, lotEnd }: { column: string; made: string; form?: NumForm; lotEnd: string }) {
  const groups = useParts(column, made, 3).data?.groups ?? [];
  const g = (t: string) => groups.find((x) => x.title === t);
  const before = g("Digits before the point"), after = g("Places after the point"), both = g("Before · after");
  const head = { title: "Form · parts", sub: "digits, decimals, round numbers" };
  if (!form) return <Panel {...head}><div className="panel-body"><p className="caption">Reading…</p></div></Panel>;
  if (form.filled === 0) return <Panel {...head}><div className="panel-body"><p className="caption">No values.</p></div></Panel>;
  const { min, max } = form.places;
  // without /parts yet, the digits banded by /numform
  const digits: PartGroup = before ?? { title: "Digits before the point", total: form.filled, rows: form.before };
  const placeItem: Point = { label: "Places after the point", tone: "ok",
    value: min === max ? `${max} · every value` : `${min} to ${max}`,
    note: <>{max === 0 ? "whole numbers - " : ""}fits <code>{form.fits}</code></> };
  const lots: Point[] = form.round_lots.length ? [{ label: "Round lots", tone: "warn",
    value: form.round_lots.map((v) => fmt(v)).join(" · "),
    note: `${form.round_lots.length} of the ${form.top.length} most frequent values end in ${lotEnd}` }] : [];
  return (
    <Panel {...head}><div className="panel-body">
      <h4 className="eyebrow">Digits before the point</h4>
      <PartBars g={digits} />
      <Points name="Places after the point" items={[placeItem]} />
      {after && after.rows.length > 1 && <PartBars g={after} />}
      {both && both.rows.length > 1 && <>
        <h4 className="eyebrow">Before · after the point</h4>
        <PartBars g={both} label="Before · after" />
      </>}
      {lots.length > 0 && <Points name="Round lots" items={lots} />}
    </div></Panel>
  );
}

/** The ten most frequent with bars; the least frequent as bars, or as one inline list when each is seen once. */
function NumFrequent({ column, made, st }: { column: string; made: string; st: Row }) {
  const q = useFreq(column, made);
  const body = (() => {
    if (q.error) return <div className="note error">{(q.error as Error).message}</div>;
    if (!q.data) return <p className="caption">Reading…</p>;
    const { top, rest, all } = splitFreq(q.data.top, q.data.bottom);
    if (!rest) return <><span className="eyebrow">Every value · most to least frequent</span>
      <FreqBars t={top} numeric label={`Most frequent values of ${column}`} /></>;
    const rows = rowsOf(rest);
    const once = !all && rows.length > 0 && rows.every((r) => Number(r.Count) === 1);
    const scale = Math.max(1, ...rowsOf(top).map((r) => Number(r.Count ?? 0)));
    return <>
      <span className="eyebrow">Most frequent</span>
      <FreqBars t={top} numeric label={`Most frequent values of ${column}`} />
      {once ? <>
        <span className="eyebrow freq-rest">Least frequent · each once</span>
        <p className="num-once m" aria-label={`Least frequent values of ${column}`}>{rows.map((r) => fmt(r.Value)).join(" · ")}</p>
        <p className="caption">No bars - every count is 1.</p>
      </> : <>
        <span className="eyebrow accent freq-rest">{all ? `The other ${rows.length} · down to the least frequent` : "Least frequent"}</span>
        <FreqBars t={rest} numeric label={`Least frequent values of ${column}`} scale={all ? scale : undefined} tone={all ? "accent" : "warn"} />
      </>}
    </>;
  })();
  return <Panel title="Most and least frequent" sub={`${num(st.Distinct as number)} distinct`}><div className="panel-body">{body}</div></Panel>;
}
