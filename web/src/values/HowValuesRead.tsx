import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { DERIVED_KEYS, errorText, SETUP_KEY, type Settings } from "../setup/api";
import { CommitInput, InfoTip } from "../ui/kit";
import "./values.css";

const NULLS = "Comma separated, any case - read as null on both sides";
const ORDER = "Order, per value: transform steps → null folding → trim → type.";

/** How values are read - the switches the run takes with it. They live on the server, so they
 *  survive a trip to the Profiling page as state.KEEP made them do. */
export function HowValuesRead({ settings }: { settings: Settings }) {
  const qc = useQueryClient();
  const put = useMutation({
    mutationFn: (patch: Partial<Settings>) => api.send<Settings>("PUT", "/api/setup/settings", patch),
    onSuccess: () => [...SETUP_KEY, ...DERIVED_KEYS].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
  });
  const tick = (key: "trim" | "empty_as_null" | "ignore_case", label: string) => (
    <label className="check"><input type="checkbox" checked={settings[key]}
                                    onChange={(e) => put.mutate({ [key]: e.target.checked })} />{label}</label>
  );
  return (
    <div className="vx-how" role="group" aria-labelledby="vx-how-h">
      <div className="vx-how-head">
        <h4 className="vx-h" id="vx-how-h">How values are read</h4>
        <InfoTip label="Order, per value" text={ORDER} />
      </div>
      <div className="field">
        <span className="vx-how-head">
          <label className="lbl" htmlFor="vx-nulls">Null tokens</label>
          <InfoTip label="About null tokens" text={NULLS} />
        </span>
        <CommitInput id="vx-nulls" className="in mono" aria-label="Null tokens" value={settings.null_tokens} title={NULLS}
                     onDone={(v) => put.mutate({ null_tokens: v })} />
      </div>
      {tick("empty_as_null", "Empty string is null")}
      {tick("trim", "Trim whitespace")}
      {tick("ignore_case", "Ignore case in values")}
      <div className="tol">
        <label className="lbl" htmlFor="vx-tol">Numeric tolerance</label>
        <CommitInput id="vx-tol" type="number" min={0} step="any" aria-label="Numeric tolerance" value={String(settings.tolerance)}
                     onDone={(v) => put.mutate({ tolerance: Math.max(0, Number(v) || 0) })} />
        <span className="hint">absolute · 0 = exact</span>
      </div>
      {put.error && <div className="note error" role="alert">{errorText(put.error)}</div>}
    </div>
  );
}
