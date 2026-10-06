// web/src/keys/BucketCard.tsx - "Profile by bucket" (SPEC §06): a tick and a column. The buckets are
// the run's own groups of rows (keys matched, matched and same, matched but different, only in either side); the
// Summary's Profile by bucket lists the top values of the key columns in each, and the column picked
// here is counted in every bucket too - the results' kept picks `bucket_cols_<bucket>` it reads.
import { useId } from "react";
import { useSetup } from "../setup/api";
import { usePick } from "../results/pickStore";
import "./keys.css";

export const BUCKET_IDS = ["matched", "same", "differ", "left", "right"] as const;
const PICK = "rows_bucket_col";
const NO_COLS: string[] = [];        // a stable empty pick

/** The column the Rows page asked to count in every bucket ('' = off), and the setter that writes it
 *  into each bucket's kept columns - adding it, and taking out the one it replaces. */
export function useBucketColumn(): [string, (col: string) => void] {
  const [held, setHeld] = usePick<string>(PICK, "");
  const lists = BUCKET_IDS.map((b) => usePick<string[]>(`bucket_cols_${b}`, NO_COLS));   // fixed count: hooks stay in order
  const put = (col: string) => {
    lists.forEach(([cols, setCols]) => {
      const kept = cols.filter((c) => c !== held);
      setCols(col && !kept.includes(col) ? [...kept, col] : kept);
    });
    setHeld(col);
  };
  return [held, put];
}

export function BucketCard() {
  const id = useId();
  const { data: s } = useSetup();
  const [col, setCol] = useBucketColumn();
  const names = s?.ready ? s.specs.map((sp) => sp.canon) : [];
  const label = (c: string) => {
    const sp = s?.ready ? s.specs.find((x) => x.canon === c) : undefined;
    return sp && sp.a_src && sp.b_src && sp.a_src !== sp.b_src ? `${sp.a_src} ⇄ ${sp.b_src}` : c;
  };
  const first = names.find((c) => !(s?.ready && s.keys.includes(c))) ?? names[0] ?? "";
  const on = !!col;
  return (
    <div className="card bucket">
      <label className="check"><input type="checkbox" checked={on} disabled={!names.length}
                                      onChange={(e) => setCol(e.target.checked ? first : "")} />Count a column in every bucket</label>
      <select className="in mono bucket-col" id={`${id}-c`} aria-label="Bucket column" value={col || first} disabled={!on}
              onChange={(e) => setCol(e.target.value)}>
        {names.map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
      <span className="bucket-say">{on
        ? <>its top values in matched, differing and one-sided rows · the column is compared as usual, too</>
        : <>off - the buckets list the key columns' top values</>}</span>
      <span className="grow" />
      <span className="caption">Which rows match worst, and what they hold: <strong>Summary → Profile by bucket</strong>.</span>
    </div>
  );
}
