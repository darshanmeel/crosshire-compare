// web/src/profiling/column/FlagView.tsx - a boolean column's page (screen 29): the findings, how the
// rows split between true and false, the spellings the values were written in and the pairs the
// reader accepts, and the true rate across the groups of another column - all from
// GET /api/profiling/flag. GET /api/profiling/flags names the text (and 1 / 0 number) columns
// whose every value reads as a boolean, so the header can offer "read as boolean" for them.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Bar, Chip, num, Panel, StatGrid } from "../../ui/kit";
import { Dependencies, NotShown, share } from "../ColumnDetail";
import { pct } from "../frame";
import { Findings, type Finding } from "./Findings";
import type { ColumnViewProps } from "./types";
import "./flag.css";

export type FlagSpelling = { value: string; n: number; reads: boolean | null };
export type FlagRate = { group: string | null; n: number; true: number; rate: number; lo?: number; hi?: number };
export type FlagGroup = { column: string; how: "value" | "year" | "band"; distinct: number };
export type FlagBody = {
  column: string; true: number; false: number; nulls: number; blanks: number; odd: number;
  spellings: FlagSpelling[]; accepts: [string, string][];
  groups: FlagGroup[]; by: string; how: FlagGroup["how"] | ""; rates: FlagRate[];
};
export type FlagReading = { column: string; filled: number; true: number; false: number };

const FLAT = 10;          // points between the lowest and the highest true rate under which the rates read as flat
const IMBALANCED = 25;    // % of the filled values under which the smaller side makes the flag imbalanced

export function useFlag(column: string, made: string, by = "", how = "", enabled = true) {
  return useQuery({
    queryKey: ["profiling-flag", made, column, by, how], enabled: !!made && enabled, staleTime: Infinity,
    // switching the group keeps this column's page up while the rates count; another column starts empty
    placeholderData: (prev: FlagBody | undefined, pq?: { queryKey: readonly unknown[] }) =>
      pq && pq.queryKey[1] === made && pq.queryKey[2] === column ? prev : undefined,
    queryFn: () => api.get<FlagBody>(`/api/profiling/flag?column=${encodeURIComponent(column)}`
      + (by ? `&by=${encodeURIComponent(by)}&how=${encodeURIComponent(how)}` : "")),
  });
}

/** The text (and 1 / 0 number) columns whose every filled value reads as a boolean. */
export function useFlagReadings(made: string) {
  return useQuery({
    queryKey: ["profiling-flags", made], enabled: !!made, staleTime: Infinity,
    queryFn: () => api.get<{ columns: FlagReading[] }>("/api/profiling/flags"),
  });
}

/** True when `column` can be offered "read as boolean" (its own type is not boolean already). */
export function useReadsAsFlag(column: string, made: string, kind: string) {
  const q = useFlagReadings(made);
  return kind !== "boolean" && !!q.data?.columns.some((c) => c.column === column);
}

type Pair = { t: string; f: string; n: number };

/** The spelling pairs a column's values fall in, the most rows first: an accepted pair when the
 *  value is one of its two, else a pair of its own true and false spellings. */
function pairsOf(d: Pick<FlagBody, "spellings" | "accepts">): Pair[] {
  const by = new Map<string, Pair>();
  for (const s of d.spellings) {
    if (s.reads == null) continue;
    const i = d.accepts.findIndex((p) => p.includes(s.value));
    const key = i >= 0 ? `#${i}` : `=${s.value}`;
    const p = by.get(key) ?? (i >= 0 ? { t: d.accepts[i][0], f: d.accepts[i][1], n: 0 }
      : { t: s.reads ? s.value : "", f: s.reads ? "" : s.value, n: 0 });
    p.n += s.n;
    by.set(key, p);
  }
  return [...by.values()].sort((a, b) => b.n - a.n);
}
const pairText = (p: Pair) => [p.t, p.f].filter(Boolean).join(" / ");

/** The form beside "read as boolean" in the column's header: the spelling pair the values are
 *  written in ("Y / N"), every pair when they are mixed ("Y / N · true / false"). */
export function flagForm(d: Pick<FlagBody, "spellings" | "accepts">): string {
  return pairsOf(d).map(pairText).join(" · ");
}

/** flagForm for the header, from the same query the page makes (by = its default group). */
export function useFlagForm(column: string, made: string, on: boolean): string {
  const d = useFlag(column, made, "", "", on).data;
  return on && d && d.column === column ? flagForm(d) : "";
}

const times = (n: number) => `${num(n)} time${n === 1 ? "" : "s"}`;
const groupName = (g: Pick<FlagGroup, "column" | "how">) =>
  g.how === "year" ? `${g.column} · year` : g.how === "band" ? `${g.column} · bands` : g.column;
