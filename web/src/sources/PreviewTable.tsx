// web/src/sources/PreviewTable.tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSources } from "./useSources";
import type { Tag } from "./types";
import { ErrorNote, Loading } from "../ui/kit";

/** The first 10 rows of a loaded side, as the file has them (numbers right-aligned, written as read). */
export function PreviewTable({ tag }: { tag: Tag }) {
  const { data: src } = useSources();
  const loaded = !!src?.sides?.[tag]?.loaded;
  const q = useQuery({ queryKey: ["preview", tag], enabled: loaded,
                       queryFn: () => api.get<{ columns: string[]; rows: unknown[][] }>(`/api/sources/${tag}/preview?n=10`) });
  if (q.error) return <ErrorNote>{(q.error as Error).message}</ErrorNote>;
  if (!q.data) return <Loading>Reading…</Loading>;
  return (
    <div className="table-wrap preview">
      <table className="grid">
        <thead><tr>{q.data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{q.data.rows.map((r, i) => (
          <tr key={i}>{r.map((x, j) => (
            <td key={j} className={x == null ? "null" : typeof x === "number" ? "num" : ""}>
              {x == null ? "" : String(x)}
            </td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}
