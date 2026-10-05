// web/src/columns/useColumnCalls.ts - the writes the Columns section makes, and the last refusal.
import { useState } from "react";
import { errorText, useSetupSend, type Editable, type SetupReady } from "../setup/api";
import { roleWrites, type Role } from "./pairing";

export function useColumnCalls(s: SetupReady) {
  const send = useSetupSend();
  const [err, setErr] = useState("");
  const call = (path: string, method: "POST" | "DELETE" = "POST", body?: unknown) =>
    send.mutate({ method, path, body }, { onSuccess: () => setErr(""), onError: (e) => setErr(errorText(e)) });
  /** One cell of the table, with the version of the table the page holds. */
  const edit = (row: number, column: Editable, value: string | boolean) => call("/cell", "POST", { rev: s.rev, row, column, value });
  /** Key / Compare / Skip: one or two tick writes, the second with the version the first answered. */
  const setRole = async (row: number, to: Role) => {
    let rev = s.rev;
    try {
      for (const [column, value] of roleWrites(s.rows[row], to)) {
        const v = await send.mutateAsync({ path: "/cell", body: { rev, row, column, value } });
        if (v.ready) rev = v.rev;
      }
      setErr("");
    } catch (e) { setErr(errorText(e)); }
  };
  const pending = send.isPending ? send.variables?.path ?? "" : null;
  return { call, edit, setRole, err, busy: send.isPending, pending };
}
export type ColumnCalls = ReturnType<typeof useColumnCalls>;
