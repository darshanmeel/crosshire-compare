import { Fragment, type ReactNode } from "react";
import { useRunAuto, useRunCompare, useRunError } from "../compare/actions";
import { useCompareNow } from "../compare/useCompare";
import { useFilters } from "../keys/summary";
import { useRunProfile } from "../profiling/actions";
import { ProfileFiles } from "../profiling/SaveRow";
import { useProfiling } from "../profiling/useProfiling";
import { useSetup } from "../setup/api";
import { useSideForm } from "../sources/formStore";
import { sideLabels, sideName } from "../sources/names";
import { useSources } from "../sources/useSources";
import { Icon } from "../ui/icons";
import { Button, ErrorNote, num } from "../ui/kit";
import { activeFilters } from "../values/FiltersBox";
import { useLog } from "./LogPanel";
import type { Page } from "./usePage";
import { goToSection, logOrigin, setView, useView } from "./view";

export type StepState = "todo" | "now" | "done" | "run";
export type RailStep = { title: string; sub: string; state: StepState; go?: () => void };

/** The step rail under the header: each step's state and one mono line, the page's actions on the right. */
export function StepRail({ steps, actions, note }: { steps: RailStep[]; actions: ReactNode; note?: string }) {
  return (
    <nav className="rail" aria-label="Steps">
      <ol className="steps">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            {i > 0 && <li className="line" aria-hidden="true" />}
            <li>
              <button type="button" className={`step ${s.state}`} onClick={s.go} disabled={!s.go}
                aria-current={s.state === "now" || s.state === "run" ? "step" : undefined}>
                <span className="n">{s.state === "done" ? <Icon name="check" size="sm" /> : s.state === "run" ? <i /> : i + 1}</span>
                <span><span className="t">{s.title}</span><span className="s">{s.sub}</span></span>
              </button>
            </li>
          </Fragment>
        ))}
      </ol>
      <span className="grow" />
      <div className="actions">{actions}</div>
      {note && <ErrorNote className="rail-note" role="alert">{note}</ErrorNote>}
    </nav>
  );
}

const rowsOf = (n: number | null | undefined) => (n == null ? "" : num(n));

export function CompareRail() {
  const v = useView();
  const view = v.view === "log" ? logOrigin() : v.view;     // over the Log, the rail of the view it was opened from
  const src = useSources().data;
  const [fa] = useSideForm("A");
  const [fb] = useSideForm("B");
  const setup = useSetup().data;
  const st = useCompareNow().data;
  const last = useLog().data?.last?.Compare;
  const compare = useRunCompare();
  const auto = useRunAuto();
  const refused = useRunError();
  const ready = !!setup?.ready;
  const filters = useFilters(ready).data;
  const A = src?.sides?.A, B = src?.sides?.B;
  const loaded = !!(A?.loaded && B?.loaded);
  const busy = !!st?.busy || compare.isPending || auto.isPending;
  const run = st?.run;
  const [NA, NB] = sideLabels(sideName("A", fa.name, A), sideName("B", fb.name, B));
  const cur = !loaded ? 1 : busy || view === "results" ? 4 : view === "rows" ? 3 : 2;
  const state = (i: number): StepState =>
    i === 4 && busy ? "run" : i === cur ? "now" : i < cur || (i === 4 && run) ? "done" : "todo";
  const sourcesSub = [A?.loaded && `${NA} ${rowsOf(A.rows)}`, B?.loaded && `${NB} ${rowsOf(B.rows)}`].filter(Boolean).join(" · ") || "nothing loaded yet";
  const nFilters = activeFilters(filters).length;
  const cut = [A?.cut, B?.cut].filter(Boolean).length;
  const steps: RailStep[] = [
    { title: "Sources", sub: sourcesSub, state: state(1), go: () => goToSection("sources") },
    { title: "Columns", sub: ready && setup.specs.length ? `${setup.specs.length} pairs · ${setup.keys.length ? `key ${setup.keys.join(", ")}` : "no key"}` : "-",
      state: state(2), go: loaded ? () => goToSection("columns") : undefined },
    { title: "Rows", sub: !ready ? "-" : nFilters || cut ? `${cut ? "rows cut" : "all rows"} · ${nFilters ? `${nFilters} filter${nFilters > 1 ? "s" : ""}` : "no filter"}` : "all rows · no filter",
      state: state(3), go: ready ? () => setView({ view: "rows" }) : undefined },
    { title: "Results", sub: busy ? "comparing…" : run ? (last?.seconds != null ? `compared in ${last.seconds}s` : `compared ${run.at}`) : loaded ? "press Compare" : "-",
      state: state(4), go: run && !busy ? () => setView({ view: "results" }) : undefined },
  ];
  const actions = busy
    ? <Button variant="primary" disabled iconAfter="arrow">Comparing…</Button>
    : view === "results" && run
      ? <>
          <Button onClick={() => goToSection("columns")}>Edit setup</Button>
          <a className="btn primary" href={`/api/results/${run.id}/report?download=true`} download><Icon name="download" />Download report</a>
        </>
      : <>
          <Button icon="sparkle" aria-label="Figure it all out and compare" disabled={!loaded} onClick={() => auto.mutate()}>Auto · figure it all out</Button>
          <Button variant="primary" iconAfter="arrow" disabled={!loaded || st?.gate !== ""} onClick={() => compare.mutate()}>Compare</Button>
        </>;
  // The setup, rows and results views say why a press was refused themselves; the others have only the rail.
  const note = ["values", "log", "config"].includes(v.view) ? refused : "";
  return <StepRail steps={steps} actions={actions} note={note} />;
}

export function ProfileRail() {
  const src = useSources().data;
  const [fp] = useSideForm("P");
  const P = src?.sides?.P;
  const name = P ? sideName("P", fp.name, P) : "Table";
  const held = useProfiling(!!P?.loaded).data;
  const { go, busy } = useRunProfile(name);
  const secs = useLog().data?.last?.Profiling?.seconds;
  const steps: RailStep[] = [
    { title: "Source", sub: P?.loaded ? `${name} ${rowsOf(P.rows)} rows` : "nothing loaded yet", state: P?.loaded ? "done" : "now", go: () => setView({ view: "setup", column: null }) },
    { title: "Profile", sub: busy ? "profiling…" : held?.profile ? (held.stale ? "from earlier settings" : secs != null ? `ready in ${secs}s` : "profiled") : P?.loaded ? "press Profile" : "-",
      state: busy ? "run" : P?.loaded ? (held?.profile ? "done" : "now") : "todo" },
  ];
  const ready = !!held?.profile && !busy;
  return <StepRail steps={steps} actions={<>
    <Button variant={held?.profile ? "default" : "primary"} disabled={!P?.loaded || busy} onClick={go}>Profile</Button>
    {ready && <ProfileFiles name={name} made={held!.made} />}
  </>} />;
}

export function Rail({ page }: { page: Page }) {
  return page === "Profiling" ? <ProfileRail /> : <CompareRail />;
}
