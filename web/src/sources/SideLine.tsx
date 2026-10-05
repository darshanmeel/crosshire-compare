// web/src/sources/SideLine.tsx - a side collapsed to one line while a run is going (screen 07): badge,
// name, file · rows × columns, Loaded pill. It keeps the side's region name, so "File A" is still found.
import { Pill, SideBadge } from "../ui/kit";
import { useSideForm } from "./formStore";
import { loadedSummary } from "./LoadedLine";
import { sideName } from "./names";
import { useSources } from "./useSources";
import type { Tag } from "./types";
import "./sources.css";

export function SideLine({ tag }: { tag: Tag }) {
  const view = useSources().data?.sides?.[tag];
  const [f] = useSideForm(tag);
  const s = view?.loaded ? loadedSummary(view) : null;
  return (
    <section className="card side-line" aria-label={tag === "P" ? "File" : `File ${tag}`}>
      <div className="card-head">
        <SideBadge side={tag} />
        <strong className="nm">{sideName(tag, f.name, view)}</strong>
        {s ? <span className="what" title={`${s.what} · ${s.rest}`}>{s.what} · {s.rest}</span> : <span className="grow" />}
        {s ? <Pill tone="ok">Loaded</Pill> : <Pill tone="idle">Not loaded</Pill>}
      </div>
    </section>
  );
}
