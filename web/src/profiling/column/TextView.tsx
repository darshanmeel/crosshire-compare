// web/src/profiling/column/TextView.tsx - a text column's page below its header (screen 25): the
// findings, its statistics, a verdict, the values that are probably the same thing spelled twice
// (GET /api/profiling/similar - fingerprint, 3-grams, a shared start or a shared value of another
// column), every value with its near-duplicates indented under the kept one, a free text column's
// first and last characters, dependencies. Text read as a number keeps the general layout.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { Icon } from "../../ui/icons";
import { Bar, Button, Callout, num, Panel, Seg, StatGrid } from "../../ui/kit";
import { castType } from "../casts";
import { CouldBe, Dependencies, Frequent, NotShown, Parts, Points, readShape, Shapes, share } from "../ColumnDetail";
import { SHOWN, strongest } from "../DepMatrix";
import { FreqBars } from "../FreqSection";
import { fmt, pct, rowsOf, statsOf, type Row } from "../frame";
import type { CastRow, SpellingBody } from "../types";
import { useFreq, useSpelling } from "../useProfiling";
import { Findings, type Finding } from "./Findings";
import type { ColumnViewProps } from "./types";
import "./text.css";

export const CATEGORY = 20;   // distinct values up to which a text column reads as a category
const HIGH = 50;              // distinct values past which a text column is high-cardinality
const NEAR_KEY = 10;          // distinct % of rows from which a column is a near-key and never the "decided by"
const EVEN = 2;               // the largest value at most this many times an even share: balanced

export type Method = "fingerprint" | "ngram" | "prefix" | "same";
export type SimMember = { value: string; n: number };
export type SimGroup = { members: SimMember[]; keep: string; rows: number; why: string; on?: { column: string; value: string } };
export type SimilarBody = {
  column: string; kind: string; method: Method; counts: Record<Method, number>; groups: SimGroup[]; by: string;
  threshold: number; distinct: number; filled: number; scanned: number; capped: boolean;
  values: SimMember[]; more: number; shortest: string | null; longest: string | null;
};

export function useSimilar(column: string, made: string, method: Method | "", on = true) {
  return useQuery({
    queryKey: ["profiling-similar", made, column, method], enabled: on && !!made, staleTime: Infinity,
    // switching the method keeps this column's page up while it counts; another column starts empty
    placeholderData: (prev: SimilarBody | undefined, pq?: { queryKey: readonly unknown[] }) =>
      pq && pq.queryKey[1] === made && pq.queryKey[2] === column ? prev : undefined,
    queryFn: () => api.get<SimilarBody>(`/api/profiling/similar?column=${encodeURIComponent(column)}${method ? `&method=${method}` : ""}`),
    // a group with no members, or a body missing a list, never breaks the page
    select: (d: SimilarBody): SimilarBody => ({ ...d,
      groups: (d.groups ?? []).filter((g) => g.members?.length).map((g) => ({ ...g, keep: g.keep ?? g.members[0].value })),
      values: d.values ?? [], counts: d.counts ?? {} as SimilarBody["counts"] }),
  });
}

/** The form beside "read as" in the header for a text column: "exact · 2,985 rows" when no value
 *  differs from another only in case or outer spaces, else how many do. */
export function textForm(st: Row, spell?: SpellingBody): string {
  const rows = `${num(Number(st.Rows))} rows`;
  if (!spell) return rows;
  const variants = spell.distinct - spell.folded;
  return variants ? `${num(variants)} case variant${variants === 1 ? "" : "s"} · ${rows}`
    : spell.padded ? `${num(spell.padded)} padded · ${rows}` : `exact · ${rows}`;
}

const METHODS: { value: Method; label: string }[] = [
  { value: "fingerprint", label: "Fingerprint" }, { value: "ngram", label: "n-gram" },
  { value: "prefix", label: "Shared prefix" }, { value: "same", label: "Same" }];
const NO_STEPS = "The Profile page has no steps to add to yet - add a replace step to this column on the Compare page";
const has = (v: unknown) => v != null && v !== "";

/** A group with the member the reader picked kept instead of the most frequent one. */
const kept = (g: SimGroup, pick?: string) => (pick && g.members.some((m) => m.value === pick) ? pick : g.keep);

