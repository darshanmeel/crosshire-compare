// web/src/profiling/column/WhenView.tsx - a date or timestamp column's page (screens 19 and 21),
// for a typed column and for text or numbers read as one: range, span, precision, repeats, the
// calendar checks and rows per bin - all from GET /api/profiling/when.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Callout, num, Panel, Seg, StatGrid, type SegOption } from "../../ui/kit";
import { Dependencies, Points, share, type Point } from "../ColumnDetail";
import { pct } from "../frame";
import type { ColumnViewProps } from "./types";
import "./when.css";

export type WhenBin = "minute" | "hour" | "day" | "month" | "year" | "weekday";
type Count = { label: string; n: number };
export type WhenBody = {
  column: string; kind: "date" | "timestamp"; form: string; filled: number; distinct: number;
  first: string | null; last: string | null; span_seconds: number; days: number; date_only: number;
  weekend: number; first_of_month: number; future: number; today: string; before_1900: number;
  placeholders: { value: string; n: number }[]; fraction_digits: number; whole_ms: number | null; shared: number;
  repeated: { value: string; n: number; weekday: string }[]; bin: WhenBin; bins: Count[];
  weekday: Count[]; months: Count[]; quarters: Count[];
};

const MAX_BINS = 2000;          // the server draws no finer bin than this many over the span
const STEP: Partial<Record<WhenBin, number>> = { minute: 60, hour: 3600, day: 86400 };
const PLACEHOLDERS = ["1900-01-01", "1970-01-01", "9999-12-31", "0001-01-01"];
const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const TABLE_BINS = 24;          // bins up to which the chart has a table under it
const TICKS = 7;

export function useWhen(column: string, made: string, as: string, bin: WhenBin | "") {
  const q = new URLSearchParams({ column, as });
  if (bin) q.set("bin", bin);
  return useQuery({ queryKey: ["profiling-when", made, column, as, bin], enabled: !!made, placeholderData: keepPreviousData,
                    queryFn: () => api.get<WhenBody>(`/api/profiling/when?${q}`) });
}

const pad = (n: number) => String(n).padStart(2, "0");
const day = (s: string | null) => (s ?? "").slice(0, 10);
const clock = (s: string | null) => (s ?? "").slice(11);
const weekdayOf = (d: string) => WEEKDAY_NAMES[new Date(`${d}T00:00:00Z`).getUTCDay()];

/** Calendar years, months and days from one date to another: "8 y 8 m 27 d". */
export function ymd(a: string, b: string) {
  const [y1, m1, d1] = a.split("-").map(Number), [y2, m2, d2] = b.split("-").map(Number);
  const months = (y2 - y1) * 12 + (m2 - m1) - (d2 < d1 ? 1 : 0);
  // the first date moved on that many months, its day kept within the month it lands in
  const ym = (m1 - 1) + months, ay = y1 + Math.floor(ym / 12), am = ym % 12;
  const anchor = Date.UTC(ay, am, Math.min(d1, new Date(Date.UTC(ay, am + 1, 0)).getUTCDate()));
  const d = Math.round((Date.UTC(y2, m2 - 1, d2) - anchor) / 86400000);
  return `${Math.floor(months / 12)} y ${months % 12} m ${d} d`;
}

/** A span said the way it reads best: "12 h 00 m 41 s" within a day, "3 d 04 h 10 m" within 90, else years, months, days. */
export function spanText(w: Pick<WhenBody, "span_seconds" | "first" | "last" | "kind">) {
  const s = Math.floor(w.span_seconds);
  if (w.kind === "date" || s > 90 * 86400) return w.first && w.last ? ymd(day(w.first), day(w.last)) : "";
  if (s < 86400) return `${Math.floor(s / 3600)} h ${pad(Math.floor(s / 60) % 60)} m ${pad(s % 60)} s`;
  return `${Math.floor(s / 86400)} d ${pad(Math.floor(s / 3600) % 24)} h ${pad(Math.floor(s / 60) % 60)} m`;
}

const precision = (d: number) => (d === 0 ? "s" : d <= 3 ? "ms" : "µs");
const label = (b: WhenBin) => b[0].toUpperCase() + b.slice(1);

