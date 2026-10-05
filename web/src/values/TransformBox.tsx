import { useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { marks } from "../ui/marks";
import { Icon } from "../ui/icons";
import { Button, Chip, num, Pill, Seg, type Tone as PillTone } from "../ui/kit";
import { errorText, useSetupSend, useStepsRebuild, type CheckView, type Frame, type SetupReady, type Spec, type Step, type StepsMeta, type TryView } from "../setup/api";
import { FrameTable } from "../setup/FrameTable";
import { sideLabels } from "../sources/names";
import { setView, useView } from "../shell/view";
import "./values.css";

type Which = "A" | "B";
const other = (w: Which): Which => (w === "A" ? "B" : "A");

/** The pair the editor shows: the view's pair, kept inside the list. */
export const pairIndex = (s: SetupReady, pair: number) => Math.max(0, Math.min(pair, s.specs.length - 1));

export const useStepsMeta = () =>
  useQuery({ queryKey: ["setup-steps"], queryFn: () => api.get<StepsMeta>("/api/setup/steps"), staleTime: Infinity });

/** "N", "find", "format" - a parameter's label cut to its name, as values.describe_step does. */
const shortLabel = (label: string) => label.split(" -")[0].split(",")[0];

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

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
      {send.error && <div className="note error" role="alert">{errorText(send.error)}</div>}
    </div>
  );
}

/** One line on what the steps do to this pair. */
function Say({ spec, labels }: { spec: Spec; labels: [string, string] }) {
  const sides = (["A", "B"] as const).filter((w) => (w === "A" ? spec.a_steps : spec.b_steps).length);
  if (!sides.length) return <p className="vx-say">Both sides are read as they are in the file, then compared as <b>{spec.kind}</b>.</p>;
  return (
    <p className="vx-say">
      {sides.map((w, i) => {
        const said = w === "A" ? spec.a_said : spec.b_said;
        return (
          <span key={w}>{i > 0 && "; "}{labels[w === "A" ? 0 : 1]} runs {plural(said.length, "step")} on <code>{w === "A" ? spec.a_src : spec.b_src}</code> ({said.join(" → ")})</span>
        );
      })}
      {sides.length === 1 && <>, {labels[sides[0] === "A" ? 1 : 0]} reads it as it is</>}; then both are compared as <b>{spec.kind}</b>.
    </p>
  );
}

