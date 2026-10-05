// web/src/sources/formStore.ts
// What is typed and picked in each side panel. It lives outside React's tree so that it survives
// the Compare | Profiling switch, which unmounts one page's panels - what state.KEEP did.
import { useSyncExternalStore } from "react";
import { blankForm, type SideForm, type Tag } from "./types";

const blank = (): Record<Tag, SideForm> => ({ A: blankForm("A"), B: blankForm("B"), P: blankForm("P") });
let forms = blank();
let configSeen = 0;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

export function getForm(tag: Tag): SideForm { return forms[tag]; }

export function setForm(tag: Tag, patch: Partial<SideForm>) {
  forms = { ...forms, [tag]: { ...forms[tag], ...patch } };
  emit();
}

export function resetForms() { forms = blank(); configSeen = 0; emit(); }

/** True once per loaded config (its counter n): the time to put its boxes into the forms. */
export function takeConfig(n: number): boolean {
  if (n === configSeen) return false;
  configSeen = n;
  return true;
}

export function useSideForm(tag: Tag): [SideForm, (patch: Partial<SideForm>) => void] {
  const f = useSyncExternalStore((cb) => { subs.add(cb); return () => { subs.delete(cb); }; }, () => forms[tag]);
  return [f, (patch) => setForm(tag, patch)];
}
