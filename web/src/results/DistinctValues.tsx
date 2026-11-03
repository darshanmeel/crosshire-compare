// web/src/results/DistinctValues.tsx - "Show every row | distinct values · count(*) of column …": a
// set of rows grouped by one column, most frequent value first, with its share, the running total
// and a bar, a page at a time - on the Differing rows and the One-sided rows tabs.
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "../ui/icons";
import { Button, DiffCell, Loading, num, pctText, Seg } from "../ui/kit";
import { Failed } from "./Failed";
import { axisMax, rankCls, useValues, type Side, type Subset } from "./valuesApi";
import "./values.css";

export type RowsView = "rows" | "distinct";
export type GroupBarProps = {
  view: RowsView; setView: (v: RowsView) => void;
  columns: { value: string; label: string }[]; column: string; setColumn: (c: string) => void;
  sides: { value: Side; label: string }[]; side: Side; setSide: (s: Side) => void;
};

/** The switch between every row and the values of one column, and in values the column and side. */
export function GroupBar({ view, setView, columns, column, setColumn, sides, side, setSide, caption, tools }:
  GroupBarProps & { caption?: ReactNode; tools?: ReactNode }) {
  return (
    <div className="vc-groupbar">
      <span className="vc-lbl">Show</span>
      <Seg label="Rows view" value={view} onChange={setView}
           options={[{ value: "rows", label: "Every row" },
                     { value: "distinct", label: <>Distinct values · <span className="m">count(*)</span></> }]} />
      {view === "distinct" && (
        <>
          <label className="vc-of">
            <span className="vc-lbl">of column</span>
            <select className="sel" aria-label="Group by column" value={column} onChange={(e) => setColumn(e.target.value)}>
              {columns.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          {sides.length > 1 && <Seg label="Value from" mini value={side} onChange={setSide} options={sides} />}
          {caption && <span className="vc-caption">{caption}</span>}
          {tools && <><span className="grow" />{tools}</>}
        </>
      )}
    </div>
  );
}

const SIZES = [25, 50, 100];
const said = (v: string | null | undefined) => (v == null ? "null" : v === "" ? "empty" : v);
const shown = (v: string | null | undefined) => (v == null || v === "" ? <em className="vc-null">{said(v)}</em> : v);

/** One column's values over a set of rows: search, rows per page, and paging. The caller keys it by
 *  column and side, so a new pick starts on page one with an empty search. */
export function DistinctTable({ runId, subset, differs = "", bar, label, names }: {
  runId: string; subset: Subset; differs?: string; bar: GroupBarProps; label: string; names: [string, string];
}) {
  const { column, side } = bar;
  const [find, setFind] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);
  useEffect(() => {
    const v = find.trim();
    if (v === search) return;
    const t = setTimeout(() => { setSearch(v); setPage(1); }, 250);
    return () => clearTimeout(t);
  }, [find, search]);
  const q = useValues(runId, { column, subset, side, differs, search, page, size });
  const d = q.data;
  const s = d?.sides[0];
  const rows = s?.rows ?? 0;
  const all = s ? s.distinct + (s.nulls > 0 ? 1 : 0) : 0;
  const pages = d ? Math.max(1, Math.ceil(d.values / size)) : 1;
  const max = s && rows ? axisMax((100 * s.top) / rows) : 100;
  const head = side === "pair" ? `${names[0]} → ${names[1]}` : label;
  const tools = (
    <>
      <label className="search vc-search">
        <Icon name="search" />
        <input type="search" aria-label="Find a value" placeholder="Find a value" value={find} onChange={(e) => setFind(e.target.value)} />
      </label>
      <label className="vc-of">
        <span className="vc-lbl">Rows per page</span>
        <select className="sel vc-size" aria-label="Rows per page" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }}>
          {SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
    </>
  );
  const first = d ? (d.page - 1) * d.size + 1 : 0;
  return (
    <>
      <GroupBar {...bar} tools={tools}
        caption={s && <>GROUP BY {label}{side === "pair" ? ` (${names[0]} → ${names[1]})` : side === "b" && subset !== "only_b" ? ` (${names[1]})` : ""} → {num(all)} distinct across {num(rows)} rows</>} />
      {q.error && <div className="rd-pad"><Failed error={q.error} /></div>}
      {!d && !q.error && <div className="rd-pad"><Loading>Counting values…</Loading></div>}
      {d && (
        <div className="tblwrap vc-scroll">
          <table className="tbl compact vc-tbl" aria-label={`Distinct values of ${label}`} aria-busy={q.isFetching}>
            <thead><tr>
              <th className="num vc-rank">#</th>
              <th>{head}</th>
              <th className="num" aria-sort="descending">Count(*) <Icon name="sortdesc" size="sm" /></th>
              <th className="num">% of rows</th>
              <th className="num vc-cum">Cumulative</th>
              <th className="vc-share-h vc-bar">Share · axis 0–{max}%</th>
            </tr></thead>
            <tbody>
              {d.rows.map((r) => {
                const n = r.n[0], p = rows ? (100 * n) / rows : 0;
                const isNull = side === "pair" ? r.value == null && r.b == null : r.value == null;
                // the shade goes by place among the non-null values: a null with more rows ranks above
                const tone = side === "pair" ? "rp" : isNull ? "rnull" : rankCls(r.rank - 1 - (s!.nulls > n ? 1 : 0));
                return (
                  <tr key={r.rank}>
                    <td className="num m dim vc-rank">{num(r.rank)}</td>
                    <td className="m vc-val" title={side === "pair" && r.value !== r.b ? `${said(r.value)} → ${said(r.b)}` : said(r.value)}>
                      {side !== "pair" ? shown(r.value)
                        : r.value === r.b ? <>{shown(r.value)} <span className="dim vc-same">unchanged</span></>
                        : <DiffCell a={shown(r.value)} b={shown(r.b)} />}
                    </td>
                    <td className="num m vc-n">{num(n)}</td>
                    <td className="num m">{pctText(n, rows)}%</td>
                    <td className="num m dim vc-cum">{pctText(r.cum[0], rows)}%</td>
                    <td className="vc-bar"><span className="vc-share ticks"><i className={`vc-seg ${tone} ${side === "b" ? "b" : "a"}`} style={{ width: `${Math.min(100, (100 * p) / max)}%` }} /></span></td>
                  </tr>
                );
              })}
              {d.rows.length === 0 && (
                <tr><td colSpan={6} className="dim">{search ? `No value of ${label} contains "${search}".` : "No rows."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {d && (
        <div className="panel-foot vc-foot">
          <span>
            {d.rows.length
              ? <>Values <strong>{num(first)}–{num(first + d.rows.length - 1)}</strong> of {num(d.values)} {search ? `matching (${num(all)} distinct, ` : "distinct ("}{num(rows)} rows)</>
              : <>{num(d.values)} values {search ? "match" : ""}</>}
          </span>
          <span className="grow" />
          <nav className="vc-pager" aria-label="Pages">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage(1)}>First</Button>
            <Button size="sm" icon="arrowl" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
            <span role="status" className="m">Page {num(Math.min(page, pages))} of {num(pages)}</span>
            <Button size="sm" iconAfter="arrow" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage(pages)}>Last</Button>
          </nav>
        </div>
      )}
    </>
  );
}
