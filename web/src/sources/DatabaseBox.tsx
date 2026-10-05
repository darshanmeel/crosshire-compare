// web/src/sources/DatabaseBox.tsx - a database side (screen 03): connection + Manage, a table or a SQL
// query, the fetch cap. The fetch is a job that writes Parquet; Load then reads that Parquet.
import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type LogEntry, type Meta } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import { useConnections } from "../connections/ConnectionsManager";
import { setView } from "../shell/view";
import { Button, num } from "../ui/kit";
import { useSideForm } from "./formStore";
import { RadioSeg } from "./SourceChoice";
import { dbOf, type DbPlan, type Tag } from "./types";

const manage = () => setView({ drawer: "connections" });

export function DatabaseBox({ tag }: { tag: Tag; meta: Meta }) {
  const id = useId();
  const qc = useQueryClient();
  const [f, set] = useSideForm(tag);
  const [a] = useSideForm("A");
  const { data: rows = [], error } = useConnections();
  const dbRows = rows.filter((r) => !r.is_folder).sort((x, y) => x.name.localeCompare(y.name));   // a folder is picked under Path on disk
  const name = dbRows.some((r) => r.name === f.connection) ? f.connection : dbRows[0]?.name ?? "";
  useEffect(() => { if (name && name !== f.connection) set({ connection: name, password: "" }); }, [name]);
  const d = { ...dbOf(f), connection: name };
  const plan = useQuery({ queryKey: ["db", tag, d], enabled: !!name,
                          queryFn: () => api.send<DbPlan>("POST", `/api/sources/${tag}/db`, d) });
  const [err, setErr] = useState("");
  const fail = (e: unknown) => setErr(e instanceof ApiError ? e.detail : String(e));
  const refresh = () => ["db", "sources", "connections"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
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
  });
  const forget = useMutation({     // the server drops the typed password; the box then asks for one again
    mutationFn: () => api.send("DELETE", `/api/connections/${encodeURIComponent(name)}/password`),
    onSuccess: () => { set({ password: "" }); setErr(""); refresh(); },
    onError: fail,
  });
  const again = useMutation({ mutationFn: () => api.send("DELETE", `/api/sources/${tag}/fetch`), onSuccess: refresh, onError: fail });

  if (error) return <div className="note error">{(error as Error).message}</div>;
  if (!dbRows.length)
    return (
      <div className="row db-empty">
        <span className="caption">No database connections yet - add one, or import a connections file.</span>
        <Button icon="plug" onClick={manage}>Manage</Button>
      </div>
    );
  const conn = dbRows.find((r) => r.name === name)!;
  const p = plan.data;
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
      </div>
      {f.db_mode === "sql" && (
        <label className="field"><span className="lbl">SQL - SELECT or WITH only</span>
          <textarea className="in mono" aria-label="SQL" rows={5} value={f.sql} onChange={(e) => set({ sql: e.target.value })}
                    placeholder={"SELECT emp_id, first_name, department, hire_date\nFROM hr.employees\nWHERE hire_date >= '2026-01-01'"} />
        </label>
      )}
      <div className="row spread">
        <span className="row" title="The most rows the fetch reads from the database - 0 reads them all.">
          <label className="lbl" htmlFor={`${id}-cap`}>Fetch at most</label>
          <input id={`${id}-cap`} type="number" className="in mono cap" aria-label="Fetch at most (0 = all)" min={0} max={1_000_000_000} step={100_000}
                 value={f.cap} onChange={(e) => set({ cap: Math.max(0, Number(e.target.value) || 0) })} />
          <span className="caption">{f.cap ? "rows" : "all rows"}</span>
        </span>
        {tag === "B" && a.how === "database" && (
          <Button size="sm" title="Copy the connection, the table or SQL and the cap from side A."
                  onClick={() => set({ connection: a.connection, db_mode: a.db_mode, table: a.table, sql: a.sql, cap: a.cap, password: "" })}>
            Same SQL as A
          </Button>
        )}
      </div>
      {p?.error && <div className="note error">{p.error}</div>}
      {p?.held ? (
        <div className="row">
          <span className="caption">Fetched at {p.held.at} - {num(p.held.rows)} rows{p.held.capped ? " · capped" : ""}</span>
          <Button size="sm" icon="refresh" onClick={() => again.mutate()}>Fetch again</Button>
        </div>
      ) : <>
        {p?.warning && <div className="note warning">{p.warning}</div>}
        <div className="row">
          <Button icon="db" disabled={!p?.sql || busy || start.isPending} onClick={() => start.mutate()}>
            {busy ? (running?.lines.at(-1) ?? "Fetching…") : tag === "P" ? "Fetch" : `Fetch ${tag}`}
          </Button>
          <span className="caption">then Load reads what was fetched</span>
        </div>
      </>}
      {err && <div className="note error">{err}</div>}
    </div>
  );
}
