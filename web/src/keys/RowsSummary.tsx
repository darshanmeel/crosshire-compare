// web/src/keys/RowsSummary.tsx - the setup's Rows card (SPEC §04 "Rows"): how rows match, what cuts
// them, the bucket column, and Edit rows to the rows page. Shown once a pair is set up.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSetup, type KeysView } from "../setup/api";
import { setView } from "../shell/view";
import { useSources } from "../sources/useSources";
import { Button, Section } from "../ui/kit";
import { useBucketColumn } from "./BucketCard";
import { KEYS_KEY } from "./KeyBox";
import { filterLine, NOKEY_SHORT, useFilters } from "./summary";
import "./keys.css";

export function RowsSummary() {
  const { data: s } = useSetup();
  const ready = !!(s?.ready && s.specs.length);
  const k = useQuery({ queryKey: KEYS_KEY, queryFn: () => api.get<KeysView>("/api/setup/keys"), enabled: ready }).data;
  const { data: f } = useFilters();
  const { data: src } = useSources();
  const [bucket] = useBucketColumn();
  if (!s?.ready || !s.specs.length) return null;
  return (
    <Section n="03" id="rows" title="Rows" sub="optional - narrow what is compared">
      <div className="card rows-sum">
        <span className="field"><span className="lbl">Match rows</span>
          <span className="v">{s.keys.length ? <>on key <code>{s.keys.join(" + ")}</code></> : NOKEY_SHORT[k?.nokey_mode ?? s.settings.nokey_mode]}</span></span>
        <span className="field"><span className="lbl">Filter</span><span className="v">{filterLine(src, f)}</span></span>
        <span className="field"><span className="lbl">Profile by bucket</span><span className="v">{bucket ? <code>{bucket}</code> : "off"}</span></span>
        <span className="grow" />
        <Button onClick={() => setView({ view: "rows", anchor: null })}>Edit rows</Button>
      </div>
    </Section>
  );
}
