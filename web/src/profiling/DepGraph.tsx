// web/src/profiling/DepGraph.tsx - the dependencies as a picture: the columns that determine others
// on the left, the columns they determine on the right, an arrow for each X → Y (both ways for a
// one-to-one), and the correlated number pairs as dashed lines. Built from the profile's own tables.
import { rowsOf } from "./frame";
import type { Frame } from "./types";

const W = 760, ROW = 34, NODE_W = 220, PAD = 14;
const short = (s: string) => (s.length > 26 ? `${s.slice(0, 25)}…` : s);

export function DepGraph({ deps, corr }: { deps: Frame; corr: Frame }) {
  const edges = [
    ...rowsOf(deps).map((r) => ({ a: String(r.Determines), b: String(r.Determined), kind: String(r.Kind) })),
    ...rowsOf(corr).map((r) => ({ a: String(r["Column A"]), b: String(r["Column B"]), kind: `correlated · r = ${Number(r.r).toFixed(2)}` })),
  ];
  if (!edges.length) return null;
  const left = [...new Set(edges.map((e) => e.a))];
  const right = [...new Set(edges.map((e) => e.b))];
  const H = Math.max(left.length, right.length) * ROW + PAD * 2;
  const y = (list: string[], c: string) => PAD + (H - PAD * 2 - list.length * ROW) / 2 + list.indexOf(c) * ROW + ROW / 2;
  const x1 = NODE_W, x2 = W - NODE_W;
  return (
    <figure className="dep-graph">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Dependency graph: ${edges.map((e) => `${e.a} to ${e.b}`).join(", ")}`}>
        <defs>
          <marker id="dep-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="dep-head" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const ya = y(left, e.a), yb = y(right, e.b);
          const mid = (x1 + x2) / 2;
          const cls = e.kind.startsWith("correlated") ? "dep-edge corr" : e.kind === "one-to-one" ? "dep-edge both" : "dep-edge";
          return (
            <path key={i} className={cls} d={`M${x1},${ya} C${mid},${ya} ${mid},${yb} ${x2 - 2},${yb}`}
              markerEnd={e.kind.startsWith("correlated") ? undefined : "url(#dep-arrow)"}
              markerStart={e.kind === "one-to-one" ? "url(#dep-arrow)" : undefined}>
              <title>{`${e.a} → ${e.b} · ${e.kind}`}</title>
            </path>
          );
        })}
        {left.map((c) => (
          <g key={`l-${c}`} className="dep-node">
            <rect x={2} y={y(left, c) - 12} width={NODE_W - 4} height={24} rx={6} />
            <text x={12} y={y(left, c) + 4}>{short(c)}<title>{c}</title></text>
          </g>
        ))}
        {right.map((c) => (
          <g key={`r-${c}`} className="dep-node">
            <rect x={x2 + 2} y={y(right, c) - 12} width={NODE_W - 4} height={24} rx={6} />
            <text x={x2 + 12} y={y(right, c) + 4}>{short(c)}<title>{c}</title></text>
          </g>
        ))}
      </svg>
      <figcaption className="caption">Left determines right: every value on the left goes with one value on the right · arrows both ways - one-to-one · dashed - correlated numbers</figcaption>
    </figure>
  );
}
