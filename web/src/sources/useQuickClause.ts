// web/src/sources/useQuickClause.ts - the Column / Condition / Value builder that both "Rows to read"
// editors share: the three picks and the call that adds them to the side's WHERE.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSideForm } from "./formStore";
import type { Tag } from "./types";

const NULL_OPS = ["is null", "is not null"];

/** The picks, and `add`, which puts them on the side's WHERE and empties Value once it worked. */
export function useQuickClause(tag: Tag, cols: string[], onError?: (e: unknown) => void) {
  const [f, set] = useSideForm(tag);
  const [picked, setCol] = useState("");
  const [op, setOp] = useState("=");
  const [value, setValue] = useState("");
  const col = cols.includes(picked) ? picked : cols[0] ?? "";
  const add = useMutation({
    mutationFn: () => api.send<{ where: string }>("POST", "/api/sources/quick-clause", { column: col, op, value, where: f.where }),
    onSuccess: (r) => { set({ where: r.where }); setValue(""); },
    onError,
  });
  return { col, setCol, op, setOp, value, setValue, add, noValue: NULL_OPS.includes(op) };
}
