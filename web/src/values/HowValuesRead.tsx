import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { DERIVED_KEYS, errorText, SETUP_KEY, type Settings } from "../setup/api";
import "./values.css";

/** A box that keeps what is typed and sends it when it is left - a number or the null words. */
function Draft({ label, value, number, className, id, onDone }:
  { label: string; value: string; number?: boolean; className?: string; id: string; onDone: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [was, setWas] = useState(value);
  if (value !== was) { setWas(value); setDraft(value); }
  return (
    <input id={id} className={className} type={number ? "number" : "text"} aria-label={label} value={draft}
           min={number ? 0 : undefined} step={number ? "any" : undefined}
           onChange={(e) => setDraft(e.target.value)} onBlur={() => { if (draft !== value) onDone(draft); }}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

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
      <h4 className="vx-h" id="vx-how-h">How values are read</h4>
      <div className="field">
        <label className="lbl" htmlFor="vx-nulls">Null tokens</label>
        <Draft id="vx-nulls" className="in mono" label="Null tokens" value={settings.null_tokens}
               onDone={(v) => put.mutate({ null_tokens: v })} />
        <span className="hint">comma separated, any case - read as null on both sides</span>
      </div>
      {tick("empty_as_null", "Empty string is null")}
      {tick("trim", "Trim whitespace")}
      {tick("ignore_case", "Ignore case in values")}
      <div className="tol">
        <label className="lbl" htmlFor="vx-tol">Numeric tolerance</label>
        <Draft id="vx-tol" number label="Numeric tolerance" value={String(settings.tolerance)}
               onDone={(v) => put.mutate({ tolerance: Math.max(0, Number(v) || 0) })} />
        <span className="hint">absolute · 0 = exact</span>
      </div>
      <span className="hint">Order, per value: transform steps → null folding → trim → type.</span>
      {put.error && <div className="note error" role="alert">{errorText(put.error)}</div>}
    </div>
  );
}