/** Rows per bin as CSS bars, a few edge labels under them; the bins said in full to a screen reader. */
function Bars({ bins, bin }: { bins: Count[]; bin: WhenBin }) {
  const top = Math.max(1, ...bins.map((b) => b.n));
  const every = Math.max(1, Math.ceil(bins.length / TICKS));
  const said = bins.slice(0, 60).map((b) => `${b.label} ${num(b.n)}`).join(", ") + (bins.length > 60 ? `, and ${num(bins.length - 60)} more` : "");
  return (<>
    <div className={bins.length > 60 ? "hist when-hist dense" : "hist when-hist"} role="img" aria-label={`Rows per ${bin}: ${said}`}>
      {bins.map((b, i) => <i key={i} style={{ height: `${(100 * b.n) / top}%` }} title={`${b.label}: ${num(b.n)}`} />)}
    </div>
    <div className="when-x" aria-hidden="true">
      {bins.map((b, i) => <span key={i}>{i % every === 0 ? b.label : ""}</span>)}
    </div>
  </>);
}

/** One plain line on the bins: flat, clustered or gapped - only what the counts show. */
function binLine(bins: Count[], bin: WhenBin) {
  if (bins.length < 2) return null;
  const ns = bins.map((b) => b.n);
  const top = Math.max(...ns), low = Math.min(...ns);
  const empty = ns.filter((n) => n === 0).length;
  if (empty) return `${num(empty)} empty ${bin}${empty > 1 ? "s" : ""} of ${num(bins.length)} - the values leave gaps.`;
  if (top <= low * 1.25) return `Flat: ${num(low)} - ${num(top)} rows a ${bin}.`;
  if (top >= low * 4) return `Clustered: the fullest ${bin} holds ${num(top)} rows, the emptiest ${num(low)}.`;
  return `${num(low)} - ${num(top)} rows a ${bin}.`;
}

function BinTable({ bins, bin, total }: { bins: Count[]; bin: WhenBin; total: number }) {
  const per = Math.ceil(bins.length / 3);
  const cols = [0, 1, 2].map((c) => bins.slice(c * per, (c + 1) * per));
  const cell = (b?: Count) => b
    ? <><td className="m">{b.label}</td><td className="num m">{num(b.n)}</td><td className="num m dim">{pct(share(b.n, total))}</td></>
    : <><td /><td /><td /></>;
  const head = label(bin);
  return (
    <div className="tblwrap">
      <table className="tbl compact prof-bins when-bins" aria-label={`Rows per ${bin}`}>
        <thead><tr>{[0, 1, 2].map((c) => <ThreeHead key={c} head={head} first={c === 0} />)}</tr></thead>
        <tbody>{cols[0].map((b, i) => <tr key={i}>{cell(b)}{cell(cols[1][i])}{cell(cols[2][i])}</tr>)}</tbody>
      </table>
    </div>
  );
}
const ThreeHead = ({ head, first }: { head: string; first: boolean }) =>
  <><th className={first ? undefined : "b2"}>{head}</th><th className="num">Rows</th><th className="num">Share</th></>;

/** A bar list: label, bar on the list's own scale, count and share. */
function Counts({ name, rows, total, mark }: { name: string; rows: { key: string; label: ReactNode; n: number }[]; total: number; mark?: (k: string) => boolean }) {
  const top = Math.max(1, ...rows.map((r) => r.n));
  return (
    <ul className="kv prof-kv when-kv" aria-label={name}>
      {rows.map((r) => (
        <li key={r.key}>
          <span className={mark?.(r.key) ? "m when-we" : "m"}>{r.label}</span>
          <span className="bar"><i style={{ width: `${(100 * r.n) / top}%` }} /></span>
          <span className="v">{num(r.n)} <span className="pc">· {pct(share(r.n, total))}</span></span>
        </li>
      ))}
    </ul>
  );
}

