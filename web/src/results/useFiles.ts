// web/src/results/useFiles.ts
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

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

/** The run's files as Downloads lists them - the report among them built for the rows shown. */
export function useFiles(runId: string, limit: number) {
  return useQuery({ queryKey: filesKey(runId, limit), staleTime: Infinity,
                    queryFn: () => api.get<FilesView>(`/api/results/${runId}/files`) });
}
