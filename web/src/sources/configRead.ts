// What a saved config holds, read in the page from an uploaded file's text (the API reads a path
// itself, so a path's contents are known only once it has loaded), and a pairs.csv for the batch
// command - previewed here only; batch runs stay a command-line feature.

type Step = Record<string, unknown> & { op?: string };
type Col = { a?: string; b?: string; key?: boolean; compare?: boolean; a_steps?: Step[]; b_steps?: Step[] };
type SideBlock = { name?: string; path?: string; file?: string; folder?: string; connection?: string; query?: string; where?: string; limit?: number };
export type Conf = { kind?: string; sides?: { A?: SideBlock; B?: SideBlock }; columns?: Col[]; settings?: Record<string, unknown>; filters?: unknown[] };

export type ConfSummary = { pairs: number; keys: string[]; sources: string; pairList: string; steps: string; rows: string };

const KIND = "crosshire-compare config";
const base = (p: string) => p.split(/[\\/]/).pop() ?? p;

/** The config's text checked the way the server checks it, or why not. */
export function readConf(text: string): { conf?: Conf; error?: string } {
  let conf: Conf;
  try { conf = JSON.parse(text); } catch { return { error: "Not JSON - pick the config.json a run wrote." }; }
  if (!conf || typeof conf !== "object" || conf.kind !== KIND) return { error: "Not a config file - save one from the Downloads tab after a run." };
  if (!conf.sides?.A || !conf.sides?.B) return { error: "It needs both sides, A and B." };
  if (!conf.columns?.length) return { error: "It pairs no columns." };
  return { conf };
}

function source(s: SideBlock | undefined, tag: string): string {
  const name = s?.name || tag;
  if (s?.connection) return `${name} · ${s.connection}${s.query ? " (query)" : ""}`;
  const f = s?.file ? `${s.folder}/${s.file}` : s?.path ? base(s.path) : "?";
  return `${name} · ${f}`;
}

function stepText(s: Step): string {
  const rest = Object.entries(s).filter(([k, v]) => k !== "op" && v !== "" && v != null).map(([, v]) => (typeof v === "string" ? `"${v}"` : String(v)));
  return [String(s.op ?? "").replace(/_/g, " "), ...rest].join(" ");
}

export function summarise(conf: Conf): ConfSummary {
  const cols = (conf.columns ?? []).filter((c) => c.a && c.b);
  const keys = cols.filter((c) => c.key).map((c) => c.a!);
  const nameA = conf.sides?.A?.name || "A", nameB = conf.sides?.B?.name || "B";
  const steps: string[] = [];
  for (const [side, field] of [[nameA, "a_steps"], [nameB, "b_steps"]] as const) {
    const parts = cols.filter((c) => c[field]?.length).map((c) => `${field === "a_steps" ? c.a : c.b} ${c[field]!.map(stepText).join(", ")}`);
    if (parts.length) steps.push(`${side}: ${parts.join(" · ")}`);
  }
  const s = conf.settings ?? {};
  const mode = s.mode === "hash" ? "match by hash" : s.mode === "position" ? "match by position" : `match on key${keys.length ? ` ${keys.join(", ")}` : ""}`;
  const filtered = (conf.filters?.length ?? 0) > 0 || !!conf.sides?.A?.where || !!conf.sides?.B?.where;
  const capped = [conf.sides?.A, conf.sides?.B].some((x) => (x?.limit ?? 0) > 0);
  return {
    pairs: cols.length, keys,
    sources: `${source(conf.sides?.A, "A")} - ${source(conf.sides?.B, "B")}`,
    pairList: cols.map((c) => `${c.a} ⇄ ${c.b}${c.key ? " (key)" : c.compare === false ? " (skip)" : ""}`).join(" · "),
    steps: steps.join(" · ") || "none",
    rows: [mode, filtered ? "filtered" : "no filter", capped ? "top rows only" : "all rows"].join(" · "),
  };
}

/** One CSV line's cells, with "quoted, values" and "" inside quotes. */
function cells(line: string): string[] {
  const out: string[] = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') q = false;
      else cur += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { out.push(cur.trim()); cur = ""; }
    else cur += ch;
  }
  out.push(cur.trim());
  return out;
}

export type PairRow = { left: string; right: string; name_left: string; name_right: string };

/** A pairs.csv as `python -m tablecmp.run --pairs` reads it: left, right[, name_left, name_right]. */
export function readPairs(text: string): { rows?: PairRow[]; error?: string } {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { error: "The file is empty." };
  const head = cells(lines[0]).map((h) => h.toLowerCase());
  if (!head.includes("left") || !head.includes("right")) return { error: "It needs a left and a right column." };
  const at = (r: string[], k: string) => (head.indexOf(k) >= 0 ? r[head.indexOf(k)] ?? "" : "");
  const rows = lines.slice(1).map(cells).map((r) => ({ left: at(r, "left"), right: at(r, "right"), name_left: at(r, "name_left"), name_right: at(r, "name_right") }))
    .filter((r) => r.left || r.right);
  return { rows };
}

/** A path for a shell command line: quoted when it has a space. */
export const arg = (p: string) => (/\s/.test(p) ? `"${p}"` : p);