/** A parameter box that keeps what is typed and hands it on when it is left. */
function ParamBox({ k, m, value, label, onDone }: { k: string; m: StepsMeta; value: string; label: string; onDone: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [was, setWas] = useState(value);
  if (value !== was) { setWas(value); setDraft(value); }
  const numeric = m.numeric.includes(k);
  return (
    <span className="vx-param">
      <span className="lbl" aria-hidden="true">{shortLabel(m.labels[k] ?? k)}</span>
      <input type={numeric ? "number" : "text"} aria-label={label} value={draft} className={k === "expr" ? "wide" : k === "fmt" ? "" : "short"}
             min={numeric ? 1 : undefined} max={numeric ? 100000 : undefined}
             onChange={(e) => setDraft(e.target.value)} onBlur={() => { if (draft !== value) onDone(draft); }}
             onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
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
        <span key={k} className="vx-param">
          <span className="lbl" aria-hidden="true">{shortLabel(m.labels[k] ?? k)}</span>
          <input type={m.numeric.includes(k) ? "number" : "text"} aria-label={m.labels[k] ?? k} value={params[k] ?? ""}
                 className={k === "expr" ? "wide" : "short"}
                 min={m.numeric.includes(k) ? 1 : undefined} max={m.numeric.includes(k) ? 100000 : undefined}
                 placeholder={k === "expr" ? "upper(split_part(x, '-', 1))" : undefined}
                 onChange={(e) => setParams({ ...params, [k]: e.target.value })} />
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
  return (
    <section className="panel vx-preview" aria-label="Preview">
      <div className="panel-head">
        <h4 className="vx-h">Preview on the first rows</h4>
        {check}
      </div>
      {f?.error ? <div className="vx-check"><div className="note error" role="alert">{f.error}</div></div>
        : f && f.columns.length ? (
        <>
          <div className="tblwrap">
            <table className="tbl compact preview" aria-label="Preview on the first rows">
              <thead><tr>
                <th><span className={`sw ${sw}`} />{src} · before</th>
                <th>{steps ? `after step ${steps}` : "as read"}</th>
                {typed && <th>as {spec.kind}</th>}
                <th><span className={`sw ${sw === "a" ? "b" : "a"}`} />{osrc}</th>
                <th className="match">Match</th>
              </tr></thead>
              <tbody>{f.rows.map((_, r) => {
                const conv = cell(f, r, "Converts");
                const theirsVal = o && !o.error ? cell(o, r, "Compared as") : "";
                const ok = o && !o.error && r < o.rows.length
                  ? same(cell(f, r, "Compared as"), theirsVal, spec.kind, fold, s.settings.tolerance) : null;
                return (
                  <tr key={r}>
                    <td className="m before">{cell(f, r, "In the file")}</td>
                    <td className="m after">{cell(f, r, "After the steps")}</td>
                    {typed && <td className={conv === "no" ? "m neg" : "m"}>{cell(f, r, "Compared as")}{conv === "no" && " · does not convert"}</td>}
                    <td className={`m ${sw === "a" ? "cb" : "ca"}`}>{theirsVal}</td>
                    <td className="match">{ok === null ? <span className="dim">—</span>
                      : ok ? <Chip tone="pos"><Icon name="check" size="sm" label="matches" /></Chip>
                           : <Chip tone="neg"><Icon name="x" size="sm" label="differs" /></Chip>}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          <div className="vx-cap">The first rows of each file, side by side as they sit in the file - {labels[which === "A" ? 0 : 1]} after its steps, {labels[which === "A" ? 1 : 0]} as it is compared.</div>
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
  const [picked, setWhich] = useState<{ canon: string; which: Which } | null>(null);
  const [draft, setDraft] = useState<{ op: string; params: Record<string, string> } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [both, setBoth] = useState(false);            // a new step goes to this side, or to both
  const check = useMutation({ mutationFn: (canon: string) => api.send<CheckView>("POST", "/api/setup/check", { canon }) });
  const labels = sideLabels(s.names[0], s.names[1]);
  const m = meta.data;
  const spec = s.specs[pairIndex(s, pair)];
  if (!spec || !m) return null;
  const canon = spec.canon;
  const which: Which = picked?.canon === canon ? picked.which : !spec.a_steps.length && spec.b_steps.length ? "B" : "A";
  const steps = which === "A" ? spec.a_steps : spec.b_steps;
  const said = which === "A" ? spec.a_said : spec.b_said;
  const wi = which === "A" ? 0 : 1;
  const pending = busy || send.isPending || redo.isPending;

  const stepsCall = async (action: string, step: Step | null = null) =>
    send.mutateAsync({ path: "/steps", body: { canon, which, action, step } });
  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try { await work(); setErr(""); return true; } catch (e) { setErr(errorText(e)); return false; } finally { setBusy(false); }
  };
  /** The server keeps a side's steps as a list it adds to; a reorder or an edit is Clear, then each step again. */
  const rebuild = (next: Step[]) => run(() => redo.mutateAsync({ canon, which, steps: next, was: steps }));
  const add = async (step: Step) => {
    const sides: Which[] = both ? ["A", "B"] : [which];
    if (await run(async () => { for (const w of sides) await send.mutateAsync({ path: "/steps", body: { canon, which: w, action: "add", step } }); })) setDraft(null);
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
        <Seg<Which> label="Which side" value={which} onChange={(w) => { setWhich({ canon, which: w }); setDraft(null); }}
          options={(["A", "B"] as const).map((w, i) => ({
            value: w, label: <span className="vx-side"><span className={`sw ${w.toLowerCase()}`} />{labels[i]} steps · {(w === "A" ? spec.a_steps : spec.b_steps).length}</span>,
          }))} />

        <div className="pipe" aria-label={`${labels[wi]} steps`} role="list">
          {!steps.length && !draft && <div className="vx-empty" role="listitem">No steps - {labels[wi]} reads <code>{which === "A" ? spec.a_src : spec.b_src}</code> as it is in the file.</div>}
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

        {steps.length > 0 && (
          <div className="vx-tools">
            <Button size="sm" disabled={pending} onClick={() => void run(() => stepsCall("copy"))}>Copy to {labels[1 - wi]}</Button>
            <Button size="sm" disabled={pending} onClick={() => void run(() => stepsCall("clear"))}>Clear</Button>
          </div>
        )}
        {err && <div className="note error" role="alert">{marks(err)}</div>}

        <div className="field">
          <span className="vx-add-head">
            <span className="lbl" id="vx-add">Add a step</span>
            <Seg<"one" | "both"> mini label="Add the step to" value={both ? "both" : "one"} onChange={(v) => setBoth(v === "both")}
              options={[{ value: "one", label: `${labels[wi]} only` }, { value: "both", label: `both - ${labels[0]} and ${labels[1]}` }]} />
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
        {ck?.error && <div className="note error" role="alert">{errorText(ck.error)}</div>}
        {ck?.data?.said && <div className="note">{ck.data.said}</div>}
        {report && <FrameTable label="Conversion check" frame={report} />}
      </div>
      <div className="panel-foot">
        <span>Other conversions this run:</span>
        {!others.length && <span className="dim">none</span>}
        {others.map(({ x, j }) => {
          const sides = (["A", "B"] as const).filter((w) => (w === "A" ? x.a_steps : x.b_steps).length);
          const items = sides.length ? sides : [null];
          return items.map((w) => (
            <span className="vx-other" key={`${x.canon}-${w ?? "type"}`}>
              <button type="button" className={`chip ${w ? w.toLowerCase() : ""}`} onClick={() => setView({ pair: j })}
                      aria-label={`Edit ${x.a_src} and ${x.b_src}`}>
                {w === "A" ? x.a_src : w === "B" ? x.b_src : x.canon}
              </button>
              <span className="m">{w ? (w === "A" ? x.a_said : x.b_said).join(" → ") : ""}{x.kind !== "text" ? `${w ? " → " : "read as "}${x.kind}` : ""}</span>
            </span>
          ));
        })}
      </div>
    </>
  );
}
