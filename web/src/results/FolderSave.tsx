// web/src/results/FolderSave.tsx - a labelled folder box and a button that write the run's report,
// config or every file there (POST /api/results/{run}/save) - no browser involved, the reliable route
// for big results. The box starts at the run's own folder and keeps what was typed for this run; a
// new run starts at its own folder again (the same kept pick SaveRow uses). Out of focus the box
// shows the end of the path - the run's own folder - with the whole path on hover.
import { useId, useLayoutEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { NoteLine } from "../sources/NoteLine";
import type { Note } from "../sources/types";
import { Button } from "../ui/kit";
import type { FilesView, SaveOut } from "./detailApi";
import { usePick } from "./pickStore";

export function FolderSave({ runId, what, label, field, folder, onSaved }: {
  runId: string; what: "report" | "config" | "all"; label: string; field: string; folder: string;
  onSaved?: (f: FilesView) => void;
}) {
  const id = useId();
  const [typed, setTyped] = usePick<string>(`save:${runId}:${what}`, folder);
  const [said, setSaid] = useState<Note | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const toEnd = () => { const el = box.current; if (el && document.activeElement !== el) el.scrollLeft = el.scrollWidth; };
  useLayoutEffect(toEnd, [typed]);
  const go = useMutation({
    mutationFn: () => api.send<SaveOut>("POST", `/api/results/${runId}/save`, { what, folder: typed }),
    onSuccess: (r) => { setSaid({ tone: "success", text: r.text }); onSaved?.(r.files); },
    onError: (e) => setSaid({ tone: "error", text: errorText(e) }),
  });
  return (
    <div className="rd-folder">
      <div className="rd-folder-row">
        <label className="lbl" htmlFor={id}>{field}</label>
        <input id={id} ref={box} className="in mono grow" type="text" placeholder="C:\data\compare_out" value={typed} title={typed}
               onChange={(e) => setTyped(e.target.value)} onBlur={toEnd} />
        <Button icon="folder" disabled={go.isPending} onClick={() => go.mutate()}>{go.isPending ? "Saving…" : label}</Button>
      </div>
      {said && <NoteLine note={said} />}
    </div>
  );
}
