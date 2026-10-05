// web/src/profiling/column/KeyView.tsx - the page of the column the profile found to be the key
// (screen 30): what makes it safe to match rows on, how its ids are built - the prefix and the
// number part drawn in order, runs and gaps (GET /api/profiling/keycheck) - and what it does in the
// comparison on the page (GET /api/profiling/keycompare, GET /api/setup before a run).
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import { useSetup } from "../../setup/api";
import { setView } from "../../shell/view";
import { Button, Callout, num, Panel, StatGrid } from "../../ui/kit";
import { NotShown, Points, readShape, share, type Point } from "../ColumnDetail";
import { pct } from "../frame";
import { Findings, type Finding } from "./Findings";
import type { ColumnViewProps } from "./types";
import "./key.css";

/** One stretch of the number part: ids that are there (`run`, with `holes` left by smaller gaps
 *  not drawn) or a block that is not (`gap`). */
export type KeySpan = { from: number; to: number; kind: "run" | "gap"; n: number; holes: number; id_from: string; id_to: string };

export type KeyCheck = {
  column: string; rows: number; filled: number; nulls: number; blanks: number; distinct: number; duplicates: number;
  case_variants: number; spaces: number; width: { min: number; max: number };
  shapes: { shape: string; n: number; example: string }[];
  prefix: { text: string; n: number } | null;
  number: { min: number; max: number; distinct: number; gaps: number; leading_zeros: number } | null;
  order: "ascending" | "descending" | "neither"; next_id: string;
  runs?: KeySpan[];
  gaps?: { count: number; ids: number; shown: number };
  beyond?: { from: number; to: number; n: number; id_from: string; id_to: string; rows: number;
             shared: { column: string; value: string }[] } | null;
};

/** The key in the comparison on the page - `key` is null when the run did not match on this column alone. */
export type KeyCompare = {
  run: string | null; names?: [string, string]; stale?: boolean;
  key: null | {
    canon: string; columns: [string, string]; side: "A" | "B"; matched: number; rows: [number, number];
    only: { side: "A" | "B"; n: number; filled: number; min: string; max: string }[];
  };
};

export function useKeyCheck(column: string, made: string) {
  return useQuery({
    queryKey: ["profiling-keycheck", made, column],
    queryFn: () => api.get<KeyCheck>(`/api/profiling/keycheck?column=${encodeURIComponent(column)}`),
    enabled: !!made,
  });
}

function useKeyCompare(column: string, made: string) {
  return useQuery({
    queryKey: ["profiling-keycompare", made, column],
    queryFn: () => api.get<KeyCompare>(`/api/profiling/keycompare?column=${encodeURIComponent(column)}`),
    enabled: !!made,
  });
}

/** Whether a column's name says identifier: an id, key, code, no or number at its end. */
export function saysId(name: string) {
  return /(^|[_\-\s.])(id|uuid|guid|key|code|no|nr|num|number)$/i.test(name)
    || /[a-z0-9](Id|ID|Key|Code|No|Nr|Num|Number)$/.test(name)
    || /^(id|key|uuid|guid)$/i.test(name);
}

/** The form the header shows next to "read as" on the key's page: a text key keeps its leading
 *  zeros, a number key is whole. */
export function keyForm(kind: string) {
  return kind === "number" ? "whole" : "keep leading zeros";
}

const M = ({ children }: { children: ReactNode }) => <code>{children}</code>;
const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;
const range = (a: string, b: string) => (a === b ? a : `${a} - ${b}`);

/** The Compare page's setup view, when the column table is in it. */
function openCompare() {
  location.hash = "";          // the header's Page switch: no hash is Compare
  setView({ view: "setup", column: null, anchor: "columns" });
}

/** The Compare page's results, on the One-sided rows tab. */
function openOneSided() {
  location.hash = "";
  setView({ view: "results", tab: "onesided", column: null });
}

/** Which of the run's one-sided id sets are this column's gap or the ids past it - matched exactly. */
function sameAs(o: { n: number; min: string; max: string }, s: { n: number; id_from: string; id_to: string } | null | undefined) {
  return !!s && o.n === s.n && o.min === s.id_from && o.max === s.id_to;
}

