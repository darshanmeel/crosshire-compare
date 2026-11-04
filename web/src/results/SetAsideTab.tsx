// web/src/results/SetAsideTab.tsx - Results · Rows set aside: the rows Load left out for having too few
// or too many fields, a side each, as the source cards list them.
import { SetAside } from "../sources/SetAside";
import { useSources } from "../sources/useSources";
import type { Tag } from "../sources/types";

export function SetAsideTab() {
  const sides = useSources().data?.sides;
  return (
    <div className="onesided">
      {(["A", "B"] as Tag[]).map((tag) => {
        const v = sides?.[tag];
        if (!v?.set_aside) return null;
        return (
          <section key={tag} className="panel" aria-label={`Rows set aside in ${v.name}`}>
            <div className="panel-body">
              <h3>{v.name}</h3>
              <SetAside tag={tag} info={v.set_aside} startOpen />
            </div>
          </section>
        );
      })}
    </div>
  );
}