/** One line on a text column: what it is and what to do with it. */
function TextVerdict({ st, cast, as, category, spell, sim }:
  { st: Row; cast?: CastRow; as: string; category: boolean; spell?: SpellingBody; sim?: SimilarBody }) {
  const distinct = Number(st.Distinct), filled = Number(st.Rows) - Number(st.Nulls);
  const nulls = Number(st["Null %"] ?? 0) > 0 ? `${pct(st["Null %"])} null` : "no nulls";
  const empty = Number(st["Null %"] ?? 0) >= 50 ? <> Mostly empty - {pct(st["Null %"])} null.</> : null;
  const hit = as === "number" ? cast?.number : undefined;
  if (cast && hit) {
    const { type, form } = castType("number", hit);
    return <Callout tone="pos" icon="check"><strong>Text read as a number.</strong> {pct(share(hit.any, cast.filled))} of the filled values read as <code>{type}</code>{form && <> {form}</>} - its digits are counted below.{empty}</Callout>;
  }
  if (category) {
    if (!spell) return null;          // said once the spelling is counted, so a clean verdict never flips to variants
    const variants = spell.distinct - spell.folded;
    const groups = sim?.groups.length ?? 0;
    if (variants > 0)
      return <Callout tone="warn"><strong>A category with spelling variants.</strong> {num(distinct)} values, {num(spell.folded)} once case and outer spaces are ignored - tidy them with a step before comparing.{empty}</Callout>;
    if (groups && sim)
      return <Callout tone="warn"><strong>A category with near-duplicates.</strong> {num(distinct)} values, {num(merged(sim))} once the {num(groups)} group{groups === 1 ? "" : "s"} under <em>Similar values</em> are merged.{empty}</Callout>;
    return <Callout tone="pos" icon="check"><strong>A clean category.</strong> {num(distinct)} value{distinct > 1 ? "s" : ""}, {nulls}, no case or whitespace variants. In Compare this is a good <em>Profile by bucket</em> column.{empty}</Callout>;
  }
  if (Number(st["Distinct % of filled"] ?? 0) >= 95)
    return <Callout icon="key"><strong>Nearly every value different.</strong> {num(distinct)} distinct of {num(filled)} filled - an id or free text, a key candidate rather than a category.{empty}</Callout>;
  return empty ? <Callout tone="warn"><strong>Sparse.</strong>{empty}</Callout> : null;
}

/** Distinct values once every group is merged into one. */
const merged = (s: SimilarBody) => s.distinct - s.groups.reduce((t, g) => t + g.members.length - 1, 0);

/** The pills under the header - each from a measured fact. */
export function textFindings({ p, column, st, spell, sim, category }:
  { p: ColumnViewProps["p"]; column: string; st: Row; spell?: SpellingBody; sim?: SimilarBody; category: boolean }): Finding[] {
  const out: Finding[] = [];
  const distinct = Number(st.Distinct), nulls = Number(st.Nulls);
  if (sim?.groups.length)
    out.push({ tone: "warn", label: "Near-duplicates",
      detail: `${num(sim.groups.length)} group${sim.groups.length === 1 ? "" : "s"} · ${num(sim.distinct)} values that are really ${num(merged(sim))}` });
  const near = (col: string) => Number(statsOf(p, col)?.["Distinct % of rows"] ?? 0) >= NEAR_KEY;
  const by = strongest(p.matrix, column, Infinity).decidedBy.find((h) => !near(h.col) && h.v >= SHOWN);
  if (by) out.push({ tone: "info", label: `Decided by ${by.col}`, detail: `U ${pct(by.v)}` });
  if (category && distinct > 1 && has(st["Top %"])) {
    const top = Number(st["Top %"]);
    out.push(top <= (EVEN * 100) / distinct
      ? { tone: "pos", label: "Balanced", detail: `largest value ${pct(top)}` }
      : { tone: "warn", label: "Imbalanced", detail: `largest value ${pct(top)}` });
  }
  out.push(nulls ? { tone: "warn", label: `${num(nulls)} null${nulls === 1 ? "" : "s"}`, detail: pct(st["Null %"]) }
    : { tone: "pos", label: "No nulls" });
  if (spell) {
    const variants = spell.distinct - spell.folded;
    out.push(variants || spell.padded
      ? { tone: "warn", label: variants ? "Case variants" : "Outer spaces",
          detail: variants ? `${num(variants)} value${variants === 1 ? "" : "s"} differ only in case or spaces` : `${num(spell.padded)} values` }
      : { tone: "pos", label: "Clean case and whitespace" });
  }
  out.push(distinct > HIGH
    ? { tone: "info", label: "High-cardinality", detail: `${num(distinct)} distinct · ${pct(st["Distinct % of filled"])} of filled` }
    : { tone: "pos", label: "Not high-cardinality" });
  return out;
}

