// web/src/compare/actions.ts - the two buttons that start a run, shared by the rail and the page:
// Compare (POST /api/compare) and Auto (POST /api/auto). Both are jobs; the Log and the compare
// state are read again so the rail and the running panel follow them. A refusal stays on the
// mutation, where useRunError finds it.
import { useMutation, useMutationState, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type LogEntry } from "../api/client";
import { setView } from "../shell/view";

const RUN = ["start-run"];
let quiet = false;

/** Whether the run going now was started by the re-run on every change, which leaves the person where they are. */
export const startedQuietly = () => quiet;

/** `stay`: the re-run on every change keeps the person where they are (the values or rows editor)
 *  rather than taking them to the setup and then the results. */
function useStart(path: string, stay = false) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: RUN,
    mutationFn: () => api.send<LogEntry>("POST", path),
    onSuccess: () => {
      quiet = stay;
      qc.invalidateQueries({ queryKey: ["log"] });
      qc.invalidateQueries({ queryKey: ["compare"] });
      if (!stay) setView({ view: "setup", anchor: null, tab: "summary" });
    },
  });
}

export const useRunCompare = ({ stay = false } = {}) => useStart("/api/compare", stay);
export const useRunAuto = () => useStart("/api/auto");

/** Why the last Compare or Auto press was refused, if it was - '' once a later one went through. */
export function useRunError(): string {
  const last = useMutationState({ filters: { mutationKey: RUN }, select: (m) => m.state }).at(-1);
  if (!last || last.status !== "error") return "";
  return last.error instanceof ApiError ? last.error.detail : String(last.error);
}