function InCompare({ column, cmp, gap, past }: {
  column: string; cmp?: KeyCompare; gap: KeySpan | null; past: KeyCheck["beyond"];
}) {
  const q = useSetup().data;
  const key = cmp?.key;
  let items: Point[] | null = null;
  let sub: ReactNode = undefined;
  if (key && cmp?.names) {
    const names = cmp.names;
    const me = key.side === "A" ? 0 : 1, other = 1 - me;
    sub = <>against {names[other]} · {key.columns[other]}</>;
    items = [
      { label: "Pairs with", tone: "ok", value: <>{names[other]} · {key.columns[other]}</>,
        note: `${num(key.matched)} rows matched on it · ${pct(share(key.matched, key.rows[me]))} of ${names[me]}` },
      ...key.only.map((o): Point => {
        const name = names[o.side === "A" ? 0 : 1];
        const mine = o.side === key.side;
        const note = !o.n ? `every ${name} id is on the other side`
          : !mine && sameAs(o, gap) ? "the missing ids in the gap above"
          : mine && sameAs(o, past) ? "the ids past the gap above" : undefined;
        return { label: `Only in ${name}`, tone: o.n ? "warn" : "ok",
                 value: o.n ? <>{num(o.n)}{o.min && <> · {range(o.min, o.max)}</>}</> : "0", note };
      }),
    ];
  } else if (q?.ready) {
    const row = q.rows.find((r) => r["A column"] === column) ?? q.rows.find((r) => r["B column"] === column);
    if (row) {
      const onA = row["A column"] === column;
      const other = onA ? row["B column"] : row["A column"];
      const otherName = onA ? q.names[1] : q.names[0];
      items = [
        row.Key
          ? { label: "Role", value: "key", tone: "ok", note: "rows are matched on it; its own values are not compared" }
          : { label: "Role", value: row.Compare ? "compared" : "not compared", tone: "warn",
              note: q.keys.length ? <>the key in Compare is {q.keys.map((k, i) => <span key={k}>{i > 0 && " + "}<M>{k}</M></span>)}</> : "no key is set in Compare yet" },
        other
          ? { label: "Pairs with", value: <>{otherName} · {other}</>, tone: "ok",
              note: row["Matched by"] ? `matched by ${row["Matched by"]}` : undefined }
          : { label: "Pairs with", value: "nothing", tone: "warn", note: `no column on the ${otherName} side` },
      ];
    } else items = [{ label: "Role", value: "not in the column table", tone: "warn", note: `the comparison set up does not pair ${column}` }];
  }
  return (
    <Panel title="In Compare" sub={sub}><div className="panel-body">
      {items ? <Points name="In Compare" items={items} />
        : <p className="caption">{q ? "No comparison is set up yet - load two tables on the Compare page." : "Reading…"}</p>}
      {key && cmp?.stale && <p className="caption">From the last run - the setup has changed since.</p>}
      {key && key.only.some((o) => o.n > 0)
        ? <Button className="key-open" iconAfter="arrow" onClick={openOneSided}>See the one-sided rows</Button>
        : <Button className="key-open" iconAfter="arrow" onClick={openCompare}>Open the compare setup</Button>}
    </div></Panel>
  );
}

