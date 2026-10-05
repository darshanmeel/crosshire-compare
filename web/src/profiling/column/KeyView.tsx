// web/src/profiling/column/KeyView.tsx - the page of the column the profile found to be the key
// (screen 23): what makes it safe to match rows on, how its ids are built (GET
// /api/profiling/keycheck) and what it does in Compare (GET /api/setup).
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../../api/client";
import { useSetup } from "../../setup/api";
import { setView } from "../../shell/view";
import { Button, Callout, num, Panel, StatGrid } from "../../ui/kit";
import { NotShown, Points, readShape, share, type Point } from "../ColumnDetail";
import { pct } from "../frame";
import type { ColumnViewProps } from "./types";
import "./key.css";

export type KeyCheck = {
  column: string; rows: number; filled: number; nulls: number; blanks: number; distinct: number; duplicates: number;
  case_variants: number; spaces: number; width: { min: number; max: number };
  shapes: { shape: string; n: number; example: string }[];
  prefix: { text: string; n: number } | null;
  number: { min: number; max: number; distinct: number; gaps: number; leading_zeros: number } | null;
  order: "ascending" | "descending" | "neither"; next_id: string;
};

export function useKeyCheck(column: string, made: string) {
  return useQuery({
    queryKey: ["profiling-keycheck", made, column],
    queryFn: () => api.get<KeyCheck>(`/api/profiling/keycheck?column=${encodeURIComponent(column)}`),
    enabled: !!made,
  });
}

/** Whether a column's name says identifier: an id, key, code, no or number at its end. */
export function saysId(name: string) {
  return /(^|[_\-\s.])(id|uuid|guid|key|code|no|nr|num|number)$/i.test(name)
    || /[a-z0-9](Id|ID|Key|Code|No|Nr|Num|Number)$/.test(name)
    || /^(id|key|uuid|guid)$/i.test(name);
}

