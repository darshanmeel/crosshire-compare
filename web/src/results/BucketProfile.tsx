import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { Seg } from "../ui/kit";
import { ColumnPick, notCompared } from "./ColumnPick";
import { marks } from "../ui/marks";
import { Failed } from "./Failed";
import { Grid } from "./Grid";
import { usePick } from "./pickStore";
import { qs, type BucketBody } from "./types";

/** Profile by bucket: top values per column for one bucket of rows (matched, differing, only in
 * A, only in B) - the profile of what went wrong. The bucket is held by its id across runs (its
 * label carries this run's counts). */
export function BucketProfile({ run, buckets, first, sidedTip }:
  { run: RunView; buckets: { id: string; label: string }[]; first: string; sidedTip: string }) {
  const [held, setHeld] = usePick<string>("bucket_id", "");
  const bucket = buckets.some((b) => b.id === held) ? held : first;
  // null: the plan's own columns (the key and three); a list: exactly those, in the order ticked.
  const [picked, setPicked] = usePick<string[] | null>(`bucket_pick_${bucket}`, null);
  const q = useQuery({
    enabled: !!bucket, staleTime: Infinity, placeholderData: (prev) => prev,
    queryKey: ["results", run.id, "bucket", bucket, picked],
    queryFn: () => api.get<BucketBody>(`/api/results/${run.id}/buckets/${bucket}${picked ? `${qs("add", picked)}${picked.length ? "&" : "?"}exact=true` : ""}`),
  });
  if (!buckets.length) return null;
  const d = q.data;
  const now = picked ?? d?.shown ?? [];
  const nc = notCompared(d?.groups);
  return (
    <section className="panel buckets" aria-labelledby="h-buckets">
      <div className="panel-head">
        <h2 id="h-buckets">Profile by bucket</h2>
        <span className="sub">the top values of a set of rows · every mismatched column counted, tick any other · <span className="nc-word">not compared</span> columns in orange · paired rows count both sides</span>
      </div>
      <div className="panel-body">
        <Seg label="Bucket" value={bucket} onChange={setHeld} options={buckets.map((b) => ({ label: b.label, value: b.id }))} />
        {sidedTip && <p className="caption">{marks(sidedTip)}</p>}
        {q.error && <Failed error={q.error} />}
        {!d && !q.error && <p className="caption">Profiling…</p>}
        {d && (
          <>
            {d.by_key && (
              <>
                <p className="bucket-line">{marks(d.by_key.title)}</p>
                <div className="bucket-grids">{d.by_key.tables.map((t, i) => <div key={i}><p className="caption">{marks(t.title)}</p><Grid frame={t.table} /></div>)}</div>
                <p className="bucket-line">{marks(d.by_key.after)}</p>
              </>
            )}
            {d.groups.length > 0 && <ColumnPick label="Columns to count" groups={d.groups} shown={d.shown} now={now} set={setPicked} />}
            {d.empty
              ? <p className="caption">{d.empty}</p>
              : <div className="bucket-grids">{inOrder(d.profiles, now).map((p) => <div key={p.column} className={nc.has(p.column) ? "nc" : undefined}><p className="caption">{marks(p.title)}</p><Grid frame={p.table} /></div>)}</div>}
          </>
        )}
      </div>
    </section>
  );
}

/** The profiles in the order their columns were ticked - a new one lands at the end, so what is
 *  already on screen stays put. */
function inOrder<T extends { column: string }>(profiles: T[], now: string[]) {
  const at = (c: string) => { const i = now.indexOf(c); return i < 0 ? now.length : i; };
  return [...profiles].sort((a, b) => at(a.column) - at(b.column));
}
