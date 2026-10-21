// web/src/results/ReportTab.tsx - Results · Report (SPEC §11): the run's standalone report in a viewer
// - the file Download report gives, built for the rows shown - with the engine's own report beside
// it, the report in a tab of its own, a save to a folder on this machine and the viewer's height.
// The header holds the page's one primary Download report, so this one is secondary. The viewer runs no script (the
// report has none), and the server says so too.
import { useState } from "react";
import type { RunView } from "../compare/types";
import { Icon } from "../ui/icons";
import { fileUrl, useRunFiles } from "./detailApi";
import { Failed } from "./Failed";
import { FolderSave } from "./FolderSave";
import "./detail.css";

const HEIGHTS = ["fit", "600", "820", "1200", "1600"] as const;
type Height = (typeof HEIGHTS)[number];

export function ReportTab({ run, limit }: { run: RunView; limit: number }) {
  const f = useRunFiles(run.id, limit);
  const [height, setHeight] = useState<Height>("820");
  const src = `/api/results/${run.id}/report?limit=${limit}`;
  const d = f.data;
  return (
    <div className="rd">
      <div className="toolbar rd-report-bar">
        <span className="rd-explain">One standalone HTML file - setup, counts, every column, the differing rows marked, the one-sided rows. Opens anywhere; attach it to a ticket.</span>
        {d?.engine && (
          <a className="btn" href={fileUrl(run.id, d.engine.name)} download aria-label="Download engine report"
             title="The engine's own HTML, as it produces it">Engine report</a>
        )}
        <a className="btn" href={src} target="_blank" rel="noopener"><Icon name="external" />Open in new tab</a>
        <a className="btn" href={`${src}&download=1`} download><Icon name="download" />Download report</a>
      </div>
      {d?.engine_gone && <p className="caption rd-tight">The engine's report file is no longer on disk - run Compare again.</p>}
      {f.error && <Failed error={f.error} />}
      <div className="rd-run-row">
        {d && <FolderSave runId={run.id} what="report" field="Run folder" label="Save report to folder" folder={d.save_folder} />}
        <label className="rd-viewer"><span className="lbl">Viewer</span>
          <select className="in" aria-label="Viewer height" value={height} onChange={(e) => setHeight(e.target.value as Height)}>
            {HEIGHTS.map((h) => <option key={h} value={h}>{h === "fit" ? "Fit to window" : `${h} px`}</option>)}
          </select>
        </label>
      </div>
      <div className="report-frame" role="region" aria-label="Report preview">
        <div className="chrome"><Icon name="file" size="sm" /><span className="rd-file">{d?.report ?? `${run.pair}__report.html`}</span><span className="grow" /><span className="ph-hide">preview · the file is self-contained</span></div>
        <iframe title="Report" src={src} sandbox="" className={height === "fit" ? "rd-fit" : undefined}
                height={height === "fit" ? undefined : height} />
      </div>
    </div>
  );
}
