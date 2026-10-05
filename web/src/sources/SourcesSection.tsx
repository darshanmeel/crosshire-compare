// web/src/sources/SourcesSection.tsx - section 01 of the Compare page (screens 01, 03, 04, 07): the A and
// B cards side by side - one line each while a run is going - and, when a side reads a database, the
// table-vs-query note once (dismissable). ProfileSource is the Profile page's single card (14, 15).
import { useState } from "react";
import type { Meta } from "../api/client";
import { useCompareNow } from "../compare/useCompare";
import { Callout, Section } from "../ui/kit";
import { useSideForm } from "./formStore";
import { SideCard } from "./SideCard";
import { SideLine } from "./SideLine";
import { useSources } from "./useSources";
import "./sources.css";

const DISMISS_KEY = "fs-db-callout";
let dismissedNow = false;              // for this page load, when the browser keeps no storage
function wasDismissed(): boolean {
  if (dismissedNow) return true;
  try { return localStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; }
}

function DatabaseCallout() {
  const [gone, setGone] = useState(wasDismissed);
  if (gone) return null;
  const dismiss = () => {
    dismissedNow = true;
    try { localStorage.setItem(DISMISS_KEY, "1"); } catch { /* the page still hides it until reloaded */ }
    setGone(true);
  };
  return (
    <Callout icon="db" onDismiss={dismiss}>
      <strong>SQL query</strong> reads exactly what you write — join, filter or cast on the warehouse side and compare the result.{" "}
      <strong>A table</strong> is read whole, then cut by <em>Rows to read</em> here. Either way the rows land in DuckDB once; comparing never goes back to the database.
    </Callout>
  );
}

export function SourcesSection({ meta }: { meta: Meta }) {
  const sides = useSources().data?.sides;
  const busy = !!useCompareNow().data?.busy;
  const [fa] = useSideForm("A");
  const [fb] = useSideForm("B");
  const both = !!sides?.A.loaded && !!sides?.B.loaded;
  if (busy && both)
    return (
      <Section n="01" id="sources" title="Sources">
        <div className="two"><SideLine tag="A" /><SideLine tag="B" /></div>
      </Section>
    );
  return (
    <Section n="01" id="sources" title="Sources" sub={both ? "CSV, JSON, Parquet or a database table on either side" : "load both sides to continue"}>
      <div className="two"><SideCard tag="A" meta={meta} /><SideCard tag="B" meta={meta} /></div>
      {(fa.how === "database" || fb.how === "database") && <DatabaseCallout />}
    </Section>
  );
}

export function ProfileSource({ meta }: { meta: Meta }) {
  const P = useSources().data?.sides?.P;
  const [fp] = useSideForm("P");
  if (P?.loaded)                        // screen 15: one compact card above the profile, no section head
    return (
      <div id="sources" className="profile-source loaded">
        <SideCard tag="P" meta={meta} compact />
        {fp.how === "database" && <DatabaseCallout />}
      </div>
    );
  return (
    <Section n="01" id="sources" title="Source" sub="one table">
      <div className="profile-source">
        <SideCard tag="P" meta={meta} />
        {fp.how === "database" && <DatabaseCallout />}
      </div>
    </Section>
  );
}
