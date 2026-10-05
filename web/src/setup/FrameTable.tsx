// web/src/setup/FrameTable.tsx
import { num } from "../ui/kit";
import type { Frame } from "./api";

const shown = (x: unknown) =>
  x == null ? "" : typeof x === "number" ? (Number.isInteger(x) ? num(x) : x.toLocaleString("en-US", { maximumFractionDigits: 6 })) : String(x);

/** A table the server measured (setupws.frame): its columns, then its rows - nulls left blank,
 *  numbers right-aligned with thousands separators. */
export function FrameTable({ frame, label }: { frame: Frame; label?: string }) {
  if (!frame.columns.length) return null;
  return (
    <div className="tblwrap">
      <table className="tbl compact" aria-label={label}>
        <thead><tr>{frame.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{frame.rows.map((r, i) => (
          <tr key={i}>{r.map((x, j) => <td key={j} className={x == null ? "null" : typeof x === "number" ? "num" : ""}>{shown(x)}</td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}
