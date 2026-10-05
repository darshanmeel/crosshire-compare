// web/src/columns/ColumnTable.tsx - the pairing board (SPEC §04): one row per pair, then the columns one
// side alone has, muted, at the bottom (the server sorts them so). Every control writes one cell of
// the column table (POST /api/setup/cell); the server makes the table whole again and sends it back.
import { useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Editable, Row, SetupReady } from "../setup/api";
import { setView } from "../shell/view";
import { Icon } from "../ui/icons";
import { LinkButton, Seg } from "../ui/kit";
import { caseText, isText, originOf, paired, roleOf, specIndex, stepsLine, type Role } from "./pairing";

/** Past this many rows only the rows in sight are drawn - a pair of wide files has hundreds. */
export const VIRTUAL_FROM = 200;
const ROW_PX = 47;           // 46 px row + its border
const COLS = 9;

const HELP = {
  role: "Key: what identifies a row. Compare: check its values. Skip: leave it out - a column one side alone has is always skipped.",
  type: "The type both sides are converted to before comparing. number: 100.00 = 100 · date: 27/08/2026 = 2026-08-27 · timestamp keeps the time · boolean: 1 = yes = true.",
  steps: "Steps that change a side's values before comparing - open one to edit it.",
  matched: "How the pair was made: by the same name, a similar name, the values (a guess - check it) or by you.",
  case: "Text pairs: ignore or exact case; default follows the Ignore case in values switch.",
};

type Edit = (row: number, column: Editable, value: string | boolean) => void;

