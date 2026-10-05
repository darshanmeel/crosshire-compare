// web/src/results/ResultsPage.tsx - the Results view of the Compare page (SPEC §08-§12): what the
// last run said, the stale note, the head (verdict, row outcome, tabs) and the tab on screen.
import { useCompareNow } from "../compare/useCompare";
import { useRunError } from "../compare/actions";
import { STALE } from "../compare/types";
import { goToSection } from "../shell/view";
import { NoteLine } from "../sources/NoteLine";
import { Callout, LinkButton } from "../ui/kit";
import { marks } from "../ui/marks";
import { ResultsHead } from "./ResultsHead";
import { ResultsView } from "./ResultsView";
import "./results.css";

export function ResultsPage() {
  const { data: st } = useCompareNow();
  const refused = useRunError();
  if (!st) return null;
  const notes = (
    <>
      {refused && <div className="note error">{marks(refused)}</div>}
      {st.filter_error && <div className="note error">{st.filter_error}</div>}
      {st.said.map((n, i) => <NoteLine key={i} note={n} />)}
    </>
  );
  if (!st.run) {
    return (
      <div className="results-page">
        {notes}
        <Callout icon="table">
          No result yet - set up the two sides and press <strong>Compare</strong>.{" "}
          <LinkButton onClick={() => goToSection("sources")} iconAfter="arrow">Back to the setup</LinkButton>
        </Callout>
      </div>
    );
  }
  return (
    <div className="results-page">
      {notes}
      {st.stale && <div className="note warning">{marks(STALE)}</div>}
      <ResultsHead run={st.run} stale={st.stale} />
      <ResultsView run={st.run} limit={st.settings.display_rows} />
    </div>
  );
}
