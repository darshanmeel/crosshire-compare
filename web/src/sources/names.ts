// web/src/sources/names.ts - loading.side_name / compare.side_labels / loading.name_hint, on the page
import { DEFAULT_NAMES, type SideView, type Tag } from "./types";

export function sideName(tag: Tag, box: string, side?: SideView): string {
  const b = (box ?? "").trim();
  return b && b !== DEFAULT_NAMES[tag] ? b : (side?.name || DEFAULT_NAMES[tag]).trim();
}

export function sideLabels(a: string, b: string): [string, string] {
  return a !== b ? [a, b] : [`A · ${a}`, `B · ${b}`];
}

export function nameHint(tag: Tag, box: string, side: SideView, mine: string, other: string): string {
  if (mine === other) return `:orange[Both sides are called ${other}] - name this one to tell them apart`;
  const b = (box ?? "").trim();
  if (!side.is_database && (b === "" || b === DEFAULT_NAMES[tag])) return "Tip: name this side - it names the output files";
  return "";
}
