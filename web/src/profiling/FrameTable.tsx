// web/src/profiling/FrameTable.tsx
import { fmt } from "./frame";
import type { Frame } from "./types";

/** A table the server sent as rows - a fold's table (outliers, patterns, dependencies): numbers
 *  right-aligned with separators, nulls greyed, wide tables scrolling inside their panel. */
export function FrameTable({ t, tall = false, label }: { t: Frame; tall?: boolean; label?: string }) {
  return (
    <div className={`tblwrap${tall ? " tall" : ""}`}>
      <table className="tbl compact frame" aria-label={label}>
        <thead><tr>{t.columns.map((c, j) => <th key={c} className={t.rows.some((r) => typeof r[j] === "number") ? "num" : undefined}>{c}</th>)}</tr></thead>
        <tbody>{t.rows.map((r, i) => (
          <tr key={i}>{r.map((x, j) => (
            <td key={j} className={x == null ? "null" : typeof x === "number" ? "num m" : "m"}>{x == null ? "" : typeof x === "number" ? fmt(x) : String(x)}</td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}
