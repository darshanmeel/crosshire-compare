// web/src/keys/ProfileBox.tsx - "Profile both files" (SPEC §06): statistics per column per file (a job),
// the stale line, and the 10 most and least frequent values of the columns picked.
import { useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LogEntry } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import { RunDisc } from "../shell/RunDisc";
import { Expander } from "../ui/Expander";
import { Icon } from "../ui/icons";
import { Bar, Button, num, Tabs } from "../ui/kit";
import { marks } from "../ui/marks";
import { errorText, refreshSetup, type Frame, type FreqView, type ProfileView } from "../setup/api";
import { splitFreq } from "../profiling/FreqSection";
import { StatsTable, STATS_FOOT } from "../profiling/ColumnsTable";
import { fmt, pct, rowsOf } from "../profiling/frame";
import { FrameTable } from "../setup/FrameTable";
import "../profiling/profiling.css";
import "./keys.css";

// The columns whose frequencies are listed - kept outside React's tree so they survive the
// Compare | Profiling switch (state.KEEP's freq_cols_pair); null = not picked yet, the default then.
let freqPicks: string[] | null = null;
const subs = new Set<() => void>();
export function setFreqPicks(p: string[] | null) { freqPicks = p; subs.forEach((f) => f()); }
function useFreqPicks(): string[] | null {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => { subs.delete(cb); }; }, () => freqPicks);
}

/** The most and least frequent without a value twice - every value once when there are ten or
 *  fewer, the rest after the ten most frequent when there are under 20 (see splitFreq). */
function SplitTables({ name, top, rest, all }: { name: string; top: Frame; rest: Frame | null; all: boolean }) {
  if (!rest) return <div><p className="caption">Every value · most to least frequent</p><FrameTable label={`${name} most frequent`} frame={top} /></div>;
  return (
    <div className="two">
      <div><p className="caption">Most frequent</p><FrameTable label={`${name} most frequent`} frame={top} /></div>
      <div><p className={all ? "caption freq-rest" : "caption"}>{all ? `The other ${rest.rows.length} · down to the least frequent` : "Least frequent"}</p>
        <FrameTable label={`${name} least frequent`} frame={rest} /></div>
    </div>
  );
}

function FreqTables({ col, names }: { col: string; names: [string, string] }) {
  const q = useQuery({ queryKey: ["setup-freq", col],
                       queryFn: () => api.get<FreqView>(`/api/setup/profile/freq?col=${encodeURIComponent(col)}`) });
  if (!q.data) return q.error ? <div className="note error">{errorText(q.error)}</div> : null;
  return (
    <Expander open title={marks(q.data.title)}>
      <div className="two">
        {(["A", "B"] as const).map((w, i) => (
          <div key={w} className="freq-side">
            <span className={`lbl side-${w.toLowerCase()}`}>{names[i]}</span>
            <SplitTables name={names[i]} {...splitFreq(q.data![w].top, q.data![w].bottom)} />
          </div>
        ))}
      </div>
    </Expander>
  );
}

type Tab = "both" | "A" | "B";

/** Profile both files: statistics per column per file, and the most and least frequent values. */
/** Both sides of each paired column on one row - nulls and distinct values as a bar and a %,
 *  and the range - in the order the engine gives (the biggest gap in nulls first). */