function SimilarPanel({ column, sim, method, setMethod, picks, pick }:
  { column: string; sim?: SimilarBody; method: Method; setMethod: (m: Method) => void;
    picks: Record<string, string>; pick: (g: number, v: string) => void }) {
  const by = sim?.by || "";
  const opts = METHODS.map((m) => ({ ...m, label: m.value === "same" ? `Same ${by || "other column"}` : m.label,
    title: sim ? `${num(sim.counts?.[m.value] ?? 0)} group${sim.counts?.[m.value] === 1 ? "" : "s"}` : undefined }));
  const groups = sim?.groups ?? [];
  const fewer = sim ? merged(sim) : 0;
  let body: ReactNode;
  if (!sim) body = <p className="caption">Looking…</p>;
  else if (!groups.length) body = <p className="caption">{method === "same" && !by
    ? `No other column names one value of ${column} each - nothing to tell renames by.`
    : "No values look alike this way."}</p>;
  else body = (<>
    <ol className="sim-groups" aria-label="Similar value groups">
      {groups.map((g, gi) => {
        const keep = kept(g, picks[`${method}:${gi}`]);
        const others = g.members.filter((m) => m.value !== keep);
        const head = g.members.find((m) => m.value === keep) ?? g.members[0];
        const why = g.on && g.why.endsWith(g.on.value)
          ? <>{g.why.slice(0, -g.on.value.length)}<code>{g.on.value}</code></> : g.why;
        return (
          <li key={gi} className="sim-group">
            <div className="sim-head">
              <strong>Group {gi + 1}</strong><span className="dot" aria-hidden="true">·</span>
              <span className="num">{num(g.rows)} rows</span><span className="dot" aria-hidden="true">·</span>
              <span className="why">{why}</span>
              <Button size="sm" disabled title={NO_STEPS}>Merge into {keep}</Button>
            </div>
            <div className="sim-members" role="group" aria-label={`Group ${gi + 1} - pick the spelling to keep`}>
              {[head, ...others].map((m, i) => (<span key={m.value} className="sim-m">
                {i === 1 && <Icon name="arrowl" size="sm" />}
                <button type="button" className={m.value === keep ? "sim-v keep" : "sim-v"} aria-pressed={m.value === keep}
                  aria-label={`${m.value === "" ? "(blank)" : m.value}, ${num(m.n)} rows`} title={m.value === keep ? "kept" : "keep this spelling instead"} onClick={() => pick(gi, m.value)}>
                  <code>{m.value === "" ? "(blank)" : m.value}</code><span className="n">{num(m.n)}{m.value === keep && " · keep"}</span>
                </button>
              </span>))}
            </div>
          </li>
        );
      })}
    </ol>
    <p className="caption">Merging needs steps on the profiled table, and the Profile page has none yet. The kept spelling is the most frequent; click a member to keep it instead.</p>
    <div><Button variant="dark" icon="sparkle" disabled title={NO_STEPS}>
      Merge all {num(groups.length)} · {num(sim.distinct)} → {num(fewer)} values</Button></div>
  </>);
  return (
    <Panel className="sim-panel" title="Similar values" sub="values that are probably the same thing spelled twice">
      <div className="panel-body">
        <div className="sim-method">
          <span className="eyebrow">Method</span>
          <Seg mini label="Method" value={method} onChange={setMethod} options={opts} />
          <span className="caption">fingerprint and n-gram catch case, spacing and typos; a shared prefix and a shared {by || "code"} catch renames</span>
        </div>
        {sim?.capped && <p className="caption">Among the {num(sim.scanned)} most frequent of {num(sim.distinct)} values.</p>}
        {body}
      </div>
    </Panel>
  );
}

