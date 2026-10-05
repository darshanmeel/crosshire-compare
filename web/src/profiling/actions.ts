// web/src/profiling/actions.ts - the Profile button (a job), shared by the rail and the page. Why
// the last one failed lives outside React's tree, so the page can say it under the rail's button.
import { useState, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type LogEntry } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import type { KeySearch } from "./types";

let failed = "";
const subs = new Set<() => void>();
const setFailed = (s: string) => { failed = s; subs.forEach((f) => f()); };

export function useProfileFailed(): string {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => { subs.delete(cb); }; }, () => failed);
}

// How far the key search goes - set on the Profile page, sent with every Profile, kept in this
// browser between visits.
const SEARCH_KEY = "profile.keySearch";
let search: KeySearch = { key_cols: 5, top_keys: 5, shortlist: 10 };
try { search = { ...search, ...JSON.parse(localStorage.getItem(SEARCH_KEY) ?? "{}") }; } catch { /* no storage */ }
const searchSubs = new Set<() => void>();

export function useKeySearch(): [KeySearch, (s: Partial<KeySearch>) => void] {
  const s = useSyncExternalStore((cb) => { searchSubs.add(cb); return () => { searchSubs.delete(cb); }; }, () => search);
  return [s, (part) => {
    search = { ...search, ...part };
    try { localStorage.setItem(SEARCH_KEY, JSON.stringify(search)); } catch { /* no storage */ }
    searchSubs.forEach((f) => f());
  }];
}

export function useRunProfile(name: string) {
  const qc = useQueryClient();
  const [starting, setStarting] = useState(false);          // the POST is in flight: no second click
  const { follow, busy, running } = useJobOfKind("Profile", "Profiling", "", (e) => {
    if (e.state === "error") setFailed(`Profile failed: ${e.lines[e.lines.length - 1] ?? ""}`);
    qc.invalidateQueries({ queryKey: ["profiling"] });
  });
  async function go() {
    setFailed("");
    setStarting(true);
    try {
      const { key_cols, top_keys, shortlist } = search;
      const e = await api.send<LogEntry>("POST", "/api/profiling/run", { name, key_cols, top_keys, shortlist });
      follow(e.id);
      qc.invalidateQueries({ queryKey: ["log"] });
    } catch (x) {
      setFailed(`Profile failed: ${(x as Error).message}`);
    }
    setStarting(false);
  }
  return { go, busy: busy || starting, running };
}
