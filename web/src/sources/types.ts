// web/src/sources/types.ts
export type Tag = "A" | "B" | "P";
export type Tone = "error" | "warning" | "info" | "success" | "caption";
export type Note = { tone: Tone; text: string };
export type FetchedView = { at: string; rows: number; capped: boolean };
export type SideView = {
  tag: Tag; loaded: boolean; name: string; label: string; origin: string; kind: string; rows: number | null;
  columns: string[]; cut: string; is_database: boolean; conn: string; fetched_at: string; snapshot: boolean;
  caption: string; notes: Note[]; staged: string; fetched: FetchedView | null;
  sheet?: string; cell_range?: string; stop_at_blank?: boolean; skip_rows?: number; read_from?: string;
  quote?: Quote; bad_rows?: BadRows; set_aside?: SetAsideInfo | null;
};
export type Quote = '"' | "'" | "";
export type BadRows = "keep" | "set_aside";
/** The rows Load set aside for having too few or too many fields: all, kept to show, the width a row should have. */
export type SetAsideInfo = { rows: number; kept: number; fields: number; said: string; by: { fields: number | null; rows: number }[] };
export type SetAsidePage = SetAsideInfo & { page: number; size: number; lines: { line: number; fields: number | null; raw: string }[] };
export type How = "upload" | "path" | "database";
export type SideForm = {
  name: string; how: How; path: string; folder: string; file: string; delimiter: string; header: boolean;
  where: string; order_by: string[]; desc: boolean; limit: number; column_names: string; snapshot: boolean;
  connection: string; db_mode: "table" | "sql"; table: string; sql: string; cap: number; password: string;
  sheet: string; cell_range: string; stop_at_blank: boolean; skip_rows: number;   // Excel: where the table sits; CSV: lines above the header
  quote: Quote; bad_rows: BadRows;                                                 // CSV: the quote character, rows of the wrong width
};
export type ConfigView = { n: number; said: Note[]; boxes: { settings: Record<string, unknown>; A: Partial<SideForm>; B: Partial<SideForm> } };
export type SourcesBody = {
  sides: Record<Tag, SideView>; defaults: Record<Tag, string>; quick_ops: string[];
  name_help: { side: string; table: string }; upload_types: string[]; config: ConfigView | null;
};
export type Schema = { label: string; kind: string; columns: { name: string; type: string }[]; error: string;
                       sheets?: string[]; sheet?: string; hidden?: string[] };   // an Excel file: its sheets, the one read, the hidden ones
export type DbPlan = { sql: string; error: string; warning: string; held: FetchedView | null; password: "none" | "held" | "asked" };
export type FolderRow = { name: string; host: string };
export type FolderFiles = { root: string; files: string[]; note: Note | null };

export const DEFAULT_NAMES: Record<Tag, string> = { A: "Left", B: "Right", P: "Table" };   // = loading.DEFAULT_NAMES
export const CAP_DEFAULT = 1_000_000;                                                       // = connforms.CAP_DEFAULT

export function blankForm(tag: Tag): SideForm {
  return { name: DEFAULT_NAMES[tag], how: "upload", path: "", folder: "", file: "", delimiter: ",", header: true,
           where: "", order_by: [], desc: false, limit: 0, column_names: "", snapshot: true,
           connection: "", db_mode: "table", table: "", sql: "", cap: CAP_DEFAULT, password: "",
           sheet: "", cell_range: "", stop_at_blank: false, skip_rows: 0, quote: '"', bad_rows: "keep" };
}

/** Where the table sits in a file - cleared whenever the user picks another file, so a range or a
 *  sheet meant for the old one is never applied to the new one. */
export const FRESH_READ = { sheet: "", cell_range: "", stop_at_blank: false, skip_rows: 0 } as const;

export const dbOf = (f: SideForm) => ({ connection: f.connection, mode: f.db_mode, table: f.table, sql: f.sql, cap: f.cap });

export const pickOf = (f: SideForm) => ({
  how: f.how, path: f.path, folder: f.folder, file: f.file, delimiter: f.delimiter, header: f.header,
  db: f.how === "database" ? dbOf(f) : null,
  sheet: f.sheet, cell_range: f.cell_range, stop_at_blank: f.stop_at_blank, skip_rows: f.skip_rows,
  quote: f.quote, bad_rows: f.bad_rows,
});

/** What a Load sends, past the name: the pick and the cut. Callers add `name`. */
export const loadBody = (f: SideForm) => ({
  ...pickOf(f), where: f.where, order_by: f.order_by, desc: f.desc, limit: f.limit,
  column_names: f.column_names, snapshot: f.snapshot,
});