/** Every value most to least frequent, each group's other spellings indented under the kept one. */
function ValuesPanel({ column, sim, method, picks, shapes, made, category }:
  { column: string; sim?: SimilarBody; method: Method; picks: Record<string, string>; shapes: Row[]; made: string; category: boolean }) {
  const freq = useFreq(sim && sim.more > 0 ? column : null, made).data;
  if (!sim) return <Panel title="Values"><div className="panel-body"><p className="caption">Reading…</p></div></Panel>;
  const vals = sim.values ?? [];
  const under = new Map<string, SimMember[]>();       // kept value → the spellings merged into it
  const folded = new Set<string>();
  sim.groups.forEach((g, gi) => {
    const keep = kept(g, picks[`${method}:${gi}`]);
    const rest = g.members.filter((m) => m.value !== keep);
    under.set(keep, rest);
    rest.forEach((m) => folded.add(m.value));
  });
  const top = Math.max(1, ...vals.map((v) => v.n));
  const filled = sim.filled || 1;
  const line = (m: SimMember, sub = false) => (
    <li key={(sub ? "↳" : "") + m.value} className={sub ? "sub" : undefined}>
      <span className="m" title={m.value}>{sub && <span aria-hidden="true">↳ </span>}{m.value === "" ? "(blank)" : m.value}</span>
      <Bar pct={(100 * m.n) / top} tone={sub ? "accent" : "warn"} />
      <span className="v">{num(m.n)} <span className="pc">· {pct(share(m.n, filled))}</span></span>
    </li>
  );
  const rows: ReactNode[] = [];
  for (const v of vals) {
    if (folded.has(v.value)) continue;
    rows.push(line(v));
    for (const m of under.get(v.value) ?? []) rows.push(line(m, true));
  }
  const totals = sim.groups.length
    ? vals.filter((v) => !folded.has(v.value)).map((v) => v.n + (under.get(v.value) ?? []).reduce((t, m) => t + m.n, 0))
    : [];
  const sub = sim.more ? `the ${num(vals.length)} most frequent of ${num(sim.distinct)}` : `all ${num(sim.distinct)} · most to least frequent`;
  return (
    <Panel title="Values" sub={sim.groups.length ? `${sub} · grouped members shown indented` : sub}>
      <div className="panel-body">
        <ul className="kv prof-kv text-values" aria-label={`Values of ${column}`}>{rows}</ul>
        {sim.groups.length > 0 && !sim.more && totals.length > 0 &&
          <p className="caption">After merging, the {num(totals.length)} values run {num(Math.min(...totals))} - {num(Math.max(...totals))} rows each.</p>}
        {sim.more > 0 && freq && <>
          <span className="eyebrow accent freq-rest">Least frequent</span>
          <FreqBars t={freq.bottom} numeric={false} label={`Least frequent values of ${column}`} />
        </>}
        {category && shapes.length > 0 && <Points name="Shape findings" items={[{ label: "Shapes", tone: "ok",
          value: <span className="m">{shapes.map((r) => readShape(String(r.Pattern))).join(" · ")}</span>,
          note: shapes.length >= vals.length ? `folded in - with ${num(vals.length)} values each has exactly one` : "folded in for a column with so few values" }]} />}
      </div>
    </Panel>
  );
}

