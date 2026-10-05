// web/src/shell/view.ts - which view of a page is on screen, outside React's tree like the forms,
// so a header button, a rail step or a section's link can switch it. Compare: the setup (sources,
// columns, rows), the values editor, the rows editor, the results, the Log or Run from config;
// Profiling: the profile, or one column of it. The drawer (Connections) sits over any of them.
import { useSyncExternalStore } from "react";

export type View = "setup" | "values" | "rows" | "results" | "log" | "config";
export type ResultsTab = "summary" | "rows" | "onesided" | "report" | "downloads";
export type ViewState = {
  view: View; drawer: "connections" | null; tab: ResultsTab; pair: number; column: string | null;
  anchor: string | null;     // a section of the setup to scroll to once it is drawn: "sources" | "columns" | "rows"
};

const START: ViewState = { view: "setup", drawer: null, tab: "summary", pair: 0, column: null, anchor: null };
let state = START;
const subs = new Set<() => void>();

export function getView(): ViewState { return state; }

export function setView(patch: Partial<ViewState>) {
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}

export function resetView() { setView(START); }

/** Back to the setup with one section in view: the rail's steps and the editors' Back buttons. */
export function goToSection(anchor: "sources" | "columns" | "rows") { setView({ view: "setup", anchor }); }

export function useView(): ViewState {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => { subs.delete(cb); }; }, () => state);
}
