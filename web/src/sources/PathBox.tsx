// web/src/sources/PathBox.tsx - a path on this machine (read in place, any size), or a file by name
// in a folder saved under Connections; Browse… opens the file dialog where the app runs.
import { useEffect, useId, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { Button } from "../ui/kit";
import { useSideForm } from "./formStore";
import { NoteLine } from "./NoteLine";
import type { FolderFiles, FolderRow, Tag } from "./types";

export function PathBox({ tag, meta }: { tag: Tag; meta: Meta }) {
  const id = useId();
  const [f, set] = useSideForm(tag);
  const folders = useQuery({ queryKey: ["folders"], queryFn: () => api.get<FolderRow[]>("/api/sources/folders"), staleTime: 20_000 });
  const rows = folders.data ?? [];
  const folder = rows.some((r) => r.name === f.folder) ? f.folder : "";     // deleted since it was picked: Any path
  const files = useQuery({
    queryKey: ["folder-files", folder], enabled: !!folder, staleTime: 20_000,
    queryFn: () => api.get<FolderFiles>(`/api/sources/folders/${encodeURIComponent(folder)}/files`),
  });
  const [err, setErr] = useState("");
  const [gone, setGone] = useState("");
  useEffect(() => {                       // a pick whose folder was deleted: back to Any path, and say so
    if (folders.data && f.folder && !rows.some((r) => r.name === f.folder)) { setGone(f.folder); set({ folder: "", file: "" }); }
  }, [folders.data, f.folder]);
  const browse = useMutation({
    mutationFn: () => api.send<{ path: string; file: string }>("POST", "/api/sources/browse", { start: f.path, folder }),
    onSuccess: (r) => { setErr(""); if (r.file) set({ file: r.file }); else if (r.path) set({ path: r.path, folder: "" }); },
    onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)),
  });
  return (
    <div className="pathbox">
      {folders.error && <div className="note error">{(folders.error as Error).message}</div>}
      {rows.length > 0 && (
        <div className="row" title="A folder saved under Connections (kind Folder): pick its file by name. The config keeps the folder and the name, so a rerun reads the next file there by name.">
          <label className="lbl w" htmlFor={`${id}-folder`}>Folder</label>
          <select id={`${id}-folder`} className="in grow" aria-label="Folder" value={folder} onChange={(e) => set({ folder: e.target.value })}>
            <option value="">Any path</option>
            {rows.map((r) => <option key={r.name} value={r.name}>{r.name} · {r.host}</option>)}
          </select>
        </div>
      )}
      <div className="row">
        {folder === "" ? <>
          <label className="lbl w" htmlFor={`${id}-path`}>Path</label>
          <input id={`${id}-path`} type="text" className="in mono grow" aria-label="Path to CSV or JSON" placeholder="C:\data\exports\employees_2026-09.csv"
                 value={f.path} onChange={(e) => set({ path: e.target.value })} />
        </> : <>
          <label className="lbl w" htmlFor={`${id}-file`} title="CSV, JSON and Parquet files in the folder and its subfolders. A name typed is read in the folder - 2026-10/hr.csv too.">File</label>
          <input id={`${id}-file`} type="text" className="in mono grow" aria-label={`File in ${folder}`} list={`files_${tag}`} placeholder="pick one, or type its name"
                 value={f.file} onChange={(e) => set({ file: e.target.value })} />
          <datalist id={`files_${tag}`}>{files.data?.files.map((x) => <option key={x} value={x} />)}</datalist>
        </>}
        {meta.filepick && (
          <Button onClick={() => browse.mutate()} disabled={browse.isPending}
                  title="Opens the file dialog on the machine the app runs on - the file is read where it lies, never copied, so it can be any size.">
            {browse.isPending ? "Waiting…" : "Browse…"}
          </Button>
        )}
      </div>
      {gone && !folder && <div className="note warning">The folder {gone} is gone - reading Any path instead.</div>}
      {folder && files.data?.note && <NoteLine note={files.data.note} />}
      {err && <div className="note error">{err}</div>}
    </div>
  );
}