function BothTable({ p }: { p: NonNullable<ProfileView> }) {
  const [na, nb] = p.names;
  const of = (f: Frame) => new Map(rowsOf(f).map((r) => [String(r.Column), r]));
  const A = of(p.A), B = of(p.B);
  const cols = rowsOf(p.both).map((r) => String(r.Column)).filter((c) => A.has(c) && B.has(c));
  const nulls = (r: Record<string, unknown>) => Number(r.Nulls) > 0
    ? <span className="pair">{num(r.Nulls as number)}<Bar pct={Number(r["Null %"])} tone="warn" label={pct(r["Null %"])} /></span> : "0";
  const distinct = (r: Record<string, unknown>) => {
    const d = Number(r["Distinct % of rows"] ?? 0);
    return <span className="pair" title={Number(r.Nulls) > 0 ? `${pct(r["Distinct % of filled"])} of the rows with a value` : undefined}>
      {num(r.Distinct as number)}<Bar pct={d} tone={d >= 100 ? "ok" : "accent"} label={pct(d)} /></span>;
  };
  const range = (r: Record<string, unknown>) => {
    const isNum = r.Type === "number", lo = fmt(r.Min, isNum), hi = fmt(r.Max, isNum);
    return <span className="clip" title={`${lo} – ${hi}`}>{lo === hi ? lo : `${lo} – ${hi}`}</span>;
  };
  return (
    <div className="tblwrap">
      <table className="tbl prof-stats" aria-label="Profile">
        <thead><tr>
          <th>Column</th><th>Type</th><th className="num">Nulls {na}</th><th className="num">Nulls {nb}</th>
          <th className="num">Distinct {na}</th><th className="num">Distinct {nb}</th><th>Range {na}</th><th>Range {nb}</th>
        </tr></thead>
        <tbody>{cols.map((c) => {
          const a = A.get(c)!, b = B.get(c)!;
          return (
            <tr key={c}>
              <td className="m col">{c}</td>
              <td><span className="chip">{String(a.Type)}</span></td>
              <td className="num m dim nulls">{nulls(a)}</td><td className="num m dim nulls">{nulls(b)}</td>
              <td className="num m">{distinct(a)}</td><td className="num m">{distinct(b)}</td>
              <td className="m dim">{range(a)}</td><td className="m dim">{range(b)}</td>
            </tr>
          );
        })}</tbody>
      </table>
    </div>
  );
}

export function ProfileBox() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["setup-profile"], queryFn: () => api.get<ProfileView>("/api/setup/profile") });
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<Tab>("both");
  const picked = useFreqPicks();
  const start = useMutation({
    mutationFn: () => api.send<LogEntry>("POST", "/api/setup/profile"),
    onSuccess: (e) => { setErr(""); follow(e.id); qc.invalidateQueries({ queryKey: ["log"] }); },
    onError: (e) => setErr(errorText(e)),
  });
  const { follow, busy, running } = useJobOfKind("Profile", "Compare", "", (e) => {
    if (e.state === "error") setErr(e.lines.at(-1) ?? e.label);
    refreshSetup(qc);                  // the key's formats may have been fixed first
  });
  const p = q.data;
  const cols = p ? (picked ?? p.freq_default).filter((c) => p.freq_columns.includes(c)) : [];
  const toggle = (c: string) => setFreqPicks(cols.includes(c) ? cols.filter((x) => x !== c) : [...cols, c]);
  return (
    <div className="panel profilebox">
      <div className="panel-head">
        <h3>Profile both files</h3>
        <span className="sub">nulls, distinct values and ranges per column, per file - feeds the key search</span>
        <div className="actions">
          <Button variant={p ? "default" : "primary"} size="sm" icon={p ? "refresh" : "play"} disabled={busy || start.isPending}
                  onClick={() => start.mutate()}>{p ? "Profile again" : "Profile both files"}</Button>
        </div>
      </div>
      {(running || err || p?.stale) && (
        <div className="panel-body">
          {running && <RunDisc entry={running} />}
          {err && <div className="note error">{err}</div>}
          {p?.stale && <div className="callout warn"><Icon name="refresh" /><span className="grow">{p.stale_said}</span></div>}
        </div>
      )}
      {p && <>
        <div className="panel-body">
          <Tabs<Tab> label="Profile of" value={tab} onChange={setTab}
                     items={[{ label: "Both sides", value: "both" }, { label: p.names[0], value: "A" }, { label: p.names[1], value: "B" }]} />
          {tab === "both" ? <BothTable p={p} /> : <StatsTable stats={p[tab]} label="Profile" />}
          <p className="caption">{tab === "both" ? "Distinct: the share of all rows - hover for the share of the rows with a value" : STATS_FOOT}</p>
        </div>
        <div className="panel-body freq">
          <span className="lbl">Value frequencies · 10 most and 10 least frequent, per file</span>
          <div className="chips" role="group" aria-label="Columns to list"
               title="The figures are measured already - this only draws the tables, and a table per column of a wide pair is what makes the page slow.">
            {p.freq_columns.map((c) => {
              const on = cols.includes(c);
              return <button key={c} type="button" className={`chip pick${on ? " on" : ""}`} aria-pressed={on} onClick={() => toggle(c)}>
                {on && <Icon name="check" size="sm" />}{c}</button>;
            })}
          </div>
          {cols.map((c) => <FreqTables key={c} col={c} names={p.names} />)}
        </div>
      </>}
    </div>
  );
}
