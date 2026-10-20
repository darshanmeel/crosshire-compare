// web/src/columns/pairing.ts - what the pairing board says about a row, worked out from the setup view
// (no fetching here): its role, how the pair was made, its steps in a line, its case.
import type { Row, SetupReady, Spec, Step } from "../setup/api";
import { plural } from "../ui/kit";

export type Role = "key" | "compare" | "skip";

export const paired = (r: Row) => !!(r["A column"] && r["B column"]);

/** Key, Compare or Skip - a pair not compared and a one-sided column are both Skip. */
export const roleOf = (r: Row): Role => (!paired(r) ? "skip" : r.Key ? "key" : r.Compare ? "compare" : "skip");

/** The Key / Compare ticks to send, in order, to turn a row's role into another. */
export function roleWrites(r: Row, to: Role): ["Key" | "Compare", boolean][] {
  const w: ["Key" | "Compare", boolean][] = [];
  if (to === "key") { if (!r.Key) w.push(["Key", true]); return w; }
  if (r.Key) w.push(["Key", false]);
  if (to === "compare" && !r.Compare) w.push(["Compare", true]);
  if (to === "skip" && r.Compare) w.push(["Compare", false]);
  return w;
}

export type Origin = { text: string; tone: "" | "warn" | "neg"; title?: string; guess?: "values" | "name" };

/** How the row came to be, from its Matched by cell (columns.build_table / match_by_data / normalise). */
export function originOf(r: Row, names: [string, string]): Origin {
  if (!paired(r)) return { text: `only in ${r["A column"] ? names[0] : names[1]}`, tone: "neg" };
  const m = r["Matched by"];
  if (m === "name") return { text: "name", tone: "", title: "The same name on both sides" };
  if (m === "similar name") return { text: "similarity", tone: "", title: "Names close enough to pair" };
  if (m === "guess - check") return { text: "guess · check", tone: "warn", title: "Names only loosely alike - check the pair", guess: "name" };
  if (m === "data") return { text: "guess · check", tone: "warn", title: "Paired by the values they hold - check the pair", guess: "values" };
  if (m === "you") return { text: "you", tone: "", title: "Picked by hand" };
  return { text: m || "-", tone: "" };
}

/** The pair's spec (its steps) - the specs are the pairs, named by their common name. */
export const specIndex = (s: SetupReady, r: Row) => (paired(r) ? s.specs.findIndex((sp) => sp.canon === r["Common name"]) : -1);

/** A step in plain words with its values in place: `part 2 split by " "`, `to date %d/%m/%Y`. A
 *  parameter the op names by a capital letter (N, M, S, C) takes that letter's place; any other
 *  follows the op, a lone one as it is (a format, an expression), two quoted with an arrow. */
export function plainStep(st: Step): string {
  const p = Object.entries(st.params ?? {}).map(([k, v]) => [k, String(v ?? "")] as const);
  const q = (v: string) => (/^\d+$/.test(v) ? v : `"${v}"`);
  const inName = (k: string) => k.length === 1 && st.op.split(" ").map((w) => w.replace(",", "")).includes(k.toUpperCase());
  const words = st.op.replace(/\b[A-Z]\b/g, (c) => { const hit = p.find(([k]) => k === c.toLowerCase()); return hit ? q(hit[1]) : c; });
  const rest = p.filter(([k]) => !inName(k)).map(([, v]) => v);
  const tail = rest.length > 1 ? rest.map(q).join(" → ") : (rest[0] ?? "").trim();
  return tail ? `${words} ${tail}` : words;
}

/** A side's steps in plain words, or as the engine said them when the two lists do not line up. */
export const plainSteps = (steps: Step[] | undefined, said: string[] | undefined): string[] =>
  steps?.length && steps.length === said?.length ? steps.map(plainStep) : said ?? [];

/** The steps of a pair in one line, as the engine says them: `B · part N split by S (separator=' ', N=2)`,
 *  both sides when both have some. `plain` says them in plain words instead: `B · part 2 split by " "`. */
export function stepsLine(sp: Spec | undefined, plain = false): string {
  if (!sp) return "";
  const said = (k: "A" | "B") => (k === "A" ? sp.a_said ?? [] : sp.b_said ?? []);
  const words = (k: "A" | "B") => (plain ? plainSteps(k === "A" ? sp.a_steps : sp.b_steps, said(k)) : said(k));
  const side = (k: "A" | "B") => (words(k).length ? `${k} · ${words(k).join(", then ")}` : "");
  return [side("A"), side("B")].filter(Boolean).join("; ");
}

export const isText = (r: Row) => r.Type === "text";

/** The words a Case value is shown as: blank follows the Ignore case in values switch. */
export const caseText = (v: string, ignoreCase: boolean) =>
  v === "ignore" ? "ignore" : v === "exact" ? "exact" : `${ignoreCase ? "ignore" : "exact"} · default`;

/** The section's sub-line: `6 pairs · 1 only in HR · 1 only in Payroll`. */
export function subLine(s: SetupReady): string {
  const [NA, NB] = s.names;
  return [plural(s.specs.length, "pair"),
          s.only_a.length ? `${s.only_a.length.toLocaleString("en-US")} only in ${NA}` : "",
          s.only_b.length ? `${s.only_b.length.toLocaleString("en-US")} only in ${NB}` : ""].filter(Boolean).join(" · ");
}

/** The pairs that are guesses, and the line the panel foot says about them. */
export function guessLine(s: SetupReady): string {
  const guesses = s.rows.filter((r) => originOf(r, s.names).guess);
  if (!guesses.length) return "";
  const fromValues = guesses.every((r) => originOf(r, s.names).guess === "values");
  const what = guesses.length === 1 ? "1 pair is a guess" : `${guesses.length} pairs are guesses`;
  return `${what}${fromValues ? " from the values" : ""} — check`;
}
export const guessPairs = (s: SetupReady) =>
  s.rows.filter((r) => originOf(r, s.names).guess).map((r) => `${r["A column"]} ⇄ ${r["B column"]}`);
