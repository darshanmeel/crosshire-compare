// web/src/keys/RunSettingsCard.tsx - "Run settings" (SPEC §06): Re-run on every change, Rows to display
// per section, Profile both sides first and Tables as - the compare settings (PUT /api/compare/settings) -
// and DuckDB's memory and disk limits.
import { useId } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AUTO_PROFILE_HELP, RERUN_HELP } from "../compare/types";
import { useCompareNow, useSaveSettings } from "../compare/useCompare";
import { EngineLimits } from "../shell/EngineLimits";
import "./keys.css";

const FORMATS = [["csv", "CSV"], ["parquet", "Parquet"], ["both", "both"]] as const;
const FORMAT_HELP = "Parquet: typed counts, a fraction of the size, straight into DuckDB, pandas or a warehouse. Applies to the next run; COMPARE_TABLE_FORMATS sets the default.";

export const roundRows = (v: string) => Math.min(10000, Math.max(100, Math.round(Number(v || 0) / 100) * 100));

export function RunSettingsCard() {
  const id = useId();
  const { data: st } = useCompareNow();
  const save = useSaveSettings();
  const qc = useQueryClient();
  const set = st?.settings;
  if (!set) return null;
  const commitRows = (v: string) => {
    const n = roundRows(v);
    if (n !== set.display_rows) save.mutate({ display_rows: n });
  };
  return (
    <div className="card runset">
      <label className="check" title={RERUN_HELP}>
        <input type="checkbox" checked={set.auto_rerun} onChange={(e) => save.mutate({ auto_rerun: e.target.checked })} />
        Re-run on every change
      </label>
      <label className="check" title={AUTO_PROFILE_HELP}>
        <input type="checkbox" checked={set.auto_profile} onChange={(e) => save.mutate({ auto_profile: e.target.checked })} />
        Profile both sides first
      </label>
      <span className="runset-rows">
        <label htmlFor={`${id}-r`}>Rows to display per section</label>
        <input type="number" className="in mono" id={`${id}-r`} min={100} max={10000} step={100} key={set.display_rows}
               defaultValue={set.display_rows} title="Downloads always contain everything."
               onBlur={(e) => commitRows(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") commitRows((e.target as HTMLInputElement).value); }} />
      </span>
      <span className="runset-fmt" role="radiogroup" aria-label="Tables as" title={FORMAT_HELP}>
        <span className="runset-lbl">Tables as</span>
        {FORMATS.map(([v, text]) => (
          <label key={v} className="check">
            <input type="radio" name={`${id}-fmt`} checked={set.out_fmt === v}
                   onChange={() => save.mutate({ out_fmt: v }, {   // a run's Downloads tab says the setting
                     onSuccess: () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "results" && q.queryKey[2] === "files" }),
                   })} />
            {text}
          </label>
        ))}
      </span>
      <span className="caption runset-help">Profile both sides first runs with Auto - minutes on a big pair. Downloads always hold every row.</span>
      <EngineLimits />
    </div>
  );
}
