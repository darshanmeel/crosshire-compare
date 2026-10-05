// web/src/profiling/DepMatrix.tsx - how much each column decides each other one: a row per
// deciding column, a column per decided one, each cell the share of the row's values that go with
// one value of the column beyond chance - 0 is unrelated, 100% is X → Y - shaded from SHOWN up. A
// column's own page lists what it decides most and what decides it most (strongest).
import { num } from "../ui/kit";
import type { Frame } from "./types";

export const SHOWN = 30;   // a share from here up reads as some dependency
export const TOP = 5;

type Hit = { col: string; v: number };

/** For one column, the TOP columns it decides most and the TOP that decide it most - under SHOWN% too,
 *  for the page to mark as not conclusive. */
export function strongest(m: Frame, column: string, n = TOP): { decides: Hit[]; decidedBy: Hit[] } {
  const ys = m.columns.slice(1);
  const top = (hits: { col: string; v: unknown }[]) => hits
    .filter((h): h is Hit => typeof h.v === "number")
    .sort((a, b) => b.v - a.v).slice(0, n);
  const row = m.rows.find((r) => r[0] === column);
  const at = ys.indexOf(column);
  return {
    decides: row ? top(row.slice(1).map((v, i) => ({ col: ys[i], v }))) : [],
    decidedBy: at < 0 ? [] : top(m.rows.filter((r) => r[0] !== column).map((r) => ({ col: String(r[0]), v: r[at + 1] }))),
  };
}

const shade = (v: number) =>
  `color-mix(in srgb, var(--fs-accent) ${Math.round(Math.max(0, v - SHOWN) / (100 - SHOWN) * 80)}%, transparent)`;

export function DepMatrix({ m, note }: { m: Frame; note: string }) {
  if (m.rows.length === 0) return null;
  const ys = m.columns.slice(1);
  return (
    <figure className="dep-matrix">
      <div className="dep-matrix-scroll">
        <table aria-label="Dependency matrix">
          <thead>
            <tr>
              <th scope="col" className="corner"><span>decides →</span></th>
              {ys.map((y) => <th key={y} scope="col" title={y}><span>{y}</span></th>)}
            </tr>
          </thead>
          <tbody>
            {m.rows.map((r) => {
              const x = String(r[0]);
              return (
                <tr key={x}>
                  <th scope="row" title={x}>{x}</th>
                  {r.slice(1).map((v, i) => v == null
                    ? <td key={i} className="self" aria-label={`${x} itself`} />
                    : <td key={i} className={(v as number) >= 100 ? "full" : (v as number) < SHOWN ? "faint" : undefined}
                        style={{ background: shade(v as number) }}
                        title={`${x} → ${ys[i]}: ${num(v as number)}%`}>{Math.round(v as number)}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <figcaption className="caption">
        Each cell: how far the row decides the column beyond chance, in % - 0 is what unrelated columns give, 100 means
        every value of the row goes with one value of the column; from {SHOWN}% up it is shaded · a column's own page lists its strongest · {note}
      </figcaption>
    </figure>
  );
}
