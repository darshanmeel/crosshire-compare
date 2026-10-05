// web/src/profiling/ProfilingPage.tsx
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Running } from "../compare/RunningPanel";
import { EngineLimits } from "../shell/EngineLimits";
import { setView, useView } from "../shell/view";
import { Panel, Pill } from "../ui/kit";
import { Tips } from "../ui/Tips";
import { useSideForm } from "../sources/formStore";
import { sideName } from "../sources/names";
import { useSources } from "../sources/useSources";
import { useProfileFailed, useRunProfile } from "./actions";
import { ColumnDetail } from "./ColumnDetail";
import { KeySearch } from "./KeySearch";
import { statsOf } from "./frame";
import { ProfileView } from "./ProfileView";
import { useProfiling } from "./useProfiling";

export { STALE } from "./ProfileView";

const TIPS = ["Every column is measured; with no single-column key, combinations are tried - up to the size set below",
              "A wide or big table: :orange[minutes] - to try a slice, cut **Rows to read** on the source card"];

/** Under the source card: the profile held - or, before one, what Profile (in the bar above) will
 *  do, and while it runs, its last line. A column opened (useView().column) shows that column. */
export function ProfilingPage() {
  const qc = useQueryClient();
  const src = useSources();
  const [fp] = useSideForm("P");
  const P = src.data?.sides?.P;
  const name = P ? sideName("P", fp.name, P) : "Table";
  const view = useProfiling(!!P?.loaded);
  const failed = useProfileFailed();
  const { busy, running } = useRunProfile(name);
  const { column } = useView();
  // a table loaded again drops the profile on the server: ask again whenever the sources change
  useEffect(() => { qc.invalidateQueries({ queryKey: ["profiling"] }); }, [src.dataUpdatedAt]);
  const v = view.data;
  const shown = v?.profile && column && statsOf(v.profile, column) ? column : null;
  // a column the profile no longer has: back to the list
  useEffect(() => { if (v?.profile && column && !shown) setView({ column: null }); }, [v?.profile, column, shown]);
  if (!P?.loaded) return null;

  return (
    <>
      {busy && (running
        ? <Running job={running} title="Profiling…" />
        : <div className="prof-running" role="status"><Pill tone="run">Profiling…</Pill><span className="caption">Starting…</span></div>)}
      {failed && <div className="note error">{failed}</div>}
      {view.error && <div className="note error">{(view.error as Error).message}</div>}
      {v?.profile
        ? shown
          ? <ColumnDetail p={v.profile} column={shown} made={v.made} name={name} label={P.label} />
          : <ProfileView view={v} name={name} />
        : !busy && (
          <Panel title="Ready to profile" sub="press Profile in the bar above">
            <div className="panel-body"><Tips items={TIPS} /><KeySearch /><EngineLimits /></div>
          </Panel>
        )}
    </>
  );
}