/** The Common name box: typed freely, sent when the box is left or Enter is pressed. */
function NameCell({ value, label, disabled, onDone }: { value: string; label: string; disabled: boolean; onDone: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [was, setWas] = useState(value);
  if (value !== was) { setWas(value); setDraft(value); }        // the server renamed it (made it unique)
  const done = () => { if (draft.trim() !== value) onDone(draft.trim()); };
  return <input type="text" className="in mono" aria-label={label} value={draft} disabled={disabled}
                onChange={(e) => setDraft(e.target.value)} onBlur={done}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />;
}

/** What DuckDB read a column as and what its values look like - the select's tooltip. */
const sniffed = (detected: string, looks: string) =>
  [detected && `detected ${detected}`, looks && `looks like ${looks}`].filter(Boolean).join(" · ") || undefined;

function ColumnPick({ side, row, i, s, busy, edit }: { side: "A" | "B"; row: Row; i: number; s: SetupReady; busy: boolean; edit: Edit }) {
  const key = side === "A" ? "A column" : "B column";
  const value = row[key];
  const name = side === "A" ? s.names[0] : s.names[1];
  return (
    <select className={value ? `sel ${side.toLowerCase()}` : "sel none"} aria-label={`${name} column, row ${i + 1}`} value={value}
            disabled={busy} title={sniffed(row[`${side} detected`], row[`${side} looks like`])}
            onChange={(e) => edit(i, key, e.target.value)}>
      {["", ...s.columns[side]].map((o) => <option key={o} value={o}>{o || "no partner"}</option>)}
    </select>
  );
}

function Detail({ row, i, s, busy, edit }: { row: Row; i: number; s: SetupReady; busy: boolean; edit: Edit }) {
  const [NA, NB] = s.names;
  const side = (k: "A" | "B", name: string) => row[`${k} column`] && (
    <div className="cols-sniff">
      <span className="lbl">{name}</span>
      <span>detected <code>{row[`${k} detected`] || "-"}</code></span>
      <span title={s.looks_help}>looks like <code>{row[`${k} looks like`] || "-"}</code></span>
    </div>
  );
  return (
    <tr className="cols-detail">
      <td colSpan={COLS}>
        <div className="cols-detail-body">
          <label className="field cols-name">
            <span className="lbl">Common name</span>
            <NameCell value={row["Common name"]} label={`Common name, row ${i + 1}`} disabled={busy}
                      onDone={(v) => edit(i, "Common name", v)} />
          </label>
          {side("A", NA)}
          {side("B", NB)}
        </div>
      </td>
    </tr>
  );
}

function PairRow({ row, i, s, busy, edit, setRole, open, toggle }: {
  row: Row; i: number; s: SetupReady; busy: boolean; edit: Edit; setRole: (i: number, r: Role) => void; open: boolean; toggle: () => void;
}) {
  const both = paired(row);
  const o = originOf(row, s.names);
  const si = specIndex(s, row);
  const steps = stepsLine(s.specs[si]);
  const role = roleOf(row);
  return (
    <tr className={both ? (role === "key" ? "cols-key" : undefined) : "muted"}>
      <td>
        <Seg mini label={`Role, row ${i + 1}`} value={role} onChange={(v) => setRole(i, v)}
             options={[{ label: "Key", value: "key", disabled: busy || !both }, { label: "Compare", value: "compare", disabled: busy || !both },
                       { label: "Skip", value: "skip", disabled: busy || !both }]} />
      </td>
      <td><ColumnPick side="A" row={row} i={i} s={s} busy={busy} edit={edit} /></td>
      <td className="swap"><Icon name="swap" size="sm" /></td>
      <td><ColumnPick side="B" row={row} i={i} s={s} busy={busy} edit={edit} /></td>
      <td>
        <select className="sel type" aria-label={`Type, row ${i + 1}`} value={row.Type} disabled={busy}
                onChange={(e) => edit(i, "Type", e.target.value)}>
          {s.types.map((t) => <option key={t}>{t}</option>)}
        </select>
      </td>
      <td className="cols-steps">
        {both && si >= 0 && (steps
          ? <button type="button" className="cols-steps-link" title={steps} onClick={() => setView({ view: "values", pair: si })}
                    aria-label={`Steps for ${row["Common name"]}: ${steps}`}>{steps}</button>
          : <LinkButton className="cols-add" onClick={() => setView({ view: "values", pair: si })} aria-label={`Add a step to ${row["Common name"]}`}>+ Add</LinkButton>)}
      </td>
      <td className={o.tone ? `cols-origin ${o.tone}` : "cols-origin dim"} title={o.title}>{o.text}</td>
      <td className="dim">
        {both && isText(row)
          ? <select className="sel type" aria-label={`Case, row ${i + 1}`} value={row.Case} disabled={busy}
                    onChange={(e) => edit(i, "Case", e.target.value)}>
              {s.cases.map((x) => <option key={x} value={x}>{caseText(x, s.settings.ignore_case)}</option>)}
            </select>
          : "—"}
      </td>
      <td className="cols-more-cell">
        <button type="button" className={open ? "cols-more open" : "cols-more"} aria-expanded={open}
                aria-label={`More on row ${i + 1}: common name and detected types`} onClick={toggle}>
          <Icon name="chevron" size="sm" />
        </button>
      </td>
    </tr>
  );
}

/** The pairing board: every column from either file, a row a pair or a column on one side alone. */
export function ColumnTable({ s, busy, edit, setRole }: { s: SetupReady; busy: boolean; edit: Edit; setRole: (i: number, r: Role) => void }) {
  const [NA, NB] = s.names;
  const box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const keyOf = (r: Row) => `${r["A column"]}\u0000${r["B column"]}`;
  const virtual = s.rows.length >= VIRTUAL_FROM;
  const v = useVirtualizer({ count: s.rows.length, getScrollElement: () => box.current, estimateSize: () => ROW_PX,
                             overscan: 12, enabled: virtual });
  const items = virtual ? v.getVirtualItems() : null;
  const shown = items ? items.map((it) => it.index) : s.rows.map((_, i) => i);
  const top = items?.length ? items[0].start : 0;
  const bottom = items?.length ? v.getTotalSize() - items[items.length - 1].end : 0;
  const tall = s.rows.length > 13;
  return (
    <div className={tall ? "tblwrap cols-wrap tall" : "tblwrap cols-wrap"} ref={box} aria-busy={busy}>
      <table className="tbl cols-tbl" aria-label="Column table">
        <thead><tr>
          <th className="w-role" title={HELP.role}>Role</th>
          <th className="w-col"><span className="sw a" />{NA} column</th>
          <th className="w-swap"><span className="sr-only">pairs with</span></th>
          <th className="w-col"><span className="sw b" />{NB} column</th>
          <th className="w-type" title={HELP.type}>Read as</th>
          <th title={HELP.steps}>Transform</th>
          <th className="w-origin" title={HELP.matched}>Matched by</th>
          <th className="w-case" title={HELP.case}>Case</th>
          <th className="w-more"><span className="sr-only">More</span></th>
        </tr></thead>
        {top > 0 && <tbody><tr style={{ height: top }} /></tbody>}
        {shown.map((i) => {
          const row = s.rows[i];
          const k = keyOf(row);
          const isOpen = open.has(k);
          const toggle = () => setOpen((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n; });
          return (
            <tbody key={k + i} data-index={i} ref={virtual ? v.measureElement : undefined}>
              <PairRow row={row} i={i} s={s} busy={busy} edit={edit} setRole={setRole} open={isOpen} toggle={toggle} />
              {isOpen && <Detail row={row} i={i} s={s} busy={busy} edit={edit} />}
            </tbody>
          );
        })}
        {bottom > 0 && <tbody><tr style={{ height: bottom }} /></tbody>}
      </table>
    </div>
  );
}
