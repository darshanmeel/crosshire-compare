// web/src/sources/loadTime.ts - how long each side's last Load took, for the card's "Loaded · 0.3s".
// The API does not keep it, so the page times its own Load; a side loaded some other way (the example,
// a config) shows plain "Loaded". Kept outside React so it survives the Compare | Profiling switch.
import type { SideView, Tag } from "./types";

const times = new Map<Tag, { sig: string; secs: number; asked: string }>();
const sigOf = (v: SideView) => `${v.origin}|${v.label}|${v.rows}|${v.columns.join(",")}`;

/** asked: what the Load sent (its JSON, the name left out) - so the card can tell when the choices changed since. */
export function noteLoadTime(tag: Tag, v: SideView, secs: number, asked = "") { times.set(tag, { sig: sigOf(v), secs, asked }); }

/** True when this page loaded the side and the choices now differ from what that Load sent. */
export function changedSinceLoad(tag: Tag, v: SideView | undefined, asked: string): boolean {
  const t = times.get(tag);
  return !!(v?.loaded && t && t.sig === sigOf(v) && t.asked && t.asked !== asked);
}

/** The seconds the Load that read this very side took, or null when this page did not time it. */
export function loadTime(tag: Tag, v?: SideView): number | null {
  const t = times.get(tag);
  return v?.loaded && t && t.sig === sigOf(v) ? t.secs : null;
}

export function resetLoadTimes() { times.clear(); }

export const secs = (s: number) => (s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`);
