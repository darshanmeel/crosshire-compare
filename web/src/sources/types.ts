// web/src/sources/types.ts
export type Tag = "A" | "B" | "P";
export type Tone = "error" | "warning" | "info" | "success" | "caption";
export type Note = { tone: Tone; text: string };
export type FetchedView = { at: string; rows: number; capped: boolean };
export type SideView = {
  tag: Tag; loaded: boolean; name: string; label: string; origin: string; kind: string; rows: number | null;
  columns: string[]; cut: string; is_database: boolean; conn: string; fetched_at: string; snapshot: boolean;
  caption: string; notes: Note[]; staged: string; fetched: FetchedView | null;
};
export type How = "upload" | "path" | "database";
export type SideForm = {
  name: string; how: How; path: string; folder: string; file: string; delimiter: string; header: boolean;
  where: string; order_by: string[]; desc: boolean; limit: number; column_names: string; snapshot: boolean;
  connection: string; db_mode: "table" | "sql"; table: string; sql: string; cap: number; password: string;
};
export type ConfigView = { n: number; said: Note[]; boxes: { settings: Record<string, unknown>; A: Partial<SideForm>; B: Partial<SideForm> } };
export type SourcesBody = {
  sides: Record<Tag, SideView>; defaults: Record<Tag, string>; quick_ops: string[];
  name_help: { side: string; table: string }; upload_types: string[]; config: ConfigView | null;
};
export type Schema = { label: string; kind: string; columns: { name: string; type: string }[]; error: string };
export type DbPlan = { sql: string; error: string; warning: string; held: FetchedView | null; password: "none" | "held" | "asked" };
export type FolderRow = { name: string; host: string };
export type FolderFiles = { root: string; files: string[]; note: Note | null };

export const DEFAULT_NAMES: Record<Tag, string> = { A: "Left", B: "Right", P: "Table" };   // = loading.DEFAULT_NAMES
export const CAP_DEFAULT = 1_000_000;                                                       // = connforms.CAP_DEFAULT

export function blankForm(tag: Tag): SideForm {
  return { name: DEFAULT_NAMES[tag], how: "upload", path: "", folder: "", file: "", delimiter: ",", header: true,
           where: "", order_by: [], desc: false, limit: 0, column_names: "", snapshot: true,
           connection: "", db_mode: "table", table: "", sql: "", cap: CAP_DEFAULT, password: "" };
}

export const dbOf = (f: SideForm) => ({ connection: f.connection, mode: f.db_mode, table: f.table, sql: f.sql, cap: f.cap });

export const pickOf = (f: SideForm) => ({
  how: f.how, path: f.path, folder: f.folder, file: f.file, delimiter: f.delimiter, header: f.header,
  db: f.how === "database" ? dbOf(f) : null,
});
