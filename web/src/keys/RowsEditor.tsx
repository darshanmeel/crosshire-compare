// web/src/keys/RowsEditor.tsx - the rows page (SPEC §06): how rows pair up, the rows each side reads,
// the filters at compare, profile by bucket, profile both files, the run settings, then Compare.
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useRunCompare, useRunError } from "../compare/actions";
import { TICK_COMPARE } from "../compare/types";
import { useCompareNow } from "../compare/useCompare";
import { useSetup, type KeysView } from "../setup/api";
import { goToSection } from "../shell/view";
import { useSources } from "../sources/useSources";
import { Button, Section } from "../ui/kit";
import { marks } from "../ui/marks";
import { FiltersBox } from "../values/FiltersBox";
import { BucketCard } from "./BucketCard";
import { KEYS_KEY, KeyBox } from "./KeyBox";
import { ProfileBox } from "./ProfileBox";
import { RowsToReadCard } from "./RowsToReadCard";
import { RunSettingsCard } from "./RunSettingsCard";
import { filterLine, matchLine, useFilters } from "./summary";
import "./keys.css";

function Sub({ id, title, sub, children }: { id: string; title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="sec rows-sub" aria-labelledby={id}>
      <div className="sec-head"><h3 id={id}>{title}</h3>{sub && <span className="sub">{sub}</span>}</div>
      {children}
    </section>
  );
}

function CompareRow() {
  const { data: st } = useCompareNow();
  const { data: s } = useSetup();
  const { data: f } = useFilters();
  const { data: src } = useSources();
  const k = useQuery({ queryKey: KEYS_KEY, queryFn: () => api.get<KeysView>("/api/setup/keys") }).data;
  const go = useRunCompare();
  const err = useRunError();
  if (!st || st.gate === "load") return null;
  const n = s?.ready ? s.compare.length : 0;
  const filt = filterLine(src, f);
  return (
    <div className="rows-go">
      <div className="actions">
        <Button variant="primary" size="lg" iconAfter="arrow" disabled={st.gate !== "" || st.busy || go.isPending} onClick={() => go.mutate()}>
          Compare {st.names[0]} against {st.names[1]}
        </Button>
        <span className="caption">{n} column{n === 1 ? "" : "s"} {matchLine(s?.ready ? s.keys : [], k)} · {filt.startsWith("none") ? "no filters applied" : filt}</span>
      </div>
      {st.gate === "tick" && <div className="note warning">{marks(TICK_COMPARE)}</div>}
      {st.filter_error && <div className="note error">{marks(st.filter_error)}</div>}
      {err && <div className="note error">{marks(err)}</div>}
    </div>
  );
}

export function RowsEditor() {
  return (
    <Section n="03" title="Rows · how they pair up" sub="a key when there is one; position or a hash of the compared columns when there is not"
             actions={<Button icon="arrowl" onClick={() => goToSection("rows")}>Back to the setup</Button>}>
      <KeyBox />
      <Sub id="rows-read" title="Rows to read" sub="cut either side down before it is compared - DuckDB SQL, applied at load">
        <div className="two"><RowsToReadCard tag="A" /><RowsToReadCard tag="B" /></div>
      </Sub>
      <FiltersBox />
      <Sub id="rows-bucket" title="Profile by bucket" sub="optional - the Summary then shows what each group of rows holds">
        <BucketCard />
      </Sub>
      <ProfileBox />
      <Sub id="rows-run" title="Run settings">
        <RunSettingsCard />
      </Sub>
      <CompareRow />
    </Section>
  );
}
