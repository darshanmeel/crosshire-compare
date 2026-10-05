// web/src/profiling/types.ts - what /api/profiling answers (tablecmp/web/routes_profiling.py)
import type { Tone } from "../sources/types";

export type Frame = { columns: string[]; rows: unknown[][] };
export type FreqInfo = { columns: string[]; picked: string[]; titles: Record<string, string> };
export type Profile = {
  headline: string; keys: { tone: Tone; text: string; table: Frame }; stats: Frame; notes: string[];
  outliers: Frame; patterns: Frame; deps: Frame; corr: Frame; freq: FreqInfo;
  matrix: Frame; matrix_note: string; search: KeySearch & { key_sample: number };
};
/** How far the key search grows and how many candidates it lists. */
/** Set on the page: combinations up to key_cols, the best `shortlist` found on the sample checked on every row, top_keys listed */
export type KeySearch = { key_cols: number; top_keys: number; shortlist: number };
export type ProfilingView = { profile: Profile | null; stale: boolean; made: string };
export type SaveDefaults = { csv_name: string; save_folder: string };
export type FreqBody = { column: string; title: string; top: Frame; bottom: Frame };
export type Saved = { text: string; folder: string };
export type HistBin = { lo: number | string; hi: number | string; n: number };
export type HistBody = { column: string; kind: string; bins: HistBin[] };
/** A text or number column that could be read as another type (GET /api/profiling/casts): how many filled
 *  values would, in any form tried, and the form most of them take. */
export type CastHit = { any: number; form: string; n: number; before?: number; after?: number };
export type CastRow = { column: string; kind: string; filled: number; number?: CastHit; date?: CastHit; timestamp?: CastHit };
export type CastsBody = { columns: CastRow[] };
/** One column taken apart (GET /api/profiling/parts). */
export type PartGroup = { title: string; total: number; rows: { label: string; n: number }[] };
export type PartsBody = { column: string; kind: string; groups: PartGroup[] };