const M = ({ children }: { children: ReactNode }) => <code>{children}</code>;
const plural = (n: number, one: string, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;

/** The Compare page's setup view, when the column table is in it. */
function openCompare() {
  location.hash = "";          // the header's Page switch: no hash is Compare
  setView({ view: "setup", column: null, anchor: "columns" });
}

function InCompare({ column }: { column: string }) {
  const q = useSetup().data;
  let items: Point[] | null = null;
  if (q?.ready) {
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
    <Panel title="In Compare"><div className="panel-body">
      {items ? <Points name="In Compare" items={items} />
        : <p className="caption">{q ? "No comparison is set up yet - load two tables on the Compare page." : "Reading…"}</p>}
      <Button className="key-open" iconAfter="arrow" onClick={openCompare}>Open the compare setup</Button>
    </div></Panel>
  );
}

export function KeyView({ column, made, st }: ColumnViewProps) {
  const k = useKeyCheck(column, made);
  const isNum = st.Type === "number";
  const notShown = (shape?: string) => (
    <NotShown items={[
      { label: "Frequencies", why: "every value once - nothing to rank" },
      { label: "Distribution · Outliers", why: "an identifier is not a quantity" },
      { label: "Parts", why: shape ? `the shape above says it: ${readShape(shape)}` : "the shape above says it" },
      { label: "Dependencies", why: "a key determines every column, trivially" },
    ]} />
  );
  if (k.error) return <div className="note error">{(k.error as Error).message}</div>;
  if (!k.data) return <p className="caption">Checking the key…</p>;
  const d = k.data;
  const n = d.number;
  const top = d.shapes[0];
  const unique = d.duplicates === 0 && d.nulls + d.blanks === 0;
  const fixed = d.width.min === d.width.max;
  const run = n ? <><M>{String(n.min)}</M> → <M>{String(n.max)}</M></> : null;

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

  // the banner: one factual sentence
  const said: string[] = [];
  said.push(d.duplicates ? `${plural(d.duplicates, "duplicate")}` : "Unique on every row");
  said.push(d.nulls + d.blanks ? `${plural(d.nulls + d.blanks, "null or blank", "nulls or blanks")}` : "no nulls");
  said.push(fixed ? "fixed width" : `${num(d.width.min)} to ${num(d.width.max)} characters`);
  said.push(d.shapes.length === 1 ? "one shape" : `${plural(d.shapes.length, "shape")}${d.shapes.length >= 3 ? " or more" : ""}`);
  const banner = (
    <Callout tone={unique ? "pos" : "warn"} icon="key">
      <strong>The key.</strong> {said.join(", ")}.
      {n && <> {d.prefix ? <>Prefix <M>{d.prefix.text}</M> and a number</> : "A number"} that runs {run}{" "}
        {n.gaps ? `with ${plural(n.gaps, "gap")}` : "with no gaps"}{d.order !== "neither" ? `, ${d.order} in file order` : ""}
        {" - "}{num(d.distinct)} ids for {num(d.rows)} rows.</>}
      {n && (isNum ? <> Read as a number - a leading zero in the file would not show.</>
        : <> Read as text - a leading zero is kept.</>)}
    </Callout>
  );

  const check: Point[] = [
    { label: "Unique", tone: d.duplicates ? "warn" : "ok",
      value: `${num(d.distinct)} distinct of ${num(d.filled)}`,
      note: d.duplicates ? `${plural(d.duplicates, "value")} repeat` : "unique by itself - no other column needed" },
    { label: "Nulls · blanks", tone: d.nulls + d.blanks ? "warn" : "ok", value: `${num(d.nulls)} · ${num(d.blanks)}`,
      note: d.nulls + d.blanks ? "rows with no key cannot be matched" : undefined },
    { label: "Case variants", tone: d.case_variants ? "warn" : "ok", value: num(d.case_variants),
      note: d.case_variants ? "values that differ only in case - turn on Ignore case or add a step" : "lower-casing changes nothing" },
    { label: "Whitespace", tone: d.spaces ? "warn" : "ok", value: num(d.spaces),
      note: d.spaces ? "values with leading, trailing or inner spaces" : "no leading, trailing or inner spaces" },
    n ? (n.leading_zeros
      ? { label: "Leading zeros", tone: isNum ? "warn" : "ok", value: plural(n.leading_zeros, "value"),
          note: isNum ? "read as a number they would be lost" : "number parts start with 0 - kept, the column is read as text" }
      : { label: "Leading zeros", tone: "ok", value: "none at risk", note: "no number part starts with 0" })
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
      ? { label: "Number part", tone: n.gaps ? "warn" : "ok",
          value: <>{String(n.min)} → {String(n.max)} · {n.gaps ? plural(n.gaps, "gap") : "contiguous · 0 gaps"}</>,
          note: n.gaps ? `${num(n.gaps)} numbers between the lowest and the highest are not used` : "every number from the lowest to the highest is used" }
      : { label: "Number part", value: "none", note: "the values are not letters then digits" },
    { label: "Order in the file", tone: d.order === "neither" ? undefined : "ok", value: d.order,
      note: d.order === "ascending" ? "each value follows a lower one - the file is sorted on the key"
        : d.order === "descending" ? "each value follows a higher one - the file is sorted on the key, high to low"
        : "the file is not sorted on the key" },
    ...(d.next_id ? [{ label: "Next id", value: d.next_id, note: "where the sequence continues" } as Point] : []),
  ];

  return (
    <div className="key-view">
      <StatGrid stats={stats} />
      {banner}
      <div className="prof-grid prof-col-grid">
        <div className="prof-stack">
          <Panel title="Key check" sub="what makes a column safe to match rows on"><div className="panel-body">
            <Points name="Key check" items={check} />
          </div></Panel>
          <Panel title="Shape and sequence" sub="how the ids are built"><div className="panel-body">
            <Points name="Shape and sequence" items={seq} />
          </div></Panel>
        </div>
        <div className="prof-stack">
          {notShown(top?.shape)}
          <InCompare column={column} />
        </div>
      </div>
    </div>
  );
}
