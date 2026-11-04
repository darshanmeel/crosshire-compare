// web/src/sources/SetAside.tsx - the rows Load set aside for having too few or too many fields: the
// line under the loaded file and, opened, the rows themselves a page at a time with a CSV of them all.
import { useId, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Button, ErrorNote, LinkButton, num } from "../ui/kit";
import type { SetAsideInfo, SetAsidePage, Tag } from "./types";

const SIZE = 25;

export function SetAside({ tag, info }: { tag: Tag; info: SetAsideInfo }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["set-aside", tag, info.rows, info.said, page],
    queryFn: () => api.get<SetAsidePage>(`/api/sources/${tag}/set-aside?page=${page}&size=${SIZE}`),
    enabled: open, placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil(info.kept / SIZE));
  return (
    <div className="set-aside">
      <div className="row">
        <span className="note warning">{info.said}</span>
        <LinkButton iconAfter="chevron" aria-expanded={open} aria-controls={id} className={open ? "open" : undefined}
                    onClick={() => setOpen(!open)}>Show the rows set aside</LinkButton>
        <a className="link-btn" href={`/api/sources/${tag}/set-aside.csv`} download>Download them (CSV)</a>
      </div>
      {open && (
        <div id={id} className="set-aside-rows">
          {q.isError && <ErrorNote role="alert">Could not read the rows set aside.</ErrorNote>}
          <div className="tblwrap">
            <table className="tbl compact" aria-label="Rows set aside">
              <thead><tr><th className="num">Line</th><th className="num">Fields</th><th>The line in the file</th></tr></thead>
              <tbody>{(q.data?.lines ?? []).map((r) => (
                <tr key={r.line}>
                  <td className="num">{num(r.line)}</td>
                  <td className="num">{r.fields === null ? "?" : num(r.fields)}</td>
                  <td className="m raw" title={r.raw}>{r.raw}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="row">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="sub">Page {num(page)} of {num(pages)}{info.kept < info.rows ? ` · the first ${num(info.kept)} of ${num(info.rows)} kept` : ""}</span>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </div>
      )}
    </div>
  );
}
