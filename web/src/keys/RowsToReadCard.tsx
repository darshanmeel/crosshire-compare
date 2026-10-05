// web/src/keys/RowsToReadCard.tsx - one side's "Rows to read" card (SPEC §06): WHERE, a condition
// built from Column / Condition / Value, Order by (+ Descending), Top N, the rows the side holds, and
// Apply - which loads the side again with these options, the body the side card's Load sends - and
// Copy to the other side. What is typed lives in sources/formStore, so the side card sees it too.
import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { refreshSetup, useSetup } from "../setup/api";
import { getForm, setForm, useSideForm } from "../sources/formStore";
import { useSources } from "../sources/useSources";
import { pickOf, type SideView, type Tag } from "../sources/types";
import { Button, LinkButton, num, Pill, SideBadge } from "../ui/kit";
import { marks } from "../ui/marks";
import "./keys.css";

const NULL_OPS = ["is null", "is not null"];
const splitCols = (t: string) => t.split(",").map((c) => c.trim()).filter(Boolean);

/** The rows a side holds, as the pill says it. */
export function rowsPill(view?: SideView) {
  if (!view?.loaded) return <Pill tone="idle">not loaded</Pill>;
  return <Pill tone={view.rows === 0 ? "warn" : "ok"}>{num(view.rows ?? 0)} rows{view.cut ? " · cut" : ""}</Pill>;
}

