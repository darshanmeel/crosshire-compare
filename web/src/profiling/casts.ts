// web/src/profiling/casts.ts - what a text column could be read as (GET /api/profiling/casts),
// said as the type it would take: DECIMAL(p, s) or BIGINT, DATE or TIMESTAMP with its format.
import type { CastHit, CastRow } from "./types";

export type CastKind = "number" | "date" | "timestamp";
export const CAST_KINDS: CastKind[] = ["timestamp", "date", "number"];

/** The SQL type the values would take, and the form they are written in when it is not plain. */
export function castType(kind: CastKind, h: CastHit): { type: string; form: string } {
  if (kind === "number") {
    const p = h.before ?? 0, s = h.after ?? 0;
    const type = s === 0 && p <= 18 ? "BIGINT" : `DECIMAL(${Math.min(38, p + s)}, ${s})`;
    return { type, form: h.form === "plain" ? "" : h.form };
  }
  return { type: kind.toUpperCase(), form: h.form === "ISO" ? "" : h.form };
}

/** The types a column could take, the most values first; a number only when no date or time
 *  reads as many (a compact 20260504 reads as both). */
export function castsOf(r: CastRow): { kind: CastKind; hit: CastHit }[] {
  const all = CAST_KINDS.filter((k) => r[k]).map((k) => ({ kind: k, hit: r[k]! }));
  return all.sort((a, b) => b.hit.any - a.hit.any);
}
