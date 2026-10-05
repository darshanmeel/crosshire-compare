// web/src/columns/ColumnsSection.tsx - 02 Columns (SPEC §04; §07 while a run works): the pairing board
// with its actions in the section head; before both sides load, a callout says what will appear here.
import { useState } from "react";
import { useCompareNow } from "../compare/useCompare";
import { useSetup, type SetupReady } from "../setup/api";
import { useLog } from "../shell/LogPanel";
import { Button, Callout, Pill, Section } from "../ui/kit";
import { AddColumn, AddedColumns } from "./AddColumn";
import { ColumnsActions, ColumnsBox } from "./ColumnsBox";
import { subLine } from "./pairing";
import { RunningTable } from "./RunningTable";
import { useColumnCalls } from "./useColumnCalls";
import "./columns.css";

const BEFORE = (
  <Callout icon="table">
    Every column from either file lands in one table: pick each column's partner, what is the <strong>key</strong>, what
    is <strong>compared</strong>, and what type both sides become. <strong>Auto</strong> fills it in by name, then by the values.
  </Callout>
);

function Ready({ s }: { s: SetupReady }) {
  const c = useColumnCalls(s);
  const [adding, setAdding] = useState(false);
  const busy = !!useCompareNow().data?.busy;
  const auto = !!useLog().data?.entries?.some((e) => e.state === "running" && e.kind === "Auto");
  if (busy) {
    const pairing = auto && s.only_a.length > 0 && s.only_b.length > 0;
    return (
      <Section n="02" id="columns" title="Columns" sub={pairing ? <Pill tone="run">pairing…</Pill> : subLine(s)}>
        <div className="panel cols-panel"><RunningTable s={s} pairing={pairing} /></div>
      </Section>
    );
  }
  return (
    <Section n="02" id="columns" title="Columns" sub={subLine(s)}
      actions={<><Button icon="plus" aria-pressed={adding} disabled={c.busy} onClick={() => setAdding(!adding)}>Add a column</Button><ColumnsActions s={s} c={c} /></>}>
      {adding && <AddColumn s={s} onClose={() => setAdding(false)} />}
      <AddedColumns s={s} />
      {!s.specs.length && (
        <Callout tone="warn" icon="swap">Nothing is paired yet - pick a counterpart for at least one column in the table.</Callout>
      )}
      <ColumnsBox s={s} c={c} />
    </Section>
  );
}

export function ColumnsSection() {
  const { data: s } = useSetup();
  if (s?.ready) return <Ready s={s} />;
  return <Section n="02" id="columns" title="Columns" sub="appears once both sides are loaded">{BEFORE}</Section>;
}