/** The number part in order: each run and gap as wide as the numbers it spans (at least a sliver). */
function SequenceBar({ spans, past }: { spans: KeySpan[]; past: KeyCheck["beyond"] }) {
  const tone = (s: KeySpan) => (s.kind === "gap" ? "gap" : past && s.from >= past.from ? "past" : "run");
  const said = spans.map((s) => `${range(s.id_from, s.id_to)}: ${s.kind === "gap" ? `${num(s.n)} missing` : `${num(s.n)} ids`}`).join("; ");
  // the legend: every stretch when there are few, else the runs at either end and the largest gaps
  const many = spans.length > 7;
  const gaps = spans.filter((s) => s.kind === "gap");
  const big = new Set([...gaps].sort((a, b) => b.n - a.n).slice(0, 4));
  const listed = many ? spans.filter((s, i) => i === 0 || i === spans.length - 1 || big.has(s)) : spans;
  return (
    <>
      <div className="key-bar" role="img" aria-label={`The number part in order - ${said}`}>
        {spans.map((s, i) => <span key={i} className={tone(s)} style={{ flexGrow: s.to - s.from + 1 }} />)}
      </div>
      <ul className="key-legend" aria-label="Sequence">
        {listed.map((s) => (
          <li key={`${s.kind}${s.from}`} className={tone(s)}>
            <i aria-hidden="true" /><span className="m">{range(s.id_from, s.id_to)}</span>
            {s.kind === "gap" ? <strong>{num(s.n)} missing</strong>
              : <><strong>{plural(s.n, "id")}</strong>
                  <span className="n">{s.holes ? `${num(s.holes)} missing in smaller gaps`
                    : tone(s) === "past" && past?.shared.length ? `all ${past.shared[0].value} in ${past.shared[0].column}`
                    : "contiguous"}</span></>}
          </li>
        ))}
        {many && <li className="more"><span className="n">{plural(gaps.length - big.size, "smaller gap")} drawn, not listed</span></li>}
      </ul>
    </>
  );
}

