// web/src/results/ResultsView.tsx - the body of the results tab on screen (the head holds the tabs).
import type { RunView } from "../compare/types";
import { useView } from "../shell/view";
import { DiffRowsTab } from "./DiffRowsTab";
import { DownloadsTab } from "./DownloadsTab";
import { OneSidedTab } from "./OneSidedTab";
import { ReportTab } from "./ReportTab";
import { SummaryView } from "./SummaryView";

export function ResultsView({ run, limit }: { run: RunView; limit: number }) {
  const { tab } = useView();
  return (
    <div className="results-body" role="tabpanel">
      {tab === "summary" && <SummaryView run={run} />}
      {tab === "rows" && <DiffRowsTab run={run} limit={limit} />}
      {tab === "onesided" && <OneSidedTab run={run} />}
      {tab === "report" && <ReportTab run={run} limit={limit} />}
      {tab === "downloads" && <DownloadsTab run={run} limit={limit} />}
    </div>
  );
}
