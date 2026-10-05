// web/src/compare/CompareBar.tsx - the foot of the setup (SPEC §04, §06): the big "Compare <A> against
// <B>" button, what it will compare in one grey line, and why it cannot run when it cannot - nothing
// paired, no column ticked, a filter the engine refused, or the server's refusal of the last press.
import { useId } from "react";
import { useSetup } from "../setup/api";
import { NoteLine } from "../sources/NoteLine";
import { Button, Callout, num } from "../ui/kit";
import { marks } from "../ui/marks";
import { useRunCompare, useRunError } from "./actions";
import { TICK_COMPARE } from "./types";
import { useCompareNow } from "./useCompare";
import "./running.css";

export const NOTHING_PAIRED = "Nothing is paired yet - pick a counterpart for at least one column in the table.";   // = comparing.NOTHING_PAIRED

const plural = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;

export function CompareBar() {
  const st = useCompareNow().data;
  const setup = useSetup().data;
  const go = useRunCompare();
  const err = useRunError();
  const whyId = useId();
  const refused = err ? <Callout tone="neg" icon="x"><span role="alert">{marks(err)}</span></Callout> : null;
  if (!st || st.gate === "load") return refused && <div className="compare-bar">{refused}</div>;

  const why = st.gate === "pair" ? NOTHING_PAIRED : st.gate === "tick" ? TICK_COMPARE : "";
  const help: string[] = [];
  if (setup?.ready) {
    const n = setup.compare.length;
    const fresh = st.run && !st.stale ? st.run.matched : null;
    help.push(fresh !== null ? `${plural(n, "column", "columns")} on ${plural(fresh, "paired row", "paired rows")}` : plural(n, "column", "columns"));
    help.push(setup.keys.length ? `key ${setup.keys.join(" + ")}`
      : setup.settings.nokey_mode === "position" ? "no key - rows paired by position" : "no key - rows paired by hash");
  }
  help.push("runs in DuckDB");

  return (
    <div className="compare-bar">
      <div className="actions">
        <Button variant="primary" size="lg" iconAfter="arrow" disabled={!!why || st.busy || go.isPending}
                aria-describedby={why ? whyId : undefined} onClick={() => go.mutate()}>
          {st.busy ? "Comparing…" : `Compare ${st.names[0]} against ${st.names[1]}`}
        </Button>
        {why ? <span className="why" id={whyId}>{marks(why)}</span> : <span className="help">{help.join(" · ")}</span>}
      </div>
      {st.filter_error && <div className="note error">{marks(st.filter_error)}</div>}
      {refused}
      {st.said.map((n, i) => <NoteLine key={i} note={n} />)}
    </div>
  );
}
