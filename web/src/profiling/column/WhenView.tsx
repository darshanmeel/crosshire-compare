// web/src/profiling/column/WhenView.tsx - a date or timestamp column's page (screens 26 and 28, v3),
// for a typed column and for text or numbers read as one: the findings row, range, span, precision,
// how the values are written, repeats, the calendar checks, rows per bin and the column taken apart
// by weekday, hour, month, quarter and year - all from GET /api/profiling/when.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Callout, num, Panel, Seg, StatGrid, type SegOption } from "../../ui/kit";
import { Dependencies, NotShown, Points, share, type Point } from "../ColumnDetail";
import { pct } from "../frame";
import { Findings, type Finding } from "./Findings";
import type { ColumnViewProps } from "./types";
import "./when.css";

export type WhenBin = "minute" | "hour" | "day" | "month" | "year" | "weekday";
type Count = { label: string; n: number };
/** How a text column read as a date or a timestamp is written: its shapes (digits 9, letters A),
 *  the digits after the seconds' point, how many values carry a number above 12 in the first and
 *  the second slot, and its latest value as text with what that reads as. */
export type WhenWritten = {
  shapes: { shape: string; n: number; example: string; spelled: string }[]; shape_count: number;
  fractions: { digits: number; n: number }[]; first_over_12: number; second_over_12: number;
  text_last: { text: string; read: string | null } | null;
};
export type WhenBody = {
  column: string; kind: "date" | "timestamp"; form: string; filled: number; distinct: number;
  first: string | null; last: string | null; span_seconds: number; days: number; date_only: number;
  weekend: number; first_of_month: number; future: number; today: string; before_1900: number;
  placeholders: { value: string; n: number }[]; fraction_digits: number; whole_ms: number | null; shared: number;
  repeated: { value: string; n: number; weekday: string }[]; bin: WhenBin; bins: Count[];
  weekday: Count[]; months: Count[]; quarters: Count[]; hours?: Count[]; years?: Count[];
  /** The time of day most stamps fall in (quartiles ± 1.5 IQR, kept within the day) and the stamps outside it. */
  session?: { from: string; to: string; before: number; after: number } | null;
  written?: WhenWritten | null;
};

const MAX_BINS = 2000;          // the server draws no finer bin than this many over the span
const STEP: Partial<Record<WhenBin, number>> = { minute: 60, hour: 3600, day: 86400 };
const PLACEHOLDERS = ["1900-01-01", "1970-01-01", "9999-12-31", "0001-01-01"];
const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TABLE_BINS = 24;          // bins up to which the chart has a table under it
const TICKS = 7;
const BATCH = 10;               // a date is a batch from this many rows, and three times the next one

export function useWhen(column: string, made: string, as: string, bin: WhenBin | "") {
  const q = new URLSearchParams({ column, as });
  if (bin) q.set("bin", bin);
  return useQuery({ queryKey: ["profiling-when", made, column, as, bin], enabled: !!made, placeholderData: keepPreviousData,
                    queryFn: () => api.get<WhenBody>(`/api/profiling/when?${q}`) });
}

/** The format a column is read in, as the header shows it next to "read as": %n (1 to 9 digits)
 *  said as %f when no value has more than 6, ISO said as ISO 8601, and a trailing letter the
 *  values carry (the Z of UTC) put back on the end. Empty for a column stored as a date or timestamp. */
export function formText(w: Pick<WhenBody, "form" | "written"> | undefined): string {
  if (!w?.form) return "";
  if (w.form === "ISO") return "ISO 8601";
  const most = Math.max(0, ...(w.written?.fractions ?? []).map((f) => f.digits));
  const tail = /[A-Za-z]+$/.exec(w.written?.shapes[0]?.example ?? "")?.[0] ?? "";
  const form = most <= 6 ? w.form.replace("%n", "%f") : w.form;
  return tail && !form.endsWith(tail) ? form + tail : form;
}