export function KeyView({ column, made, st }: ColumnViewProps) {
  const k = useKeyCheck(column, made);
  const cmp = useKeyCompare(column, made).data;
  const isNum = st.Type === "number";
  if (k.error) return <div className="note error">{(k.error as Error).message}</div>;
  if (!k.data) return <p className="caption">Checking the key…</p>;
  const d = k.data;
  const n = d.number;
  const top = d.shapes[0];
  const missing = d.nulls + d.blanks;
  const unique = d.duplicates === 0 && missing === 0;
  const fixed = d.width.min === d.width.max;
  const spans = d.runs ?? [];
  const gapsAt = spans.filter((s) => s.kind === "gap");
  const g = d.gaps ?? { count: n?.gaps ? 1 : 0, ids: n?.gaps ?? 0, shown: gapsAt.length };
  const oneGap = g.count === 1 ? gapsAt[0] ?? null : null;
  const past = d.beyond ?? null;
  const pastWhat = g.count === 1 ? "the gap" : "the largest run";

  // the row of findings
  const findings: Finding[] = [];
  findings.push(unique
    ? { tone: "pos", label: "Unique", detail: `${num(d.distinct)} of ${num(d.rows)} · the key` }
    : { tone: "neg", label: d.duplicates ? "Not unique" : "Rows with no key",
        detail: [d.duplicates ? plural(d.duplicates, "repeat") : "", missing ? `${plural(missing, "null or blank", "nulls or blanks")}` : ""].filter(Boolean).join(" · ") });
  if (n && g.count) findings.push(oneGap
    ? { tone: "warn", label: "Sequence gap", detail: `${range(oneGap.id_from, oneGap.id_to)} · ${plural(oneGap.n, "id")} missing` }
    : { tone: "warn", label: "Sequence gaps", detail: `${num(g.count)} gaps · ${plural(g.ids, "id")} missing` });
  else if (n && spans.length) findings.push({ tone: "pos", label: "Contiguous", detail: range(spans[0].id_from, spans[spans.length - 1].id_to) });
  if (past) findings.push({ tone: "info", label: `${plural(past.n, "id")} past ${pastWhat}`,
    detail: `${range(past.id_from, past.id_to)}${past.shared.length ? ` · all ${past.shared[0].value}` : ""}` });
  findings.push(d.shapes.length === 1
    ? { tone: fixed ? "pos" : "info", label: fixed ? `One shape · fixed width ${num(d.width.min)}` : "One shape" }
    : { tone: "warn", label: `${num(d.shapes.length)}${d.shapes.length >= 3 ? " or more" : ""} shapes`,
        detail: fixed ? `width ${num(d.width.min)}` : `width ${num(d.width.min)} to ${num(d.width.max)}` });
  const dirt = [missing ? plural(missing, "null or blank", "nulls or blanks") : "",
    d.case_variants ? plural(d.case_variants, "case variant") : "", d.spaces ? `${num(d.spaces)} with spaces` : ""].filter(Boolean);
  findings.push(dirt.length ? { tone: "warn", label: dirt.join(" · ") }
    : { tone: "pos", label: "No nulls · no case or whitespace variants" });

  const stats = [
    { label: "Rows", value: num(d.rows) },
    { label: "Nulls", value: <>{num(d.nulls)} <span className="pc">· {pct(share(d.nulls, d.rows))}</span></>,
      sub: d.blanks ? `${plural(d.blanks, "blank")} too` : undefined },
    { label: "Distinct", value: <span className={unique ? "ok-t" : undefined}>{num(d.distinct)}</span>,
      sub: unique ? "100% - unique" : `${pct(share(d.distinct, d.rows))} of rows` },
    { label: "Duplicates", value: <span className={d.duplicates ? "warn-t" : undefined}>{num(d.duplicates)}</span> },
    { label: "Min", value: String(st.Min ?? "") },
    { label: "Max", value: String(st.Max ?? "") },
    { label: "Width", value: fixed ? num(d.width.min) : `${num(d.width.min)} to ${num(d.width.max)}`,
      sub: fixed ? "fixed · every value" : "characters" },
    ...(top ? [{ label: "Shape", value: top.shape, sub: pct(share(top.n, d.filled)) }] : []),
  ];

  // the banner: what the ids are, where they break, and what the comparison says about the breaks
  const head = !unique ? "The key - not unique." : !g.count ? "The key." : g.count === 1 ? "The key - with a hole in it." : "The key - with gaps in it.";
  const problems = [d.duplicates ? plural(d.duplicates, "duplicate") : "",
    missing ? plural(missing, "null or blank", "nulls or blanks") : ""].filter(Boolean);
  const key = cmp?.key, names = cmp?.names;
  const told: string[] = [];
  if (key && names) {
    const other = key.only.find((o) => o.side !== key.side), mine = key.only.find((o) => o.side === key.side);
    if (other && oneGap && sameAs(other, oneGap)) told.push(`the ${num(other.n)} ${names[other.side === "A" ? 0 : 1]}-only ids`);
    if (mine && past && sameAs(mine, past)) told.push(`the ${num(mine.n)} ${names[mine.side === "A" ? 0 : 1]}-only ids`);
  }
  const banner = (
    <Callout tone={unique && !g.count ? "pos" : "warn"} icon="key">
      <strong>{head}</strong>{problems.length > 0 && <> {problems.join(", ")} - rows with those cannot be matched one to one.</>}
      {n ? <> {d.prefix && d.prefix.n === d.filled ? <>Prefix <M>{d.prefix.text}</M> and a number</> : "A number part"} from{" "}
        <M>{String(n.min)}</M> to <M>{String(n.max)}</M>{" - "}
        {!g.count ? <>every number is used{d.order !== "neither" ? `, ${d.order} in file order` : ""}.</>
          : oneGap ? <>every number is used except <strong>{plural(oneGap.n, "id")} from {range(oneGap.id_from, oneGap.id_to)}</strong></>
          : <>{plural(g.ids, "number")} in {plural(g.count, "gap")} are not used</>}
        {g.count > 0 && (past
          ? <>, and the {plural(past.n, "id")} past {pastWhat}{past.shared.length
              ? <> all read <M>{past.shared[0].value}</M> in {past.shared[0].column}</> : <> come after it</>}.</>
          : ".")}
        {told.length > 0 && <> Against {names![key!.side === "A" ? 1 : 0]}, {told.length === 2 ? "those are exactly" : "that is exactly"} {told.join(" and ")}.</>}
      </> : <> Its values are not letters then digits, so there is no number part to follow.</>}
    </Callout>
  );

  const check: Point[] = [
    { label: "Unique", tone: d.duplicates ? "warn" : "ok",
      value: `${num(d.distinct)} distinct of ${num(d.filled)}`,
      note: d.duplicates ? `${plural(d.duplicates, "value")} repeat` : "unique by itself - no other column needed" },
    { label: "Nulls · blanks", tone: missing ? "warn" : "ok", value: `${num(d.nulls)} · ${num(d.blanks)}`,
      note: missing ? "rows with no key cannot be matched" : undefined },
    { label: "Case variants", tone: d.case_variants ? "warn" : "ok", value: num(d.case_variants),
      note: d.case_variants ? "values that differ only in case - turn on Ignore case or add a step" : "lower-casing changes nothing" },
    { label: "Whitespace", tone: d.spaces ? "warn" : "ok", value: num(d.spaces),
      note: d.spaces ? "values with leading, trailing or inner spaces" : "no leading, trailing or inner spaces" },
    n ? (n.leading_zeros
      ? { label: "Leading zeros", tone: isNum ? "warn" : "ok", value: plural(n.leading_zeros, "value"),
          note: isNum ? "read as a number they would be lost" : "number parts start with 0 - kept, the column is read as text" }
      : { label: "Leading zeros", tone: "ok", value: "none at risk", note: isNum ? "no number part starts with 0" : "no number part starts with 0 - read as text" })
      : { label: "Leading zeros", value: "no number part", note: "the values are not letters then digits" },
    { label: "Name", tone: saysId(column) ? "ok" : undefined, value: column,
      note: saysId(column) ? "says identifier" : "the name does not say identifier" },
  ];

  const seq: Point[] = [
    top
      ? { label: "Shape", tone: d.shapes.length === 1 ? "ok" : "warn",
          value: `${top.shape} · ${num(top.n)} · ${pct(share(top.n, d.filled))}`,
          note: d.shapes.length === 1 ? readShape(top.shape)
            : <>{readShape(top.shape)}; also {d.shapes.slice(1).map((s, i) => <span key={s.shape}>{i > 0 && ", "}<M>{s.shape}</M> · {num(s.n)}</span>)}</> }
      : { label: "Shape", value: "no values" },
    d.prefix
      ? { label: "Prefix", tone: d.prefix.n === d.filled ? "ok" : undefined, value: `${d.prefix.text} · ${pct(share(d.prefix.n, d.filled))}`,
          note: d.prefix.n === d.filled ? undefined : `${num(d.prefix.n)} of ${num(d.filled)} values start with it` }
      : { label: "Prefix", value: "none", note: "no value starts with letters" },
    n
      ? (g.count
        ? { label: "Gaps", tone: "warn",
            value: oneGap ? `1 · ${plural(oneGap.n, "id")} · ${range(oneGap.id_from, oneGap.id_to)}` : `${num(g.count)} · ${plural(g.ids, "id")}`,
            note: g.count === 1 ? "one contiguous hole"
              : g.shown < g.count ? `the ${num(g.shown)} largest are drawn above; the rest sit inside their runs` : "each drawn above" }
        : { label: "Gaps", tone: "ok", value: "0", note: "every number from the lowest to the highest is used" })
      : { label: "Gaps", value: "no number part", note: "the values are not letters then digits" },
    { label: "Order in the file", tone: d.order === "neither" ? undefined : "ok", value: d.filled < 2 ? "one value" : d.order,
      note: d.filled < 2 ? "no order to read"
        : d.order === "ascending" ? "each value follows a lower one - the file is sorted on the key"
        : d.order === "descending" ? "each value follows a higher one - the file is sorted on the key, high to low"
        : "the file is not sorted on the key" },
    ...(d.next_id ? [{ label: "Next id", value: d.next_id, note: "where the sequence continues" } as Point] : []),
  ];

  return (
    <div className="key-view">
      <Findings items={findings} />
      <StatGrid stats={stats} />
      {banner}
      <div className="prof-grid prof-col-grid">
        <div className="prof-stack">
          <Panel title="Sequence · Parts" sub="the prefix and the number part, in order - where it runs and where it breaks"><div className="panel-body">
            {spans.length > 0 && <SequenceBar spans={spans} past={past} />}
            <Points name="Shape and sequence" items={seq} />
          </div></Panel>
          <Panel title="Key check" sub="what makes a column safe to match rows on"><div className="panel-body">
            <Points name="Key check" items={check} />
          </div></Panel>
        </div>
        <div className="prof-stack">
          <InCompare column={column} cmp={cmp} gap={oneGap} past={past} />
          <NotShown items={[
            { label: "Frequencies", why: "every value once - nothing to rank" },
            { label: "Distribution · Outliers", why: "an identifier is not a quantity; the sequence above takes their place" },
            { label: "Dependencies", why: "a key decides every other column, trivially, and no column decides a key" },
          ]} />
        </div>
      </div>
    </div>
  );
}
