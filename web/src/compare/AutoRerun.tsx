// web/src/compare/AutoRerun.tsx - "Re-run on every change": when the setting is on and the result is
// stale, compare again - once per settings signature, so a run that keeps failing is not a loop.
// Renders nothing; App mounts it once on the Compare page.
import { useEffect, useRef } from "react";
import { useRunCompare } from "./actions";
import { useCompareNow } from "./useCompare";

export function AutoRerun() {
  const st = useCompareNow().data;
  const go = useRunCompare({ stay: true });
  const triedFor = useRef("");
  useEffect(() => {
    if (st?.gate === "" && st.stale && st.settings?.auto_rerun && !st.busy && !go.isPending && !st.filter_error && triedFor.current !== st.sig) {
      triedFor.current = st.sig;
      go.mutate();
    }
  }, [st?.sig, st?.stale, st?.busy, st?.settings?.auto_rerun, st?.gate, st?.filter_error, go.isPending]);
  return null;
}
