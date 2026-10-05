// web/src/setup/api.ts - the setup's contract with the server (tablecmp/web/routes_setup.py):
// every shape /api/setup answers with, and the hooks the Columns, Values, Key and Rows boxes share.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";

export type Tone = "error" | "warning" | "info" | "success" | "caption";
export type Said = { tone: Tone; text: string };
export type Frame = { columns: string[]; rows: unknown[][] };

export const EDITABLE = ["A column", "B column", "Common name", "Type", "Key", "Compare", "Case"] as const;
export type Editable = (typeof EDITABLE)[number];
export type Row = {
  "A column": string; "B column": string; "Common name": string; Type: string; Key: boolean; Compare: boolean;
  Case: string; "Matched by": string; "A detected": string; "A looks like": string; "B detected": string;
  "B looks like": string; Role: string; tone: "pos" | "neg" | "";
};
export type Step = { op: string; params: Record<string, string> };
export type Spec = {
  canon: string; kind: string; a_src: string; b_src: string; a_steps: Step[]; b_steps: Step[]; case: string; describe: string;
  a_said: string[]; b_said: string[];    // each step as the page says it: "left N characters (N=10)"
};
export type Settings = {
  trim: boolean; empty_as_null: boolean; ignore_case: boolean; tolerance: number; null_tokens: string;
  nokey_mode: "hash" | "position";
};
export type SetupReady = {
  ready: true; names: [string, string]; rev: string;
  columns: { A: string[]; B: string[] }; types: string[]; cases: string[];
  rows: Row[]; pairs: number; chips: { text: string; cls: "" | "key" | "off" }[]; duplicates: string[];
  card: { label: string; html: string }[]; specs: Spec[];
  keys: string[]; compare: string[]; only_a: string[]; only_b: string[];
  can_match: boolean; data_match: (Frame & { pairs: number }) | null; said: Said[]; settings: Settings; looks_help: string;
  derived?: { name: string; a: string; b: string; a_type: string; b_type: string }[];   // the columns added from an expression
};
export type SetupView = { ready: false; names: [string, string] } | SetupReady;

export type StepsMeta = {
  steps: Record<string, string[]>; labels: Record<string, string>; numeric: string[];
  presets: Record<string, string>; types: string[];
};
export type TryView = Frame & { error: string };
export type CheckView = Frame & { said: string };
export type FilterRow = { "Apply to": string; Column: string; Operator: string; Value: string; Type: string };
export type FiltersView = { rows: FilterRow[]; rev: string; columns: string[]; apply_to: string[]; ops: string[]; types: string[]; error: string };

export type FormatLine = Said & { apply: number | null };
export type KeysView = {
  keys: string[]; mode: "key" | "hash" | "position"; nokey_mode: "hash" | "position";
  nokey_modes: Record<"hash" | "position", string>; tips: string[]; nokey_tips: string[];
  suggestions: (Frame & { said: Said; combos: string[][]; labels: string[] }) | null;
  report: (Frame & { said: Said }) | null;
  formats: FormatLine[]; error: string;
};
export type ProfileView = {
  stale: boolean; names: [string, string]; stale_said: string; both: Frame; A: Frame; B: Frame;
  freq_columns: string[]; freq_default: string[];
} | null;
export type FreqView = { title: string; A: { top: Frame; bottom: Frame }; B: { top: Frame; bottom: Frame } };

export const SETUP_KEY = ["setup"];
/** What a change to the column table can make stale - refetched after every setup write. */
export const DERIVED_KEYS = ["setup-keys", "setup-profile", "setup-freq", "setup-try", "setup-filters"];
export const STALE_TABLE = "The column table changed since - it is shown again as it is now.";

export const errorText = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));

export function useSetup() {
  return useQuery({ queryKey: SETUP_KEY, queryFn: () => api.get<SetupView>("/api/setup") });
}

export type SetupCall = { method?: "POST" | "PUT" | "DELETE"; path: string; body?: unknown };

/** A write to /api/setup that answers with the whole setup view: the view replaces the one held,
 *  and what was worked out from the table is fetched again. A 409 (the table changed since) fetches
 *  the table again too. */
export function useSetupSend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ method = "POST", path, body }: SetupCall) => api.send<SetupView>(method, `/api/setup${path}`, body),
    onSuccess: (view) => {
      qc.setQueryData(SETUP_KEY, view);
      DERIVED_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e) => { if (e instanceof ApiError && e.status === 409) qc.invalidateQueries({ queryKey: SETUP_KEY }); },
  });
}

/** A side's steps replaced as one write (a reorder, an edit, a step taken out of the middle): the
 *  server only adds to the list, so it is Clear and each step again - held back from the page until
 *  the last one lands, so a re-run never starts from half a list, and the old steps put back if
 *  any is refused. */
export function useStepsRebuild() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ canon, which, steps, was }: { canon: string; which: "A" | "B"; steps: Step[]; was: Step[] }) => {
      const call = (action: string, step: Step | null = null) =>
        api.send<SetupView>("POST", "/api/setup/steps", { canon, which, action, step });
      let view = await call("clear");
      try {
        for (const st of steps) view = await call("add", st);
      } catch (e) {
        try {
          await call("clear");
          for (const st of was) await call("add", st);
        } catch { /* the setup is fetched again below */ }
        throw e;
      }
      return view;
    },
    onSuccess: (view) => {
      qc.setQueryData(SETUP_KEY, view);
      DERIVED_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
    onError: () => refreshSetup(qc),
  });
}

/** After a write that changed the table without answering with it (the Key section's): fetch it all again. */
export function refreshSetup(qc: ReturnType<typeof useQueryClient>) {
  [...SETUP_KEY, ...DERIVED_KEYS].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}
