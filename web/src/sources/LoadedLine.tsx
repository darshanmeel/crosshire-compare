// web/src/sources/LoadedLine.tsx - the card's foot once a side is loaded: what was read (file or
// table · rows × columns · cut, fetch, snapshot), its column names, the Preview 10 rows toggle, then
// the name hint and the engine's notes on what it read.
import type { ReactNode } from "react";
import { LinkButton, num } from "../ui/kit";
import { marks } from "../ui/marks";
import { nameHint, sideName } from "./names";
import { NoteLine } from "./NoteLine";
import type { SideView, Tag } from "./types";

/** "hr_employees.csv · 3,000 rows × 7 columns · Parquet snapshot", from the side the API reports. */
export function loadedSummary(view: SideView): { what: string; rest: string } {
  const capped = /capped at [\d,]+/.exec(view.caption)?.[0];
  const rest = [`${num(view.rows ?? 0)} rows × ${view.columns.length} columns`, view.cut, view.fetched_at && `fetched ${view.fetched_at}`,
                capped, view.snapshot && "Parquet snapshot"].filter(Boolean).join(" · ");
  return { what: view.origin || view.label, rest };
}

export function LoadedLine({ tag, view, box, otherBox, otherView, preview, onPreview, previewId, cols, children }:
  { tag: Tag; view: SideView; box: string; otherBox: string; otherView?: SideView; preview: boolean; onPreview: () => void;
    previewId: string; cols?: string; children?: ReactNode }) {
  const otherTag: Tag = tag === "A" ? "B" : "A";
  const hint = tag === "P" ? "" : nameHint(tag, box, view, sideName(tag, box, view), sideName(otherTag, otherBox, otherView));
  const s = loadedSummary(view);
  return <>
    <div className="card-foot loaded">
      <span className="what"><strong>{s.what}</strong> · {s.rest}</span>
      <span className="cols">{cols ?? view.columns.join(", ")}</span>
      <span className="foot-end">
        <LinkButton className={preview ? "preview-toggle open" : "preview-toggle"} aria-expanded={preview} aria-controls={previewId}
                    onClick={onPreview} iconAfter="chevron">Preview 10 rows</LinkButton>
        {children}
      </span>
    </div>
    {hint && <p className="caption hint">{marks(hint)}</p>}
    {view.notes.map((n, i) => <NoteLine key={i} note={n} />)}
  </>;
}
