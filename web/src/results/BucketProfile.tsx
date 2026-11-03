import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { Expander } from "../ui/Expander";
import { ErrorNote, InfoTip, Loading, num, Seg } from "../ui/kit";
import { ColumnPick, notCompared } from "./ColumnPick";
import { marks } from "../ui/marks";
import { Failed } from "./Failed";
import { Grid } from "./Grid";
import { usePick } from "./pickStore";
import { Findings, type Finding } from "../profiling/column/Findings";
import "./values.css";
import { qs, type BucketBody, type BucketFacts, type Frame, type SideFacts } from "./types";

/** Profile by bucket, folded under the Summary: top values per column for one bucket of rows (matched, differing, only in
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
  const [open, setOpen] = usePick("fold_bucket", false);     // a closed fold under the Summary, kept as left
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
    <section className="panel fold buckets" aria-label="Profile by bucket">
      <Expander open={open} onToggle={setOpen} title={<>Profile by bucket <span className="sub">the top values of a set of rows</span></>}>
      <div className="panel-body">
        <div className="bucket-bar">
          <Seg label="Bucket" value={bucket} onChange={setHeld} options={buckets.map((b) => ({ label: b.label, value: b.id }))} />
          <div className="bucket-end">
            <Seg label="Column profile" mini value={depth} onChange={setDepth}
              options={[{ label: "Simple", value: "simple", title: "The top values of each column" },
                        { label: "Extended", value: "extended", title: "Nulls, distinct, top value, range, shapes, first and last characters and spellings - a side each" }]} />
            <InfoTip label="About Profile by bucket" text="Every mismatched column is counted, tick any other. Not compared columns show in orange. Paired rows count both sides." />
          </div>
        </div>
        {sidedTip && <p className="caption">{marks(sidedTip)}</p>}
        {q.error && <Failed error={q.error} />}
        {!d && !q.error && <Loading>Profiling…</Loading>}
        {d && (
          <>
            {d.by_key && (
              <>
                <p className="bucket-line">{marks(d.by_key.title)}</p>
                <div className="bucket-keys">{d.by_key.tables.map((t, i) => <div key={i}><p className="caption">{marks(t.title)}</p><KeyBars frame={t.table} /></div>)}</div>
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
      </Expander>
    </section>
  );
}

const STEPS = [1, 2, 5];
/** The count axis: the smallest 1, 2 or 5 times a power of ten that holds the largest count. */
export const countMax = (n: number) => {
  for (let p = 1; ; p *= 10) for (const s of STEPS) if (s * p >= n) return s * p;
};

/** One key column's values the differing rows sit under, in the engine's order: a bar each for
 *  the matched rows and the rows that differ on one count axis, the numbers beside them. */
function KeyBars({ frame }: { frame: Frame }) {
  const at = (c: string) => frame.columns.indexOf(c);
  const [iM, iD, iP, iC, iL] = ["Matched rows", "Rows that differ", "% of those rows", "Cells that differ", "Columns that differ"].map(at);
  const n = (r: unknown[], i: number) => (i < 0 ? 0 : Number(r[i] ?? 0));
  const max = countMax(Math.max(1, ...frame.rows.map((r) => Math.max(n(r, iM), n(r, iD)))));
  const ticks = [0, max / 2, max].filter(Number.isInteger);
  const key = frame.columns[0];
  return (
    <div className="vc-list kb" role="list" aria-label={`${key} - rows that differ by value`}>
      <div className="vc-row vc-axis" aria-hidden="true">
        <span>{key}</span>
        <span className="vc-ticks">{ticks.map((t) => <b key={t} style={{ left: `${(100 * t) / max}%` }}>{num(t)}</b>)}</span>
        <span className="num">Rows · % differ</span>
      </div>
      {frame.rows.map((r, k) => {
        const v = String(r[0] ?? "");
        const cols = iL < 0 ? "" : String(r[iL] ?? "");
        const cells = iC < 0 ? "" : `${num(n(r, iC))} ${n(r, iC) === 1 ? "cell" : "cells"}${cols ? `: ${cols}` : ""}`;
        return (
          <div className="vc-row" role="listitem" key={k}>
            <span className="kb-val">
              <span className="m" title={v}>{v}</span>
              {cells && <span className="kb-cols" title={cells}>{cells}</span>}
            </span>
            <span className="vc-bars">
              <span className="vc-share"><i className="vc-seg kb-m" style={{ width: `${(100 * n(r, iM)) / max}%` }} /></span>
              <span className="vc-share"><i className="vc-seg kb-d" style={{ width: `${(100 * n(r, iD)) / max}%` }} /></span>
            </span>
            <span className="num vc-nums">
              <span><span className="sw kb-m" /><span>{num(n(r, iM))} matched</span></span>
              <span><span className="sw kb-d" /><span>{num(n(r, iD))} differ · <strong>{n(r, iP).toFixed(2)}%</strong></span></span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The profiles in the order their columns were ticked - a new one lands at the end, so what is
 *  already on screen stays put. */
function inOrder<T extends { column: string }>(profiles: T[], now: string[]) {
  const at = (c: string) => { const i = now.indexOf(c); return i < 0 ? now.length : i; };
  return [...profiles].sort((a, b) => at(a.column) - at(b.column));
}

const pc = (v: number) => `${v.toFixed(2)}%`;

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
  if (!sides) return failed ? <ErrorNote>The column facts could not be read.</ErrorNote> : loading ? <Loading>Reading the column…</Loading> : <p className="caption" />;
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
