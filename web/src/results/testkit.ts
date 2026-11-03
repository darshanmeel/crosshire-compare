// web/src/results/testkit.ts - a stub of GET /api/results/{run}/values for the results tests (not a
// test file itself): counts that follow the query - side, basis, search, paging and bins.
import { json } from "../sources/testkit";
import type { Side, ValueRow, ValuesBody } from "./valuesApi";

// value, rows on A, rows on B - five named values, 35 small ones, and null
const BASE: [string | null, number, number][] = [
  ["Alpha", 900, 880], ["Bravo", 700, 690], ["Charlie", 500, 520], ["Delta", 300, 310], ["Echo", 100, 90],
  ...Array.from({ length: 35 }, (_, i): [string, number, number] => [`V${String(i + 6).padStart(2, "0")}`, 12, 11]),
  [null, 80, 64],
];

export function valuesBody(over: Partial<ValuesBody> = {}): ValuesBody {
  return { column: "department", subset: "all", side: "a", differs: "", basis: "all", kind: "text", sides: [],
           values: 0, page: 1, size: 25, rows: [], hist: [], ...over };
}

/** The values a query asks for, counted on BASE; null when the URL is not the values call. */
export function serveValues(url: string): Response | null {
  const u = new URL(url, "http://x");
  if (!/^\/api\/results\/\w+\/values$/.test(u.pathname)) return null;
  const p = u.searchParams;
  const column = p.get("column") ?? "", side = (p.get("side") ?? "a") as Side, basis = p.get("basis") === "nonnull" ? "nonnull" : "all";
  const search = (p.get("search") ?? "").toLowerCase(), page = Number(p.get("page") ?? 1), size = Number(p.get("size") ?? 25);
  const bins = Number(p.get("bins") ?? 0);
  const at = side === "both" ? [1, 2] : side === "b" ? [2] : [1];
  const sum = (r: (typeof BASE)[number]) => at.reduce((t, i) => t + (r[i] as number), 0);
  const ranked = BASE.filter((r) => basis === "all" || r[0] != null).sort((x, y) => sum(y) - sum(x));
  const cum = at.map(() => 0);
  const all: ValueRow[] = ranked.map((r, k) => ({
    rank: k + 1, value: r[0], ...(side === "pair" ? { b: r[0] === "Delta" ? "Delta" : r[0] && `${r[0]} EMEA` } : {}),
    n: at.map((i) => r[i] as number), cum: at.map((i, j) => (cum[j] += r[i] as number)),
  }));
  const said = (v: string | null | undefined) => (v == null ? "null" : v === "" ? "empty" : v.toLowerCase());   // as the page shows it
  const hit = all.filter((r) => !search || [r.value, ...(side === "pair" ? [r.b] : [])].some((v) => said(v).includes(search)));
  const sides = at.map((i) => ({
    side: (side === "pair" ? "pair" : i === 1 ? "a" : "b") as "a" | "b" | "pair",
    rows: BASE.reduce((t, r) => t + (r[i] as number), 0), nulls: BASE.find((r) => r[0] == null)![i] as number,
    distinct: BASE.length - 1, top: Math.max(...ranked.map((r) => r[i] as number)),
  }));
  const number = column === "salary";
  const hist = number && bins && side !== "pair"
    ? at.map((i) => ({ side: (i === 1 ? "a" : "b") as "a" | "b", median: 8672.87,
                       bins: [{ lo: 2152.33, hi: 6428.08, n: 987 }, { lo: 6428.08, hi: 10703.82, n: 992 }, { lo: 10703.82, hi: 14979.57, n: 1021 }] }))
    : [];
  return json(valuesBody({ column, subset: (p.get("subset") ?? "all") as ValuesBody["subset"], side, differs: p.get("differs") ?? "", basis,
                           kind: number ? "number" : "text", sides, values: hit.length, page, size,
                           rows: hit.slice((page - 1) * size, page * size), hist }));
}
