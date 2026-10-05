export type Frame = { columns: string[]; rows: unknown[][] };
export type Metric = { label: string; value: number | string; help?: string };
export type Summary = {
  mode: "key" | "hash" | "position"; keys: string[]; key_line: string; key_warning: { head: string; points: string[] } | null;
  counts: Metric[]; filter_note: string; unmatched: { lead: string; lines: string[] } | null; column_counts: Metric[];
  one_sided: string; overall: Metric[] | null; overall_caption: string; hash_caption: string; ledger: Frame; tones: string[];
  buckets: { id: string; label: string }[]; default_bucket: string; sided_tip: string;
};
export type BucketBody = {
  bucket: string; by_key: { title: string; tables: { title: string; table: Frame }[]; after: string } | null;
  others: { name: string; label: string }[]; others_title: string; profiles: { column: string; title: string; table: Frame }[];
  empty: string;
  shown: string[]; groups: { title: string; tone?: "nc"; items: { name: string; label: string }[] }[];   // the plan's own, every column by kind
};
/** GET /api/results/{run}/buckets/{bucket}/facts - the extended column profile, a side each. */
export type Top = { value: string; n: number; pct: number };
export type SideFacts = {
  side: "A" | "B"; label: string; rows: number; nulls: number; null_pct: number; distinct: number; top: Top | null;
  length: { min: number; max: number } | null; number: { min: number; max: number; mean: number } | null;
  date: { min: string; max: string } | null; shapes: { shape: string; n: number; pct: number }[];
  prefixes: Top[]; suffixes: Top[]; spellings: { members: string[]; rows: number; why: string }[];
};
export type BucketFacts = { bucket: string; columns: { column: string; sides: SideFacts[] }[] };
export type Card = { column: string; head: string; warning: string; pairs: Frame | null };
export type ColumnsBody = {
  hash_caption: string; tips?: string[]; differ_error?: string;
  rows?: { title: string; table: Frame | null; marks: Record<string, string[]> } | null;
  rest?: string[]; rest_title?: string; cards?: Card[]; near_match?: boolean;
};

/** ?key=a&key=b - the columns a view is asked to add. */
export const qs = (key: string, values: string[]) =>
  values.length ? "?" + values.map((v) => `${key}=${encodeURIComponent(v)}`).join("&") : "";

/** GET /api/results/{run}/pairs/{column} - the most frequent value pairs behind a column's mismatches. */
export type Pairs = { column: string; mismatches: number; distinct: number; pairs: { a: string; b: string; n: number }[] };
/** GET /api/results/{run}/one-sided/{A|B} - a page of the rows only one side has. */
export type OneSided = {
  side: "A" | "B"; file: string; keys: string[]; total: number; offset: number;
  columns: string[]; rows: unknown[][]; constant: { column: string; value: string }[];
  groups: { title: string; tone?: "nc"; items: string[] }[]; shown: string[];   // every column by kind; the key and three compared
};

/** The row counts of the Summary by what they are - the server lists them in this order. */
export function countsOf(s: Summary) {
  const v = (i: number) => (typeof s.counts[i]?.value === "number" ? (s.counts[i].value as number) : 0);
  const matched = v(2), diff = v(5);
  return { rowsA: v(0), rowsB: v(1), matched, onlyA: v(3), onlyB: v(4), diff, full: matched - diff };
}

/** The ledger as records: one per column of either file. */
export type LedgerRow = Record<string, unknown> & { Column: string; Role: string };
export const ledgerRows = (f: Frame): LedgerRow[] =>
  f.rows.map((r) => Object.fromEntries(f.columns.map((c, i) => [c, r[i]])) as LedgerRow);
