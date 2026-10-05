// web/src/results/detailApi.ts - what the Differing rows, Report and Downloads tabs read (SPEC §09,
// §11, §12): the page of differing rows and its pivot to one row per key, and the run's files.
import { useInfiniteQuery, useQuery, type InfiniteData } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Frame } from "./types";

/** GET /api/results/{run}/diff-rows - a page of the rows that paired but differ, A then B. */
export type DiffRowsPage = {
  keys: string[]; columns: string[]; only_a: string[]; only_b: string[];
  by_column: { column: string; n: number }[]; column: string; total: number; offset: number;
  frame: Frame; marks: string[][]; cells: number[]; file: string; note: string;
};
/** One row per key: the key values, A's and B's value of every column, the columns that differ. */
export type KeyRow = { key: unknown[]; a: Record<string, unknown>; b: Record<string, unknown>; diff: Set<string>; n: number };

export const PAGE = 50;

/** The A/B row pairs of a page turned into one row per key. */
export function pivot(page: Pick<DiffRowsPage, "keys" | "frame" | "marks" | "cells">): KeyRow[] {
  const { columns, rows } = page.frame;
  const at = (r: unknown[]) => Object.fromEntries(columns.map((c, j) => [c, r[j]]));
  const out: KeyRow[] = [];
  for (let i = 0; i + 1 < rows.length; i += 2) {
    const a = at(rows[i]), b = at(rows[i + 1]);
    const p = i / 2;
    out.push({ key: page.keys.map((k) => a[k]), a, b, diff: new Set(page.marks[p] ?? []), n: page.cells[p] ?? 0 });
  }
  return out;
}

export function useDiffRows(runId: string, column: string) {
  return useInfiniteQuery<DiffRowsPage, Error, InfiniteData<DiffRowsPage>, string[], number>({
    queryKey: ["results", runId, "diff-rows", column], staleTime: Infinity, initialPageParam: 0, 
    placeholderData: (prev, q) => (q?.queryKey[1] === runId ? prev : undefined),   // a filter switch keeps the table up
    queryFn: ({ pageParam }) => api.get<DiffRowsPage>(
      `/api/results/${runId}/diff-rows?offset=${pageParam}&limit=${PAGE}${column ? `&column=${encodeURIComponent(column)}` : ""}`),
    getNextPageParam: (last) => (last.offset + last.marks.length < last.total ? last.offset + last.marks.length : undefined),
  });
}

// The run's files - the same read and cache key as results/useFiles.ts, so the tabs share one fetch.
export type Sized = { name: string; bytes: number };
export type FileRow = { name: string; label: string; bytes: number };
export type FilesView = {
  config: Sized | null; engine: Sized | null; engine_gone: boolean; report: string; files: FileRow[];
  paired: boolean; zip: Sized | null; parquet: boolean; out_fmt: "csv" | "parquet" | "both"; save_folder: string;
};
export type SaveOut = { tone: "success"; text: string; files: FilesView };

export const filesKey = (runId: string, limit: number) => ["results", runId, "files", limit];
export const fileUrl = (runId: string, name: string) => `/api/results/${runId}/file/${encodeURIComponent(name)}`;
const one = { minimumFractionDigits: 1, maximumFractionDigits: 1 };
/** A file's size with its unit: KB under a megabyte, so a small file is not "0.0 MB". */
export const size = (bytes: number) =>
  bytes < 1e6 ? `${Math.max(1, Math.round(bytes / 1e3)).toLocaleString("en-US")} KB` : `${(bytes / 1e6).toLocaleString("en-US", one)} MB`;

export function useRunFiles(runId: string, limit: number) {
  return useQuery({ queryKey: filesKey(runId, limit), staleTime: Infinity,
                    queryFn: () => api.get<FilesView>(`/api/results/${runId}/files`) });
}

/** Start a browser download of one URL, as a link the reader clicked would. */
export function download(href: string, name = "") {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
