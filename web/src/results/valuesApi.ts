// web/src/results/valuesApi.ts - GET /api/results/{run}/values: one column's values counted over a
// set of rows (all rows of a side, the differing rows, a side's one-sided rows), most frequent first.
// Written by hand - npm run gen:api does not run with this TypeScript.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { HistBin } from "../profiling/types";

export type Subset = "all" | "differ" | "only_a" | "only_b";
export type Side = "a" | "b" | "both" | "pair";
export type Basis = "all" | "nonnull";
export type ValuesQuery = {
  column: string; subset?: Subset; side?: Side; differs?: string; basis?: Basis;
  search?: string; page?: number; size?: number; bins?: number;
};
/** Counted on the whole set, whatever the search: rows, the null rows, non-null values, the largest count. */
export type ValueSide = { side: "a" | "b" | "pair"; rows: number; nulls: number; distinct: number; top: number };
/** n and cum in the order of `sides`; `b` only for a pair. Values are text or null. */
export type ValueRow = { rank: number; value: string | null; b?: string | null; n: number[]; cum: number[] };
export type HistSide = { side: "a" | "b"; bins: HistBin[]; median: number | string | null };
export type ValuesBody = {
  column: string; subset: Subset; side: Side; differs: string; basis: Basis; kind: string;
  sides: ValueSide[]; values: number; page: number; size: number; rows: ValueRow[]; hist: HistSide[];
};

const ORDER = ["column", "subset", "side", "differs", "basis", "search", "page", "size", "bins"] as const;

export function valuesUrl(runId: string, q: ValuesQuery) {
  const p = new URLSearchParams();
  for (const k of ORDER) if (q[k] !== undefined && q[k] !== "") p.set(k, String(q[k]));
  return `/api/results/${runId}/values?${p}`;
}

export const useValues = (runId: string, q: ValuesQuery, enabled = true) =>
  useQuery({ queryKey: ["results", runId, "values", q], enabled, staleTime: Infinity, placeholderData: keepPreviousData,
             queryFn: () => api.get<ValuesBody>(valuesUrl(runId, q)) });

const STEPS = [1, 2, 5, 10, 20, 25, 50, 100];
/** The axis a bar chart is drawn on: the smallest round step that holds the largest share. */
export const axisMax = (pct: number) => STEPS.find((s) => s >= pct) ?? 100;

/** The colour class of a value by its place: the first three their own shade, the rest one. */
export const rankCls = (i: number) => (i < 3 ? `r${i + 1}` : "rn");

export const HIST_KINDS = new Set(["number", "date", "timestamp"]);
