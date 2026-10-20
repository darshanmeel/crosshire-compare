// web/src/sources/names.ts - loading.side_name / compare.side_labels / loading.name_hint, on the page
import { DEFAULT_NAMES, type SideView, type Tag } from "./types";

export function sideName(tag: Tag, box: string, side?: SideView): string {
  const b = (box ?? "").trim();
  return b && b !== DEFAULT_NAMES[tag] ? b : (side?.name || DEFAULT_NAMES[tag]).trim();
}

export function sideLabels(a: string, b: string): [string, string] {
  return a !== b ? [a, b] : [`A · ${a}`, `B · ${b}`];
}

/** The word under a loaded A or B about its name: only when both sides share one. */
export function nameHint(mine: string, other: string): string {
  return mine === other ? `:orange[Both sides are called ${other}] - name this one to tell them apart` : "";
}

/** The Name box after a Load: a box left blank or at its default takes the name the side was loaded
 *  with (a database side's connection); a typed name stays. */
export function boxAfterLoad(tag: Tag, box: string, side: SideView): string {
  const b = (box ?? "").trim();
  return (b === "" || b === DEFAULT_NAMES[tag]) && side.name ? side.name : box;
}
