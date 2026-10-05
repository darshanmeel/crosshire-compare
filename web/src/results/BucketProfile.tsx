import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { Seg } from "../ui/kit";
import { ColumnPick, notCompared } from "./ColumnPick";
import { marks } from "../ui/marks";
import { Failed } from "./Failed";
import { Grid } from "./Grid";
import { usePick } from "./pickStore";
import { Findings, type Finding } from "../profiling/column/Findings";
import { qs, type BucketBody, type BucketFacts, type SideFacts } from "./types";

/** Profile by bucket: top values per column for one bucket of rows (matched, differing, only in
 * A, only in B) - the profile of what went wrong. The bucket is held by its id across runs (its
 * label carries this run's counts). */
export function BucketProfile({ run, buckets, first, sidedTip }:
  { run: RunView; buckets: { id: string; label: string }[]; first: string; sidedTip: string }) {
  const [held, setHeld] = usePick<string>("bucket_id", "");
  const bucket = buckets.some((b) => b.id === held) ? held : first;
  // null: the plan's own columns (the key and three); a list: exactly those, in the order ticked.
  const [picked, setPicked] = usePick<string[] | null>(`bucket_pick_${bucket}`, null);
  // Simple: the top values, as it always was; Extended adds each column's facts as pills
  const [depth, setDepth] = usePick<"simple" | "extended">("bucket_depth", "simple");
  const ask = picked ? `${qs("add", picked)}${picked.length ? "&" : "?"}exact=true` : "";
  const q = useQuery({
    enabled: !!bucket, staleTime: Infinity, placeholderData: (prev) => prev,
    queryKey: ["results", run.id, "bucket", bucket, picked],
    queryFn: () => api.get<BucketBody>(`/api/results/${run.id}/buckets/${bucket}${ask}`),
  });
  const f = useQuery({
    enabled: !!bucket && depth === "extended", staleTime: Infinity,
    queryKey: ["results", run.id, "bucket-facts", bucket, picked],
    queryFn: () => api.get<BucketFacts>(`/api/results/${run.id}/buckets/${bucket}/facts${ask}`),
  });
  const facts = depth === "extended" ? new Map((f.data?.columns ?? []).map((c) => [c.column, c.sides])) : null;
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
        <div className="bucket-bar">
          <Seg label="Bucket" value={bucket} onChange={setHeld} options={buckets.map((b) => ({ label: b.label, value: b.id }))} />
          <Seg label="Column profile" mini value={depth} onChange={setDepth}
            options={[{ label: "Simple", value: "simple", title: "The top values of each column" },
                      { label: "Extended", value: "extended", title: "Nulls, distinct, top value, range, shapes, first and last characters and spellings - a side each" }]} />
        </div>
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
              : <div className="bucket-grids">{inOrder(d.profiles, now).map((p) => <div key={p.column} className={nc.has(p.column) ? "nc" : undefined}><p className="caption">{marks(p.title)}</p>
                  {facts && <ColumnFacts sides={facts.get(p.column)} loading={f.isFetching} failed={!!f.error} />}
                  <Grid frame={p.table} /></div>)}</div>}
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

const nf = new Intl.NumberFormat();
const pc = (v: number) => `${v.toFixed(2)}%`;
const num = (v: number) => nf.format(v);

/** One side's facts as pills: nulls, distinct, the top value, the range or the length, the
 *  commonest shape, start and end, and the values spelled two ways. */
export function factPills(s: SideFacts): Finding[] {
  const out: Finding[] = [
    { tone: s.nulls ? "warn" : "info", label: "Nulls", detail: s.nulls ? `${num(s.nulls)} · ${pc(s.null_pct)}` : "none" },
    { label: "Distinct", detail: num(s.distinct) },
  ];
  if (s.top) out.push({ label: "Top", detail: `${s.top.value} · ${pc(s.top.pct)}` });
  if (s.number) out.push({ label: "Range", detail: `${num(s.number.min)} - ${num(s.number.max)} · mean ${num(s.number.mean)}` });
  if (s.date) out.push({ label: "Range", detail: `${s.date.min} - ${s.date.max}` });
  if (s.length) out.push({ label: "Length", detail: s.length.min === s.length.max ? num(s.length.min) : `${num(s.length.min)} - ${num(s.length.max)}` });
  if (s.shapes[0]) out.push({ label: "Shape", detail: `${s.shapes[0].shape} · ${pc(s.shapes[0].pct)}` });
  if (s.prefixes[0]) out.push({ label: "Starts", detail: `${s.prefixes[0].value}… · ${pc(s.prefixes[0].pct)}` });
  if (s.suffixes[0]) out.push({ label: "Ends", detail: `…${s.suffixes[0].value} · ${pc(s.suffixes[0].pct)}` });
  for (const g of s.spellings.slice(0, 2))
    out.push({ tone: "warn", label: `${g.members.length} spellings`, detail: g.members.join(" / ") });
  return out;
}

function ColumnFacts({ sides, loading, failed }: { sides?: SideFacts[]; loading: boolean; failed: boolean }) {
  if (!sides) return <p className="caption">{failed ? "The column facts could not be read." : loading ? "Reading the column…" : ""}</p>;
  return (
    <div className="bucket-facts">
      {sides.map((s) => (
        <div key={s.side}>
          {sides.length > 1 && <span className="side">{s.label}</span>}
          <Findings items={factPills(s)} label={`Facts · ${s.label}`} />
        </div>
      ))}
    </div>
  );
}
