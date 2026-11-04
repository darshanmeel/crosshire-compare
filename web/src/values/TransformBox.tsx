import { useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { marks } from "../ui/marks";
import { Icon } from "../ui/icons";
import { Button, Chip, CommitArea, CommitInput, ErrorNote, LinkButton, num, Pill, plural, Seg, type Tone as PillTone } from "../ui/kit";
import { plainSteps } from "../columns/pairing";
import { errorText, useSetupSend, useStepsRebuild, type CheckView, type Frame, type SetupReady, type Spec, type Step, type StepsMeta, type TryView } from "../setup/api";
import { FrameTable } from "../setup/FrameTable";
import { sideLabels } from "../sources/names";
import { setView, useView } from "../shell/view";
import "./values.css";

type Which = "A" | "B";
type Mode = "both" | Which;                 // one list for both sides, or one side's own
const other = (w: Which): Which => (w === "A" ? "B" : "A");
const sameSteps = (sp: Spec) => JSON.stringify(sp.a_steps) === JSON.stringify(sp.b_steps);
/** A side's steps in a few words - a custom expression by its name, the expression in the tooltip. */
const fewWords = (steps: Step[], said: string[]) =>
  plainSteps(steps, said).map((w, i) => (steps[i]?.op === "custom expression" ? "custom expression" : w)).join(" → ");

/** The pair the editor shows: the view's pair, kept inside the list. */
export const pairIndex = (s: SetupReady, pair: number) => Math.max(0, Math.min(pair, s.specs.length - 1));

export const useStepsMeta = () =>
  useQuery({ queryKey: ["setup-steps"], queryFn: () => api.get<StepsMeta>("/api/setup/steps"), staleTime: Infinity });

/** "N", "find", "format" - a parameter's label cut to its name, as values.describe_step does. */
const shortLabel = (label: string) => label.split(" -")[0].split(",")[0];

/** Text pairs follow "Ignore case in values" unless the column table set their case. */
function caseOf(s: SetupReady, spec: Spec): string | null {
  if (spec.kind !== "text") return null;
  return spec.case || (s.settings.ignore_case ? "ignore" : "exact");
}

/** The editor's head: A chip ⇄ B chip, the type both sides become, the case, how the pair was made. */
export function PairHead({ s, spec }: { s: SetupReady; spec: Spec }) {
  const send = useSetupSend();
  const m = useStepsMeta().data;
  const row = s.rows.find((r) => r["Common name"] === spec.canon);
  const by = row?.["Matched by"] ?? "";
  const tone: PillTone = /data|value|guess/i.test(by) ? "warn" : by === "name" ? "ok" : "idle";
  const cs = caseOf(s, spec);
  return (
    <div className="panel-head">
      <h3 className="vx-pairname">
        <Chip tone="a">{spec.a_src}</Chip>
        <span className="swap" role="img" aria-label="paired with"><Icon name="swap" /></span>
        <Chip tone="b">{spec.b_src}</Chip>
      </h3>
      <select className="sel type" aria-label="Type · both sides" value={spec.kind} disabled={send.isPending}
              onChange={(e) => send.mutate({ path: "/type", body: { canon: spec.canon, kind: e.target.value } })}>
        {(m?.types ?? s.types).map((t) => <option key={t}>{t}</option>)}
      </select>
      {cs && <Chip title={spec.case ? "Set in the column table" : "Follows Ignore case in values"}>{cs} case</Chip>}
      <span className="grow" />
      {by && <Pill tone={tone}>paired by {by}{tone === "warn" && !/check/.test(by) ? " · check" : ""}</Pill>}
      {send.error && <ErrorNote role="alert">{errorText(send.error)}</ErrorNote>}
    </div>
  );
}

/** One short line on what the steps do to this pair: `Both: trim · compared as number`. */
function Say({ spec, labels }: { spec: Spec; labels: [string, string] }) {
  const of = (w: Which) => (w === "A" ? [spec.a_steps, spec.a_said] as const : [spec.b_steps, spec.b_said] as const);
  const said = (w: Which) => { const [st, sd] = of(w); return st.length ? <span title={sd.join(" → ")}>{fewWords(st, sd)}</span> : "as in the file"; };
  const tail = <> · compared as <b>{spec.kind}</b></>;
  if (sameSteps(spec)) return <p className="vx-say"><b>Both:</b> {said("A")}{tail}</p>;
  return (
    <p className="vx-say">
      {(["A", "B"] as const).map((w, i) => <span key={w}>{i > 0 && " · "}<b>{labels[i]}:</b> {said(w)}</span>)}{tail}
    </p>
  );
}

/** A parameter box that keeps what is typed and hands it on when it is left. */
function ParamBox({ k, m, value, label, onDone }: { k: string; m: StepsMeta; value: string; label: string; onDone: (v: string) => void }) {
  const numeric = m.numeric.includes(k);
  return (
    <span className={k === "expr" ? "vx-param expr" : "vx-param"}>
      <span className="lbl" aria-hidden="true">{shortLabel(m.labels[k] ?? k)}</span>
      {k === "expr"
        ? <CommitArea aria-label={label} value={value} className="expr" spellCheck={false} onDone={onDone} />
        : <CommitInput type={numeric ? "number" : "text"} aria-label={label} value={value} className={k === "fmt" ? "" : "short"}
                       min={numeric ? 1 : undefined} max={numeric ? 100000 : undefined} onDone={onDone} />}
    </span>
  );
}

/** The new step's parameters, as the server says the op takes them. */
function DraftParams({ op, m, params, setParams }: { op: string; m: StepsMeta; params: Record<string, string>; setParams: (p: Record<string, string>) => void }) {
  const [preset, setPreset] = useState("");
  const [fnPick, setFn] = useState("");
  const fns = useQuery({ queryKey: ["setup-functions"], enabled: op === "custom expression", staleTime: Infinity,
                         queryFn: () => api.get<Frame>("/api/setup/functions") });
  const fn = fns.data?.rows.find((r) => r[0] === fnPick);
  const names = m.steps[op] ?? [];
  return (
    <>
      {names.map((k) => k === "fmt" ? (
        <span key={k} className="row">
          <span className="vx-param">
            <span className="lbl" aria-hidden="true">looks like</span>
            <select aria-label="What the value looks like" value={preset}
                    onChange={(e) => { setPreset(e.target.value); setParams({ ...params, fmt: m.presets[e.target.value] ?? "" }); }}>
              <option value="">(auto)</option>
              {Object.entries(m.presets).map(([k2, f]) => <option key={k2} value={k2}>{k2}   →   {f}</option>)}
            </select>
          </span>
          <span className="vx-param">
            <span className="lbl" aria-hidden="true">or a format</span>
            <input type="text" aria-label="or a format" placeholder="%d/%m/%Y %H:%M" value={params.fmt ?? ""}
                   onChange={(e) => setParams({ ...params, fmt: e.target.value })} />
          </span>
        </span>
      ) : (
        <span key={k} className={k === "expr" ? "vx-param expr" : "vx-param"}>
          <span className="lbl" aria-hidden="true">{shortLabel(m.labels[k] ?? k)}</span>
          {k === "expr" ? (
            <textarea aria-label={m.labels[k] ?? k} value={params[k] ?? ""} className="expr" spellCheck={false}
                      rows={Math.min(6, Math.max(2, (params[k] ?? "").split("\n").length))}
                      placeholder="case when x is null then 0 else x end" onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
          ) : (
            <input type={m.numeric.includes(k) ? "number" : "text"} aria-label={m.labels[k] ?? k} value={params[k] ?? ""} className="short"
                   min={m.numeric.includes(k) ? 1 : undefined} max={m.numeric.includes(k) ? 100000 : undefined}
                   onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
          )}
        </span>
      ))}
      {op === "custom expression" && (
        <span className="vx-fn">
          <span className="vx-param">
            <span className="lbl" aria-hidden="true">functions</span>
            <input type="text" aria-label="DuckDB functions" list="tx_fn" value={fnPick} className="wide"
                   placeholder="left · regexp_replace · split_part · strptime …" onChange={(e) => setFn(e.target.value)} />
          </span>
          <datalist id="tx_fn">{fns.data?.rows.map((r) => <option key={String(r[0])} value={String(r[0])} />)}</datalist>
          {fn && <span className="vx-hint">{marks(`\`${fn[1]}\` - ${fn[2]}` + (fn[3] ? ` · e.g. \`${fn[3]}\`` : ""))}</span>}
        </span>
      )}
    </>
  );
}

const col = (f: Frame | undefined, name: string) => (f ? f.columns.indexOf(name) : -1);
const cell = (f: Frame, r: number, name: string) => { const i = col(f, name); return i < 0 ? "" : String(f.rows[r]?.[i] ?? ""); };

/** Do two compared values match, as the run would read them: numbers within the tolerance, text in its case. */
function same(a: string, b: string, kind: string, fold: boolean, tol: number) {
  if (kind === "number" && a !== "" && b !== "" && !Number.isNaN(Number(a)) && !Number.isNaN(Number(b)))
    return Math.abs(Number(a) - Number(b)) <= tol;
  return fold ? a.toLowerCase() === b.toLowerCase() : a === b;
}

/** Preview on the first rows: this side before and after its steps, the other side as it is compared. */
function Preview({ s, spec, which, check }: { s: SetupReady; spec: Spec; which: Which; check: ReactNode }) {
  const labels = sideLabels(s.names[0], s.names[1]);
  const q = (w: Which) => ({
    queryKey: ["setup-try", spec.canon, w, s.rev],
    queryFn: () => api.get<TryView>(`/api/setup/try?canon=${encodeURIComponent(spec.canon)}&which=${w}`),
  });
  const mine = useQuery(q(which));
  const theirs = useQuery(q(other(which)));
  const steps = (which === "A" ? spec.a_steps : spec.b_steps).length;
  const src = which === "A" ? spec.a_src : spec.b_src;
  const osrc = which === "A" ? spec.b_src : spec.a_src;
  const sw = which === "A" ? "a" : "b";
  const typed = spec.kind !== "text";
  const fold = caseOf(s, spec) === "ignore";
  const f = mine.data;
  const o = theirs.data;
  const [me, them] = which === "A" ? labels : [labels[1], labels[0]];
  /** Each shown row's match, as the run would read it; null where the other side has no such row. */
  const oks = f && !f.error && o && !o.error
    ? f.rows.map((_, r) => (r < o.rows.length ? same(cell(f, r, "Compared as"), cell(o, r, "Compared as"), spec.kind, fold, s.settings.tolerance) : null))
    : [];
  const shown = oks.filter((x) => x !== null).length;
  const heads = [`${src} · before`, steps ? `after step ${steps}` : "as read", `as ${spec.kind}`];   // a phone card labels its values with them
  return (
    <section className="panel vx-preview" aria-label="Preview">
      <div className="panel-head">
        <h4 className="vx-h">Preview on the first rows</h4>
        {shown > 0 && <span className="sub">{num(oks.filter((x) => x === true).length)} of {plural(shown, "shown row")} match after these steps</span>}
        {check}
      </div>
      {f?.error ? <div className="vx-check"><ErrorNote role="alert">{f.error}</ErrorNote></div>
        : f && f.columns.length ? (
        <>
          <div className="tblwrap">
            <table className="tbl compact preview cards" aria-label="Preview on the first rows">
              <thead><tr>
                <th title={`${me} as it sits in the file`}><span className={`sw ${sw}`} />{heads[0]}</th>
                <th title={steps ? `${me} after its steps` : `${me} as it is read, with no steps`}>{heads[1]}</th>
                {typed && <th title={`${me} as it is compared`}>{heads[2]}</th>}
                <th title={`${them} as it is compared, the same row of its file`}><span className={`sw ${sw === "a" ? "b" : "a"}`} />{osrc}</th>
                <th className="match">Match</th>
              </tr></thead>
              <tbody>{f.rows.map((_, r) => {
                const conv = cell(f, r, "Converts");
                const theirsVal = o && !o.error ? cell(o, r, "Compared as") : "";
                const ok = oks[r] ?? null;
                return (
                  <tr key={r}>
                    <td className="m before" data-label={heads[0]}>{cell(f, r, "In the file")}</td>
                    <td className="m after" data-label={heads[1]}>{cell(f, r, "After the steps")}</td>
                    {typed && <td className={conv === "no" ? "m neg" : "m"} data-label={heads[2]}>{cell(f, r, "Compared as")}{conv === "no" && " · does not convert"}</td>}
                    <td className={`m ${sw === "a" ? "cb" : "ca"}`} data-label={osrc}>{theirsVal}</td>
                    <td className="match" data-label="Match">{ok === null ? <span className="dim">—</span>
                      : ok ? <Chip tone="pos"><Icon name="check" size="sm" label="matches" /></Chip>
                           : <Chip tone="neg"><Icon name="x" size="sm" label="differs" /></Chip>}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </>
      ) : <div className="vx-cap">{mine.isLoading ? "Reading the first rows…" : "No rows to show."}</div>}
    </section>
  );
}

/** Transform and convert values: one pair's steps per side, the step chips, the preview, the check. */
export function TransformBox({ s }: { s: SetupReady }) {
  const send = useSetupSend();
  const redo = useStepsRebuild();
  const meta = useStepsMeta();
  const { pair } = useView();
  const [picked, setMode] = useState<{ canon: string; mode: Mode } | null>(null);
  const [draft, setDraft] = useState<{ op: string; params: Record<string, string> } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const check = useMutation({ mutationFn: (canon: string) => api.send<CheckView>("POST", "/api/setup/check", { canon }) });
  const labels = sideLabels(s.names[0], s.names[1]);
  const m = meta.data;
  const spec = s.specs[pairIndex(s, pair)];
  if (!spec || !m) return null;
  const canon = spec.canon;
  const same = sameSteps(spec);
  // both sides alike (none included) open as one list; else the side with steps
  const fallback: Mode = same ? "both" : !spec.a_steps.length && spec.b_steps.length ? "B" : "A";
  // a picked Both holds only while the sides agree - never one list over two different sides
  const mode: Mode = picked?.canon === canon && (picked.mode !== "both" || same) ? picked.mode : fallback;
  const both = mode === "both";
  const which: Which = both ? "A" : mode;
  const sides: Which[] = both ? ["A", "B"] : [which];
  const steps = which === "A" ? spec.a_steps : spec.b_steps;
  const said = which === "A" ? spec.a_said : spec.b_said;
  const wi = which === "A" ? 0 : 1;
  const pending = busy || send.isPending || redo.isPending;

  const stepsCall = async (action: string, on: Which[] = sides) => {
    for (const w of on) await send.mutateAsync({ path: "/steps", body: { canon, which: w, action, step: null } });
  };
  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try { await work(); setErr(""); return true; } catch (e) { setErr(errorText(e)); return false; } finally { setBusy(false); }
  };
  /** The server keeps a side's steps as a list it adds to; a reorder or an edit is Clear, then each step again. */
  const was = (w: Which) => (w === "A" ? spec.a_steps : spec.b_steps);
  /** Both: a side that fails puts back the sides done before it, so the two never part. */
  const onEach = async (work: (w: Which) => Promise<unknown>, undo: (w: Which) => Promise<unknown>) => {
    const done: Which[] = [];
    try { for (const w of sides) { await work(w); done.push(w); } } catch (e) {
      for (const w of done) await undo(w).catch(() => undefined);
      throw e;
    }
  };
  const rebuild = (next: Step[]) => run(() => onEach(
    (w) => redo.mutateAsync({ canon, which: w, steps: next, was: was(w) }),
    (w) => redo.mutateAsync({ canon, which: w, steps: was(w), was: next })));
  /** Both: one list from now on - the steps on screen go to the other side too. */
  const choose = async (v: Mode) => {
    setDraft(null);
    if (v === "both" && !same && !(await run(() => stepsCall("copy", [which])))) return;   // not copied: stay apart
    setMode({ canon, mode: v });
  };
  const add = async (step: Step) => {
    const ok = await run(() => onEach(
      (w) => send.mutateAsync({ path: "/steps", body: { canon, which: w, action: "add", step } }),
      (w) => send.mutateAsync({ path: "/steps", body: { canon, which: w, action: "pop", step: null } })));
    if (ok) setDraft(null);
  };
  const pick = (op: string) => {
    const names = m.steps[op] ?? [];
    if (!names.length) { void add({ op, params: {} }); return; }
    setDraft({ op, params: Object.fromEntries(names.filter((k) => m.numeric.includes(k)).map((k) => [k, k === "n" ? "6" : "4"])) });
  };
  const draftStep = (): Step | null => draft && {
    op: draft.op, params: Object.fromEntries((m.steps[draft.op] ?? []).map((k) => [k, k === "fmt" ? (draft.params[k] ?? "").trim() : draft.params[k] ?? ""])),
  };
  const ck = check.variables === canon ? check : null;
  const report = ck?.data && !ck.data.said ? ck.data : null;
  const others = s.specs.map((x, j) => ({ x, j })).filter(({ x }) => x.canon !== canon && (x.a_steps.length || x.b_steps.length || x.kind !== "text"));

  const checkLine = (
    <>
      {report && (
        <span className="sub">
          {report.rows.map((_, r) => `${cell(report, r, "Side")}: ${num(Number(cell(report, r, "Converted")))} of ${num(Number(cell(report, r, "Values")))} convert`).join(" · ")}
        </span>
      )}
      <span className="actions">
        <Button size="sm" disabled={check.isPending} title="Counts the values on each side that do not convert." onClick={() => check.mutate(canon)}>
          {check.isPending ? "Checking…" : "Check this column on all rows"}
        </Button>
      </span>
    </>
  );

  return (
    <>
      <div className="panel-body">
        <Say spec={spec} labels={labels} />
        <div className="vx-sides">
          <Seg<Mode> label="Which side" value={mode} onChange={(v) => void choose(v)}
            options={[
              { value: "both", label: <span className="vx-side" title={same ? undefined : `Uses ${labels[wi]}'s steps on both sides`}><span className="sw a" /><span className="sw b" />Both sides{same ? ` · ${spec.a_steps.length}` : ""}</span> },
              ...(["A", "B"] as const).map((w, i) => ({
                value: w, label: <span className="vx-side"><span className={`sw ${w.toLowerCase()}`} />{labels[i]} steps · {(w === "A" ? spec.a_steps : spec.b_steps).length}</span>,
              })),
            ]} />
          {steps.length > 0 && <>
            <span className="grow" />
            {!both && <LinkButton disabled={pending} onClick={() => void run(() => stepsCall("copy"))}>Copy to {labels[1 - wi]}</LinkButton>}
            <LinkButton disabled={pending} onClick={() => void run(() => stepsCall("clear"))}>Clear</LinkButton>
          </>}
        </div>

        <div className="pipe" aria-label={both ? "Steps on both sides" : `${labels[wi]} steps`} role="list">
          {!steps.length && !draft && <div className="vx-empty" role="listitem">{both
            ? <>No steps - both sides are read as they are in the file.</>
            : <>No steps - {labels[wi]} reads <code>{which === "A" ? spec.a_src : spec.b_src}</code> as it is in the file.</>}</div>}
          {steps.map((st, i) => (
            <div className="pstep" role="listitem" key={`${i}-${st.op}`}>
              <span className="n">{i + 1}</span>
              <div className="op">
                <strong>{st.op}</strong>
                {(m.steps[st.op] ?? []).map((k) => (
                  <ParamBox key={k} k={k} m={m} value={String(st.params[k] ?? "")} label={`${m.labels[k] ?? k}, step ${i + 1}`}
                    onDone={(v) => void rebuild(steps.map((x, j) => (j === i ? { ...x, params: { ...x.params, [k]: v } } : x)))} />
                ))}
                {said[i] && said[i] !== st.op && !(m.steps[st.op] ?? []).length && <span className="sql">{said[i]}</span>}
              </div>
              <div className="actions">
                <Button size="sm" className="ico" aria-label={`Move step ${i + 1} up`} title="Move up" disabled={i === 0 || pending}
                  onClick={() => void rebuild(steps.map((x, j) => (j === i - 1 ? steps[i] : j === i ? steps[i - 1] : x)))}>↑</Button>
                <Button size="sm" className="ico" aria-label={`Remove step ${i + 1}`} title="Remove" disabled={pending}
                  onClick={() => void (i === steps.length - 1 ? run(() => stepsCall("pop")) : rebuild(steps.filter((_, j) => j !== i)))}><Icon name="x" size="sm" /></Button>
              </div>
            </div>
          ))}
          {draft && (
            <div className="pstep draft" role="listitem">
              <span className="n">{steps.length + 1}</span>
              <div className="op">
                <strong>{draft.op}</strong>
                <DraftParams op={draft.op} m={m} params={draft.params} setParams={(p) => setDraft({ ...draft, params: p })} />
              </div>
              <div className="actions">
                <Button size="sm" variant="primary" disabled={pending} onClick={() => { const st = draftStep(); if (st) void add(st); }}>{both ? "Add to both" : "Add step"}</Button>
                <Button size="sm" className="ico" aria-label="Cancel the new step" title="Cancel" onClick={() => setDraft(null)}><Icon name="x" size="sm" /></Button>
              </div>
            </div>
          )}
        </div>

        {err && <ErrorNote role="alert">{marks(err)}</ErrorNote>}

        <div className="field">
          <span className="vx-add-head">
            <span className="lbl" id="vx-add">Add a step</span>
            <span className="sub">{both ? `to both - ${labels[0]} and ${labels[1]}` : `to ${labels[wi]} only`}</span>
          </span>
          <div className="ops" role="group" aria-labelledby="vx-add">
            {Object.keys(m.steps).map((op) => (
              <button key={op} type="button" aria-pressed={draft?.op === op} disabled={pending} onClick={() => pick(op)}>
                {op}{(m.steps[op] ?? []).length ? "…" : ""}
              </button>
            ))}
          </div>
        </div>

        <Preview s={s} spec={spec} which={which} check={checkLine} />
        {ck?.error && <ErrorNote role="alert">{errorText(ck.error)}</ErrorNote>}
        {ck?.data?.said && <div className="note">{ck.data.said}</div>}
        {report && <FrameTable label="Conversion check" frame={report} />}
      </div>
      <div className="panel-foot">
        <span>Other conversions this run:</span>
        {!others.length && <span className="dim">none</span>}
        {others.map(({ x, j }) => {
          const one = (w: Which) => { const st = w === "A" ? x.a_steps : x.b_steps, sd = w === "A" ? x.a_said : x.b_said;
                                      return st.length ? fewWords(st, sd) : "as in the file"; };
          const has = x.a_steps.length || x.b_steps.length;
          const words = !has ? "" : sameSteps(x) ? `both: ${one("A")}` : `${labels[0]}: ${one("A")} · ${labels[1]}: ${one("B")}`;
          const title = [x.a_said.length ? `${labels[0]}: ${x.a_said.join(" → ")}` : "", x.b_said.length ? `${labels[1]}: ${x.b_said.join(" → ")}` : ""].filter(Boolean).join("\n");
          return (
            <span className="vx-other" key={x.canon}>
              <button type="button" className="chip" onClick={() => setView({ pair: j })} aria-label={`Edit ${x.a_src} and ${x.b_src}`}>{x.canon}</button>
              <span className="m" title={title || undefined}>{words}{x.kind !== "text" ? `${words ? " → " : "read as "}${x.kind}` : ""}</span>
            </span>
          );
        })}
      </div>
    </>
  );
}
