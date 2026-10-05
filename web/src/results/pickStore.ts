// What the reader picked in the results - the view, the bucket, the columns opened, a save folder
// typed. It lives outside React's tree, so a trip to the Profiling page or to another view keeps
// it (what state.KEEP did for res_view, bucket_id, col_cards and bucket_cols_*).
import { useSyncExternalStore } from "react";

const picks = new Map<string, unknown>();
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

export const NONE: string[] = [];          // a stable empty pick - useSyncExternalStore needs one

/** A kept pick. `initial` must be stable: a string, a number, or a constant such as NONE. */
export function usePick<T>(key: string, initial: T): [T, (v: T) => void] {
  const v = useSyncExternalStore(
    (cb) => { subs.add(cb); return () => { subs.delete(cb); }; },
    () => (picks.has(key) ? picks.get(key) : initial) as T,
  );
  return [v, (next) => { picks.set(key, next); emit(); }];
}

export function resetPicks() { picks.clear(); emit(); }
