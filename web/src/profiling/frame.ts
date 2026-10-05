// web/src/profiling/frame.ts - reading the profile's tables by column name, and the number formats
// the Profile page shows (thousands separators, at most two decimals, percentages to two decimals).
import type { Frame, Profile } from "./types";

export type Row = Record<string, unknown>;

/** A table's rows as objects keyed by column name. */
export function rowsOf(t: Frame): Row[] {
  return t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])));
}

const two = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** A value as the page shows it: a number (or numeric text in a number column) with separators. */
export function fmt(v: unknown, numeric = true): string {
  if (v == null || v === "") return "";
  if (typeof v === "number") return two.format(v);
  const s = String(v);
  if (numeric && /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i.test(s.trim())) return two.format(Number(s));
  return s;
}

export const pct = (v: unknown) => `${Number(v ?? 0).toFixed(2)}%`;

/** The key's columns when the profile found one unique on every row, else []. */
export function keyColumns(p: Profile): string[] {
  if (p.keys.tone !== "success") return [];
  const first = rowsOf(p.keys.table)[0];
  return first ? String(first["Key columns"] ?? "").split(" + ").filter(Boolean) : [];
}

/** The statistics row of one column. */
export function statsOf(p: Profile, column: string): Row | undefined {
  return rowsOf(p.stats).find((r) => r.Column === column);
}

/** "20261004-154900" -> "04 Oct 2026 15:49". */
export function madeAt(made: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(made);
  if (!m) return made;
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1];
  return `${m[3]} ${mon} ${m[1]} ${m[4]}:${m[5]}`;
}
