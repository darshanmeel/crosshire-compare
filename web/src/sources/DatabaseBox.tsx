// web/src/sources/DatabaseBox.tsx - a database side (screen 03): connection + Manage, a table or a SQL
// query; the fetch cap sits under Advanced (FetchCap). The fetch is a job that writes Parquet; the
// card's one Load button fetches first when nothing is held for the boxes, then reads that Parquet.
import { useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText, type LogEntry } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import { useConnections } from "../connections/ConnectionsManager";
import { setView } from "../shell/view";
import { Button, ErrorNote, num } from "../ui/kit";
import { useSideForm } from "./formStore";
import { RadioSeg } from "./SourceChoice";
import { dbOf, type DbPlan, type Tag } from "./types";

const manage = () => setView({ drawer: "connections" });

/** What a database side needs, for its box and for the card's Load: the connections, the plan the
 *  boxes make, the fetch job and its errors. `on` is false while the side reads a file - nothing is
 *  asked then and the form is left alone. `onFetched` runs when a fetch ends done. */
export function useDbSide(tag: Tag, on: boolean, onFetched: () => void) {
  const qc = useQueryClient();
  const [f, set] = useSideForm(tag);
  const conns = useConnections(on);
  const rows = on && Array.isArray(conns.data) ? conns.data : [];
  const dbRows = rows.filter((r) => !r.is_folder).sort((x, y) => x.name.localeCompare(y.name));   // a folder is picked under Path on disk
  const name = dbRows.some((r) => r.name === f.connection) ? f.connection : dbRows[0]?.name ?? "";
  useEffect(() => { if (on && name && name !== f.connection) set({ connection: name, password: "" }); }, [on, name]);
  const d = { ...dbOf(f), connection: name };
  const plan = useQuery({ queryKey: ["db", tag, d], enabled: on && !!name,
                          queryFn: () => api.send<DbPlan>("POST", `/api/sources/${tag}/db`, d) });
  const [err, setErr] = useState("");
  const fail = (e: unknown) => setErr(errorText(e));
  const refresh = () => ["db", "sources", "connections"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const then = useRef(onFetched);
  then.current = onFetched;
  const start = useMutation({
    mutationFn: () => api.send<LogEntry>("POST", `/api/sources/${tag}/fetch`, { ...d, password: f.password || null }),
    onSuccess: (e) => { setErr(""); follow(e.id); set({ password: "" }); qc.invalidateQueries({ queryKey: ["log"] }); },
    onError: fail,
  });
  const { follow, busy, running } = useJobOfKind("Fetch", tag === "P" ? "Profiling" : "Compare", tag, (e) => {
    if (e.state === "error") {
      const line = e.lines.at(-1) ?? e.label;
      setErr(/password|authenticat|login/i.test(line) ? `${line} - Type the password again.` : line);
    }
    refresh();
    if (e.state === "done") then.current();
  });
  const forget = useMutation({     // the server drops the typed password; the box then asks for one again
    mutationFn: () => api.send("DELETE", `/api/connections/${encodeURIComponent(name)}/password`),
    onSuccess: () => { set({ password: "" }); setErr(""); refresh(); },
    onError: fail,
  });
  const again = useMutation({ mutationFn: () => api.send("DELETE", `/api/sources/${tag}/fetch`), onSuccess: refresh, onError: fail });
  const fetching = busy || start.isPending;
  return { conns, dbRows, name, plan: plan.data, err, start, forget, again, fetching,
           line: fetching ? (running?.lines.at(-1) ?? "Fetching…") : "" };
}
export type DbSide = ReturnType<typeof useDbSide>;

/** Under Advanced on a database side: the most rows a fetch reads, and the warning a cap can bring. */
export function FetchCap({ tag, db }: { tag: Tag; db: DbSide }) {
  const id = useId();
  const [f, set] = useSideForm(tag);
  return <>
    <span className="row" title="The most rows the fetch reads from the database - 0 reads them all.">
      <label className="lbl" htmlFor={`${id}-cap`}>Fetch at most</label>
      <input id={`${id}-cap`} type="number" className="in mono cap" aria-label="Fetch at most (0 = all)" min={0} max={1_000_000_000} step={100_000}
             value={f.cap} onChange={(e) => set({ cap: Math.max(0, Number(e.target.value) || 0) })} />
      <span className="caption">{f.cap ? "rows" : "all rows"}</span>
    </span>
    {db.plan?.warning && !db.plan.held && <div className="note warning">{db.plan.warning}</div>}
  </>;
}

export function DatabaseBox({ tag, db }: { tag: Tag; db: DbSide }) {
  const id = useId();
  const [f, set] = useSideForm(tag);
  const [a] = useSideForm("A");
  const { dbRows, name, err, forget, again } = db;
  const p = db.plan;

  if (db.conns.error) return <ErrorNote>{(db.conns.error as Error).message}</ErrorNote>;
  if (!dbRows.length)
    return (
      <div className="row db-empty">
        <span className="caption">No database connections yet - add one, or import a connections file.</span>
        <Button icon="plug" onClick={manage}>Manage</Button>
      </div>
    );
  const conn = dbRows.find((r) => r.name === name)!;
  return (
    <div className="dbbox">
      <div className="row">
        <label className="lbl w" htmlFor={`${id}-conn`}>Conn.</label>
        <select id={`${id}-conn`} className="in mono grow" aria-label="Connection" value={name}
                onChange={(e) => set({ connection: e.target.value, password: "" })}>
          {dbRows.map((r) => <option key={r.name} value={r.name}>{r.name} · {r.label} · {r.where}</option>)}
        </select>
        <Button icon="plug" onClick={manage} aria-label="Manage connections">Manage</Button>
      </div>
      {p?.password === "asked" && (
        <div className="row">
          <label className="lbl w" htmlFor={`${id}-pw`}>{conn.kind === "snowflake" ? "Key" : "Pass."}</label>
          <input id={`${id}-pw`} type="password" className="in grow" aria-label="Password" value={f.password}
                 placeholder={conn.kind === "snowflake" ? "password or private key - this session only" : "kept for this session only"}
                 onChange={(e) => set({ password: e.target.value })} />
        </div>
      )}
      {p?.password === "held" && (
        <div className="row">
          <span className="caption">Password held for this session</span>
          <Button size="sm" onClick={() => forget.mutate()} disabled={forget.isPending}>Change password</Button>
        </div>
      )}
      <div className="row">
        <span className="lbl w">Read</span>
        <RadioSeg name={`dbmode_${tag}`} label="Read" value={f.db_mode} onChange={(v) => set({ db_mode: v })}
                  options={[["table", "A table"], ["sql", "SQL query"]]} />
        {f.db_mode === "table" && <>
          <label className="lbl" htmlFor={`${id}-table`}>Table</label>
          <input id={`${id}-table`} type="text" className="in mono grow" aria-label="Table" placeholder="schema.table - hr.employees"
                 value={f.table} onChange={(e) => set({ table: e.target.value })} />
        </>}
        {tag === "B" && a.how === "database" && (
          <Button size="sm" title="Copy the connection, the table or SQL and the cap from side A."
                  onClick={() => set({ connection: a.connection, db_mode: a.db_mode, table: a.table, sql: a.sql, cap: a.cap, password: "" })}>
            Same SQL as A
          </Button>
        )}
      </div>
      {f.db_mode === "sql" && (
        <label className="field"><span className="lbl">SQL - SELECT or WITH only</span>
          <textarea className="in mono" aria-label="SQL" rows={5} value={f.sql} onChange={(e) => set({ sql: e.target.value })}
                    placeholder={"SELECT emp_id, first_name, department, hire_date\nFROM hr.employees\nWHERE hire_date >= '2026-01-01'"} />
        </label>
      )}
      {p?.error && <ErrorNote>{p.error}</ErrorNote>}
      {p?.held && (
        <div className="row">
          <span className="caption">Fetched at {p.held.at} - {num(p.held.rows)} rows{p.held.capped ? " · capped" : ""}</span>
          <Button size="sm" icon="refresh" onClick={() => again.mutate()}>Fetch again</Button>
        </div>
      )}
      {err && <ErrorNote>{err}</ErrorNote>}
    </div>
  );
}
