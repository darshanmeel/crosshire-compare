// web/src/results/WhyTheyDiffer.tsx - the Summary's side panel: per differing column the most
// frequent (A value -> B value) pairs, or - when every pair is different - how alike the values
// are (near-match); then the one-sided rows, with their pattern when the data has one.
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { setView } from "../shell/view";
import { Bar, Button, num } from "../ui/kit";
import { Icon } from "../ui/icons";
import { useOneSided } from "./OneSidedTab";
import { ledgerRows, countsOf, type Frame, type Pairs, type Summary } from "./types";

const MAX_COLUMNS = 6;

function nearLine(frame: Frame | undefined, column: string): string {
  const row = frame?.rows.find((r) => r[0] === column);
  const sim = row ? Number(row[frame!.columns.indexOf("Similarity %")]) : NaN;
  if (!Number.isFinite(sim)) return "Every mismatch is a different pair of values.";
  if (sim >= 80) return `Every pair is different, but the values are ${sim}% alike on average - most likely formatting (spacing, case, separators) rather than data.`;
  if (sim < 50) return `Every pair is different and the values are only ${sim}% alike on average - real differences, not formatting.`;
  return `Every pair is different; the values are ${sim}% alike on average - check a few rows on the Differing rows tab.`;
}

export function WhyTheyDiffer({ run, s }: { run: RunView; s: Summary }) {
  const [NA, NB] = run.names;
  const differing = ledgerRows(s.ledger)
    .filter((r) => r.Role === "compared" && typeof r.Mismatched === "number" && r.Mismatched > 0)
    .sort((a, b) => (b.Mismatched as number) - (a.Mismatched as number));
  const cols = differing.slice(0, MAX_COLUMNS).map((r) => r.Column);
  const pairs = useQueries({
    queries: cols.map((c) => ({
      queryKey: ["results", run.id, "pairs", c], staleTime: Infinity,
      queryFn: () => api.get<Pairs>(`/api/results/${run.id}/pairs/${encodeURIComponent(c)}?limit=5`),
    })),
  });
  const allDistinct = pairs.some((p) => p.data && p.data.mismatches > 0 && p.data.distinct === p.data.mismatches);
  const near = useQuery({ enabled: allDistinct, staleTime: Infinity, queryKey: ["results", run.id, "near-match"],
                          queryFn: () => api.get<Frame>(`/api/results/${run.id}/near-match`) });
  const c = countsOf(s);
  const a = useOneSided(run.id, "A", 6, c.onlyA > 1), b = useOneSided(run.id, "B", 6, c.onlyB > 1);
  const pattern = [{ name: NA, d: a.data }, { name: NB, d: b.data }].filter((x) => x.d && x.d.total > 1 && x.d.constant.length);
  const nothing = !cols.length && !c.onlyA && !c.onlyB;
  return (
    <section className="panel why" aria-labelledby="h-why">
      <div className="panel-head"><h2 id="h-why">Why they differ</h2><span className="sub">most frequent value pairs per column</span></div>
      <div className="panel-body">
        {nothing && <p className="caption">No differing values on the paired rows, and no one-sided rows.</p>}
        {cols.map((col, i) => {
          const d = pairs[i].data;
          const top = d?.pairs[0]?.n ?? 0;
          const few = d && d.distinct > 0 && d.distinct <= d.pairs.length;
          return (
            <div key={col} className="why-col">
              <div className="why-head">
                <span className="m">{col}</span>
                <span className="m neg">{num(differing[i].Mismatched as number)} mismatches</span>
                {few && <span className="dim">- {d!.distinct === 1 ? "one value pair accounts for all of them" : `${d!.distinct} value pairs account for all of them`}</span>}
              </div>
              {pairs[i].error && <p className="caption">Could not read the value pairs.</p>}
              {!d && !pairs[i].error && <p className="caption">Reading…</p>}
              {d && top > 1 && (
                <ul className="kv" aria-label={`Value pairs for ${col}`}>
                  {d.pairs.filter((p) => p.n > 1).map((p, j) => (
                    <li key={j}>
                      <span className="why-pair"><span className="ca">{p.a}</span><Icon name="arrow" size="sm" /><span className="cb">{p.b}</span></span>
                      <Bar pct={(100 * p.n) / top} tone="warn" />
                      <span className="v">{num(p.n)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {d && top === 1 && <p className="why-text">{near.isFetching && !near.data ? "Measuring how alike the values are…" : nearLine(near.data, col)}</p>}
            </div>
          );
        })}
        {differing.length > MAX_COLUMNS && <p className="caption">{differing.length - MAX_COLUMNS} more differing columns - see Columns &amp; values below.</p>}
        {(c.onlyA > 0 || c.onlyB > 0) && (
          <div className="why-col">
            <div className="why-head"><span className="m">one-sided rows</span><span className="m dim">{num(c.onlyA)} · {num(c.onlyB)}</span></div>
            {pattern.map((x) => (
              <p key={x.name} className="why-text">
                All {num(x.d!.total)} rows only in {x.name} read{" "}
                {x.d!.constant.slice(0, 4).map((k, j, all) => (
                  <span key={k.column}>{k.column} <code>{k.value}</code>{j < all.length - 1 ? ", " : ""}</span>
                ))}
                {x.d!.constant.length > 4 ? " …" : ""} - one batch, not separate records.
              </p>
            ))}
            <Button size="sm" className="why-go" iconAfter="arrow" onClick={() => setView({ tab: "onesided" })}>See the one-sided rows</Button>
          </div>
        )}
        {run.diff_rows > 0 && (
          <Button className="why-go" iconAfter="arrow" onClick={() => setView({ tab: "rows" })}>See the {num(run.diff_rows)} rows</Button>
        )}
      </div>
    </section>
  );
}