const rateLabel = (r: FlagRate) => r.group == null ? "(blank)" : r.lo != null && r.hi != null ? `${num(r.lo)} - ${num(r.hi)}` : r.group;

export function FlagView({ p, column, made, st }: ColumnViewProps) {
  const [pick, setPick] = useState<{ column: string; by: string; how: string } | null>(null);
  const by = pick?.column === column ? pick : { by: "", how: "" };
  const q = useFlag(column, made, by.by, by.how);
  const d = q.data;
  const rows = Number(st.Rows), nulls = Number(st.Nulls);
  const nullCard = { label: "Nulls", value: <>{num(nulls)} <span className="pc">· {pct(st["Null %"])}</span></> };
  if (q.error) return (<>
    <StatGrid stats={[{ label: "Rows", value: num(rows) }, nullCard]} />
    <div className="note error">{(q.error as Error).message}</div>
  </>);
  if (!d) return (<>
    <StatGrid stats={[{ label: "Rows", value: num(rows) }, nullCard]} />
    <p className="caption">Counting…</p>
  </>);

  const t = d.true, f = d.false, filled = t + f;
  const seen = d.spellings;
  const odd = seen.filter((s) => s.reads == null && s.value.trim() !== "");
  const pairs = pairsOf(d);
  const onePair = pairs.length <= 1 && !d.odd;
  const empty = d.nulls + d.blanks;
  const spelled = (b: boolean) => seen.filter((s) => s.reads === b).map((s) => s.value);
  const tw = spelled(true), fw = spelled(false);
  const nulled = { label: "Nulls", value: <>{num(d.nulls)} <span className="pc">· {pct(share(d.nulls, rows))}</span></>,
    sub: d.blanks ? `${num(d.blanks)} blank` : undefined };

  // --- findings: each a measured fact ---
  const items: Finding[] = [];
  if (pairs.length === 1 && !d.odd) items.push({ tone: "pos", label: "Read as boolean from",
    detail: `${pairText(pairs[0])} - one spelling pair, every ${empty ? "filled " : ""}row` });
  if (pairs.length > 1) items.push({ tone: "warn", label: "Mixed spellings",
    detail: pairs.map((x) => `${pairText(x)} ${num(x.n)}`).join(" · ") });
  if (d.odd) items.push({ tone: "neg", label: `${num(d.odd)} not a boolean`,
    detail: odd.slice(0, 3).map((s) => `${s.value} (${num(s.n)})`).join(", ") });
  if (filled && (!t || !f)) items.push({ tone: "warn", label: !f ? "All true" : "All false", detail: "the other value never appears" });
  else if (filled) {
    const tp = Math.round(share(t, filled)), small = Math.min(t, f);
    const word = f <= t ? "false" : "true";
    const one = Math.round(filled / small);
    items.push({ tone: "info", label: `${share(small, filled) < IMBALANCED ? "Imbalanced" : "Balanced"} ${tp} / ${100 - tp}`,
      detail: one >= 2 ? `one in ${num(one)} values is ${word}` : `${pct(share(small, filled))} ${word}` });
  }
  items.push(empty
    ? { tone: "warn", label: [d.nulls && `${num(d.nulls)} null${d.nulls === 1 ? "" : "s"}`, d.blanks && `${num(d.blanks)} blank${d.blanks === 1 ? "" : "s"}`].filter(Boolean).join(" · "),
        detail: `${pct(share(empty, rows))} of rows` }
    : { tone: "pos", label: "No nulls · no blanks" });

  // --- cards ---
  const balance = !filled ? "no values" : !f ? "all true" : !t ? "all false"
    : t >= f ? `${(t / f).toFixed(1)} : 1` : `1 : ${(f / t).toFixed(1)}`;
  const stats = [
    { label: "Rows", value: num(rows) },
    nulled,
    { label: tw.length ? `True · ${tw.slice(0, 2).join(" / ")}` : "True", value: num(t), sub: pct(share(t, rows)) },
    { label: fw.length ? `False · ${fw.slice(0, 2).join(" / ")}` : "False", value: num(f), sub: pct(share(f, rows)) },
    { label: "Spellings", value: onePair && pairs.length ? `${pairs[0].t} · ${pairs[0].f}` : num(seen.length),
      sub: onePair ? (seen.length === 1 ? "one value only" : "one pair") : `${num(pairs.length)} pair${pairs.length === 1 ? "" : "s"}${d.odd ? " and other values" : " mixed"}` },
    { label: "Balance", value: balance, sub: "true to false" },
  ];

  // --- values: each spelling as read, and what it becomes ---
  const seenSet = new Set(seen.map((s) => s.value));
  const values = (
    <Panel title="Values" sub="as read from the file, and what they become"><div className="panel-body">
      <ul className="kv prof-kv flag-kv" aria-label={`Values of ${column}`}>
        {seen.map((s) => (
          <li key={s.value} className={s.reads === true ? "t" : s.reads === false ? "f" : "o"}>
            <span className="m"><code>{s.value === "" ? "(empty)" : s.value}</code> <span className="to" aria-hidden="true">→</span> {s.reads == null ? <em>not a boolean</em> : String(s.reads)}</span>
            <Bar pct={share(s.n, rows)} />
            <span className="v">{num(s.n)} <span className="pc">· {pct(share(s.n, rows))}</span></span>
          </li>
        ))}
        {d.nulls > 0 && <li className="n"><span className="m">null</span><Bar pct={share(d.nulls, rows)} /><span className="v">{num(d.nulls)} <span className="pc">· {pct(share(d.nulls, rows))}</span></span></li>}
      </ul>
      <span className="eyebrow" id={`flag-acc-${column}`}>Spelling pairs the reader accepts</span>
      <ul className="chips flag-chips" aria-labelledby={`flag-acc-${column}`}>
        {d.accepts.map(([a, b]) => {
          const hit = seenSet.has(a) || seenSet.has(b);
          return <li key={`${a}/${b}`}><Chip tone={hit ? "pos" : undefined} title={hit ? "seen in this column" : undefined}>
            {a} / {b}{hit && <span className="sr-only"> - seen in this column</span>}
          </Chip></li>;
        })}
      </ul>
      <p className="caption">Green - seen in this column. {pairs.length > 1
        ? <>{num(pairs.length)} pairs are mixed here - each is a finding above with its row count.</>
        : <>Two pairs mixed in one column would show as a finding above with the row count of each - none here.</>}</p>
    </div></Panel>
  );

  // --- the true rate by the groups of another column ---
  const rates = d.rates;
  const known = rates.filter((r) => r.group != null);
  const lo = known.length ? Math.min(...known.map((r) => r.rate)) : 0;
  const hi = known.length ? Math.max(...known.map((r) => r.rate)) : 0;
  const cur = d.groups.find((g) => g.column === d.by && g.how === d.how);
  const curName = cur ? groupName(cur) : d.by;
  const unit = d.how === "year" ? "years" : d.how === "band" ? "bands" : "groups";
  const spread = hi - lo;
  const rateCaption = known.length < 2 ? null
    : <>{pct(lo)} - {pct(hi)} across all {num(known.length)} {unit} - {spread < FLAT
      ? <>flat, a spread of {spread.toFixed(2)} points: the true rate changes little with {curName}.</>
      : <>a spread of {spread.toFixed(2)} points: the true rate moves with {curName}.</>}</>;
  const ratePanel = (
    <Panel className="flag-rates" title={d.groups.length
      ? <label className="flag-by"><span>True rate by</span>
          <select className="sel" value={`${d.by}|${d.how}`} onChange={(e) => {
            const [b, ...h] = e.target.value.split("|");
            setPick({ column, by: b, how: h.join("|") });
          }}>
            {d.groups.map((g) => <option key={`${g.column}|${g.how}`} value={`${g.column}|${g.how}`}>{groupName(g)}</option>)}
          </select>
        </label>
      : "True rate by group"}
      sub={d.groups.length ? `share of true among the filled values in each ${d.how === "value" ? "group" : d.how === "year" ? "year" : "band of equal row counts"}` : undefined}>
      <div className="panel-body">
        {!d.groups.length ? <p className="caption">No other column with 2 to 50 values, dates or numbers to group by.</p> : <>
          <ul className="kv prof-kv flag-kv" aria-label={`True rate of ${column} by ${curName}`}>
            {rates.map((r, i) => (
              <li key={i} className="t">
                <span className="m" title={r.group ?? "blank"}>{rateLabel(r)}</span>
                <Bar pct={r.rate} />
                <span className="v">{pct(r.rate)} <span className="pc">· {num(r.n)}</span></span>
              </li>
            ))}
          </ul>
          {rateCaption && <p className="caption">{rateCaption}</p>}
        </>}
      </div>
    </Panel>
  );

  const least = [...seen].filter((s) => s.reads != null).sort((a, b) => a.n - b.n)[0];
  return (<>
    <Findings items={items} />
    <StatGrid stats={stats} />
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">{values}{ratePanel}</div>
      <div className="prof-stack">
        <NotShown items={[
          { label: "Distribution", why: "two values - the bars under Values are the distribution" },
          { label: "Parts · Shapes", why: onePair ? "one letter or word per value, nothing to break down" : "each spelling is listed under Values" },
          { label: "Outliers", why: "looked for in number, date and timestamp columns" },
          ...(least ? [{ label: "Least frequent", why: `${least.value}, ${times(least.n)}` }] : []),
        ]} />
        <Dependencies p={p} column={column} />
      </div>
    </div>
  </>);
}