export function TextView({ p, column, made, st, as, cast }: ColumnViewProps) {
  const kind = String(st.Type);
  const isText = kind === "text";
  const distinct = Number(st.Distinct);
  const category = isText && as !== "number" && distinct > 0 && distinct <= CATEGORY;
  const shapes = rowsOf(p.patterns).filter((r) => r.Column === column);
  const spell = useSpelling(column, made, isText).data;
  const plain = isText && as !== "number";          // text read as text: the similar values page
  const [method, setMethod] = useState<{ column: string; m: Method } | null>(null);
  const asked = method?.column === column ? method.m : "";
  const sim = useSimilar(column, made, asked, plain).data;
  const shown: Method = asked || sim?.method || "fingerprint";
  const [picks, setPicks] = useState<{ column: string; at: Record<string, string> }>({ column, at: {} });
  const at = picks.column === column ? picks.at : {};
  const pick = (g: number, v: string) => setPicks({ column, at: { ...at, [`${shown}:${g}`]: v } });
  const variants = spell ? spell.distinct - spell.folded : 0;
  const rows = Number(st.Rows);
  const top = sim?.values?.[0];
  const topN = top && String(top.value) === String(st["Top value"]) ? top.n : Math.round((Number(st["Top %"] ?? 0) * rows) / 100);
  const groups = sim?.groups.length ?? 0;
  const lenSub = sim && sim.shortest != null && sim.longest != null && sim.shortest !== sim.longest
    ? <><span className="m">{sim.shortest}</span> … <span className="m">{sim.longest}</span></>
    : `avg ${fmt(st["Avg length"])} characters`;
  const stats = [
    { label: "Rows", value: num(rows) },
    { label: "Nulls", value: <>{num(st.Nulls as number)} <span className="pc">· {pct(st["Null %"])}</span></> },
    { label: "Distinct", value: plain && groups && sim ? <>{num(sim.distinct)} → {num(merged(sim))}</> : num(distinct),
      sub: plain && groups ? "after merging duplicates" : category ? "a category"
        : Number(st["Distinct % of filled"] ?? 0) >= 95 ? "nearly all different" : `${pct(st["Distinct % of filled"])} of filled` },
    ...(has(st["Top value"]) ? [{ label: "Top value", value: fmt(st["Top value"], false), sub: `${num(topN)} · ${pct(st["Top %"])}` }] : []),
    ...(has(st["Min length"]) ? [{ label: "Length",
      value: Number(st["Min length"]) === Number(st["Max length"]) ? num(Number(st["Min length"])) : `${num(Number(st["Min length"]))} - ${num(Number(st["Max length"]))}`,
      sub: lenSub }] : []),
    ...(spell ? [{ label: "Case · spaces",
      value: variants || spell.padded ? <span className="warn-t">{variants ? `${num(variants)} variant${variants === 1 ? "" : "s"}` : "padded"}</span> : <span className="ok-t">clean</span>,
      sub: variants ? "values that differ only in case or outer spaces" : spell.padded ? `${num(spell.padded)} with outer spaces` : "one spelling per value" }] : []),
  ];
  const deps = <Dependencies p={p} column={column} />;
  const verdict = isText ? <TextVerdict st={st} cast={cast} as={as} category={category} spell={spell} sim={plain ? sim : undefined} /> : null;
  if (!plain) return (<>
    {/* text read as a number (or a kind with no page of its own): its parts across the page */}
    <Findings items={textFindings({ p, column, st, spell, category })} />
    <StatGrid stats={stats} />
    {verdict}
    {isText && <CouldBe column={column} made={made} />}
    <Parts column={column} kind={kind} made={made} as={as} />
    <div className="prof-grid prof-col-grid">
      <Frequent column={column} made={made} st={st} />
      <Shapes rows={shapes} kind={kind} st={st} />
      {deps}
    </div>
  </>);
  const allShown = !!sim && !sim.more;
  return (<>
    <Findings items={textFindings({ p, column, st, spell, sim, category })} />
    <StatGrid stats={stats} />
    {verdict}
    <CouldBe column={column} made={made} />
    <div className="prof-grid prof-col-grid">
      <div className="prof-stack">
        <SimilarPanel column={column} sim={sim} method={shown} setMethod={(m) => setMethod({ column, m })} picks={at} pick={pick} />
        <ValuesPanel column={column} sim={sim} method={shown} picks={at} shapes={shapes} made={made} category={category} />
        {!category && <Parts column={column} kind={kind} made={made} as={as} />}
        {!category && <Shapes rows={shapes} kind={kind} st={st} />}
      </div>
      <div className="prof-stack">
        {deps}
        <NotShown items={[
          ...(category ? [{ label: "Parts", why: `first and last characters only help with free text - with ${num(distinct)} values they repeat the list` }] : []),
          { label: "Outliers", why: "looked for in number, date and timestamp columns" },
          ...(allShown ? [{ label: "Least frequent", why: "the list of values is complete" }] : []),
        ]} />
      </div>
    </div>
  </>);
}
