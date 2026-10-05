import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Meta } from "./api/client";
import { AppHeader } from "./shell/AppHeader";
import { Rail } from "./shell/StepRail";
import { Welcome } from "./shell/Welcome";
import { LogView } from "./shell/LogView";
import { usePage, type Page } from "./shell/usePage";
import { setView, useView } from "./shell/view";
import { ConnectionsDrawer } from "./connections/ConnectionsDrawer";
import { ProfileSource, SourcesSection } from "./sources/SourcesSection";
import { ConfigView } from "./sources/ConfigView";
import { useSources } from "./sources/useSources";
import { ColumnsSection } from "./columns/ColumnsSection";
import { ValuesEditor } from "./values/ValuesEditor";
import { RowsEditor } from "./keys/RowsEditor";
import { RowsSummary } from "./keys/RowsSummary";
import { RunningPanel } from "./compare/RunningPanel";
import { CompareBar } from "./compare/CompareBar";
import { useCompareFreshness, useCompareNow } from "./compare/useCompare";
import { ResultsPage } from "./results/ResultsPage";
import { SetupSync } from "./setup/SetupPage";
import { ConfigSync } from "./sources/ConfigPanel";
import { AutoRerun } from "./compare/AutoRerun";
import { startedQuietly } from "./compare/actions";
import { ProfilingPage } from "./profiling/ProfilingPage";

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/api/meta"), staleTime: Infinity });
}

/** When a Compare, Auto or config run ends with a result, the results are what comes next - unless
 *  the person is in an editor or reading the results, or the run was a re-run on every change. */
function useResultsWhenDone() {
  const st = useCompareNow().data;
  const { view } = useView();
  const was = useRef(false);
  useEffect(() => {
    if (was.current && !st?.busy && st?.run && (view === "config" || (view === "setup" && !startedQuietly()))) setView({ view: "results", tab: "summary" });
    was.current = !!st?.busy;
  }, [st?.busy, st?.run?.id]);
}

/** A rail step or a Back button asked for one section of the setup: scroll to it once it is drawn. */
function useAnchor() {
  const { view, anchor } = useView();
  useEffect(() => {
    if (view !== "setup" || !anchor) return;
    requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }));
    setView({ anchor: null });
  }, [view, anchor]);
}

function ComparePage({ meta }: { meta: Meta }) {
  const { view } = useView();
  const sides = useSources().data?.sides;
  const nothing = !!sides && !sides.A.loaded && !sides.B.loaded;
  if (view === "results") return <ResultsPage />;
  if (view === "values") return <ValuesEditor />;
  if (view === "rows") return <RowsEditor />;
  return (
    <>
      <RunningPanel />
      {nothing && <Welcome page="Compare" meta={meta} setPage={() => undefined} />}
      <SourcesSection meta={meta} />
      <ColumnsSection />
      <RowsSummary />
      <CompareBar />
    </>
  );
}

function ProfilePage({ meta, setPage }: { meta: Meta; setPage: (p: Page) => void }) {
  const P = useSources().data?.sides?.P;
  return (
    <>
      {P && !P.loaded && <Welcome page="Profiling" meta={meta} setPage={setPage} />}
      <ProfileSource meta={meta} />
      <ProfilingPage />
    </>
  );
}

export default function App() {
  const { data: meta } = useMeta();
  const [page, setPage] = usePage();
  const v = useView();
  useCompareFreshness();
  useResultsWhenDone();
  useAnchor();
  return (
    <>
      <AppHeader meta={meta} page={page} setPage={setPage} />
      <Rail page={page} />
      <main className="page">
        {page === "Compare" && <><SetupSync /><ConfigSync /><AutoRerun /></>}
        {v.view === "log" ? <LogView />
          : v.view === "config" && page === "Compare" ? <ConfigView />
          : meta && (page === "Compare" ? <ComparePage meta={meta} /> : <ProfilePage meta={meta} setPage={setPage} />)}
      </main>
      {v.drawer === "connections" && <ConnectionsDrawer meta={meta} onClose={() => setView({ drawer: null })} />}
    </>
  );
}
