// web/src/results/OneSidedTab.tsx - One-sided rows (SPEC §10): the rows only A has and the rows only
// B has, side by side, the first few of each with "Show all", their files to download, the
// pattern they share when the data has one, and why a one-sided row is not a difference.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { goToSection } from "../shell/view";
import { Button, Callout, grouped, LinkButton, Loading, MenuButton, num } from "../ui/kit";
import { Icon } from "../ui/icons";
import { ColumnPick, notCompared } from "./ColumnPick";
import { Failed } from "./Failed";
import { usePick } from "./pickStore";
import { fileUrl } from "./detailApi";
import { ledgerRows, type OneSided } from "./types";
import { useSummary } from "./useSummary";

const FIRST = 6, MORE = 500, CAP = 10_000;

/** A page of one side's one-sided rows, from the top. */
export function useOneSided(runId: string, side: "A" | "B", limit: number, enabled = true) {
  return useQuery({
    enabled, staleTime: Infinity, placeholderData: (prev) => prev,
    queryKey: ["results", runId, "one-sided", side, limit],
    queryFn: () => api.get<OneSided>(`/api/results/${runId}/one-sided/${side}?limit=${limit}`),
  });
}

const NUMERIC = /^-?\d[\d,]*(\.\d+)?$/;

function sideLine(run: RunView, side: "A" | "B", keys: string[]) {
  const other = run.names[side === "A" ? 1 : 0];
  if (run.mode === "hash") return `no identical row in ${other}`;
  if (run.mode === "position") return `beyond the last row of ${other}`;
  return `no ${other} row with that ${keys.join(" + ") || "key"}`;
}

/** A column as this side calls it: the one-sided files carry A's names, so B's panel takes B's own
 *  from the Summary's ledger (Column -> the B name), and keeps the name when B has none. */
export function useOwnNames(run: RunView, side: "A" | "B") {
  const s = useSummary(run.id).data;
  const own = new Map<string, string>();
  if (side === "B" && s) {
    for (const r of ledgerRows(s.ledger)) {
      const b = r[run.names[1]];
      if (typeof b === "string" && b && b !== "—") own.set(r.Column, b);
    }
  }
  return (c: string) => own.get(c) ?? c;
}

/** "HR_compare_Payroll__left_only.csv" -> "left_only.csv": the two heads stay one line each. */
const short = (file: string) => file.split("__").pop() || file;

