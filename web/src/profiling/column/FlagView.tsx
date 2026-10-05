// web/src/profiling/column/FlagView.tsx - a boolean column's page (screen 22): how the rows split
// between true and false, the spellings the values were written in, and the true rate across the
// groups of a category column - all from GET /api/profiling/flag.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Bar, Callout, Chip, num, Panel, StatGrid } from "../../ui/kit";
import { Dependencies, NotShown, share } from "../ColumnDetail";
import { pct } from "../frame";
import type { ColumnViewProps } from "./types";
import "./flag.css";

export type FlagSpelling = { value: string; n: number; reads: boolean | null };
export type FlagRate = { group: string | null; n: number; true: number; rate: number };
export type FlagBody = {
  column: string; true: number; false: number; nulls: number; spellings: FlagSpelling[];
  accepts: [string, string][]; groups: string[]; by: string; rates: FlagRate[];
};

const FLAT = 10;          // points between the lowest and the highest true rate under which the rates read as flat

export function useFlag(column: string, made: string, by: string) {
  return useQuery({
    queryKey: ["profiling-flag", made, column, by], enabled: !!made, staleTime: Infinity,
    // switching the group keeps this column's page up while the rates count; another column starts empty
    placeholderData: (prev: FlagBody | undefined, pq?: { queryKey: readonly unknown[] }) =>
      pq && pq.queryKey[1] === made && pq.queryKey[2] === column ? prev : undefined,
    queryFn: () => api.get<FlagBody>(`/api/profiling/flag?column=${encodeURIComponent(column)}${by ? `&by=${encodeURIComponent(by)}` : ""}`),
  });
}

const C = ({ children }: { children: ReactNode }) => <code>{children}</code>;
const times = (n: number) => `${num(n)} time${n === 1 ? "" : "s"}`;

/** The pair of accepted spellings a value belongs to (its index), or the value itself when it is in none. */
function familyOf(value: string, accepts: [string, string][]) {
  const i = accepts.findIndex((p) => p.includes(value));
  return i >= 0 ? `#${i}` : `=${value}`;
}

/** "One in seven rows is false" when the smaller side is a seventh or less, else its share. */
function minorityLine(t: number, f: number, rows: number) {
  const [word, n] = f <= t ? ["false", f] : ["true", t];
  if (!n) return <>No row is {word}.</>;
  const one = Math.round(rows / n);
  const said = one >= 2 ? <>One in {num(one)} rows is {word}</> : <>{pct(share(n, rows))} of rows are {word}</>;
  return <>{said} - those {num(n)} are the ones to look at.</>;
}

