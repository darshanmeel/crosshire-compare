// web/src/columns/AddColumn.tsx - a column made from an expression on each side (a date from a
// datetime, say), added to A, B or both and paired like any other; and the ones added so far.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { errorText, useSetupSend, type SetupReady } from "../setup/api";
import { sideLabels } from "../sources/names";
import { Button, LinkButton } from "../ui/kit";
import { marks } from "../ui/marks";

type Preset = { id: string; label: string; expr: string };
const quote = (c: string) => `"${c.replace(/"/g, '""')}"`;
const fill = (p: Preset | undefined, col: string) => (p && col ? p.expr.replace(/\{c\}/g, quote(col)) : "");

/** The form: a name, a ready-made expression or your own, and the column each side makes it from. */
export function AddColumn({ s, onClose }: { s: SetupReady; onClose: () => void }) {
  const send = useSetupSend();
  const qc = useQueryClient();
  const presets = useQuery({ queryKey: ["setup-derived"], staleTime: Infinity,
                             queryFn: () => api.get<{ presets: Preset[] }>("/api/setup/derived") }).data?.presets ?? [];
  const [NA, NB] = sideLabels(s.names[0], s.names[1]);
  const first = s.specs[0];
  const [preset, setPreset] = useState("date");
  const [col, setCol] = useState<{ A: string; B: string }>({ A: first?.a_src ?? s.columns.A[0] ?? "", B: first?.b_src ?? s.columns.B[0] ?? "" });
  const [own, setOwn] = useState<{ A: string; B: string } | null>(null);      // typed expressions, once edited
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const p = presets.find((x) => x.id === preset);
  const expr = own ?? { A: fill(p, col.A), B: fill(p, col.B) };
  const shownName = name || (p && (col.A || col.B) ? `${(col.A || col.B).toLowerCase()}_${p.id}` : "");
  const pickA = (a: string) => {
    const partner = s.specs.find((x) => x.a_src === a)?.b_src;
    setCol({ A: a, B: partner ?? col.B }); setOwn(null);
  };
  const add = async () => {
    try {
      await send.mutateAsync({ path: "/derived", body: { name: shownName.trim(), a: expr.A, b: expr.B } });
      qc.invalidateQueries({ queryKey: ["sources"] });
      onClose();
    } catch (e) { setErr(errorText(e)); }
  };
  return (
    <div className="panel add-col" role="region" aria-label="Add a column">
      <div className="panel-head">
        <h3>Add a column</h3>
        <span className="sub">made from an expression on each side, then paired and compared like any other - DuckDB SQL on the file's columns</span>
      </div>
      <div className="panel-body add-col-body">
        <label className="field">
          <span className="lbl">Made as</span>
          <select value={preset} onChange={(e) => { setPreset(e.target.value); setOwn(null); }}>
            {presets.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
            <option value="">my own expression</option>
          </select>
        </label>
        <label className="field">
          <span className="lbl">Column name</span>
          <input value={shownName} onChange={(e) => setName(e.target.value)} placeholder="trade_date" />
        </label>
        {(["A", "B"] as const).map((w, i) => (
          <div className="add-col-side" key={w}>
            <span className="lbl"><span className={`sw ${w.toLowerCase()}`} aria-hidden="true" />{[NA, NB][i]}</span>
            {p && (
              <label className="field">
                <span className="lbl">from</span>
                <select aria-label={`${[NA, NB][i]} column`} value={col[w]}
                  onChange={(e) => (w === "A" ? pickA(e.target.value) : (setCol({ ...col, B: e.target.value }), setOwn(null)))}>
                  <option value="">none - {[NA, NB][i]} gets no such column</option>
                  {s.columns[w].map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            )}
            <label className="field grow">
              <span className="lbl">Expression on {[NA, NB][i]}</span>
              <input className="m" value={expr[w]} placeholder={`blank - ${[NA, NB][i]} gets no such column`}
                onChange={(e) => setOwn({ ...expr, [w]: e.target.value })} />
            </label>
          </div>
        ))}
        {err && <div className="note error" role="alert">{marks(err)}</div>}
        <div className="add-col-foot">
          <Button variant="primary" disabled={send.isPending || !shownName.trim() || !(expr.A.trim() || expr.B.trim())} onClick={() => void add()}>
            {send.isPending ? "Checking…" : "Add column"}
          </Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </div>
  );
}

/** The columns added so far, each with what it is made of on each side and Remove. */
export function AddedColumns({ s }: { s: SetupReady }) {
  const send = useSetupSend();
  const qc = useQueryClient();
  const [NA, NB] = sideLabels(s.names[0], s.names[1]);
  if (!s.derived?.length) return null;
  return (
    <div className="added-cols" role="list" aria-label="Added columns">
      <span className="lbl">Added columns</span>
      {s.derived.map((d) => (
        <span className="added-col" role="listitem" key={d.name}>
          <strong>{d.name}</strong>
          {d.a && <span className="m" title={`${NA}: ${d.a}`}><span className="sw a" aria-hidden="true" />{d.a}</span>}
          {d.b && <span className="m" title={`${NB}: ${d.b}`}><span className="sw b" aria-hidden="true" />{d.b}</span>}
          <LinkButton disabled={send.isPending} aria-label={`Remove ${d.name}`}
            onClick={() => send.mutate({ method: "DELETE", path: `/derived/${encodeURIComponent(d.name)}` },
                                       { onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }) })}>remove</LinkButton>
        </span>
      ))}
    </div>
  );
}
