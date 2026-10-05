// web/src/profiling/ColumnsTable.tsx - the Columns panel of the profile (screen 15): one row per
// column, its name a button that opens the column's detail. On the Profile page each row also says
// what the column is read as and what its values look like, a guess at what it holds, and what
// stands out about it, with an arrow that opens its page.
import type { ReactNode } from "react";
import { Bar, num, Panel } from "../ui/kit";
import { Icon } from "../ui/icons";
import { setView } from "../shell/view";
import { semantic } from "./column/Findings";
import { fmt, pct, rowsOf, type Row } from "./frame";
import { notesByColumn, readFrom, type FindingsBody } from "./standout";
import type { Frame, Profile } from "./types";

// the column opened last - its row stays marked when the detail goes back to the list
let last: string | null = null;
export const lastOpened = () => last;
export function openColumn(c: string) { last = c; setView({ column: c }); }

/** What the Profile page adds per column: read as · looks like, the semantic guess, what stands out. */
export type ColInfo = { readAs: ReactNode; semantic: string; stands: string[] };

const STANDS = 3;       // facts shown per column - the rest on its page
const LOOK_FORM: Record<string, string> = { plain: "", ISO: "", "with , removed": "remove thousands separators" };

/** Each column's extra cells, from the profile and its findings (which may not have come yet). */
export function columnInfo(p: Profile, keyCols: string[], f?: FindingsBody): Record<string, ColInfo> {
  const notes = notesByColumn(p.notes), from = readFrom(p.notes);
  const shape: Record<string, string> = {};
  for (const r of rowsOf(p.patterns)) shape[String(r.Column)] ??= String(r.Pattern ?? "");
  const looks = Object.fromEntries((f?.looks ?? []).map((l) => [l.column, l]));
  const out: Record<string, ColInfo> = {};
  for (const r of rowsOf(p.stats)) {
    const c = String(r.Column), kind = String(r.Type), look = looks[c];
    const rows = Number(r.Rows ?? 0), distinct = Number(r.Distinct ?? 0);
    const read = from[c];
    const lform = look ? LOOK_FORM[look.form] ?? look.form : "";
    const readAs = (
      <span className="readas">
        <span className="chip">{kind}</span>
        {read && <span className="from" title={`read as ${read.as} - ${read.how}`}>from text · {read.how}</span>}
        {look && <>
          <Icon name="arrow" size="sm" />
          <span className="chip looks" title={`${num(look.n)} of ${num(look.filled)} filled values read as ${look.as}`}>
            {look.as}{lform && <> · {lform}</>}</span>
        </>}
      </span>
    );
    const sem = semantic(c, look && look.as !== "number" ? look.as : kind, distinct, rows, keyCols.includes(c), shape[c] ?? "");
    const stands = [...new Set([...(f?.columns?.[c] ?? []), ...(notes[c] ?? [])])];
    out[c] = { readAs, semantic: sem, stands };
  }
  return out;
}

export function ColumnsTable({ p, keyCols, findings }: { p: Profile; keyCols: string[]; findings?: FindingsBody }) {
  const rows = rowsOf(p.stats);
  const sel = rows.some((r) => r.Column === last) ? last : null;
  return (
    <Panel className="prof-cols" title="Columns" sub="every column measured · open a row for its page"
      foot={<span>{STATS_FOOT} · <strong>Semantic</strong> is a guess from the name, shape and values
        {sel && <> · selected: <button type="button" className="link-btn" onClick={() => openColumn(sel)}>{sel} - open its detail</button></>}</span>}>
      <StatsTable stats={p.stats} keyCols={keyCols} sel={sel} onOpen={openColumn} info={columnInfo(p, keyCols, findings)} />
    </Panel>
  );
}

export const STATS_FOOT = "Distinct %: of all rows, then of the rows with a value when the column has nulls · 100% means a candidate key";

/** A share as a short bar and its %, on one line. */
const Share = ({ v, tone }: { v: unknown; tone?: "warn" }) => {
  const n = Number(v ?? 0);
  return <Bar pct={n} tone={tone ?? (n >= 100 ? "ok" : "accent")} label={pct(n)} />;
};

