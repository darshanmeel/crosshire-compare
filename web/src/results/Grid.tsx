import type { Frame } from "./types";

const COUNTS = /^(Rows|Count|Matched|Mismatches|Mismatched|Values only|Cells that|Distinct|Fully|Avg edit)/;

function shown(x: unknown, col: string): string {
  if (x == null) return "";
  if (typeof x === "number") {
    if (col === "Match %" || col === "%" || col === "Similarity %") return `${x.toFixed(col === "Similarity %" ? 1 : 2)}%`;
    if (COUNTS.test(col)) return x.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(x);
}

/** A results table on the kit's .tbl: numbers right-aligned in mono with thousands separators, a
 * null as an empty shaded cell; a row tinted by its role (tones), the A and B rows of a differing
 * pair in their two colours with the differing cells marked (marks), when a view passes them. */
export function Grid({ frame, tones, marks, label }:
  { frame: Frame; tones?: string[]; marks?: Record<string, string[]>; label?: string }) {
  const pairs = frame.columns[0] === "Side";
  const diff = (i: number, col: string) =>
    marks?.[String(i)]?.includes(col) ? "diff-a" : marks?.[String(i - 1)]?.includes(col) ? "diff-b" : "";
  const cls = (...names: string[]) => names.filter(Boolean).join(" ") || undefined;
  const numeric = frame.columns.map((_, j) => frame.rows.length > 0 && frame.rows.every((r) => r[j] == null || typeof r[j] === "number"));
  return (
    <div className="tblwrap">
      <table className="tbl compact grid" aria-label={label}>
        <thead><tr>{frame.columns.map((c, j) => <th key={c} className={numeric[j] ? "num" : undefined}>{c}</th>)}</tr></thead>
        <tbody>{frame.rows.map((r, i) => (
          <tr key={i} className={cls(tones?.[i] ? `tint-${tones[i]}` : "", pairs ? (r[0] === "A" ? "side-a" : "side-b") : "")}>
            {r.map((x, j) => (
              <td key={j} className={cls(x == null ? "null" : "", numeric[j] ? "num m" : "", diff(i, frame.columns[j]))}>{shown(x, frame.columns[j])}</td>
            ))}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