export function FlagView({ p, column, made, st }: ColumnViewProps) {
  const [by, setBy] = useState("");
  const q = useFlag(column, made, by);
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

  const t = d.true, f = d.false;
  const seen = d.spellings;
  const odd = seen.filter((s) => s.reads == null);                 // values that do not read as a boolean
  const families = new Set(seen.map((s) => familyOf(s.value, d.accepts)));
  const onePair = families.size <= 1 && !odd.length;
  const word = (b: boolean) => seen.find((s) => s.reads === b)?.value ?? String(b);
  const pairSub = onePair
    ? seen.length === 2 ? `${seen[0].reads ? seen[0].value : seen[1].value} · ${seen[0].reads ? seen[1].value : seen[0].value} - one pair`
      : seen.length === 1 ? `${seen[0].value} only` : "no values"
    : `${num(families.size)} pairs mixed`;
  const balance = !f ? "all true" : !t ? "all false"
    : t >= f ? `${(t / f).toFixed(1)} : 1` : `1 : ${(f / t).toFixed(1)}`;
  const stats = [
    { label: "Rows", value: num(rows) },
    nullCard,
    { label: "True", value: num(t), sub: pct(share(t, rows)) },
    { label: "False", value: num(f), sub: pct(share(f, rows)) },
    { label: "Spellings", value: num(seen.length), sub: pairSub },
    { label: "Balance", value: balance, sub: "true to false" },
  ];

  const list = (xs: FlagSpelling[]) => xs.map((s, i) => <span key={s.value}>{i > 0 && ", "}<C>{s.value}</C> ({num(s.n)})</span>);
  const banner = onePair && !d.nulls
    ? <Callout tone="pos" icon="check"><strong>A clean flag.</strong> {seen.length === 2 ? "Exactly two spellings" : "One spelling"} ({list(seen)}), no blanks. {minorityLine(t, f, rows)}</Callout>
    : <Callout tone="warn"><strong>{onePair ? "A flag with blanks." : "Mixed spellings."}</strong>{" "}
        {!onePair && <>{num(seen.length)} spellings in {num(families.size)} pairs - {list(seen)}. Pick one spelling before comparing. </>}
        {odd.length > 0 && <>{num(odd.reduce((s, x) => s + x.n, 0))} values do not read as a boolean. </>}
        {d.nulls > 0 && <>{num(d.nulls)} blank{d.nulls === 1 ? "" : "s"} - {pct(share(d.nulls, rows))} of rows. </>}
        {minorityLine(t, f, rows)}
      </Callout>;

  const seenSet = new Set(seen.map((s) => s.value));
  const values = (
    <Panel title="Values" sub="as read from the file"><div className="panel-body">
      <ul className="kv prof-kv flag-kv" aria-label={`Values of ${column}`}>
        <li className="t"><span className="m">{word(true)}</span><Bar pct={share(t, rows)} /><span className="v">{num(t)} <span className="pc">· {pct(share(t, rows))}</span></span></li>
        <li className="f"><span className="m">{word(false)}</span><Bar pct={share(f, rows)} /><span className="v">{num(f)} <span className="pc">· {pct(share(f, rows))}</span></span></li>
        {d.nulls > 0 && <li className="n"><span className="m">blank</span><Bar pct={share(d.nulls, rows)} /><span className="v">{num(d.nulls)} <span className="pc">· {pct(share(d.nulls, rows))}</span></span></li>}
      </ul>
      <span className="eyebrow" id={`flag-acc-${column}`}>Spellings this column accepts as boolean</span>
      <ul className="chips flag-chips" aria-labelledby={`flag-acc-${column}`}>
        {d.accepts.map(([a, b]) => {
          const hit = seenSet.has(a) || seenSet.has(b);
          return <li key={`${a}/${b}`}><Chip tone={hit ? "pos" : undefined} title={hit ? "seen in this column" : undefined}>
            {a} / {b}{hit && <span className="sr-only"> - seen in this column</span>}
          </Chip></li>;
        })}
      </ul>
      <p className="caption">Highlighted - seen here. One pair in a column is clean; a second pair mixed in shows as a finding above, with the row count of each.</p>
    </div></Panel>
  );

  const rates = d.rates;
  const lo = rates.length ? Math.min(...rates.map((r) => r.rate)) : 0;
  const hi = rates.length ? Math.max(...rates.map((r) => r.rate)) : 0;
  const byName = d.by;
  const spread = hi - lo;
  const rateCaption = rates.length < 2 ? null
    : <>{pct(lo)} – {pct(hi)} across {rates.length === d.groups.length ? "all " : ""}{num(rates.length)}{rates.length === 20 ? " shown" : ""} - {spread < FLAT
      ? <>flat, a spread of {spread.toFixed(2)} points: the true rate changes little with {byName}.</>
      : <>a spread of {spread.toFixed(2)} points: the true rate moves with {byName}.</>}</>;
  const ratePanel = (
    <Panel className="flag-rates" title={d.groups.length
      ? <label className="flag-by"><span>True rate by</span>
          <select className="sel" value={byName} onChange={(e) => setBy(e.target.value)}>
            {d.groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
      : "True rate by group"}
      sub={d.groups.length ? `share of true among the filled rows in each ${byName} value` : undefined}>
      <div className="panel-body">
        {!d.groups.length ? <p className="caption">No text column with 2 to 30 values to group by.</p> : <>
          <ul className="kv prof-kv flag-kv" aria-label={`True rate of ${column} by ${byName}`}>
            {rates.map((r) => (
              <li key={String(r.group)} className="t">
                <span className="m" title={r.group ?? "blank"}>{r.group ?? "(blank)"}</span>
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

  const least = f <= t ? { w: word(false), n: f } : { w: word(true), n: t };
  return (<>
    <StatGrid stats={stats} />
    {banner}
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">{values}{ratePanel}</div>
      <div className="prof-stack">
        <NotShown items={[
          { label: "Distribution", why: "two values - the bars under Values are the distribution" },
          { label: "Parts · Shapes", why: onePair ? "one spelling per value, nothing to break down" : "the spellings are counted in the banner above" },
          { label: "Outliers", why: "looked for in number, date and timestamp columns" },
          { label: "Least frequent", why: `${least.w}, ${times(least.n)}` },
        ]} />
        <Dependencies p={p} column={column} />
      </div>
    </div>
  </>);
}
