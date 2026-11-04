// web/src/sources/FirstFields.tsx - before reading each row as its first N fields, or with its split
// numbers joined: the field counts in a sample of the file and the first rows as they will read, to decide on.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorNote, Loading, num } from "../ui/kit";
import type { FirstFieldsPreview, Tag } from "./types";

export function FirstFields({ tag, pick, n, join = false }: { tag: Tag; pick: string; n: number; join?: boolean }) {
  const q = useQuery({
    queryKey: ["first-fields", tag, pick, n, join], placeholderData: keepPreviousData, retry: false,
    queryFn: () => api.send<FirstFieldsPreview>("POST", `/api/sources/${tag}/first-fields?n=${n}${join ? "&join=true" : ""}`, JSON.parse(pick)),
  });
  const d = q.data;
  if (q.error) return <ErrorNote>{(q.error as Error).message}</ErrorNote>;
  if (!d) return <Loading>Reading the first rows…</Loading>;
  const counts = d.by.map((b) => `${num(b.rows)} with ${num(b.fields)}`).join(", ");
  return (
    <div className="set-aside-rows first-fields">
      {join
        ? <p className="caption">
            In the first {num(d.sampled)} rows: {counts} fields (the header has {num(d.width)}). The quoted text marks where the columns are, so a
            comma between two whole numbers is taken as a decimal. {num(d.guessed ?? 0)} of these rows had more than one such pair - the last was
            joined. {num(d.unplaced ?? 0)} could not be placed and would be set aside. Check the numbers below.
          </p>
        : <p className="caption">
            In the first {num(d.sampled)} rows: {counts} fields (the header has {num(d.width)}). Each row keeps its first {num(d.fields)};
            the rest are ignored. If a value holds the delimiter, the columns after it shift - look down the columns below.
          </p>}
      <div className="tblwrap">
        <table className="tbl compact" aria-label="Rows as they will read">
          <thead><tr><th className="num">Line</th><th className="num">Fields</th>{d.columns.map((c) => <th key={c}>{c}</th>)}{!join && <th>Left out</th>}</tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.line}>
              <td className="num">{num(r.line)}</td><td className="num">{num(r.fields)}</td>
              {r.values.map((v, i) => <td key={i} className="m">{v}</td>)}
              {!join && <td className="m dim">{r.left_out}</td>}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
