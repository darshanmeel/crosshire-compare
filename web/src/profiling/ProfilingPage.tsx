// web/src/profiling/ProfilingPage.tsx
import { useEffect, useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Running } from "../compare/RunningPanel";
import { EngineLimits, type EngineView } from "../shell/EngineLimits";
import { setView, useView } from "../shell/view";
import { LinkButton, Panel, Pill } from "../ui/kit";
import { Tips } from "../ui/Tips";
import { useSideForm } from "../sources/formStore";
import { sideName } from "../sources/names";
import { useSources } from "../sources/useSources";
import { DEFAULT_SEARCH, useKeySearch, useProfileFailed, useRunProfile } from "./actions";
import { ColumnDetail } from "./ColumnDetail";
import { KeySearch } from "./KeySearch";
import { statsOf } from "./frame";
import { ProfileView } from "./ProfileView";
import { useProfiling } from "./useProfiling";

export { STALE } from "./ProfileView";

const TIPS = ["Every column is measured; with no single-column key, combinations are tried - up to the size set below",
              "A wide or big table: :orange[minutes] - to try a slice, cut **Rows to read** on the source card"];

/** Before a profile: one line, the tips and settings a fold away - open when a setting is not its default. */
function ReadyPanel() {
  const id = useId();
  const [s] = useKeySearch();
  const eng = useQuery({ queryKey: ["engine"], queryFn: () => api.get<EngineView>("/api/engine") }).data;
  const changed = s.key_cols !== DEFAULT_SEARCH.key_cols || s.top_keys !== DEFAULT_SEARCH.top_keys || s.shortlist !== DEFAULT_SEARCH.shortlist
    || eng?.memory_from === "saved" || eng?.disk_from === "saved";
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? changed;
  return (
    <Panel title="Ready to profile" sub="press Profile in the bar above"
      actions={<LinkButton iconAfter="chevron" className={shown ? "open" : undefined} aria-expanded={shown} aria-controls={`${id}-set`}
                           onClick={() => setOpen(!shown)}>Settings</LinkButton>}>
      {shown && <div className="panel-body" id={`${id}-set`}><Tips items={TIPS} /><KeySearch /><EngineLimits /></div>}
    </Panel>
  );
}

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
          <ReadyPanel />
        )}
    </>
  );
}
