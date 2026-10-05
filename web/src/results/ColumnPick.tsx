// web/src/results/ColumnPick.tsx - which columns a part of the results shows: Profile by bucket
// and the One-sided rows tab tick them from the same grouped list.
import { useState } from "react";
import { Button, LinkButton } from "../ui/kit";

export type Group = { title: string; tone?: "nc"; items: { name: string; label: string }[] };

/** The columns of the groups marked "nc" - on one side only, not compared - to colour them apart. */
export const notCompared = (groups: { tone?: "nc"; items: (string | { name: string })[] }[] = []) =>
  new Set(groups.filter((g) => g.tone === "nc").flatMap((g) => g.items.map((o) => (typeof o === "string" ? o : o.name))));
const FILTER_AT = 12;

/** Every column on offer, a checkbox each, under Key columns / Mismatched / Matching (or Compared) / Not compared -
 *  always in view, so what is shown can be seen and changed at any time. `shown` is what is ticked
 *  to begin with (never a column that is not compared); a filter when the pair is wide. */
export function ColumnPick({ label, groups, shown, now, set }:
  { label: string; groups: Group[]; shown: string[]; now: string[]; set: (v: string[] | null) => void }) {
  const [find, setFind] = useState("");
  const on = new Set(now);
  const f = find.trim().toLowerCase();
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const flip = (c: string, yes: boolean) => set(yes ? [...now, c] : now.filter((x) => x !== c));
  const same = now.length === shown.length && now.every((c, i) => c === shown[i]);
  return (
    <div className="col-pick" role="group" aria-label={label}>
      <div className="col-pick-bar">
        <strong>{label}</strong>
        <span className="sub" aria-live="polite">{now.length} of {total} ticked</span>
        {total > FILTER_AT && (
          <input type="search" placeholder="Filter columns" aria-label="Filter columns" value={find} onChange={(e) => setFind(e.target.value)} />
        )}
        <span className="grow" />
        <Button size="sm" disabled={same} onClick={() => set(null)}>Default</Button>
        <Button size="sm" variant="ghost" disabled={!now.length} onClick={() => set([])}>Clear</Button>
      </div>
      {groups.map((g) => {
        const seen = f ? g.items.filter((o) => o.label.toLowerCase().includes(f)) : g.items;
        if (!seen.length) return null;
        const all = seen.every((o) => on.has(o.name));
        return (
          <fieldset key={g.title} className={g.tone ? `col-pick-group ${g.tone}` : "col-pick-group"}>
            <legend>{g.title} <span className="sub">{g.items.filter((o) => on.has(o.name)).length} of {g.items.length}</span></legend>
            <LinkButton aria-label={`${all ? "Untick" : "Tick"} all ${g.title.toLowerCase()}`}
              onClick={() => set(all ? now.filter((c) => !seen.some((o) => o.name === c)) : [...now, ...seen.map((o) => o.name).filter((c) => !on.has(c))])}>
              {all ? "none" : "all"}
            </LinkButton>
            <div className="col-pick-list">
              {seen.map((o) => (
                <label key={o.name} className={on.has(o.name) ? "check on" : "check"}>
                  <input type="checkbox" checked={on.has(o.name)} onChange={(e) => flip(o.name, e.target.checked)} />{o.label}
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
      {f && groups.every((g) => !g.items.some((o) => o.label.toLowerCase().includes(f))) && <span className="caption">No column matches.</span>}
    </div>
  );
}
