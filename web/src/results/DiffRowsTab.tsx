// web/src/results/DiffRowsTab.tsx - Results · Differing rows (SPEC §09): one row per key, a differing
// cell as "A value → B value", filter chips per differing column, a search over the loaded rows, a
// Show menu to hide columns, the cell differences file, paging and the near-match analysis.
import { useMemo, useState, type ReactNode } from "react";
import type { RunView } from "../compare/types";
import { Icon } from "../ui/icons";
import { Bar, Button, Callout, DiffCell, grouped, MenuButton, num } from "../ui/kit";
import { fileUrl, pivot, useDiffRows, useNearMatch, type DiffRowsPage, type KeyRow } from "./detailApi";
import { Failed } from "./Failed";
import "./detail.css";

type Show = "all" | "differing" | "custom";
type Col = { name: string; tag: ReactNode; side: string };

function Value({ v, raw }: { v: unknown; raw?: boolean }) {
  if (v == null) return <span className="rd-null">null</span>;
  if (v === "") return <span className="rd-null">empty</span>;
  return <>{raw ? String(v) : grouped(v)}</>;
}

/** What the search looks in: a number both raw and as shown (10240.93 and 10,240.93). */
const text = (v: unknown) => (v == null ? "" : `${v} ${grouped(v)}`).toLowerCase();
const same = (s: Set<string>, l: string[]) => s.size === l.length && l.every((c) => s.has(c));

/** The Show menu: every compared column a checkbox, with the two quick picks above them, and the
 *  columns only one side has - never a difference, so off to begin with - under "On one side only". */
function ShowMenu({ all, differing, hidden, setHidden }: {
  all: Col[]; differing: Set<string>; hidden: Set<string>; setHidden: (h: Set<string>) => void;
}) {
  const one = all.filter((c) => c.side).map((c) => c.name);
  const matching = [...one, ...all.filter((c) => !c.side && !differing.has(c.name)).map((c) => c.name)];
  const show: Show = same(hidden, one) ? "all" : same(hidden, matching) ? "differing" : "custom";
  const word = show === "all" ? "all compared columns" : show === "differing" ? "columns that differ" : `${all.length - hidden.size} of ${all.length} columns`;
  const box = (c: Col) => (
    <label key={c.name} className="check">
      <input type="checkbox" checked={!hidden.has(c.name)} onChange={(e) => {
        const h = new Set(hidden);
        if (e.target.checked) h.delete(c.name); else h.add(c.name);
        setHidden(h);
      }} />
      <span className="m">{c.name}</span>{c.tag}
    </label>
  );
  return (
    <MenuButton label={<>Show: {word}</>} group="Columns to show">
      <button type="button" className="rd-opt" aria-pressed={show === "all"} onClick={() => setHidden(new Set(one))}>All compared columns</button>
      <button type="button" className="rd-opt" aria-pressed={show === "differing"} onClick={() => setHidden(new Set(matching))}>
        Only columns that differ - hide matching ones
      </button>
      <div className="rd-pop-list">{all.filter((c) => !c.side).map(box)}</div>
      {one.length > 0 && (
        <div className="rd-pop-list" role="group" aria-labelledby="rd-one-h">
          <span className="rd-pop-head" id="rd-one-h">On one side only</span>
          {all.filter((c) => c.side).map(box)}
        </div>
      )}
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
      {q.isFetching && !f && <p className="caption rd-pad">Measuring every differing cell…</p>}
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
  const [picked, setHidden] = useState<Set<string> | null>(null);   // null: every compared column, none of the one-sided ones
  const [near, setNear] = useState(false);
  const q = useDiffRows(run.id, column);
  const first: DiffRowsPage | undefined = q.data?.pages[0];
  const rows = useMemo(() => (q.data?.pages ?? []).flatMap(pivot), [q.data]);
  const [NA, NB] = run.names;
  const needle = find.trim().toLowerCase();
  const seen = needle
    ? rows.filter((r) => r.key.some((k) => text(k).includes(needle))
        || Object.values(r.a).some((v) => text(v).includes(needle)) || Object.values(r.b).some((v) => text(v).includes(needle)))
    : rows;

  if (q.error) return <div className="rd"><Failed error={q.error} /></div>;
  if (!first) return <div className="rd"><p className="caption">Reading the rows that differ…</p></div>;
  if (first.note) return <div className="rd"><Callout icon="table">{first.note}</Callout></div>;
  if (!run.diff_rows) return <div className="rd"><Callout tone="pos" icon="check">No rows differ - every matched row agrees on every compared column.</Callout></div>;

  const differing = new Set(first.by_column.map((c) => c.column));
  const all: Col[] = [
    ...first.columns.map((c) => ({ name: c, tag: null, side: "" })),
    ...first.only_a.map((c) => ({ name: c, tag: <span className="chip a">only in {NA}</span>, side: "a" })),
    ...first.only_b.map((c) => ({ name: c, tag: <span className="chip b">only in {NB}</span>, side: "b" })),
  ];
  const hidden = picked ?? new Set([...first.only_a, ...first.only_b]);
  const cols = all.filter((c) => !hidden.has(c.name));
  const total = first.total;
  const cell = (r: KeyRow, c: Col) => {
    if (c.side === "a") return <td key={c.name} className="m rd-one"><Value v={r.a[c.name]} /></td>;
    if (c.side === "b") return <td key={c.name} className="m rd-one"><Value v={r.b[c.name]} /></td>;
    if (r.diff.has(c.name)) return <td key={c.name} className="m"><DiffCell a={<Value v={r.a[c.name]} />} b={<Value v={r.b[c.name]} />} /></td>;
    return <td key={c.name} className="m dim"><Value v={r.a[c.name]} /></td>;
  };

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
        <label className="search">
          <Icon name="search" />
          <input type="search" aria-label="Find a key or value" placeholder="Find a key or value" value={find} onChange={(e) => setFind(e.target.value)} />
        </label>
        <span className="grow" />
        <ShowMenu all={all} differing={differing} hidden={hidden} setHidden={setHidden} />
        {first.file && (
          <a className="btn sm" href={fileUrl(run.id, first.file)} download title={first.file}>
            <Icon name="download" />cell_diffs.csv
          </a>
        )}
      </div>

      <section className="panel" aria-label="Differing rows">
        <div className="panel-note">
          <span>One row per key. A cell that differs reads</span>
          <DiffCell a={`${NA} value`} b={`${NB} value`} />
          <span>· matching cells stay plain · sorted by cells that differ, most first</span>
        </div>
        <div className="tblwrap rd-scroll">
          <table className="tbl rd-tbl" aria-label="Rows that differ" style={{ minWidth: Math.max(720, 140 * (first.keys.length + cols.length) + 72) }}>
            <thead><tr>
              {first.keys.map((k) => <th key={k} scope="col" className="rd-key"><Icon name="key" size="sm" /> {k}</th>)}
              {cols.map((c) => <th key={c.name} scope="col" className={c.side ? `rd-only-h ${c.side}` : undefined}>{c.name}{c.tag && <> {c.tag}</>}</th>)}
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
            <Button size="sm" icon="sparkle" aria-expanded={near} onClick={() => setNear(!near)}>
              Near-match analysis - formatting or real?
            </Button>
          )}
        </div>
      </section>
      {near && <NearMatch runId={run.id} onClose={() => setNear(false)} />}
    </div>
  );
}
