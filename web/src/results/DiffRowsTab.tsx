// web/src/results/DiffRowsTab.tsx - Results · Differing rows (SPEC §09): one row per key, a differing
// cell as "A value → B value", filter chips per differing column, a search over the loaded rows, a
// Columns menu over the columns that differ, the cell differences file, paging and the near-match analysis.
import { useMemo, useState } from "react";
import type { RunView } from "../compare/types";
import { Icon } from "../ui/icons";
import { Bar, Button, Callout, DiffCell, grouped, Loading, MenuButton, num } from "../ui/kit";
import { fileUrl, pivot, useDiffRows, useNearMatch, type DiffRowsPage, type KeyRow } from "./detailApi";
import { DistinctTable, GroupBar, type GroupBarProps, type RowsView } from "./DistinctValues";
import { Failed } from "./Failed";
import { usePick } from "./pickStore";
import type { Side } from "./valuesApi";
import "./detail.css";

function Value({ v, raw }: { v: unknown; raw?: boolean }) {
  if (v == null) return <span className="rd-null">null</span>;
  if (v === "") return <span className="rd-null">empty</span>;
  return <>{raw ? String(v) : grouped(v)}</>;
}

/** What the search looks in: a number both raw and as shown (10240.93 and 10,240.93). */
const text = (v: unknown) => (v == null ? "" : `${v} ${grouped(v)}`).toLowerCase();

/** The Columns menu: the columns that differ in this view, a checkbox each - no other column is ever shown. */
function ColumnsMenu({ all, hidden, setHidden }: { all: string[]; hidden: Set<string>; setHidden: (h: Set<string>) => void }) {
  const n = all.filter((c) => !hidden.has(c)).length;
  return (
    <MenuButton label={<>Columns: {n} of {all.length}</>} group="Columns to show">
      <div className="rd-pop-list">{all.map((c) => (
        <label key={c} className="check">
          <input type="checkbox" checked={!hidden.has(c)} onChange={(e) => {
            const h = new Set(hidden);
            if (e.target.checked) h.delete(c); else h.add(c);
            setHidden(h);
          }} />
          <span className="m">{c}</span>
        </label>
      ))}</div>
    </MenuButton>
  );
}

