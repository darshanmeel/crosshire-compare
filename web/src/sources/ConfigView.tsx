// SPEC §17: Run from a saved config, opened from the header's Run from config button.
import { Button } from "../ui/kit";
import { setView } from "../shell/view";
import { ConfigPanel } from "./ConfigPanel";

export function ConfigView() {
  return (
    <section className="sec" aria-labelledby="cfg-title">
      <div className="sec-head">
        <Button size="sm" icon="arrowl" onClick={() => setView({ view: "setup" })}>Back</Button>
        <h2 id="cfg-title">Run from a config</h2>
        <span className="sub">replay a comparison exactly - the config.json every run writes, or one you saved</span>
      </div>
      <ConfigPanel />
    </section>
  );
}
