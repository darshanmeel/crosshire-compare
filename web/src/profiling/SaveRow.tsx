// web/src/profiling/SaveRow.tsx
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Button } from "../ui/kit";
import { marks } from "../ui/marks";
import type { Saved } from "./types";

// what each profile's folder box holds, by run id - kept across a trip to the other page (save_row's _kept)
let kept: Record<string, string> = {};
export function resetKept() { kept = {}; }

/** A folder box and a button that writes the six files there - no browser involved. */
export function SaveRow({ made, folder, name }: { made: string; folder: string; name: string }) {
  const [text, setText] = useState(kept[made] ?? folder);
  const [said, setSaid] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = useRef(folder);                 // the default the box last held
  useEffect(() => { setText(kept[made] ?? folder); setSaid(null); shown.current = folder; }, [made]);
  // the Name changed the default: a box still holding the old default follows it, one the user typed in does not
  useEffect(() => {
    if (kept[made] === undefined || kept[made] === shown.current) { delete kept[made]; setText(folder); }
    shown.current = folder;
  }, [folder]);

  async function save() {
    setBusy(true);
    setSaid(null);
    try {
      const r = await api.send<Saved>("POST", "/api/profiling/save", { name, folder: text });
      setSaid({ tone: "success", text: r.text });
    } catch (x) {
      setSaid({ tone: "error", text: (x as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="saverow-wrap">
      <div className="saverow">
        <input type="text" className="in mono" aria-label="Save to folder" placeholder="C:\data\compare_out" value={text}
               onChange={(e) => { kept[made] = e.target.value; setText(e.target.value); }} />
        <Button icon="folder" onClick={save} disabled={busy}>Save to folder</Button>
      </div>
      {said && <div className={`note ${said.tone}`}>{marks(said.text)}</div>}
    </div>
  );
}