/** How close the differing values are - asked for on its button, since it reads every cell. */
function NearMatch({ runId, onClose }: { runId: string; onClose: () => void }) {
  const q = useNearMatch(runId);
  const f = q.data;
  const col = (name: string) => f?.columns.indexOf(name) ?? -1;
  return (
    <section className="panel rd-near" aria-label="Near-match analysis">
      <div className="panel-head">
        <h3>Near-match analysis</h3>
        <span className="sub">High similarity means nearly the same text - formatting, padding or casing rather than data</span>
        <div className="actions"><button type="button" className="icon-btn" aria-label="Close near-match analysis" onClick={onClose}><Icon name="x" /></button></div>
      </div>
      {q.isFetching && !f && <Loading className="rd-pad">Measuring every differing cell…</Loading>}
      {q.error && <div className="rd-pad"><Failed error={q.error} /></div>}
      {f && (
        <div className="tblwrap">
          <table className="tbl compact" aria-label="Near-match analysis">
            <thead><tr><th>Column</th><th className="num">Mismatches</th><th className="num">Avg edit distance</th><th className="rd-sim">Similarity</th></tr></thead>
            <tbody>{f.rows.map((r, i) => {
              const sim = Number(r[col("Similarity %")] ?? 0);
              return (
                <tr key={i}>
                  <td className="m">{String(r[col("Column")])}</td>
                  <td className="num m neg-n">{num(Number(r[col("Mismatches")]))}</td>
                  <td className="num m">{num(Number(r[col("Avg edit distance")]))}</td>
                  <td><Bar pct={sim} tone={sim >= 80 ? "warn" : "accent"} label={`${sim.toFixed(1)}%`} /></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function DiffRowsTab({ run }: { run: RunView }) {
  const [column, setColumn] = useState("");
  const [find, setFind] = useState("");
  const [hidden, setHidden] = useState<Set<string>>(new Set());      // differing columns unticked in the Columns menu
  const [near, setNear] = useState(false);
  const [view, setView] = usePick<RowsView>("rd_view", "rows");
  const [groupCol, setGroupCol] = useState("");
  const [groupSide, setGroupSide] = useState<Side | null>(null);
  const q = useDiffRows(run.id, column);
  const first: DiffRowsPage | undefined = q.data?.pages[0];
  const rows = useMemo(() => (q.data?.pages ?? []).flatMap(pivot), [q.data]);
  const [NA, NB] = run.names;
  const needle = find.trim().toLowerCase();

  if (q.error) return <div className="rd"><Failed error={q.error} /></div>;
  if (!first) return <div className="rd"><Loading>Reading the rows that differ…</Loading></div>;
  if (first.note) return <div className="rd"><Callout icon="table">{first.note}</Callout></div>;
  if (!run.diff_rows) return <div className="rd"><Callout tone="pos" icon="check">No rows differ - every matched row agrees on every compared column.</Callout></div>;

  const differing = new Set(first.by_column.map((c) => c.column));
  // Only the key and what differs: the chip's column, or every column that differs on at least one row
  const offered = column ? [column] : first.columns.filter((c) => differing.has(c));
  const cols = column ? offered : offered.filter((c) => !hidden.has(c));
  const seen = needle   // looks in what is shown: the key and the columns on screen
    ? rows.filter((r) => r.key.some((k) => text(k).includes(needle)) || cols.some((c) => text(r.a[c]).includes(needle) || text(r.b[c]).includes(needle)))
    : rows;
  const total = first.total;
  // Distinct values: any column of the differing rows; a compared one read on A, on B or as the A → B pair
  const gcol = groupCol || column || first.by_column[0]?.column || first.columns[0] || first.keys[0];
  const compared = first.columns.includes(gcol);
  const sides: GroupBarProps["sides"] = compared
    ? [{ value: "a", label: NA }, { value: "b", label: NB }, { value: "pair", label: `${NA} → ${NB}` }] : [];
  const gside: Side = first.only_b.includes(gcol) ? "b" : !compared ? "a" : groupSide ?? (differing.has(gcol) ? "pair" : "a");
  const bar: GroupBarProps = {
    view, setView, column: gcol, setColumn: (c) => { setGroupCol(c); setGroupSide(null); }, sides, side: gside, setSide: setGroupSide,
    columns: [...first.keys.map((k) => ({ value: k, label: `${k} · key` })), ...first.columns.map((c) => ({ value: c, label: c })),
              ...first.only_a.map((c) => ({ value: c, label: `${c} · only in ${NA}` })), ...first.only_b.map((c) => ({ value: c, label: `${c} · only in ${NB}` }))],
  };
  const distinct = run.mode === "key" && view === "distinct";
  const cell = (r: KeyRow, c: string) => r.diff.has(c)
    ? <td key={c} className="m"><DiffCell a={<Value v={r.a[c]} />} b={<Value v={r.b[c]} />} /></td>
    : <td key={c} className="m dim"><Value v={r.a[c]} /></td>;

  return (
    <div className="rd">
      <div className="toolbar">
        <div className="rd-filters" role="group" aria-label="Filter by column">
          <button type="button" className="fchip" aria-pressed={column === ""} onClick={() => setColumn("")}>
            All differing{" "}<span className="n">{num(run.diff_rows)}</span>
          </button>
          {first.by_column.map((c) => (
            <button key={c.column} type="button" className="fchip" aria-pressed={column === c.column}
                    onClick={() => setColumn(column === c.column ? "" : c.column)}>
              {c.column}{" "}<span className="n">{num(c.n)}</span>
            </button>
          ))}
        </div>
        {!distinct && (
          <label className="search">
            <Icon name="search" />
            <input type="search" aria-label="Find a key or value" placeholder="Find a key or value" value={find} onChange={(e) => setFind(e.target.value)} />
          </label>
        )}
        <span className="grow" />
        {!distinct && offered.length > 1 && <ColumnsMenu all={offered} hidden={hidden} setHidden={setHidden} />}
        {first.file && (
          <a className="btn sm" href={fileUrl(run.id, first.file)} download title={first.file}>
            <Icon name="download" />cell_diffs.csv
          </a>
        )}
      </div>

      <section className="panel" aria-label="Differing rows">
        {distinct && (
          <DistinctTable key={`${gcol}|${gside}|${column}`} runId={run.id} subset="differ" differs={column}
                         bar={bar} label={gcol} names={run.names} />
        )}
        {!distinct && <>
          {run.mode === "key" && <GroupBar {...bar} />}
          <div className="panel-note">
            <span>One row per key. A cell that differs reads</span>
            <DiffCell a={`${NA} value`} b={`${NB} value`} />
            <span>· only the key and the columns that differ · a matching cell stays plain · sorted by cells that differ, most first</span>
          </div>
          <div className="tblwrap rd-scroll">
            <table className="tbl rd-tbl" aria-label="Rows that differ" style={{ minWidth: Math.max(720, 140 * (first.keys.length + cols.length) + 72) }}>
              <thead><tr>
                {first.keys.map((k) => <th key={k} scope="col" className="rd-key"><Icon name="key" size="sm" /> {k}</th>)}
                {cols.map((c) => <th key={c} scope="col">{c}</th>)}
                <th scope="col" className="num">Cells</th>
              </tr></thead>
              <tbody>
                {seen.map((r, i) => (
                  <tr key={`${r.key.map(String).join("\u0001")}-${i}`}>
                    {r.key.map((k, j) => <td key={j} className="m rd-key"><Value v={k} raw /></td>)}
                    {cols.map((c) => cell(r, c))}
                    <td className="num m neg-n">{num(r.n)}</td>
                  </tr>
                ))}
                {seen.length === 0 && (
                  <tr><td className="dim" colSpan={first.keys.length + cols.length + 1}>
                    {needle ? `Nothing in the ${num(rows.length)} loaded rows matches "${find.trim()}".` : "No rows."}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="panel-foot">
            <span role="status">
              {needle
                ? <><strong>{num(seen.length)}</strong> of the {num(rows.length)} loaded rows match · {num(total)} {column ? `differ on ${column}` : "differ"}</>
                : <>Showing <strong>{num(rows.length)}</strong> of {num(total)} rows{column && <> that differ on <span className="m">{column}</span></>}</>}
            </span>
            <span className="grow" />
            {q.hasNextPage && (
              <Button size="sm" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
                {q.isFetchingNextPage ? "Loading…" : `Load ${num(Math.min(50, total - rows.length))} more`}
              </Button>
            )}
            {first.file && (
              <Button size="sm" icon="sparkle" aria-expanded={near} aria-label="Near-match analysis - formatting or real?" onClick={() => setNear(!near)}>
                Near-match analysis<span className="ph-hide"> - formatting or real?</span>
              </Button>
            )}
          </div>
        </>}
      </section>
      {near && !distinct && <NearMatch runId={run.id} onClose={() => setNear(false)} />}
    </div>
  );
}
