// web/src/sources/useQuickClause.ts - the Column / Condition / Value builder that both "Rows to read"
// editors share: the three picks, the values picked from the column's own, and the call that adds
// them to the side's WHERE.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSideForm } from "./formStore";
import type { Tag } from "./types";

const NULL_OPS = ["is null", "is not null"];

/** The picks, and `add`, which puts them on the side's WHERE and empties Value once it worked.
 *  `chips` are the values ticked for "in"; `picked` is the value a pick put in the box - sent as it
 *  is (spaces and all) while the box still holds it. */
export function useQuickClause(tag: Tag, cols: string[], onError?: (e: unknown) => void) {
  const [f, set] = useSideForm(tag);
  const [chosen, setChosen] = useState("");
  const [op, setOp] = useState("=");
  const [value, setValue] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [ticked, setTicked] = useState<{ col: string; list: string[] }>({ col: "", list: [] });
  const col = cols.includes(chosen) ? chosen : cols[0] ?? "";
  const isIn = op.startsWith("in");
  const chips = ticked.col === col ? ticked.list : [];                 // another column's values are not this one's
  const setChips = (list: string[]) => setTicked({ col, list });
  const setCol = (c: string) => { setChosen(c); setTicked({ col: c, list: [] }); };
  const changeOp = (o: string) => { setOp(o); setChips([]); setPicked(null); };
  /** A value from the list: into the box - or, null, the condition becomes is null / is not null. */
  const pick = (v: string | null) => {
    if (v === null) { setOp(op === "!=" ? "is not null" : "is null"); setValue(""); return; }
    setValue(v); setPicked(v);
  };
  const toggle = (v: string) => setChips(chips.includes(v) ? chips.filter((x) => x !== v) : [...chips, v]);
  const values = isIn ? (chips.length ? chips : undefined) : picked !== null && picked === value ? [value] : undefined;
  const add = useMutation({
    mutationFn: () => api.send<{ where: string }>("POST", "/api/sources/quick-clause",
                                                    { column: col, op, value, where: f.where, ...(values ? { values } : {}) }),
    onSuccess: (r) => { set({ where: r.where }); setValue(""); setPicked(null); setChips([]); },
    onError,
  });
  const hint = isIn && chips.length ? "more values, comma separated (optional)" : "2026-07-20 · Finance · 100";   // Value's placeholder
  return { col, setCol, op, setOp: changeOp, value, setValue, add, noValue: NULL_OPS.includes(op), isIn, chips, toggle, pick, hint };
}

export type QuickClause = ReturnType<typeof useQuickClause>;
