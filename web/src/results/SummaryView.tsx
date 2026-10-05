// web/src/results/SummaryView.tsx - the Summary tab (SPEC §08): the tiles, the Columns panel with
// its match bars and the one-sided columns, Profile by bucket, Why they differ beside them, and
// Columns & values (each column's value pairs) folded at the bottom.
import type { RunView } from "../compare/types";
import { Expander } from "../ui/Expander";
import { Bar, Chip, num, pctText, Tile } from "../ui/kit";
import { marks } from "../ui/marks";
import { BucketProfile } from "./BucketProfile";
import { ColumnsView } from "./ColumnsView";
import { Failed } from "./Failed";
import { useSummary } from "./useSummary";
import { WhyTheyDiffer } from "./WhyTheyDiffer";
import { countsOf, ledgerRows, type LedgerRow, type Summary } from "./types";

const n = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : null);

/** "number · B: remove thousands separators" -> the type chip and what was done to it. */
function ReadAs({ text }: { text: string }) {
  const [type, ...rest] = text.split(" · ");
  return <span className="read-as"><Chip>{type}</Chip>{rest.length > 0 && <span className="how">{rest.join(" · ")}</span>}</span>;
}

/** Two bars for a column: how much matched, and under it how much did not - drawn at least a
 *  sliver wide when anything differs, so 6 mismatches in 600,000 still show. The figure never
 *  reads 100% unless every row agrees. */
function MatchBars({ ok, bad, pct }: { ok: number; bad: number; pct: number }) {
  const all = ok + bad;
  const miss = all ? (100 * bad) / all : 0;
  return (
    <span className="barcell match-bars" title={bad ? `${num(bad)} of ${num(all)} differ - ${pctText(bad, all)}%` : undefined}>
      <span className="bars">
        <Bar pct={pct} tone={bad ? (pct >= 95 ? "good" : "warn") : "ok"} />
        <span className="bar miss" role="presentation"><i style={{ width: bad ? `max(3px, ${miss}%)` : 0 }} /></span>
      </span>
      <span className="v">{all ? pctText(ok, all) : pct.toFixed(2)}%</span>
    </span>
  );
}

function ColumnsPanel({ s, names, matched }: { s: Summary; names: [string, string]; matched: number }) {
  const [NA, NB] = names;
  const rows = ledgerRows(s.ledger);
  const shown = rows.filter((r) => !r.Role.startsWith("only in"));
  const onlyA = rows.filter((r) => r.Role === `only in ${NA}`), onlyB = rows.filter((r) => r.Role === `only in ${NB}`);
  const hash = s.mode === "hash";
  const gapA = `Values only in ${NA}`, gapB = `Values only in ${NB}`;
  const cell = (r: LedgerRow) => {
    if (r.Role === "key") return <><td className="num m dim">-</td><td className="num m dim">-</td><td><Chip tone="key">key</Chip></td></>;
    if (hash) {
      const a = n(r[gapA]), b = n(r[gapB]);
      return <><td className={a ? "num m neg-n" : "num m dim"}>{a == null ? "-" : num(a)}</td>
               <td className={b ? "num m neg-n" : "num m dim"}>{b == null ? "-" : num(b)}</td><td /></>;
    }
    const ok = n(r.Matched), bad = n(r.Mismatched) ?? 0, pct = n(r["Match %"]);
    if (ok == null) return <><td className="num m dim">-</td><td className="num m dim">-</td><td className="dim">not compared</td></>;
    const all = ok + bad;
    return (
      <>
        <td className="num m">{num(ok)}</td>
        <td className={bad ? "num m neg-n" : "num m dim"}>{num(bad)}</td>
        <td><MatchBars ok={ok} bad={bad} pct={all ? (100 * ok) / all : pct ?? 0} /></td>
      </>
    );
  };
  return (
    <section className="panel" aria-labelledby="h-cols">
      <div className="panel-head">
        <h2 id="h-cols">Columns</h2>
        <span className="sub">{hash ? "values present on one side only, per compared column" : `match measured on the ${num(matched)} paired rows`}</span>
      </div>
      <div className="panel-note"><span>{marks(s.key_line)}</span></div>
      <div className="tblwrap">
        <table className="tbl" aria-label="Columns">
          <thead><tr>
            <th><span className="sw a" />{NA}</th><th><span className="sw b" />{NB}</th><th>Read as</th>
            {hash
              ? <><th className="num">Only in {NA}</th><th className="num">Only in {NB}</th><th /></>
              : <><th className="num">Matched</th><th className="num">Mismatched</th><th className="match-col">Match %</th></>}
          </tr></thead>
          <tbody>{shown.map((r) => (
            <tr key={r.Column} className={r.Role === "paired, not compared" ? "muted" : undefined}>
              <td className="m ca">{String(r[NA] ?? "-")}</td><td className="m cb">{String(r[NB] ?? "-")}</td>
              <td><ReadAs text={String(r["Read as"] ?? "")} /></td>
              {cell(r)}
            </tr>
          ))}</tbody>
        </table>
      </div>
      {(onlyA.length > 0 || onlyB.length > 0) && (
        <div className="panel-foot not-compared">
          <span><strong>Not compared</strong> - present on one side only:</span>
          {onlyA.map((r) => <span key={"a" + r.Column} className="m ca">{r.Column} <span className="dim">· only in {NA}</span></span>)}
          {onlyB.map((r) => <span key={"b" + r.Column} className="m cb">{r.Column} <span className="dim">· only in {NB}</span></span>)}
        </div>
      )}
    </section>
  );
}

