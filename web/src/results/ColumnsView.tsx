// web/src/results/ColumnsView.tsx - Columns & values, folded at the foot of the Summary: a card per
// compared column (the worst first) with its value pairs, the rest opened on request, and the
// near-match analysis. The rows that differ themselves are on the Differing rows tab.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RunView } from "../compare/types";
import { Button } from "../ui/kit";
import { marks } from "../ui/marks";
import { Tips } from "../ui/Tips";
import { Failed } from "./Failed";
import { Grid } from "./Grid";
import { NONE, usePick } from "./pickStore";
import { qs, type ColumnsBody, type Frame } from "./types";

function NearMatch({ runId }: { runId: string }) {
  const [asked, setAsked] = useState(false);
  const q = useQuery({ enabled: asked, staleTime: Infinity, queryKey: ["results", runId, "near-match"],
                       queryFn: () => api.get<Frame>(`/api/results/${runId}/near-match`) });
  return (
    <div className="cv-block">
      <h3>Near-match analysis - is it formatting or real data?</h3>
      <p className="caption">High similarity means the two values are nearly the same text - formatting, padding or casing rather than data.</p>
      {!q.data && <Button size="sm" icon="sparkle" disabled={q.isFetching} onClick={() => setAsked(true)}>Run near-match analysis</Button>}
      {q.error && <Failed error={q.error} />}
      {q.data && <Grid frame={q.data} label="Near-match analysis" />}
    </div>
  );
}

/** The cards opened without asking first, then the ones ticked in the order they were ticked. */
function inOrder<T extends { column: string }>(cards: T[], open: string[]) {
  const at = (c: string) => open.indexOf(c);
  return [...cards.filter((c) => at(c.column) < 0), ...cards.filter((c) => at(c.column) >= 0).sort((a, b) => at(a.column) - at(b.column))];
}

export function ColumnsView({ run }: { run: RunView; limit?: number }) {
  const [open, setOpen] = usePick<string[]>("col_cards", NONE);
  const q = useQuery({
    staleTime: Infinity, placeholderData: (prev) => prev, queryKey: ["results", run.id, "columns", open],
    queryFn: () => api.get<ColumnsBody>(`/api/results/${run.id}/columns${qs("open", open)}`),
  });
  if (q.error) return <div className="cv"><Failed error={q.error} /></div>;
  const d = q.data;
  if (!d) return <div className="cv"><p className="caption">Reading…</p></div>;
  if (d.hash_caption) return <div className="cv"><p className="caption">{d.hash_caption}</p></div>;
  const rest = d.rest ?? [];
  return (
    <div className="cv">
      <Tips items={d.tips ?? []} />
      {d.differ_error && <div className="note error">{marks(d.differ_error)}</div>}
      {rest.length > 0 && (
        <fieldset className="col-pick cv-more">
          <legend>{d.rest_title}</legend>
          <div className="col-pick-list">
            {rest.map((c) => (
              <label key={c} className={open.includes(c) ? "check on" : "check"}>
                <input type="checkbox" checked={open.includes(c)}
                  onChange={(e) => setOpen(e.target.checked ? [...open, c] : open.filter((x) => x !== c))} />{c}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="cv-cards">
        {inOrder(d.cards ?? [], open).map((c) => (
          <details key={c.column} className="cv-card" open={open.includes(c.column) || undefined}>
            <summary>{marks(c.head)}</summary>
            <div className="cv-card-body">
              {c.warning && <div className="note warning">{c.warning}</div>}
              {c.pairs
                ? <><p className="caption">{marks("**Where they differ** - the value pairs behind the count")}</p>
                    <Grid frame={c.pairs} label={`Where ${c.column} differs`} /></>
                : <p className="caption">No differing values.</p>}
            </div>
          </details>
        ))}
      </div>
      {d.near_match && <NearMatch runId={run.id} />}
    </div>
  );
}
