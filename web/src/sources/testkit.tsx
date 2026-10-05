// web/src/sources/testkit.tsx - what the sources tests share (not a test file itself)
import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Meta } from "../api/client";
import type { SideView, SourcesBody, Tag } from "./types";

export type Call = [string, RequestInit | undefined];
export const META: Meta = { app_name: "X", tagline: "", theme: "aurora", kinds: {}, form: {} as Meta["form"], filepick: false };

export function view(tag: Tag, over: Partial<SideView> = {}): SideView {
  return { tag, loaded: false, name: "", label: "", origin: "", kind: "csv", rows: null, columns: [], cut: "",
           is_database: false, conn: "", fetched_at: "", snapshot: false, caption: "", notes: [], staged: "",
           fetched: null, ...over };
}

export function body(over: Partial<SourcesBody> = {}): SourcesBody {
  return { sides: { A: view("A"), B: view("B"), P: view("P") }, defaults: { A: "Left", B: "Right", P: "Table" },
           quick_ops: ["=", "contains", "is null"], name_help: { side: "side help", table: "table help" },
           upload_types: ["csv", "json", "parquet"], config: null, ...over };
}

export const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });

export function mount(ui: ReactElement) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}
