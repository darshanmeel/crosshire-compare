// web/src/shell/EngineLimits.tsx - DuckDB's memory and spill-to-disk limits (GET / PUT /api/engine),
// so a big pair spills to disk rather than taking the machine, and the spill cannot fill the disk.
// A limit the machine's owner fixed with COMPARE_DUCKDB_MEMORY / _DISK shows, but cannot be edited.
import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { Button } from "../ui/kit";

export type EngineView = {
  memory: string; memory_from: "env" | "saved" | "default";
  disk: string; disk_from: "env" | "saved" | "default";
  machine_memory: number; default_memory: string; default_disk: string;
};

const GIB = 2 ** 30;

export function EngineLimits() {
  const id = useId();
  const qc = useQueryClient();
  const v = useQuery({ queryKey: ["engine"], queryFn: () => api.get<EngineView>("/api/engine") }).data;
  const [draft, setDraft] = useState<{ memory?: string; disk?: string }>({});
  const save = useMutation({
    mutationFn: (b: { memory: string; disk: string }) => api.send<EngineView>("PUT", "/api/engine", b),
    onSuccess: (got) => { qc.setQueryData(["engine"], got); setDraft({}); },
  });
  if (!v?.memory) return null;
  const memory = draft.memory ?? v.memory, disk = draft.disk ?? v.disk;
  const changed = memory !== v.memory || disk !== v.disk;
  const fixed = (k: "memory" | "disk") => v[`${k}_from`] === "env";
  const err = save.error instanceof ApiError ? save.error.detail : save.error ? String(save.error) : "";
  return (
    <form className="engine-limits" aria-label="DuckDB limits"
          onSubmit={(e) => { e.preventDefault(); if (changed) save.mutate({ memory, disk }); }}>
      <span className="runset-rows">
        <label htmlFor={`${id}-m`}>DuckDB memory</label>
        <input id={`${id}-m`} className="in mono" value={memory} disabled={fixed("memory")} spellCheck={false}
               title={fixed("memory") ? "Set by COMPARE_DUCKDB_MEMORY on this machine" : `e.g. 2GB or 512MB - at most this machine's ${(v.machine_memory / GIB).toFixed(1)} GiB`}
               onChange={(e) => setDraft((d) => ({ ...d, memory: e.target.value }))} />
      </span>
      <span className="runset-rows">
        <label htmlFor={`${id}-d`}>Spill to disk at most</label>
        <input id={`${id}-d`} className="in mono" value={disk} disabled={fixed("disk")} spellCheck={false}
               title={fixed("disk") ? "Set by COMPARE_DUCKDB_DISK on this machine" : "e.g. 20GB - past the memory limit DuckDB writes to the work folder, up to this"}
               onChange={(e) => setDraft((d) => ({ ...d, disk: e.target.value }))} />
      </span>
      {changed && <Button type="submit" disabled={save.isPending}>Save limits</Button>}
      <span className="caption runset-help">
        Past the memory limit DuckDB spills to disk, up to the disk limit. Defaults {v.default_memory} and {v.default_disk}; the next step uses them.
      </span>
      {err && <div className="note error" role="alert">{err}</div>}
    </form>
  );
}
