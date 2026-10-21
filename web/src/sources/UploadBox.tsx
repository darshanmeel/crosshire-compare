// web/src/sources/UploadBox.tsx - the dropzone (screen 01): drop a file or choose one; it is uploaded
// at once and staged, and Load then reads the staged copy. Once the side is loaded from that upload
// the zone is one line - the file, "uploaded", Replace file - and Replace file brings the zone back.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../api/client";
import { Dropzone, ErrorNote, LinkButton } from "../ui/kit";
import type { SideView, Tag } from "./types";

export function UploadBox({ tag, staged, types, uploaded = false, onBusy }:
  { tag: Tag; staged: string; types: string[]; uploaded?: boolean; onBusy?: (busy: boolean) => void }) {
  const qc = useQueryClient();
  const [err, setErr] = useState("");
  const [replacing, setReplacing] = useState(false);
  const up = useMutation({
    mutationFn: (file: File) => { onBusy?.(true); return api.upload<SideView>(`/api/sources/${tag}/upload?filename=${encodeURIComponent(file.name)}`, file); },
    onSuccess: () => { setErr(""); setReplacing(false); qc.invalidateQueries({ queryKey: ["sources"] }); },
    onError: (e) => setErr(errorText(e)),
    onSettled: () => onBusy?.(false),
  });
  if (uploaded && !replacing && !up.isPending)
    return (
      <div className="upload">
        <p className="upload-line"><b className="staged">{staged}</b><span>uploaded</span>
          <LinkButton icon="upload" onClick={() => setReplacing(true)}>Replace file</LinkButton></p>
        {err && <ErrorNote>{err}</ErrorNote>}
      </div>
    );
  const hint = tag === "P" ? "a wide or big table takes minutes — cut it down under Rows to read to try a slice"
    : "any size — it is copied to the temp folder first";
  return (
    <div className="upload">
      <Dropzone accept={types.map((t) => "." + t).join(",")} label="CSV, JSON or Parquet file" onFile={(f) => up.mutate(f)}
        title={<><strong>Drop a CSV, JSON or Parquet file</strong> here</>} hint={hint} />
      {up.isPending ? <p className="caption" role="status">Uploading {up.variables?.name}…</p>
        : staged && <p className="caption"><b className="staged">{staged}</b> is uploaded — press Load to read it</p>}
      {err && <ErrorNote>{err}</ErrorNote>}
    </div>
  );
}