export function SummaryView({ run }: { run: RunView }) {
  const q = useSummary(run.id);
  if (q.error) return <Failed error={q.error} />;
  const s = q.data;
  if (!s) return <p className="caption">Reading…</p>;
  const c = countsOf(s);
  const [NA, NB] = run.names;
  const cc = Object.fromEntries(s.column_counts.map((m) => [m.label, m.value]));
  const every = s.ledger.rows.length;
  const overall = s.overall?.[0]?.value;
  return (
    <div className="summary">
      {s.key_warning && (
        <div className="note warning">{marks(s.key_warning.head)}
          <ul>{s.key_warning.points.map((p, i) => <li key={i}>{marks(p)}</li>)}</ul></div>
      )}
      {s.filter_note && <div className="note">{marks(s.filter_note)}</div>}
      {s.unmatched && (
        <div className="note error">{marks(s.unmatched.lead)}
          <ul>{s.unmatched.lines.map((l, i) => <li key={i}>{marks(l)}</li>)}</ul></div>
      )}
      <div className="tiles">
        <Tile label={s.counts[0]?.label ?? `Rows ${NA}`} value={num(c.rowsA)} />
        <Tile label={s.counts[1]?.label ?? `Rows ${NB}`} value={num(c.rowsB)} />
        <Tile label={s.counts[2]?.label ?? "Matched on key"} value={num(c.matched)} />
        {s.overall && <Tile label="Fully matched" value={num(c.full)} />}
        {overall !== undefined && <Tile label="Overall match" value={String(overall)} />}
        <Tile label="Columns compared" value={num(cc.Compared as number)} small={`of ${num(every)} · key ${num(cc.Key as number)}`} />
      </div>
      {s.overall_caption && <p className="caption">{s.overall_caption}</p>}
      {s.hash_caption && <p className="caption">{s.hash_caption}</p>}
      {s.mode !== "hash" && (
        <section className="panel cols-values" aria-label="Columns & values">
          <Expander title={<>Columns &amp; values <span className="sub">each compared column's value pairs, and the near-match analysis</span></>}>
            <ColumnsView run={run} />
          </Expander>
        </section>
      )}
      <div className="split">
        <div className="main">
          <ColumnsPanel s={s} names={run.names} matched={c.matched} />
          <BucketProfile run={run} buckets={s.buckets} first={s.default_bucket} sidedTip={s.sided_tip} />
        </div>
        <div className="side">
          <WhyTheyDiffer run={run} s={s} />
        </div>
      </div>
    </div>
  );
}
