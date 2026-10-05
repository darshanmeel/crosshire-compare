// web/src/sources/UploadBox.tsx - the dropzone (screen 01): drop a file or choose one; it is uploaded
// at once and staged, and Load then reads the staged copy.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Meta } from "../api/client";
import { Dropzone } from "../ui/kit";
import type { SideView, Tag } from "./types";

export function UploadBox({ tag, staged, types, onBusy }:
  { tag: Tag; meta: Meta; staged: string; types: string[]; onBusy?: (busy: boolean) => void }) {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const up = useMutation({
    mutationFn: (file: File) => { onBusy?.(true); return api.upload<SideView>(`/api/sources/${tag}/upload?filename=${encodeURIComponent(file.name)}`, file); },
    onSuccess: () => { setErr(""); qc.invalidateQueries({ queryKey: ["sources"] }); },
    onError: (e) => setErr(e instanceof ApiError ? e.detail : String(e)),
    onSettled: () => onBusy?.(false),
  });
  const hint = tag === "P" ? "a wide or big table takes minutes — cut it down under Rows to read to try a slice"
    : "any size — it is copied to the temp folder first";
  return (
    <div className="upload">
      <Dropzone accept={types.map((t) => "." + t).join(",")} label="CSV or JSON file" onFile={(f) => up.mutate(f)}
        title={<><strong>Drop a CSV, JSON or Parquet file</strong> here</>} hint={hint} />
      {up.isPending ? <p className="caption" role="status">Uploading {up.variables?.name}…</p>
        : staged && <p className="caption"><b className="staged">{staged}</b> is uploaded — press Load to read it</p>}
      {err && <div className="note error">{err}</div>}
    </div>
  );
}
