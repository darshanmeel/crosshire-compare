// web/src/columns/RunningTable.tsx - the pairs known so far while a run works (SPEC §07): read-only,
// compact; while Auto runs, a column still without a partner reads "pairing by values…".
import type { SetupReady } from "../setup/api";
import { Icon } from "../ui/icons";
import { Chip, Pill } from "../ui/kit";
import { originOf, paired, roleOf, stepsLine } from "./pairing";

const ROLE_WORD = { key: "key", compare: "compare", skip: "skip" } as const;

export function RunningTable({ s, pairing }: { s: SetupReady; pairing: boolean }) {
  const [NA, NB] = s.names;
  const pend = <Pill tone="run">pairing by values…</Pill>;
  return (
    <div className="tblwrap cols-wrap">
      <table className="tbl compact cols-tbl cols-run" aria-label="Column table">
        <thead><tr>
          <th className="w-role">Role</th>
          <th className="w-col"><span className="sw a" />{NA} column</th>
          <th className="w-swap"><span className="sr-only">pairs with</span></th>
          <th className="w-col"><span className="sw b" />{NB} column</th>
          <th className="w-type">Read as</th>
          <th>Transform</th>
          <th className="w-origin">Matched by</th>
        </tr></thead>
        <tbody>
          {s.rows.map((r, i) => {
            const both = paired(r);
            const waiting = !both && pairing;
            const role = roleOf(r);
            const sp = s.specs.find((x) => x.canon === r["Common name"]);
            const o = originOf(r, s.names);
            return (
              <tr key={i} className={both ? undefined : "muted"}>
                <td>{waiting ? <Chip>?</Chip> : role === "key" ? <Chip tone="key">key</Chip> : <Chip>{ROLE_WORD[role]}</Chip>}</td>
                <td className="m ca">{r["A column"] || (waiting ? pend : <span className="dim">no partner</span>)}</td>
                <td className="swap"><Icon name="swap" size="sm" /></td>
                <td className="m cb">{r["B column"] || (waiting ? pend : <span className="dim">no partner</span>)}</td>
                <td><Chip>{r.Type}</Chip></td>
                <td className="m dim">{both ? stepsLine(sp) || "—" : ""}</td>
                <td className={waiting ? "" : o.tone ? `cols-origin ${o.tone}` : "cols-origin dim"}>{waiting ? "" : o.text}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
