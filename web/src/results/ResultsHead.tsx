// web/src/results/ResultsHead.tsx - what stays on top of every results tab (SPEC §08): the run's
// verdict in the engine's own words, the row outcome bar, and the tabs.
import { Fragment, type ReactNode } from "react";
import type { RunView, Segment } from "../compare/types";
import { setView, useView, type ResultsTab } from "../shell/view";
import { OutcomeBar, Pill, Tabs } from "../ui/kit";
import { useSummary } from "./useSummary";
import { countsOf } from "./types";

const TONE = { ok: "ok", warn: "warn", bad: "neg" } as const;

/** One segment of the sentence: the key as code, the differing counts in neg, the share in grey. */
function piece(s: Segment, i: number, all: Segment[]): ReactNode {
  const next = all[i + 1]?.text ?? "", prev = all[i - 1]?.text ?? "";
  if (s.bold) {
    if (/ (matched|paired) on $/.test(prev)) return <code key={i}>{s.text}</code>;
    if (next.startsWith(" rows (") || next === " cells") return <strong key={i} className="neg">{s.text}</strong>;
    return <strong key={i}>{s.text}</strong>;
  }
  const pct = s.text.match(/^(.* rows )(\([\d.]+%\))( .*)$/);
  if (pct) return <Fragment key={i}>{pct[1]}<span className="pct">{pct[2]}</span>{pct[3]}</Fragment>;
  return <Fragment key={i}>{s.text}</Fragment>;
}

/** "1.2s at 10:00:00" -> "10:00:00 · 1.2s" - when first, as the mockup reads. */
function when(w: string) {
  const m = w.match(/^([\d.]+s) at (.+)$/);
  return m ? `${m[2]} · ${m[1]}` : w;
}

export function Verdict({ run, stale }: { run: RunView; stale: boolean }) {
  const v = run.verdict;
  return (
    <section className="verdict" aria-label="Result">
      <div className="meta">
        <span className="eyebrow accent">Result</span>
        <span className="eyebrow">{run.names[0]} against {run.names[1]} · {when(v.when)}</span>
        <Pill tone={TONE[v.tone] ?? "idle"}>{v.word}</Pill>
        {stale && <Pill tone="warn">Stale - settings changed since</Pill>}
      </div>
      <p>{v.segments.map(piece)}</p>
    </section>
  );
}

/** The verdict, the row outcome over every key of either file, and the tabs - bound to the view. */
export function ResultsHead({ run, stale }: { run: RunView; stale: boolean }) {
  const { tab } = useView();
  const s = useSummary(run.id).data;
  const [NA, NB] = run.names;
  const c = s ? countsOf(s) : null;
  const what = run.mode === "key" ? "distinct keys across both files" : "rows across both files";
  return (
    <div className="results-head">
      <Verdict run={run} stale={stale} />
      {c && (
        <OutcomeBar sub={`${(c.matched + c.onlyA + c.onlyB).toLocaleString("en-US")} ${what}`} segments={[
          { label: "Fully matched", n: c.full, cls: "c-full" }, { label: "Differ", n: c.diff, cls: "c-diff" },
          { label: `Only in ${NA}`, n: c.onlyA, cls: "c-onlya" }, { label: `Only in ${NB}`, n: c.onlyB, cls: "c-onlyb" }]} />
      )}
      <Tabs<ResultsTab> label="Result views" value={tab} onChange={(t) => setView({ tab: t })} items={[
        { label: "Summary", value: "summary" },
        { label: "Differing rows", value: "rows", count: run.diff_rows },
        { label: "One-sided rows", value: "onesided", count: c ? c.onlyA + c.onlyB : undefined },
        { label: "Report", value: "report" },
        { label: "Downloads", value: "downloads" },
      ]} />
    </div>
  );
}
