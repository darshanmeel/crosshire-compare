// Import a connections file (JSON or YAML) after a preview, or download the saved ones without passwords.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Icon } from "../ui/icons";
import { Button, Chip } from "../ui/kit";
import { marks } from "../ui/marks";
import { refreshConnections, type ConnRow } from "./types";

type Found = { name: string; label: string; where: string; replaces: boolean };

export function FilesBox({ rows }: { rows: ConnRow[] }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<{ text: string; filename: string } | null>(null);
  const [found, setFound] = useState<Found[]>([]);
  const [keep, setKeep] = useState(false);
  const [said, setSaid] = useState<{ tone: string; text: string } | null>(null);
  const fail = (e: unknown) => setSaid({ tone: "error", text: e instanceof ApiError ? e.detail : String(e) });

  const preview = async (f: File) => {
    setSaid(null); setFound([]);
    const body = { text: await f.text(), filename: f.name };
    setFile(body);
    try { setFound(await api.send<Found[]>("POST", "/api/connections/import/preview", body)); } catch (e) { fail(e); }
  };
  const add = useMutation({
    mutationFn: () => api.send<{ names: string[] }>("POST", "/api/connections/import", { ...file, keep_passwords: keep }),
    onSuccess: (r) => { setSaid({ tone: "success", text: `Saved ${r.names.join(", ")}` }); setFound([]); refreshConnections(qc); },
    onError: fail,
  });

  return (
    <section className="conn-files" aria-label="Import or export">
      <h3>Import or export</h3>
      <p className="conn-hint">{marks("JSON or YAML, one connection per name - the fields the form has (`kind`, `host`, `user`, `database`…) or a `uri`. `${NAME}` reads the environment, so a shared file need hold no password.")}</p>
      <div className="row">
        <label className="btn sm conn-pick">
          <Icon name="upload" size="sm" />Import a file
          <input type="file" aria-label="Connections file" accept=".yml,.yaml,.json" onChange={(e) => { const x = e.target.files?.[0]; if (x) preview(x); e.target.value = ""; }} />
        </label>
        {rows.some((r) => r.source === "file") && (
          <a className="btn sm" href="/api/connections/export" download><Icon name="download" size="sm" />Download mine (.yml, no passwords)</a>
        )}
      </div>
      {found.length > 0 && (
        <div className="conn-found">
          <ul>
            {found.map((c) => (
              <li key={c.name}><strong>{c.name}</strong> <Chip>{c.label}</Chip> <span className="uri">{c.where}</span>{c.replaces && <Chip tone="warn">replaces the saved one</Chip>}</li>
            ))}
          </ul>
          <label className="check"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />Save the passwords written in the file</label>
          <div className="row"><Button variant="dark" size="sm" onClick={() => add.mutate()} disabled={add.isPending}>Add {found.length} connection{found.length === 1 ? "" : "s"}</Button></div>
        </div>
      )}
      {said && <div className={`note ${said.tone}`} role="status">{said.text}</div>}
    </section>
  );
}