/** For ColumnDetail's header: the form a column read as a date or a timestamp is read in - the
 *  same (cached) query the page below makes, so it costs nothing more. */
export function useWhenForm(column: string, made: string, as: string): string {
  const when = as === "date" || as === "timestamp";
  const q = useWhen(column, when ? made : "", as, "");
  return when && q.data?.column === column ? formText(q.data) : "";
}

const pad = (n: number) => String(n).padStart(2, "0");
const day = (s: string | null) => (s ?? "").slice(0, 10);
const clock = (s: string | null) => (s ?? "").slice(11);
const weekdayOf = (d: string) => WEEKDAY_NAMES[new Date(`${d}T00:00:00Z`).getUTCDay()];
const sum = (xs: Count[] | undefined) => (xs ?? []).reduce((s, x) => s + x.n, 0);
const some = (xs: Count[] | undefined) => (xs ?? []).filter((x) => x.n > 0);
const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;

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

/** The date with far more rows than the others: at least BATCH rows and three times the next most repeated. */
export function batchOf(w: Pick<WhenBody, "repeated">) {
  const [top, next] = w.repeated;
  const background = next?.n ?? 1;
  return top && top.n >= BATCH && top.n >= 3 * background ? { ...top, background } : null;
}

const precision = (d: number) => (d === 0 ? "s" : d <= 3 ? "ms" : "µs");
const label = (b: WhenBin) => b[0].toUpperCase() + b.slice(1);

/** A year bin said with the months it holds when the data starts or stops inside it: "2026 to Sep". */
function binLabel(l: string, bin: WhenBin, w: WhenBody) {
  if (bin !== "year" || !w.first || !w.last) return l;
  const [fy, fm] = [w.first.slice(0, 4), Number(w.first.slice(5, 7))], [ly, lm] = [w.last.slice(0, 4), Number(w.last.slice(5, 7))];
  if (fy === ly) return l;
  if (l === ly && lm < 12) return `${l} to ${MONTH_NAMES[lm - 1]}`;
  if (l === fy && fm > 1) return `${l} from ${MONTH_NAMES[fm - 1]}`;
  return l;
}

