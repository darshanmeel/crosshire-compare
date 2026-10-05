// The add / edit form inside the Connections drawer. Its boxes come from /api/meta `form` (the
// fields each driver needs); a secret goes in and never comes back - the server shows only a ${NAME}.
import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { Button, LinkButton, Seg } from "../ui/kit";
import { NEW, connBody, envName, refreshConnections, type ConnForm, type PwWhere, type Tested } from "./types";

type Said = { tone: "success" | "error"; text: string } | null;

export function ConnectionForm({ meta, pick, onDone, onTested }: {
  meta: Meta; pick: string; onDone: (name?: string) => void; onTested?: (name: string, r: Tested) => void;
}) {
  const f = meta.form;
  const id = useId();
  const kinds = Object.keys(meta.kinds);
  const editing = pick !== NEW;
  const qc = useQueryClient();
  const cur = useQuery({ queryKey: ["connection", pick], queryFn: () => api.get<ConnForm>(`/api/connections/${encodeURIComponent(pick)}`), enabled: editing });
  const [v, setV] = useState<Record<string, string>>({ kind: kinds[0] ?? "postgresql", name: "", timeout: String(f.default_timeout) });
  const [where, setWhere] = useState<PwWhere>("session");
  const [said, setSaid] = useState<Said>(null);

  const secret = (b: string) => b === "password" || f.secret_extras.includes(b);
  useEffect(() => {
    const c = cur.data;
    if (!c) return;
    const next: Record<string, string> = { kind: c.kind, name: c.name, host: c.host, port: c.port == null ? "" : String(c.port), database: c.database,
      schema: c.schema, user: c.user, password: c.password_ref, timeout: String(c.timeout), ...c.extra };
    setV(next);
    const refs = Object.entries(next).some(([k, x]) => secret(k) && envName(x));
    setWhere(refs ? "env" : c.save_password ? "file" : "session");
  }, [cur.data]);

  const kind = v.kind;
  const isFolder = kind === "folder";
  const boxes = [...(f.fields[kind] ?? []), ...(f.extras[kind] ?? [])];
  const plain = boxes.filter((b) => !secret(b));
  const secrets = boxes.filter(secret);
  const label = (b: string) => (b === "host" && f.host_label[kind]) || (b === "password" && f.password_label[kind]) || f.labels[b] || b;
  const set = (k: string, x: string) => setV((o) => ({ ...o, [k]: x }));
  const moveTo = (w: PwWhere) => {            // a secret typed is not a variable name, nor the other way round
    if ((w === "env") !== (where === "env")) setV((o) => ({ ...o, ...Object.fromEntries(secrets.map((b) => [b, ""])) }));
    setWhere(w);
  };

  const fail = (e: unknown) => setSaid({ tone: "error", text: e instanceof ApiError ? e.detail : String(e) });
  const name = (v.name ?? "").trim();
  const test = useMutation({
    mutationFn: () => api.send<Tested>("POST", "/api/connections/test", { ...connBody(f, v, where), name: name || "TEST" }),
    onSuccess: (r) => { setSaid({ tone: r.ok ? "success" : "error", text: r.message }); if (name) onTested?.(name, r); },
    onError: fail,
  });
  const save = useMutation({
    mutationFn: () => api.send("PUT", `/api/connections/${encodeURIComponent(name)}`, connBody(f, v, where)),
    onSuccess: () => { setSaid({ tone: "success", text: `Saved ${name}` }); refreshConnections(qc); onDone(name); },
    onError: fail,
  });
  const del = useMutation({
    mutationFn: () => api.send("DELETE", `/api/connections/${encodeURIComponent(pick)}`),
    onSuccess: () => { refreshConnections(qc); onDone(); }, onError: fail,
  });

  const field = (b: string) => {
    const env = secret(b) && where === "env";
    const value = env ? (envName(v[b]) ?? v[b] ?? "") : (v[b] ?? "");
    return (
      <div key={b} className="field">
        <label className="lbl" htmlFor={`${id}-${b}`}>{label(b)}</label>
        <input id={`${id}-${b}`} className={env || b !== "password" ? "in mono" : "in"}
               type={b === "port" ? "number" : secret(b) && !env ? "password" : "text"} autoComplete={secret(b) ? "off" : undefined}
               placeholder={env ? "variable name, e.g. PG_PASSWORD" : secret(b) && editing ? "unchanged" : b === "port" ? String(f.default_ports[kind] ?? "") : ""}
               value={value} onChange={(e) => set(b, env && e.target.value.trim() ? `\${${e.target.value.trim()}}` : e.target.value)} />
      </div>
    );
  };

  return (
    <form className="conn-form" aria-label={editing ? `Edit ${pick}` : "Add a connection"} onSubmit={(e) => { e.preventDefault(); if (name) save.mutate(); }}>
      <div className="row between">
        <h3>{editing ? <>Edit <span className="m">{pick}</span></> : "Add a connection"}</h3>
        {editing && <LinkButton icon="plus" onClick={() => onDone()}>New connection</LinkButton>}
      </div>
      <div className="field">
        <label className="lbl" htmlFor={`${id}-name`}>Name</label>
        <input id={`${id}-name`} className="in" type="text" placeholder="e.g. finance-postgres" value={v.name ?? ""} onChange={(e) => set("name", e.target.value)} />
      </div>
      <div className="field">
        <label className="lbl" htmlFor={`${id}-kind`}>Driver</label>
        <select id={`${id}-kind`} className="in" value={kind} onChange={(e) => set("kind", e.target.value)}>
          {kinds.map((k) => <option key={k} value={k}>{meta.kinds[k]}</option>)}
        </select>
      </div>
      {plain.map(field)}
      {!isFolder && secrets.length > 0 && (
        <div className="field">
          <span className="lbl">{secrets.includes("password") ? "Password" : "Secrets"} kept</span>
          <Seg label="Where the password lives" value={where} onChange={moveTo} options={[
            { label: "In the file", value: "file" },
            { label: "This session", value: "session" },
            { label: "Environment variable", value: "env" },
          ]} />
          <span className="conn-hint">
            {where === "file" ? "Written to the connections file on this machine."
              : where === "session" ? "Held until the app stops - asked again next time; nothing secret touches disk."
              : <>Only the variable's name is written; the app reads it where it runs. Or set <code>COMPARE_CONN_&lt;NAME&gt;=uri</code> and save nothing.</>}
          </span>
        </div>
      )}
      {secrets.map(field)}
      {!isFolder && (
        <div className="field narrow-ish">
          <label className="lbl" htmlFor={`${id}-timeout`}>Query timeout, seconds</label>
          <input id={`${id}-timeout`} className="in mono" type="number" min={10} max={86400} value={v.timeout ?? ""} onChange={(e) => set("timeout", e.target.value)} />
        </div>
      )}
      <div className="row">
        <Button onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? "Testing…" : "Test connection"}</Button>
        <Button type="submit" variant="dark" disabled={!name || save.isPending}>Save</Button>
        {editing && <Button variant="ghost" className="conn-del" onClick={() => del.mutate()} disabled={del.isPending}>Delete</Button>}
      </div>
      {said && <div className={`note ${said.tone}`} role="status">{said.text}</div>}
    </form>
  );
}
