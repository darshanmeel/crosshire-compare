// web/src/columns/ColumnsBox.tsx - the Columns section's body: the engine's notes, the Match by data
// preview, the pairing board in its panel with the summary foot, and the setup card behind "Summary".
import { useState } from "react";
import { marks } from "../ui/marks";
import { Button } from "../ui/kit";
import { Icon } from "../ui/icons";
import type { SetupReady } from "../setup/api";
import { FrameTable } from "../setup/FrameTable";
import { ColumnTable } from "./ColumnTable";
import { guessLine, guessPairs } from "./pairing";
import type { ColumnCalls } from "./useColumnCalls";
import "./columns.css";

/** The card: what the table amounts to. The server escaped every name in it (setup.card_rows). */
export function SetupCard({ s }: { s: SetupReady }) {
  return (
    <dl className="cols-card" aria-label="Setup">
      {s.card.map((r) => (
        <div className="row" key={r.label}>
          <dt className="k">{r.label}</dt>
          <dd className="v" dangerouslySetInnerHTML={{ __html: r.html }} />
        </div>
      ))}
    </dl>
  );
}

/** Match by data, header buttons: pair the leftovers by their values, reset, save and load the mapping. */
export function ColumnsActions({ s, c }: { s: SetupReady; c: ColumnCalls }) {
  const matching = c.pending === "/match";
  return (
    <>
      <Button variant="dark" disabled={!s.can_match || c.busy} onClick={() => c.call("/match")}
              title={s.can_match ? "Reads a sample of both files and pairs the unpaired columns that hold the same values, whatever they are called."
                                 : "Every column has a partner on the other side, or one side has none left over."}>
        {matching ? "Comparing the values…" : "Match by data"}
      </Button>
      <Button disabled={c.busy} onClick={() => c.call("/reset")}>Reset to name matches</Button>
      <a className="btn" href="/api/setup/mapping" download="mapping.json">Save mapping</a>
      <label className="btn cols-file">
        Load mapping…
        <input type="file" aria-label="Load mapping" accept=".json,application/json" disabled={c.busy}
               onChange={async (e) => { const f = e.target.files?.[0]; if (f) c.call("/mapping", "POST", { text: await f.text() }); e.target.value = ""; }} />
      </label>
    </>
  );
}

/** What Match by data found: the pairs it would make, to apply or dismiss. */
function DataMatch({ s, c }: { s: SetupReady; c: ColumnCalls }) {
  const dm = s.data_match;
  if (!dm) return null;
  return (
    <div className="panel cols-match" role="region" aria-label="Match by data result">
      <div className="panel-head">
        <h3>Match by data</h3>
        <span className="sub">{dm.pairs
          ? `${dm.pairs} pair(s) of columns hold the same values.`
          : "No unpaired column on one side holds the same values as one on the other - they look like genuinely different fields."}</span>
        <div className="actions">
          {dm.pairs > 0 && <Button variant="primary" size="sm" icon="check" disabled={c.busy} onClick={() => c.call("/match/apply")}>Apply these pairs</Button>}
          <Button size="sm" disabled={c.busy} onClick={() => c.call("/match", "DELETE")}>Dismiss</Button>
        </div>
      </div>
      {dm.pairs > 0 && <FrameTable label="Match by data" frame={dm} />}
    </div>
  );
}

/** The panel foot: Key emp_id · Compare 5 columns · Skip 2 one-sided, and the guesses to check. */
function Foot({ s, open, toggle }: { s: SetupReady; open: boolean; toggle: () => void }) {
  const skippedPairs = s.rows.filter((r) => r["A column"] && r["B column"] && !r.Key && !r.Compare).length;
  const oneSided = s.only_a.length + s.only_b.length;
  const skip = [oneSided && `${oneSided} one-sided`, skippedPairs && `${skippedPairs} not compared`].filter(Boolean).join(", ");
  const guess = guessLine(s);
  return (
    <div className="panel-foot">
      <span><strong>Key</strong> {s.keys.length ? <code>{s.keys.join(" + ")}</code> : <span className="cols-warn">none - rows are matched by hashing</span>}</span>
      <span><strong>Compare</strong> {s.compare.length} {s.compare.length === 1 ? "column" : "columns"}</span>
      {skip && <span><strong>Skip</strong> {skip}</span>}
      <span className="grow" />
      {guess && <span className="cols-guess"><i aria-hidden="true" />{guess} {guessPairs(s).map((p) => <code key={p}>{p}</code>)}</span>}
      <button type="button" className="link-btn" aria-expanded={open} onClick={toggle}>
        Summary<Icon name="chevron" size="sm" />
      </button>
    </div>
  );
}

/** The Columns section's body for a loaded pair. */
export function ColumnsBox({ s, c }: { s: SetupReady; c: ColumnCalls }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {s.said.map((n, i) => <div key={i} className={`note ${n.tone}`}>{marks(n.text)}</div>)}
      {s.duplicates.length > 0 && <div className="note error">{marks(`Common name used more than once: **${s.duplicates.join(", ")}**`)}</div>}
      {c.err && <div className="note error" role="alert">{c.err}</div>}
      <DataMatch s={s} c={c} />
      <div className="panel cols-panel">
        <ColumnTable s={s} busy={c.busy} edit={c.edit} setRole={c.setRole} />
        <Foot s={s} open={open} toggle={() => setOpen(!open)} />
        {open && (
          <div className="cols-summary">
            <SetupCard s={s} />
            <div className="chips" aria-label="Columns at a glance">
              {s.chips.map((x, i) => <span key={i} className={x.cls === "key" ? "chip key" : x.cls === "off" ? "chip neg" : "chip"}>{x.text}</span>)}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
