// web/src/keys/summary.ts - the Rows step in words: how rows match and what cuts them. The setup's
// Rows card and the rows page's helper line say it the same way.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FiltersView, KeysView } from "../setup/api";
import type { SourcesBody } from "../sources/types";
import { FILTERS_KEY, activeFilters } from "../values/FiltersBox";
import { num } from "../ui/kit";

export const useFilters = () => useQuery({ queryKey: FILTERS_KEY, queryFn: () => api.get<FiltersView>("/api/setup/filters") });

export const NOKEY_SHORT = { position: "by position", hash: "by hash of compared columns" } as const;

/** "none - all 3,000 and 2,985 rows", or what cuts the rows: filters at compare, sides read cut. */
export function filterLine(src: SourcesBody | undefined, f: FiltersView | undefined): string {
  const A = src?.sides?.A, B = src?.sides?.B;
  const n = activeFilters(f).length;
  const cut = [A, B].filter((s) => s?.loaded && s.cut);
  if (!n && !cut.length) return A?.loaded && B?.loaded ? `none - all ${num(A.rows ?? 0)} and ${num(B.rows ?? 0)} rows` : "none";
  return [n ? `${n} filter${n === 1 ? "" : "s"} at compare` : "",
          ...cut.map((s) => `${s!.name} read to ${num(s!.rows ?? 0)} rows`)].filter(Boolean).join(" · ");
}

export function matchLine(keys: string[], k?: KeysView): string {
  return keys.length ? `on key ${keys.join(" + ")}` : NOKEY_SHORT[k?.nokey_mode ?? "hash"];
}