function Chart({ w, bin, setBin, options, children }: { w: WhenBody; bin: WhenBin; setBin: (b: WhenBin) => void; options: SegOption<WhenBin>[]; children?: ReactNode }) {
  const bins = w.bins;
  const sub = bins.length ? `${bins[0].label} - ${bins[bins.length - 1].label} · ${num(bins.length)} bin${bins.length === 1 ? "" : "s"}` : undefined;
  return (
    <Panel title={`Rows per ${bin}`} sub={sub} actions={<Seg mini label="Bin by" value={bin} onChange={setBin} options={options} />}>
      <div className="panel-body">
        {bins.length ? <Bars bins={bins} bin={bin} /> : <p className="caption">No values to bin.</p>}
        {children}
      </div>
    </Panel>
  );
}

function binOptions(w: WhenBody, list: WhenBin[]): SegOption<WhenBin>[] {
  return list.map((b) => {
    const too = STEP[b] ? w.span_seconds / STEP[b]! > MAX_BINS : false;
    return { value: b, label: label(b), disabled: too, title: too ? `More than ${num(MAX_BINS)} bins over this span` : undefined };
  });
}

function Timestamp({ p, column, st, w, bin, setBin }: ColumnViewProps & { w: WhenBody; bin: WhenBin; setBin: (b: WhenBin) => void }) {
  const rows = Number(st.Rows), nulls = Number(st.Nulls);
  const oneDay = w.days === 1;
  const top = w.repeated[0];
  const stats = [
    { label: "Rows", value: num(rows) },
    { label: "Nulls", value: <>{num(nulls)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: num(w.distinct), sub: `${pct(share(w.distinct, w.filled))} of filled` },
    { label: "First", value: w.first ?? "" },
    { label: "Last", value: w.last ?? "" },
    { label: "Span", value: spanText(w), sub: oneDay ? "one calendar day" : `${num(w.days)} calendar days` },
    { label: "Precision", value: precision(w.fraction_digits),
      sub: w.fraction_digits ? `${w.fraction_digits} fractional digit${w.fraction_digits > 1 ? "s" : ""}` : "whole seconds" },
    top ? { label: "Top stamp", value: oneDay ? clock(top.value) : top.value, sub: `×${num(top.n)}` }
        : { label: "Top stamp", value: "none", sub: "every stamp once" },
  ];
  const left = Math.max(0, rows - nulls - w.filled);
  const range = oneDay
    ? <>Every stamp falls on {day(w.first)} between {clock(w.first).slice(0, 5)} and {clock(w.last).slice(0, 5)}.</>
    : <>The stamps run from {w.first} to {w.last}.</>;
  const opts = binOptions(w, w.span_seconds > 90 * 86400 ? ["minute", "hour", "day", "month"] : ["minute", "hour", "day"]);
  const outl: Point[] = [
    { label: "Calendar days", value: oneDay ? <>1 · {day(w.first)}</> : num(w.days), tone: "ok" },
    { label: "Date-only stamps", value: w.date_only ? <>{num(w.date_only)} <span className="pc">· {pct(share(w.date_only, w.filled))}</span></> : "0",
      tone: w.date_only ? "warn" : "ok",
      note: w.date_only ? "at 00:00:00 - dates stored as stamps, or a default time" : "no midnight values - every row carries a time" },
    { label: "Weekend", value: w.weekend ? <>{num(w.weekend)} <span className="pc">· {pct(share(w.weekend, w.filled))}</span></> : "none",
      tone: "ok", note: oneDay && w.first ? `${day(w.first)} is a ${weekdayOf(day(w.first))}` : undefined },
  ];
  if (w.future) outl.push({ label: "In the future", value: num(w.future), tone: "warn", note: `after today, ${w.today}` });
  const ph = w.placeholders.reduce((s, x) => s + x.n, 0);
  if (ph) outl.push({ label: "Placeholders", value: num(ph), tone: "warn", note: w.placeholders.map((x) => `${x.value} ×${num(x.n)}`).join(" · ") });
  const reps: Point[] = [
    { label: "Fractional digits", value: w.fraction_digits ? String(w.fraction_digits) : "none", tone: "ok",
      note: w.fraction_digits ? `to the ${precision(w.fraction_digits) === "ms" ? "millisecond" : "microsecond"}` : "stamps to the second" },
    ...(w.whole_ms != null ? [{ label: "Whole milliseconds", value: <>{num(w.whole_ms)} <span className="pc">· {pct(share(w.whole_ms, w.filled))}</span></>,
      tone: w.whole_ms && w.whole_ms < w.filled ? "warn" as const : "ok" as const,
      note: <>microseconds ending in <code>000</code></> }] : []),
    { label: "Shared stamps", value: <>{num(w.shared)} <span className="pc">· {pct(share(w.shared, w.filled))} of filled</span></>,
      tone: w.shared ? "warn" : "ok", note: `${num(w.filled)} filled - ${num(w.distinct)} distinct` },
  ];
  const allWhole = w.fraction_digits === 6 && w.repeated.length > 0 && w.repeated.every((r) => r.value.endsWith("000"));
  return (<>
    <StatGrid stats={stats} />
    <Callout tone="pos" icon="check">
      <strong>Read as a timestamp.</strong>{w.form && <> Written as <code>{w.form}</code>.</>} {range}
      {left > 0 && <> {num(left)} filled value{left > 1 ? "s do" : " does"} not read and {left > 1 ? "are" : "is"} left out.</>}
    </Callout>
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">
        <Chart w={w} bin={bin} setBin={setBin} options={opts}>
          <Points name="Session" items={[
            { label: "Session", tone: "ok", value: <>{oneDay ? clock(w.first) : w.first} → {oneDay ? clock(w.last) : w.last} · {spanText(w)}</>, note: "first and last stamp" },
            { label: "Nulls", tone: nulls ? "warn" : "ok", value: <>{num(nulls)} rows <span className="pc">· {pct(st["Null %"])}</span></>,
              note: nulls ? "rows with no stamp" : undefined },
          ]} />
        </Chart>
        <Panel title="Precision and repeats" sub="how fine the stamps are, and which ones repeat"><div className="panel-body">
          <Points name="Precision and repeats" items={reps} />
          <span className="eyebrow">Most repeated stamps</span>
          {w.repeated.length
            ? <Counts name="Most repeated stamps" total={w.filled} rows={w.repeated.map((r) => ({ key: r.value, label: r.value, n: r.n }))} />
            : <p className="caption">no stamp repeats</p>}
          {allWhole && <p className="caption">all {num(w.repeated.length)} end in <code>000</code></p>}
        </div></Panel>
      </div>
      <div className="prof-stack">
        <Panel title="Outliers" sub="the calendar around the stamps"><div className="panel-body">
          <Points name="Outlier findings" items={outl} />
        </div></Panel>
        <Dependencies p={p} column={column} />
      </div>
    </div>
  </>);
}

function DateView({ p, column, st, w, bin, setBin }: ColumnViewProps & { w: WhenBody; bin: WhenBin; setBin: (b: WhenBin) => void }) {
  const rows = Number(st.Rows), nulls = Number(st.Nulls);
  const top = w.repeated[0];
  const we = share(w.weekend, w.filled);
  const spanDays = Math.round(w.span_seconds / 86400);
  const stats = [
    { label: "Rows", value: num(rows) },
    { label: "Nulls", value: <>{num(nulls)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: num(w.distinct), sub: `${pct(share(w.distinct, rows))} of rows` },
    { label: "First", value: w.first ?? "" },
    { label: "Last", value: w.last ?? "" },
    { label: "Span", value: spanText(w), sub: `${num(spanDays)} day${spanDays === 1 ? "" : "s"}` },
    top ? { label: "Top date", value: top.value, sub: `×${num(top.n)}` } : { label: "Top date", value: "none", sub: "every date once" },
    { label: "Weekend", value: <>{num(w.weekend)} <span className="pc">· {pct(we)}</span></> },
  ];
  const days = w.weekday.slice(0, 5).map((d) => d.n);
  const left = Math.max(0, rows - nulls - w.filled);
  const ph = w.placeholders.reduce((s, x) => s + x.n, 0);
  const checks: Point[] = [
    { label: "In the future", value: num(w.future), tone: w.future ? "warn" : "ok", note: `after today, ${w.today}` },
    { label: "Before 1900", value: num(w.before_1900), tone: w.before_1900 ? "warn" : "ok" },
    { label: "Placeholders", value: num(ph), tone: ph ? "warn" : "ok",
      note: ph ? w.placeholders.map((x) => `${x.value} ×${num(x.n)}`).join(" · ") : PLACEHOLDERS.join(" · ") },
    { label: "Weekend", value: <>{num(w.weekend)} <span className="pc">· {pct(we)}</span></>, tone: w.weekend ? "warn" : "ok",
      note: "2 in 7 days are a Saturday or Sunday - 28.57% if dates fall evenly" },
    { label: "First of a month", value: <>{num(w.first_of_month)} <span className="pc">· {pct(share(w.first_of_month, w.filled))}</span></>,
      note: "about 1 in 30 if dates fall evenly" },
    { label: "Format", tone: left ? "warn" : "ok",
      value: w.form ? <><code>{w.form}</code> · {left ? `${num(left)} do not read` : "every value"}</> : "a date column",
      note: w.form ? (left ? "the values that do not read are left out here" : undefined) : "stored as a date - no text to read" },
  ];
  const line = binLine(w.bins, bin);
  const banner = w.weekend
    ? <><strong>{pct(we)} of {column} values fall on a Saturday or Sunday</strong>{days.length === 5 && <>, and Monday to Friday hold {num(Math.min(...days))} - {num(Math.max(...days))} each</>}.</>
    : <><strong>No {column} value falls on a weekend.</strong> Monday to Friday hold {num(Math.min(...days))} - {num(Math.max(...days))} each.</>;
  return (<>
    <StatGrid stats={stats} />
    <Callout tone={w.weekend ? "warn" : "pos"} icon={w.weekend ? "sparkle" : "check"}>
      {w.form && <>Read as a date in <code>{w.form}</code>. </>}{banner}
    </Callout>
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">
        <Chart w={w} bin={bin} setBin={setBin} options={binOptions(w, ["month", "year", "weekday"])}>
          {w.bins.length > 0 && w.bins.length <= TABLE_BINS && <BinTable bins={w.bins} bin={bin} total={w.filled} />}
          {line && <p className="prof-said">{line}</p>}
        </Chart>
        <Panel title="Weekday and month" sub="where the dates land in the week and the year"><div className="panel-body when-cal">
          <span className="eyebrow">Weekday</span>
          <Counts name="Weekday" total={w.filled} rows={w.weekday.map((d) => ({ key: d.label, label: d.label, n: d.n }))}
            mark={(k) => k === "Sat" || k === "Sun"} />
          <span className="eyebrow">Quarter</span>
          <Counts name="Quarter" total={w.filled} rows={w.quarters.map((q) => ({ key: q.label, label: q.label, n: q.n }))} />
        </div></Panel>
      </div>
      <div className="prof-stack">
        <Panel title="Calendar checks" sub="the dates that usually mean trouble"><div className="panel-body">
          <Points name="Calendar checks" items={checks} />
        </div></Panel>
        <Panel title="Most repeated dates" sub={`${num(w.distinct)} distinct · ${num(w.shared)} rows share a date`}><div className="panel-body">
          {w.repeated.length
            ? <Counts name="Most repeated dates" total={w.filled}
                rows={w.repeated.map((r) => ({ key: r.value, label: <>{r.value} <span className="when-wd">{r.weekday}</span></>, n: r.n }))} />
            : <p className="caption">no date repeats</p>}
        </div></Panel>
        <Dependencies p={p} column={column} />
      </div>
    </div>
  </>);
}

export function WhenView(props: ColumnViewProps) {
  const { column, made, as } = props;
  const [pick, setPick] = useState<{ column: string; as: string; bin: WhenBin } | null>(null);
  const chosen = pick && pick.column === column && pick.as === as ? pick.bin : "";
  const q = useWhen(column, made, as, chosen);
  const setBin = (bin: WhenBin) => setPick({ column, as, bin });
  if (q.error) return <div className="note error">{(q.error as Error).message}</div>;
  const w = q.data;
  if (!w || w.column !== column) return <p className="caption">Counting…</p>;
  const bin = w.bin;
  return w.kind === "timestamp"
    ? <Timestamp {...props} w={w} bin={bin} setBin={setBin} />
    : <DateView {...props} w={w} bin={bin} setBin={setBin} />;
}
