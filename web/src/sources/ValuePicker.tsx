// web/src/sources/ValuePicker.tsx - "Pick from values" beside a filter's Value box: the column's own
// values with their row counts (over the whole loaded side), searched on the server. One value
// fills the box; for "in" each value is ticked and shows as a chip the clause takes.
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { Icon } from "../ui/icons";
import { ErrorNote, num } from "../ui/kit";
import type { Tag } from "./types";
import { useSources } from "./useSources";
import type { QuickClause } from "./useQuickClause";
import "./sources.css";

export type ColumnValues = { column: string; rows: number; distinct: number; values: { value: string | null; n: number }[]; more: boolean };
export const VALUES_LIMIT = 200;

/** The button and its panel. Not offered for is null / is not null; waits for the side to be loaded.
 *  `stale`: the card now points at another file than the one loaded - its values would mislead. */
export function ValuePicker({ tag, q, stale = false }: { tag: Tag; q: QuickClause; stale?: boolean }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null), btn = useRef<HTMLButtonElement>(null);
  const loaded = !!useSources().data?.sides?.[tag]?.loaded;
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    addEventListener("mousedown", away);
    return () => removeEventListener("mousedown", away);
  }, [open]);
  if (q.noValue || !q.col) return null;
  const close = () => { setOpen(false); btn.current?.focus(); };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape" && open) { e.stopPropagation(); close(); }       // only this panel, not the one around it
  };
  const left = (e: FocusEvent) => { if (!box.current?.contains(e.relatedTarget as Node)) setOpen(false); };   // tabbed past it
  const off = !loaded || stale;
  return (
    <div className="menu vpick" ref={box} onKeyDown={keys} onBlur={left}>
      <button ref={btn} type="button" className="btn vpick-btn" aria-label="Pick from values" aria-expanded={open} aria-controls={id}
              disabled={off} title={!loaded ? "Load this side to pick from its values"
                : stale ? "Load this side again to pick from its values" : `Pick from the values of ${q.col}`}
              onClick={() => setOpen(!open)}>
        <Icon name="bars" />Pick
      </button>
      {open && !off && <ValueList id={id} tag={tag} q={q} onDone={close} />}
    </div>
  );
}

function ValueList({ id, tag, q, onDone }: { id: string; tag: Tag; q: QuickClause; onDone: () => void }) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => { const t = setTimeout(() => setSearch(text.trim()), 250); return () => clearTimeout(t); }, [text]);
  const list = useRef<HTMLUListElement>(null);
  const many = q.isIn;
  const v = useSources().data?.sides?.[tag];
  const got = useQuery({
    queryKey: ["values", tag, `${v?.origin}|${v?.label}|${v?.sheet}|${v?.cell_range}|${v?.skip_rows}|${v?.quote}|${v?.bad_rows}|${v?.rows}`, q.col, search],
    queryFn: () => api.get<ColumnValues>(`/api/sources/${tag}/values?${new URLSearchParams({ column: q.col, search, limit: String(VALUES_LIMIT) })}`),
    placeholderData: keepPreviousData,
  });
  const d = got.data;
  const nullOk = q.op === "=" || q.op === "!=";
  /** Up and Down walk the list; Down from the search box enters it. */
  const walk = (e: KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(list.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)") ?? []);
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = items[at < 0 ? 0 : at + (e.key === "ArrowDown" ? 1 : -1)];
    if (next) { e.preventDefault(); next.focus(); }
  };
  return (
    <div className="menu-pop vpick-pop" id={id} role="dialog" aria-label={`Values of ${q.col}`} tabIndex={-1} onKeyDown={walk}>
      <input type="search" className="in" aria-label="Search values" placeholder={`Search ${q.col}…`} autoFocus
             value={text} onChange={(e) => setText(e.target.value)} />
      <p className="caption" aria-live="polite">
        {got.isPending || got.isPlaceholderData ? "Reading the values…"
          : d && (d.more ? `showing ${num(d.values.length)} of ${num(d.distinct)} - type to search`
                         : `${num(d.distinct)} ${d.distinct === 1 ? "value" : "values"}${search ? ` with "${search}"` : ` in ${num(d.rows)} rows`}`)}
      </p>
      {got.isError && <ErrorNote>{errorText(got.error)}</ErrorNote>}
      {d && d.values.length > 0 && (
        <ul className="vpick-list" ref={list} aria-label={many ? "Values to keep" : "Values"}>
          {d.values.map(({ value, n }) => {
            const shown = value === null ? <em>null</em> : value === "" ? <em>empty</em> : value;
            const count = <span className="vpick-n">{num(n)}</span>;
            if (many) {
              return (
                <li key={value ?? "\u0000null"}>
                  <label className="vpick-item" title={value === null ? "Use the condition is null" : undefined}>
                    <input type="checkbox" disabled={value === null} checked={value !== null && q.chips.includes(value)}
                           onChange={() => value !== null && q.toggle(value)} />
                    <span className="vpick-v">{shown}</span>{" "}{count}
                  </label>
                </li>
              );
            }
            const off = value === null && !nullOk;
            return (
              <li key={value ?? "\u0000null"}>
                <button type="button" className="vpick-item" disabled={off}
                        title={value === null ? (off ? "Use the condition is null" : `Becomes ${q.op === "=" ? "is null" : "is not null"}`) : undefined}
                        onClick={() => { q.pick(value); onDone(); }}>
                  <span className="vpick-v">{shown}</span>{" "}{count}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {many && <div className="row"><button type="button" className="btn sm" onClick={onDone}>Done</button>
        <span className="caption">{num(q.chips.length)} picked</span></div>}
    </div>
  );
}

/** The values ticked for "in", each with its remove button. */
export function PickedChips({ q }: { q: QuickClause }) {
  if (!q.isIn || !q.chips.length) return null;
  return (
    <ul className="chips vpick-chips" aria-label="Picked values">
      {q.chips.map((v) => (
        <li key={v} className="chip">{v === "" ? <em>empty</em> : v}
          <button type="button" className="chip-x" aria-label={`Remove ${v}`} onClick={() => q.toggle(v)}><Icon name="x" size="sm" /></button>
        </li>
      ))}
    </ul>
  );
}
