// web/src/profiling/ColumnsTable.tsx - the Columns panel of the profile (screen 15): one row per
// column, its name a button that opens the column's detail.
import { Bar, num, Panel } from "../ui/kit";
import { Icon } from "../ui/icons";
import { setView } from "../shell/view";
import { fmt, pct, rowsOf } from "./frame";
import type { Frame, Profile } from "./types";

// the column opened last - its row stays marked when the detail goes back to the list
let last: string | null = null;
export const lastOpened = () => last;
export function openColumn(c: string) { last = c; setView({ column: c }); }

export function ColumnsTable({ p, keyCols }: { p: Profile; keyCols: string[] }) {
  const rows = rowsOf(p.stats);
  const sel = rows.some((r) => r.Column === last) ? last : null;
  return (
    <Panel className="prof-cols" title="Columns" sub="every column measured · open a row for its distribution, outliers, shapes and frequencies"
      foot={<span>{STATS_FOOT}
        {sel && <> · selected: <button type="button" className="link-btn" onClick={() => openColumn(sel)}>{sel} - open its detail</button></>}</span>}>
      <StatsTable stats={p.stats} keyCols={keyCols} sel={sel} onOpen={openColumn} />
    </Panel>
  );
}

export const STATS_FOOT = "Distinct %: of all rows, then of the rows with a value when the column has nulls · 100% means a candidate key";

/** A share as a short bar and its %, on one line. */
const Share = ({ v, tone }: { v: unknown; tone?: "warn" }) => {
  const n = Number(v ?? 0);
  return <Bar pct={n} tone={tone ?? (n >= 100 ? "ok" : "accent")} label={pct(n)} />;
};

/** One row per column of a statistics table - nulls, distinct of rows and of non-null, the range
 *  and the top value, each share a bar and its %. With `onOpen` the name opens the column. */
export function StatsTable({ stats, keyCols = [], sel = null, onOpen, label = "Columns" }:
  { stats: Frame; keyCols?: string[]; sel?: string | null; onOpen?: (c: string) => void; label?: string }) {
  return (
    <div className="tblwrap">
      <table className="tbl prof-stats" aria-label={label}>
        <thead><tr>
          <th>Column</th><th>Type</th><th className="num">Nulls</th><th className="num">Distinct</th><th>Distinct %</th><th>Min</th><th>Max</th><th>Top value</th>
        </tr></thead>
        <tbody>{rowsOf(stats).map((r) => {
          const c = String(r.Column);
          const isNum = r.Type === "number";
          const nulls = Number(r.Nulls) > 0;
          return (
            <tr key={c} className={c === sel ? "sel" : undefined}>
              <td className="m col"><span className="cn">
                {onOpen ? <button type="button" className="col-open" onClick={() => onOpen(c)} title={`Open ${c}`}>{c}</button> : c}
                {keyCols.includes(c) && <span className="key-ico" title="key"><Icon name="key" size="sm" label="key" /></span>}
              </span></td>
              <td><span className="chip">{String(r.Type)}</span></td>
              <td className="num m dim nulls">{nulls ? <span className="pair">{num(r.Nulls as number)}<Share v={r["Null %"]} tone="warn" /></span> : "0"}</td>
              <td className="num m">{num(r.Distinct as number)}</td>
              <td className="mini"><span className="two">
                <span className="one" title="distinct of all rows"><Share v={r["Distinct % of rows"]} />{nulls && <span className="pc">rows</span>}</span>
                {nulls && <span className="one" title="distinct of the rows with a value"><Share v={r["Distinct % of filled"]} /><span className="pc">non-null</span></span>}
              </span></td>
              <td className="m dim clip" title={fmt(r.Min, isNum)}>{fmt(r.Min, isNum)}</td>
              <td className="m dim clip" title={fmt(r.Max, isNum)}>{fmt(r.Max, isNum)}</td>
              <td className="m">{r["Top value"] === "" || r["Top value"] == null ? <span className="pc">-</span>
                : <span className="top"><span className="clip" title={fmt(r["Top value"], isNum)}>{fmt(r["Top value"], isNum)}</span><Share v={r["Top %"]} /></span>}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}
