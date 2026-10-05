import type { Note } from "../sources/types";

export type StripKey = "Files" | "Columns" | "Key" | "Compare" | "Result";
export type Strip = { cells: Record<StripKey, string>; tones: Partial<Record<StripKey, string>> };
export type Segment = { text: string; bold: boolean };
export type VerdictView = { tone: "ok" | "warn" | "bad"; word: string; when: string; segments: Segment[] };
export type RunView = {
  id: string; at: string; pair: string; mode: "key" | "hash" | "position"; names: [string, string];
  keys: string[]; columns: string[]; matched: number; diff_rows: number; stale: boolean; verdict: VerdictView;
};
export type CompareSettings = { display_rows: number; auto_rerun: boolean; out_fmt: "csv" | "parquet" | "both"; auto_profile: boolean };
export type CompareState = {
  gate: "" | "load" | "pair" | "tick"; names: [string, string]; strip: Strip; settings: CompareSettings;
  filter_error: string; sig: string; stale: boolean; busy: boolean; said: Note[]; run: RunView | null;
};

export const TICK_COMPARE = "Tick **Compare** on at least one column in the table.";   // = comparing.TICK_COMPARE
export const STALE = "Settings have changed since this comparison ran - the result below is from the previous settings. Press **Compare** to bring it up to date.";   // = comparing.STALE
export const RERUN_HELP = "Off: press Compare when you are ready - the last result stays on screen and is marked stale. On: every change re-runs.";
export const AUTO_PROFILE_HELP = "Off by default: it measures every column of both files - minutes on a big or wide pair - and Auto finds the key without it. Tick it and the counts, nulls and distinct values per column feed the key search, the Profile section under Rows and the profile.csv in the run folder.";