function Stands({ facts }: { facts: string[] }) {
  if (!facts.length) return <span className="pc">-</span>;
  const more = facts.length - STANDS;
  return (
    <span className="stands" title={facts.join(" · ")}>
      {facts.slice(0, STANDS).join(" · ")}{more > 0 && <span className="pc"> · {num(more)} more on its page</span>}
    </span>
  );
}

/** One row per column of a statistics table - nulls, distinct of rows and of non-null, the range
 *  and the top value, each share a bar and its %. With `onOpen` the name opens the column; with
 *  `info` (the Profile page) the row says what it is read as, its semantic guess and what stands out. */
export function StatsTable({ stats, keyCols = [], sel = null, onOpen, label = "Columns", info }:
  { stats: Frame; keyCols?: string[]; sel?: string | null; onOpen?: (c: string) => void; label?: string; info?: Record<string, ColInfo> }) {
  return (
    <div className="tblwrap">
      <table className={`tbl prof-stats${info ? " prof-stats-wide" : ""}`} aria-label={label}>
        <thead><tr>
          <th>Column</th>
          {info ? <><th>Read as · looks like</th><th>Semantic</th></> : <th>Type</th>}
          <th className="num">Nulls</th><th className="num">Distinct</th><th>Distinct %</th>
          {info ? <th>Min … max</th> : <><th>Min</th><th>Max</th></>}
          <th>Top value</th>
          {info && <><th>What stands out</th><th><span className="sr-only">Open</span></th></>}
        </tr></thead>
        <tbody>{rowsOf(stats).map((r) => <StatsRow key={String(r.Column)} r={r} keyCols={keyCols} sel={sel} onOpen={onOpen} info={info?.[String(r.Column)]} />)}</tbody>
      </table>
    </div>
  );
}

function StatsRow({ r, keyCols, sel, onOpen, info }: { r: Row; keyCols: string[]; sel: string | null; onOpen?: (c: string) => void; info?: ColInfo }) {
  const c = String(r.Column);
  const isNum = r.Type === "number";
  const nulls = Number(r.Nulls) > 0;
  const lo = fmt(r.Min, isNum), hi = fmt(r.Max, isNum);
  return (
    <tr className={c === sel ? "sel" : undefined}>
      <td className="m col"><span className="cn">
        {onOpen ? <button type="button" className="col-open" onClick={() => onOpen(c)} title={`Open ${c}`}>{c}</button> : c}
        {keyCols.includes(c) && <span className="key-ico" title="key"><Icon name="key" size="sm" label="key" /></span>}
      </span></td>
      {info ? <><td>{info.readAs}</td><td><span className="chip sem">{info.semantic}</span></td></>
        : <td><span className="chip">{String(r.Type)}</span></td>}
      <td className="num m dim nulls">{nulls ? <span className="pair">{num(r.Nulls as number)}<Share v={r["Null %"]} tone="warn" /></span> : "0"}</td>
      <td className="num m">{num(r.Distinct as number)}</td>
      <td className="mini"><span className="two">
        <span className="one" title="distinct of all rows"><Share v={r["Distinct % of rows"]} />{nulls && <span className="pc">rows</span>}</span>
        {nulls && <span className="one" title="distinct of the rows with a value"><Share v={r["Distinct % of filled"]} /><span className="pc">non-null</span></span>}
      </span></td>
      {info
        ? <td className="m dim clip range" title={lo || hi ? `${lo} … ${hi}` : ""}>{lo || hi ? <>{lo} <span className="pc">…</span> {hi}</> : <span className="pc">-</span>}</td>
        : <><td className="m dim clip" title={lo}>{lo}</td><td className="m dim clip" title={hi}>{hi}</td></>}
      <td className="m">{r["Top value"] === "" || r["Top value"] == null ? <span className="pc">-</span>
        : <span className="top"><span className="clip" title={fmt(r["Top value"], isNum)}>{fmt(r["Top value"], isNum)}</span><Share v={r["Top %"]} /></span>}</td>
      {info && <>
        <td className="stands-cell"><Stands facts={info.stands} /></td>
        <td className="go">{onOpen && <button type="button" className="icon-btn row-go" aria-label={`Open the page of ${c}`} onClick={() => onOpen(c)}>
          <Icon name="arrow" size="sm" /></button>}</td>
      </>}
    </tr>
  );
}
