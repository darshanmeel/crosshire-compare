// web/src/values/ValuesEditor.tsx - SPEC §05: the pairs on the left with How values are read under
// them, one pair's steps on the right. Reached from the column table's Transform column.
import { useSetup, type SetupReady, type Spec } from "../setup/api";
import { sideLabels } from "../sources/names";
import { goToSection, setView, useView } from "../shell/view";
import { Icon } from "../ui/icons";
import { Button, Callout, Chip, Section } from "../ui/kit";
import { HowValuesRead } from "./HowValuesRead";
import { pairIndex, PairHead, TransformBox } from "./TransformBox";
import "./values.css";

const stepsSaid = (spec: Spec) => {
  const bits = (["A", "B"] as const)
    .map((w) => [w, (w === "A" ? spec.a_steps : spec.b_steps).length] as const)
    .filter(([, n]) => n)
    .map(([w, n]) => `${w} · ${n} step${n === 1 ? "" : "s"}`);
  return bits.join(" · ");
};

function Pairs({ s, at }: { s: SetupReady; at: number }) {
  const [NA, NB] = sideLabels(s.names[0], s.names[1]);
  return (
    <section className="panel vx-pairs" aria-label="Pairs">
      <div className="panel-head"><h3>Pairs</h3><span className="sub">pick one to edit its steps</span></div>
      {s.specs.length ? (
        <div className="tblwrap">
          <table className="tbl compact">
            <thead><tr><th><span className="sw a" />{NA}</th><th><span className="sw b" />{NB}</th><th>Read as</th><th>Steps</th></tr></thead>
            <tbody>{s.specs.map((spec, i) => {
              const said = stepsSaid(spec);
              return (
                <tr key={spec.canon} className={i === at ? "on" : undefined}>
                  <td>
                    <button type="button" className="vx-pick" aria-pressed={i === at} aria-label={`${spec.a_src} and ${spec.b_src}`}
                            onClick={() => setView({ pair: i })}>
                      {spec.a_src}{s.keys.includes(spec.canon) && <Icon name="key" size="sm" label="key" />}
                    </button>
                  </td>
                  <td className="m cb">{spec.b_src}</td>
                  <td><Chip>{spec.kind}</Chip></td>
                  <td className={said ? "m" : "dim"}>{said || "—"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      ) : <div className="panel-body"><span className="caption">Nothing is paired yet - pick a partner for a column in the column table.</span></div>}
      <HowValuesRead settings={s.settings} />
    </section>
  );
}

export function ValuesEditor() {
  const { data: s } = useSetup();
  const { pair } = useView();
  const back = <Button icon="arrowl" onClick={() => goToSection("columns")}>Back to the column table</Button>;
  const ready = s?.ready ? s : null;
  const at = ready ? pairIndex(ready, pair) : 0;
  const spec = ready?.specs[at];
  return (
    <Section n="02" title="Columns · transform & convert values" sub="steps run in DuckDB before the compare - each side separately" actions={back}>
      {!ready ? (
        <Callout icon="table">Load both sides first - then each pair of columns can be read through its own steps.</Callout>
      ) : (
        <div className="vx">
          <Pairs s={ready} at={at} />
          {spec && (
            <section className="panel vx-edit" aria-label={`Steps for ${spec.a_src} and ${spec.b_src}`}>
              <PairHead s={ready} spec={spec} />
              <TransformBox s={ready} />
            </section>
          )}
        </div>
      )}
    </Section>
  );
}