/** Rows per bin as CSS bars, a few edge labels under them; the bins said in full to a screen reader. */
function Bars({ bins, bin, mark }: { bins: Count[]; bin: WhenBin; mark?: string }) {
  const top = Math.max(1, ...bins.map((b) => b.n));
  const every = Math.max(1, Math.ceil(bins.length / TICKS));
  const said = bins.slice(0, 60).map((b) => `${b.label} ${num(b.n)}`).join(", ") + (bins.length > 60 ? `, and ${num(bins.length - 60)} more` : "");
  return (<>
    <div className={bins.length > 60 ? "hist when-hist dense" : "hist when-hist"} role="img" aria-label={`Rows per ${bin}: ${said}`}>
      {bins.map((b, i) => <i key={i} className={b.label === mark ? "when-mark" : undefined} style={{ height: `${(100 * b.n) / top}%` }} title={`${b.label}: ${num(b.n)}`} />)}
    </div>
    <div className="when-x" aria-hidden="true">
      {bins.map((b, i) => <span key={i}>{i % every === 0 || (bins.length <= 12 && i === bins.length - 1) ? b.label : ""}</span>)}
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

function BinTable({ w, bin }: { w: WhenBody; bin: WhenBin }) {
  const bins = w.bins;
  const per = Math.ceil(bins.length / 3);
  const cols = [0, 1, 2].map((c) => bins.slice(c * per, (c + 1) * per));
  const cell = (b?: Count) => b
    ? <><td className="m">{binLabel(b.label, bin, w)}</td><td className="num m">{num(b.n)}</td><td className="num m dim">{pct(share(b.n, w.filled))}</td></>
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
const countRows = (xs: Count[]) => xs.map((x) => ({ key: x.label, label: x.label, n: x.n }));
const weekend = (k: string) => k === "Sat" || k === "Sun";

function Chart({ w, bin, setBin, options, mark, children }: { w: WhenBody; bin: WhenBin; setBin: (b: WhenBin) => void; options: SegOption<WhenBin>[]; mark?: string; children?: ReactNode }) {
  const bins = w.bins;
  const sub = bins.length ? `${bins[0].label} - ${bins[bins.length - 1].label} · ${plural(bins.length, "bin")}` : undefined;
  return (
    <Panel title={`Rows per ${bin}`} sub={sub} actions={<Seg mini label="Bin by" value={bin} onChange={setBin} options={options} />}>
      <div className="panel-body">
        {bins.length ? <Bars bins={bins} bin={bin} mark={mark} /> : <p className="caption">No values to bin.</p>}
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

const count = (n: number, of: number) => <>{num(n)} <span className="pc">· {pct(share(n, of))}</span></>;

/** The findings both kinds share: values that do not read, nulls, the future, placeholders, before 1900. */
function trouble(w: WhenBody, nulls: number, nullPct: unknown, left: number): Finding[] {
  const ph = w.placeholders.reduce((s, x) => s + x.n, 0);
  return [
    ...(nulls ? [{ tone: "warn" as const, label: `Missing ${pct(nullPct)}`, detail: plural(nulls, "row") }] : []),
    ...(left ? [{ tone: "warn" as const, label: `${num(left)} do not read`, detail: `as a ${w.kind}${w.form ? ` in ${formText(w)}` : ""}` }] : []),
    ...(w.future ? [{ tone: "warn" as const, label: "In the future", detail: `${plural(w.future, w.kind)} after ${w.today}` }] : []),
    ...(ph ? [{ tone: "warn" as const, label: "Placeholders", detail: w.placeholders.map((x) => `${x.value} ×${num(x.n)}`).join(" · ") }] : []),
    ...(w.before_1900 ? [{ tone: "warn" as const, label: "Before 1900", detail: plural(w.before_1900, w.kind) }] : []),
  ];
}

/** The format finding: the shape the values take, the format read from it, and how sure. */
function formatFinding(w: WhenBody): Finding | null {
  const top = w.written?.shapes[0];
  if (!top || !w.form) return null;
  const many = (w.written?.shape_count ?? 1) > 1;
  return { tone: many ? "warn" : "pos", label: w.kind === "timestamp" ? "Format inferred from the shape" : "Format inferred",
    detail: <>{w.kind === "timestamp" ? top.spelled : top.shape} → {formText(w)}{many ? ` · ${plural(w.written!.shape_count, "shape")}` : ""}
      {w.kind === "date" && slotNote(w) ? ` · ${slotNote(w)}` : ""}</> };
}

/** Which slot holds the day, from the values that carry a number above 12 in it. */
function slotNote(w: WhenBody): string {
  const wr = w.written;
  if (!wr) return "";
  const [a, b] = [wr.first_over_12, wr.second_over_12];
  if (a && b) return `${num(a)} values carry a number above 12 in the first slot and ${num(b)} in the second`;
  if (a) return `day first: ${num(a)} value${a === 1 ? " carries" : "s carry"} a day above 12 in the first slot`;
  if (b) return `month first: ${num(b)} value${b === 1 ? " carries" : "s carry"} a day above 12 in the second slot`;
  return "";
}

/** The year and month parts: bars when there is more than one, else one line. */
function YearMonth({ w }: { w: WhenBody }) {
  const years = some(w.years), months = some(w.months);
  if (w.days === 1 && w.first) return <p className="caption">Year and month: all on {day(w.first)}</p>;
  return (<>
    {years.length > 1 ? <><span className="eyebrow">Year</span><Counts name="Year" total={w.filled} rows={countRows(years)} /></>
      : years.length === 1 && <p className="caption">Year: all in {years[0].label}</p>}
    {months.length > 1 ? <><span className="eyebrow">Month</span><Counts name="Month" total={w.filled} rows={countRows(w.months)} /></>
      : months.length === 1 && <p className="caption">Month: all in {months[0].label}</p>}
  </>);
}

function Timestamp({ p, column, st, w, bin, setBin }: ColumnViewProps & { w: WhenBody; bin: WhenBin; setBin: (b: WhenBin) => void }) {
  const rows = Number(st.Rows), nulls = Number(st.Nulls);
  const oneDay = w.days === 1;
  const top = w.repeated[0];
  const wr = w.written;
  const shape = wr?.shapes[0];
  // the digits after the seconds' point as written - stamps with none count too: 10:00:00 next to 10:00:00.123 is mixed
  const fr = wr?.fractions ?? [];
  const mixed = fr.length > 1;
  const wholeShare = w.whole_ms != null ? share(w.whole_ms, w.filled) : 0;
  const s = w.session;
  const outside = s ? s.before + s.after : 0;
  const left = Math.max(0, rows - nulls - w.filled);
  const uniq = share(w.distinct, w.filled);
  const findings: Finding[] = [
    ...[formatFinding(w)].filter((f): f is Finding => !!f),
    ...trouble(w, nulls, st["Null %"], left),
    ...(mixed ? [{ tone: "warn" as const, label: "Mixed precision", detail: fr.map((f) => `${plural(f.digits, "digit")} ×${num(f.n)}`).join(" · ") }]
      : w.whole_ms != null && wholeShare > 1 && w.whole_ms < w.filled
        ? [{ tone: "warn" as const, label: "Mixed precision", detail: `${pct(wholeShare)} whole milliseconds` }] : []),
    ...(w.filled && uniq >= 95 ? [{ tone: "info" as const, label: uniq === 100 ? "Unique" : "Near-unique", detail: `${pct(uniq)} distinct` }] : []),
    ...(oneDay ? [{ tone: "info" as const, label: "Single day", detail: `${day(w.first)} · ${clock(w.first).slice(0, 5)} - ${clock(w.last).slice(0, 5)}` }] : []),
    ...(s ? [outside
      ? { tone: "warn" as const, label: `${plural(outside, "stamp")} outside the session`, detail: `before ${s.from} or after ${s.to}` }
      : { tone: "pos" as const, label: "No out-of-session stamps" }] : []),
  ];
  const stats = [
    { label: "Rows", value: num(rows) },
    { label: "Nulls", value: <>{num(nulls)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: num(w.distinct), sub: `${pct(uniq)} of filled` },
    { label: "First", value: w.first ?? "" },
    { label: "Last", value: w.last ?? "" },
    { label: "Span", value: spanText(w), sub: oneDay ? "one calendar day" : `${num(w.days)} calendar days` },
    { label: "Precision", value: precision(w.fraction_digits),
      sub: w.fraction_digits ? `${w.fraction_digits} fractional digit${w.fraction_digits > 1 ? "s" : ""}` : "whole seconds" },
    top ? { label: "Top stamp", value: oneDay ? clock(top.value) : top.value, sub: `×${num(top.n)}` }
        : { label: "Top stamp", value: "none", sub: "every stamp once" },
  ];
  const range = oneDay
    ? <>Every stamp falls on {day(w.first)} between {clock(w.first).slice(0, 5)} and {clock(w.last).slice(0, 5)}.</>
    : <>The stamps run from {w.first} to {w.last}.</>;
  const opts = binOptions(w, w.span_seconds > 90 * 86400 ? ["minute", "hour", "day", "month"] : ["minute", "hour", "day"]);
  const ph = w.placeholders.reduce((acc, x) => acc + x.n, 0);
  const outl: Point[] = [
    { label: "Calendar days", value: oneDay ? <>1 · {day(w.first)}</> : num(w.days), tone: "ok" },
    { label: "Date-only stamps", value: w.date_only ? count(w.date_only, w.filled) : "0",
      tone: w.date_only ? "warn" : "ok",
      note: w.date_only ? "at 00:00:00 - dates stored as stamps, or a default time" : "no midnight values - every row carries a time" },
    ...(s ? [{ label: "Before first · after last", value: `${num(s.before)} · ${num(s.after)}`, tone: outside ? "warn" as const : "ok" as const,
      note: `the session is ${s.from} - ${s.to}, the time of day the middle half of the stamps falls in widened by 1.5 times its length` }] : []),
    { label: "Weekend", value: w.weekend ? count(w.weekend, w.filled) : "no",
      tone: "ok", note: oneDay && w.first ? `${day(w.first)} is a ${weekdayOf(day(w.first))}` : undefined },
    ...(w.future ? [{ label: "In the future", value: num(w.future), tone: "warn" as const, note: `after today, ${w.today}` }] : []),
    ...(ph ? [{ label: "Placeholders", value: num(ph), tone: "warn" as const, note: w.placeholders.map((x) => `${x.value} ×${num(x.n)}`).join(" · ") }] : []),
  ];
  const fracValue = mixed ? `${fr[0].digits} - ${fr[fr.length - 1].digits} · mixed`
    : fr.length === 1 && fr[0].digits > 0 ? `${fr[0].digits} · ${fr[0].n === w.filled ? "every value" : `${num(fr[0].n)} values`}`
    : w.fraction_digits ? String(w.fraction_digits) : "none";
  const fracNote = mixed ? fr.map((f) => `${plural(f.digits, "digit")} ×${num(f.n)}`).join(" · ")
    : shape && wr!.shape_count === 1 ? `one shape covers all ${num(w.filled)} filled rows: ${shape.spelled}`
    : w.fraction_digits ? `to the ${precision(w.fraction_digits) === "ms" ? "millisecond" : "microsecond"}` : "stamps to the second";
  const reps: Point[] = [
    ...(shape ? [{ label: "Shape → format", tone: wr!.shape_count > 1 ? "warn" as const : "ok" as const,
      value: <><code>{shape.shape}</code> → <code>{formText(w)}</code></>,
      note: wr!.shape_count > 1
        ? `${plural(wr!.shape_count, "shape")}; the top one covers ${num(shape.n)} of ${num(w.filled)} rows: ${wr!.shapes.slice(1).map((x) => `${x.shape} ×${num(x.n)}`).join(" · ")}`
        : shape.spelled }] : []),
    { label: "Fractional digits", value: fracValue, tone: mixed ? "warn" : "ok", note: fracNote },
    ...(w.whole_ms != null ? [{ label: "Whole milliseconds", value: <>{count(w.whole_ms, w.filled)} end in <code>000</code></>,
      tone: w.whole_ms && w.whole_ms < w.filled && wholeShare > 1 ? "warn" as const : "ok" as const,
      note: "microsecond stamps whose last three digits are 0" }] : []),
    { label: "Shared stamps", value: <>{num(w.shared)} rows <span className="pc">· {pct(share(w.shared, w.filled))} of filled</span></>,
      tone: w.shared ? "warn" : "ok", note: `${num(w.filled)} filled - ${num(w.distinct)} distinct${w.repeated.length ? "; the busiest stamps below" : ""}` },
  ];
  const allWhole = w.fraction_digits === 6 && w.repeated.length > 0 && w.repeated.every((r) => r.value.endsWith("000"));
  const hours = some(w.hours);
  const hourRange = hours.length ? (w.hours ?? []).slice(Number(hours[0].label), Number(hours[hours.length - 1].label) + 1) : [];
  return (<>
    <Findings items={findings} />
    <StatGrid stats={stats} />
    <Callout tone="pos" icon="check">
      <strong>Read as a timestamp.</strong>{shape && w.form
        ? <> <code>{shape.example}</code> → <code>{formText(w)}</code>.</>
        : w.form && <> Written as <code>{formText(w)}</code>.</>} {range}
      {left > 0 && <> {num(left)} filled value{left > 1 ? "s do" : " does"} not read and {left > 1 ? "are" : "is"} left out.</>}
    </Callout>
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">
        <Chart w={w} bin={bin} setBin={setBin} options={opts}>
          <Points name="Session" items={[
            { label: "Session", tone: outside ? "warn" : "ok", value: <>{oneDay ? clock(w.first) : w.first} → {oneDay ? clock(w.last) : w.last} · {spanText(w)}</>,
              note: s ? (outside ? `first and last stamp; ${plural(outside, "stamp")} before ${s.from} or after ${s.to}` : "first and last stamp; none outside the session") : "first and last stamp" },
            { label: "Nulls", tone: nulls ? "warn" : "ok", value: <>{num(nulls)} rows <span className="pc">· {pct(st["Null %"])}</span></>,
              note: nulls ? <>rows with no stamp - <code>{column} IS NULL</code></> : undefined },
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
        <Panel title="Outliers" sub="stamps that do not belong to the session"><div className="panel-body">
          <Points name="Outlier findings" items={outl} />
        </div></Panel>
        <Panel title="Parts · week and day" sub="the stamps taken apart by weekday and hour"><div className="panel-body when-cal">
          <span className="eyebrow">Weekday</span>
          <Counts name="Weekday" total={w.filled} rows={countRows(w.weekday)} mark={weekend} />
          {hourRange.length > 0 && <><span className="eyebrow">Hour of day</span>
            <Counts name="Hour of day" total={w.filled} rows={hourRange.map((h) => ({ key: h.label, label: `${h.label}:00`, n: h.n }))} /></>}
          <YearMonth w={w} />
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
  const batch = batchOf(w);
  const left = Math.max(0, rows - nulls - w.filled);
  const ph = w.placeholders.reduce((s, x) => s + x.n, 0);
  const tl = w.written?.text_last;
  const clean = [!w.future && "no future dates", !ph && "no placeholders", !nulls && "no nulls"].filter(Boolean) as string[];
  const findings: Finding[] = [
    ...[formatFinding(w)].filter((f): f is Finding => !!f),
    ...(tl && tl.read && w.last && tl.read !== w.last ? [{ tone: "info" as const, label: "As text it was wrong",
      detail: `latest read ${tl.text} · really ${w.last}` }] : []),
    ...trouble(w, nulls, st["Null %"], left),
    { tone: "info", label: `Weekend ${pct(we)}`, detail: plural(w.weekend, "date") },
    ...(batch ? [{ tone: "warn" as const, label: "Batch date", detail: `${batch.value} ×${num(batch.n)} · the next most repeated ×${num(batch.background)}` }] : []),
    ...(clean.length ? [{ tone: "pos" as const, label: clean.join(" · ").replace(/^./, (c) => c.toUpperCase()) }] : []),
  ];
  const stats = [
    { label: "Rows", value: num(rows) },
    { label: "Nulls", value: <>{num(nulls)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: num(w.distinct), sub: `${pct(share(w.distinct, rows))} of rows` },
    { label: "First", value: w.first ?? "" },
    { label: "Last", value: w.last ?? "" },
    { label: "Span", value: spanText(w), sub: `${num(spanDays)} day${spanDays === 1 ? "" : "s"}` },
    top ? { label: "Top date", value: <span className={batch ? "warn-t" : undefined}>{top.value}</span>, sub: `×${num(top.n)} · a ${weekdayOf(top.value)}` }
        : { label: "Top date", value: "none", sub: "every date once" },
    { label: "Weekend", value: <>{num(w.weekend)} <span className="pc">· {pct(we)}</span></> },
  ];
  const fomShare = share(w.first_of_month, w.filled);
  const slots = slotNote(w);
  const checks: Point[] = [
    { label: "In the future", value: num(w.future), tone: w.future ? "warn" : "ok", note: `after today, ${w.today}` },
    { label: "Before 1900", value: num(w.before_1900), tone: w.before_1900 ? "warn" : "ok" },
    { label: "Placeholders", value: num(ph), tone: ph ? "warn" : "ok",
      note: ph ? w.placeholders.map((x) => `${x.value} ×${num(x.n)}`).join(" · ") : PLACEHOLDERS.join(" · ") },
    { label: "Weekend", value: <>{num(w.weekend)} <span className="pc">· {pct(we)}</span></>, tone: w.weekend ? "warn" : "ok",
      note: "2 in 7 days are a Saturday or Sunday - 28.57% if dates fall evenly" },
    { label: "First of a month", value: <>{num(w.first_of_month)} <span className="pc">· {pct(fomShare)}</span></>,
      tone: fomShare > 6.6 ? "warn" : "ok",
      note: `about 1 in 30 (3.33%) if dates fall evenly${batch && batch.value.endsWith("-01") ? ` - ${num(batch.n)} of them are the ${batch.value} batch` : ""}` },
    { label: "Format", tone: left || (w.written?.shape_count ?? 1) > 1 ? "warn" : "ok",
      value: w.form ? <><code>{formText(w)}</code> · {left ? `${num(left)} do not read` : "every value"}</> : "a date column",
      note: w.form ? [w.written && w.written.shape_count > 1 ? `${plural(w.written.shape_count, "shape")}` : w.written ? "one shape" : "",
                      slots, left ? "the values that do not read are left out here" : ""].filter(Boolean).join("; ")
                   : "stored as a date - no text to read" },
  ];
  const line = binLine(w.bins, bin);
  const batchBin = batch && bin === "year" ? batch.value.slice(0, 4) : batch && bin === "month" ? batch.value.slice(0, 7) : undefined;
  const quarters = some(w.quarters);
  const lm = w.last ? Number(w.last.slice(5, 7)) : 12;
  const years = some(w.years);
  return (<>
    <Findings items={findings} />
    <StatGrid stats={stats} />
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">
        <Chart w={w} bin={bin} setBin={setBin} options={binOptions(w, ["month", "year", "weekday"])} mark={batchBin}>
          {w.bins.length > 0 && w.bins.length <= TABLE_BINS && <BinTable w={w} bin={bin} />}
          {(line || batchBin) && <p className="prof-said">{line}{batch && batchBin && <> {binLabel(batchBin, bin, w)} holds the {num(batch.n)}-row batch on {batch.value}.</>}</p>}
        </Chart>
        <Panel title="Parts · weekday, month and quarter" sub="where the dates land in the week and the year"><div className="panel-body when-cal">
          <span className="eyebrow">Weekday</span>
          <Counts name="Weekday" total={w.filled} rows={countRows(w.weekday)} mark={weekend} />
          {quarters.length > 1 && <><span className="eyebrow">Quarter</span>
            <Counts name="Quarter" total={w.filled} rows={w.quarters.map((q, i) => ({ key: q.label, label: `Q${i + 1} · ${q.label}`, n: q.n }))} /></>}
          {some(w.months).length > 1
            ? <><span className="eyebrow">Month</span><Counts name="Month" total={w.filled} rows={countRows(w.months)} /></>
            : some(w.months).length === 1 && <p className="caption">Month: all in {some(w.months)[0].label}</p>}
          {years.length > 1 && lm < 12 && <p className="caption">{w.last!.slice(0, 4)} stops in {MONTH_NAMES[lm - 1]}, so the months after it hold one year fewer.</p>}
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
          {batch && <p className="caption">{num(batch.n)} on {batch.value} against {num(batch.background)} on the next most repeated date</p>}
        </div></Panel>
        <Dependencies p={p} column={column} />
      </div>
    </div>
    <NotShown items={[
      { label: "Parts · year", why: years.length > 1 ? "the rows-per-year chart above holds it" : `every date is in ${years[0]?.label ?? "one year"}` },
      { label: "Parts · hour", why: "a date has no time of day" },
    ]} />
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
