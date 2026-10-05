// The body of the Connections drawer (SPEC §02): the saved connections as cards, the add / edit
// form, import and export. useConnections() is the list the header, the Database box and this share.
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { Button, Chip, Pill } from "../ui/kit";
import { ConnectionForm } from "./ConnectionForm";
import { FilesBox } from "./FilesBox";
import { NEW, passwordText, refreshConnections, savedBody, type ConnForm, type ConnRow, type Tested } from "./types";
import "./connections.css";

export function useConnections() {
  return useQuery({ queryKey: ["connections"], queryFn: () => api.get<ConnRow[]>("/api/connections") });
}

function status(t: Tested | undefined, busy: boolean) {
  if (busy) return <Pill tone="run">Testing…</Pill>;
  if (!t) return <Pill tone="idle">Not tested</Pill>;
  return t.ok ? <Pill tone="ok">Connected</Pill> : <Pill tone="neg">Failed</Pill>;
}

function ConnCard({ r, tested, onTested, onEdit, editing }: {
  r: ConnRow; tested?: Tested; onTested: (r: Tested) => void; onEdit: () => void; editing: boolean;
}) {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const test = useMutation({
    mutationFn: async () => {
      const c = await api.get<ConnForm>(`/api/connections/${encodeURIComponent(r.name)}`);
      return api.send<Tested>("POST", "/api/connections/test", { ...savedBody(c), name: r.name });
    },
    onSuccess: (t) => { setErr(""); onTested(t); },
    onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)),
  });
  const forget = useMutation({
    mutationFn: () => api.send("DELETE", `/api/connections/${encodeURIComponent(r.name)}/password`),
    onSuccess: () => refreshConnections(qc),
  });
  return (
    <li className={editing ? "conn on" : "conn"} aria-label={r.name}>
      <div className="top">
        <span className="name">{r.name}</span>
        <Chip>{r.label}</Chip>
        {status(tested, test.isPending)}
        <span className="grow" />
        {r.editable && <Button size="sm" onClick={() => test.mutate()} disabled={test.isPending} aria-label={`Test ${r.name}`}>Test</Button>}
        {r.editable && <Button size="sm" onClick={onEdit} aria-pressed={editing} aria-label={`Edit ${r.name}`}>Edit</Button>}
      </div>
      <div className="uri" title={r.where}>{r.where}</div>
      <div className="said">
        {passwordText(r)}
        {r.password === "session" && <> · <button type="button" className="link-btn inline" onClick={() => forget.mutate()} disabled={forget.isPending}>Forget the password</button></>}
      </div>
      {tested && !tested.ok && <div className="said neg">{tested.message}</div>}
      {err && <div className="note error">{err}</div>}
    </li>
  );
}

export function ConnectionsManager({ meta }: { meta?: Meta }) {
  const { data: rows = [], error, isLoading } = useConnections();
  const [pick, setPick] = useState(NEW);
  const [tested, setTested] = useState<Record<string, Tested>>({});
  const formRef = useRef<HTMLDivElement>(null);
  if (!meta) return null;
  const record = (name: string, t: Tested) => setTested((o) => ({ ...o, [name]: t }));
  const edit = (name: string) => {
    setPick(name);
    requestAnimationFrame(() => {
      formRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
      formRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    });
  };
  return (
    <div className="conns">
      <p className="conn-intro">
        {rows.length > 0 ? <><strong>{rows.length}</strong> saved. </> : null}
        Pick one under <strong>Database</strong> on either side; a folder connection shows under <strong>Path on disk</strong>.
      </p>
      {error && <div className="note error">{String((error as Error).message)}</div>}
      {!isLoading && rows.length === 0 && !error && (
        <p className="conn-hint">None yet. Fill the form and press Save, import a connections file below - or set <code>COMPARE_CONN_&lt;NAME&gt;=&lt;uri&gt;</code> in the environment.</p>
      )}
      {rows.length > 0 && (
        <ul className="conn-list" aria-label="Saved connections">
          {rows.map((r) => (
            <ConnCard key={r.name} r={r} tested={tested[r.name]} editing={pick === r.name}
                      onTested={(t) => record(r.name, t)} onEdit={() => edit(r.name)} />
          ))}
        </ul>
      )}
      <div ref={formRef} className="conn-add">
        <ConnectionForm key={pick} meta={meta} pick={pick} onDone={(name) => setPick(name ?? NEW)} onTested={record} />
      </div>
      <FilesBox rows={rows} />
      <p className="conn-foot">
        Override the file location with <code>COMPARE_CONNECTIONS</code>. Restrict file paths to a folder with <code>COMPARE_DATA_DIR</code>.
      </p>
    </div>
  );
}