function SidePanel({ run, side }: { run: RunView; side: "A" | "B" }) {
  const [want, setWant] = useState(FIRST);
  const q = useOneSided(run.id, side, want);
  const name = run.names[side === "A" ? 0 : 1];
  const d = q.data;
  const id = `h-only${side.toLowerCase()}`;
  const [picked, setPicked] = usePick<string[] | null>(`onesided_cols_${side}`, null);
  const label = useOwnNames(run, side);
  const keys = new Set(d?.keys ?? []);
  const nc = notCompared(d?.groups);
  const all = d?.columns ?? [];
  const now = (picked ?? all).filter((c) => all.includes(c));   // every column to begin with
  const at = now.map((c) => all.indexOf(c));                // the ticked columns, in the order ticked
  const numeric = at.map((j) => d!.rows.length > 0 && d!.rows.every((r) => r[j] == null || NUMERIC.test(String(r[j]))));
  const left = d ? d.total - d.rows.length : 0;
  const cls = (k: number, ...more: string[]) =>
    [numeric[k] ? "num" : "", keys.has(now[k]) ? "keycell" : "", nc.has(now[k]) ? "nc" : "", ...more].filter(Boolean).join(" ") || undefined;
  return (
    <section className={`panel only only-${side.toLowerCase()}`} aria-labelledby={id}>
      <div className="panel-head">
        <h2 id={id}><span className={`sw ${side.toLowerCase()}`} aria-hidden="true" />Only in {name}</h2>
        {d && <span className="count">{num(d.total)}</span>}
        {d && <span className="sub">{sideLine(run, side, d.keys.map(label))}</span>}
        {d && d.total > 0 && (
          <div className="actions">
            {d.groups?.length > 0 && (
              <MenuButton label={<>Columns ({num(now.length)} of {num(all.length)})</>} wide>
                <ColumnPick label="Columns to show" now={now} shown={all} set={setPicked}
                  groups={d.groups.map((g) => ({ title: g.title, tone: g.tone, items: g.items.map((c) => ({ name: c, label: label(c) })) }))} />
              </MenuButton>
            )}
            {d.file && (
              <a className="btn sm" href={fileUrl(run.id, d.file)} download={d.file} title={d.file} aria-label={d.file}>
                <Icon name="download" />{short(d.file)}
              </a>
            )}
          </div>
        )}
      </div>
      {q.error && <div className="panel-body"><Failed error={q.error} /></div>}
      {!d && !q.error && <div className="panel-body"><Loading>Reading…</Loading></div>}
      {d && d.total === 0 && <div className="panel-body"><p className="caption">Every {name} row has a partner on the other side.</p></div>}
      {d && d.total > 0 && (
        <>
          <div className={want > FIRST ? "tblwrap tall" : "tblwrap"}>
            <table className="tbl compact" aria-label={`Only in ${name}`}>
              <thead><tr>{now.map((c, k) => <th key={c} className={cls(k)} title={nc.has(c) ? "not compared - on this side only" : undefined}>{label(c)}</th>)}</tr></thead>
              <tbody>{d.rows.map((r, i) => (
                <tr key={i}>{at.map((j, k) => {
                  const x = r[j], key = keys.has(now[k]);
                  return (
                    <td key={j} className={cls(k, x == null ? "null" : "", numeric[k] || key ? "m" : "")}>
                      {x == null ? "" : key ? String(x) : grouped(x)}
                    </td>
                  );
                })}</tr>
              ))}</tbody>
            </table>
          </div>
          <div className="panel-foot">
            <span>Showing <strong>{num(d.rows.length)}</strong> of {num(d.total)}</span>
            <span className="grow" />
            {left > 0 && d.rows.length < CAP && (
              left <= MORE
                ? <Button size="sm" disabled={q.isFetching} onClick={() => setWant(Math.min(CAP, d.total))}>Show all {num(d.total)}</Button>
                : <Button size="sm" disabled={q.isFetching} onClick={() => setWant(Math.min(CAP, d.rows.length + MORE))}>Show {num(MORE)} more</Button>
            )}
            {left > 0 && d.rows.length >= CAP && <span className="caption">the file has every row</span>}
            {want > FIRST && <Button size="sm" variant="ghost" onClick={() => setWant(FIRST)}>Show fewer</Button>}
          </div>
        </>
      )}
    </section>
  );
}

/** "All 25 rows only in Payroll read FullName `New Starter`, …" - only when columns hold one value. */
function Pattern({ run }: { run: RunView }) {
  const a = useOneSided(run.id, "A", FIRST), b = useOneSided(run.id, "B", FIRST);
  const ownB = useOwnNames(run, "B");
  const found = [{ name: run.names[0], d: a.data, label: (c: string) => c }, { name: run.names[1], d: b.data, label: ownB }]
    .filter((x) => x.d && x.d.total > 1 && x.d.constant.length > 0);
  if (!found.length) return null;
  return (
    <Callout tone="warn" icon="sparkle">
      {found.map((x) => (
        <span key={x.name} className="pattern">
          <strong>Pattern in the rows only in {x.name}:</strong> all {num(x.d!.total)} read{" "}
          {x.d!.constant.map((k, j) => (
            <span key={k.column}>{x.label(k.column)} <code>{grouped(k.value)}</code>{j < x.d!.constant.length - 1 ? ", " : ""}</span>
          ))}
          {" "}- one batch rather than {num(x.d!.total)} separate records.{" "}
        </span>
      ))}
    </Callout>
  );
}

export function OneSidedTab({ run }: { run: RunView }) {
  return (
    <div className="onesided">
      <Pattern run={run} />
      <div className="two">
        <SidePanel run={run} side="A" />
        <SidePanel run={run} side="B" />
      </div>
      <Callout icon="key">
        {run.mode === "key"
          ? <>Keys that appear on one side only are never counted as differences - they are listed here and in the two one-sided files. If these should pair up, the key is probably wrong: try{" "}
              <LinkButton onClick={() => goToSection("rows")}>Suggest keys under Rows</LinkButton>.</>
          : <>Without a key, a row that has no identical (or same-position) row on the other side is one-sided. Pick a key under{" "}
              <LinkButton onClick={() => goToSection("rows")}>Rows</LinkButton> to see what changed in them instead.</>}
      </Callout>
    </div>
  );
}