export function RowsToReadCard({ tag }: { tag: "A" | "B" }) {
  const other: Tag = tag === "A" ? "B" : "A";
  const qc = useQueryClient();
  const id = useId();
  const [f, set] = useSideForm(tag);
  const { data: src } = useSources();
  const { data: setup } = useSetup();
  const view = src?.sides?.[tag];
  const otherView = src?.sides?.[other];
  const name = view?.name || f.name;
  const otherName = otherView?.name || other;
  const cols = view?.columns ?? [];
  const ops = src?.quick_ops ?? [];
  // Order by as typed: kept as a draft until it leaves the box, then a list of column names
  const [orderDraft, setOrderDraft] = useState(f.order_by.join(", "));
  const [orderWas, setOrderWas] = useState(f.order_by);
  if (orderWas !== f.order_by) { setOrderWas(f.order_by); setOrderDraft(f.order_by.join(", ")); }
  const unknown = splitCols(orderDraft).filter((c) => cols.length && !cols.includes(c));
  const [qc_, setQc] = useState("");
  const [qo, setQo] = useState("=");
  const [qv, setQv] = useState("");
  const col = cols.includes(qc_) ? qc_ : cols[0] ?? "";
  const [said, setSaid] = useState<{ warnings: string[]; error: string; done: boolean }>({ warnings: [], error: "", done: false });
  const clause = useMutation({
    mutationFn: () => api.send<{ where: string }>("POST", "/api/sources/quick-clause", { column: col, op: qo, value: qv, where: f.where }),
    onSuccess: (r) => { set({ where: r.where }); setQv(""); },
    onError: (e) => setSaid({ warnings: [], error: e instanceof ApiError ? e.detail : String(e), done: false }),
  });
  const apply = useMutation({
    mutationFn: () => {
      const g = getForm(tag);                      // as it is now - the order typed was just committed
      return api.send<{ side: SideView; warnings: string[] }>("POST", `/api/sources/${tag}/load`, {
        ...pickOf(g), name: g.name, where: g.where, order_by: g.order_by, desc: g.desc, limit: g.limit,
        column_names: g.column_names, snapshot: g.snapshot });
    },
    onSuccess: (r) => {
      setSaid({ warnings: r.warnings, error: "", done: true });
      qc.invalidateQueries({ queryKey: ["sources"] });
      qc.invalidateQueries({ queryKey: ["preview", tag] });
      refreshSetup(qc);
    },
    onError: (e) => setSaid({ warnings: [], error: e instanceof ApiError ? e.detail : String(e), done: false }),
  });
  const commitOrder = () => set({ order_by: splitCols(orderDraft) });
  /** The other side gets the same cut; the order's columns become their partners where the table pairs them. */
  const copy = () => {
    const rows = setup?.ready ? setup.rows : [];
    const mine = tag === "A" ? "A column" : "B column";
    const theirs = tag === "A" ? "B column" : "A column";
    const order = splitCols(orderDraft).map((c) => rows.find((r) => r[mine] === c)?.[theirs] || c);
    setForm(other, { where: f.where, order_by: order, desc: f.desc, limit: f.limit });
  };
  const side = tag.toLowerCase() as "a" | "b";
  return (
    <section className={`card rtr ${side}`} aria-label={`Rows to read from ${name}`}>
      <div className="card-head">
        <SideBadge side={tag} /><h3>{name}</h3><span className="grow" />{rowsPill(view)}
      </div>
      {view?.cut && <p className="caption rtr-cut">{view.cut}</p>}
      <div className="field">
        <label className="lbl" htmlFor={`${id}-w`}>Filter · WHERE</label>
        <textarea className="in mono" id={`${id}-w`} rows={3} value={f.where} onChange={(e) => set({ where: e.target.value })}
                  placeholder={cols[0] ? `e.g. ${cols[0]} IS NOT NULL AND hire_date >= '2026-07-20'` : "e.g. hire_date >= '2026-07-20'"} />
      </div>
      {cols.length > 0 && (
        <details className="rtr-build">
          <summary>Build a condition</summary>
          <div className="row">
            <select className="in mono" aria-label="Column" value={col} onChange={(e) => setQc(e.target.value)}>{cols.map((c) => <option key={c}>{c}</option>)}</select>
            <select className="in" aria-label="Condition" value={qo} onChange={(e) => setQo(e.target.value)}>{ops.map((o) => <option key={o}>{o}</option>)}</select>
            <input type="text" className="in mono grow" aria-label="Value" disabled={NULL_OPS.includes(qo)} placeholder="2026-07-20 · Finance · 100"
                   value={qv} onChange={(e) => setQv(e.target.value)} />
            <Button size="sm" icon="plus" disabled={clause.isPending} onClick={() => clause.mutate()}>Add to filter</Button>
          </div>
        </details>
      )}
      <div className="row spread rtr-order">
        <span className="field grow">
          <label className="lbl" htmlFor={`${id}-o`}>Order by</label>
          <input type="text" className="in mono" id={`${id}-o`} list={`${id}-cols`} placeholder={cols[0] ?? "a column"} value={orderDraft}
                 onChange={(e) => setOrderDraft(e.target.value)} onBlur={commitOrder}
                 onKeyDown={(e) => { if (e.key === "Enter") commitOrder(); }} />
          <datalist id={`${id}-cols`}>{cols.map((c) => <option key={c} value={c} />)}</datalist>
        </span>
        <label className="check rtr-desc"><input type="checkbox" checked={f.desc} disabled={!splitCols(orderDraft).length}
                                                onChange={(e) => set({ desc: e.target.checked })} />Descending</label>
        <span className="field">
          <label className="lbl" htmlFor={`${id}-n`}>Top N</label>
          <input type="number" className="in mono rtr-top" id={`${id}-n`} min={0} max={500_000_000} step={1000} placeholder="all"
                 title="Taken after the filter and the order, so 'order by date descending, top 100,000' is the latest 100,000 rows. Empty = all."
                 value={f.limit || ""} onChange={(e) => set({ limit: Math.max(0, Number(e.target.value) || 0) })} />
        </span>
      </div>
      {unknown.length > 0 && <p className="caption warn-text">{name} has no column {unknown.join(", ")} - the load will say so.</p>}
      {f.how === "database" && <p className="caption">On the fetched rows - to cut at the database, put a WHERE in the SQL.</p>}
      <div className="row">
        <Button disabled={!view?.loaded || apply.isPending} onClick={() => { commitOrder(); apply.mutate(); }}>
          {apply.isPending ? "Reading the rows…" : `Apply to ${name}`}
        </Button>
        <LinkButton onClick={copy}>Copy to {otherName}</LinkButton>
      </div>
      {said.error && <div className="note error">{marks(said.error)}</div>}
      {said.warnings.map((w, i) => <div key={i} className="note warning">{marks(w)}</div>)}
    </section>
  );
}
