// web/src/profiling/KeySearch.tsx - how far the key search goes: combinations up to N columns, the
// best few found on a random sample checked on every row, and the best M candidates listed. Kept in
// this browser and sent with the next Profile.
import { useKeySearch } from "./actions";
import type { KeySearch as Search } from "./types";

const SIZES = [1, 2, 3, 4, 5, 6];
const CHECKED = [5, 10, 20];
const LISTED = [3, 5, 10, 20];

/** The selects; `done` is what the profile on screen was searched with, to say when they differ. */
export function KeySearch({ done }: { done?: Search }) {
  const [s, set] = useKeySearch();
  const differs = done && (done.key_cols !== s.key_cols || done.top_keys !== s.top_keys || done.shortlist !== s.shortlist);
  return (
    <div className="key-search" role="group" aria-label="Key search">
      <label className="field">
        <span className="lbl">Columns in a key, up to</span>
        <select value={s.key_cols} onChange={(e) => set({ key_cols: Number(e.target.value) })}>
          {SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="lbl">Checked on every row</span>
        <select value={s.shortlist} onChange={(e) => set({ shortlist: Number(e.target.value) })}>
          {CHECKED.map((n) => <option key={n} value={n}>the best {n}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="lbl">Candidates listed</span>
        <select value={s.top_keys} onChange={(e) => set({ top_keys: Number(e.target.value) })}>
          {LISTED.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <span className="caption key-search-how">
        Every level up to {s.key_cols} is counted on a random sample until {s.shortlist} combinations are unique there; those
        {" "}{s.shortlist} are then counted on every row, and one that repeats there is said so.
        {s.key_cols >= 5 && " Up to 5 or 6 columns still takes longer on a wide table."}
      </span>
      {differs && (
        <span className="caption">
          this profile used up to {done.key_cols} · the best {done.shortlist} checked · {done.top_keys} listed - Profile again to use these
        </span>
      )}
    </div>
  );
}
