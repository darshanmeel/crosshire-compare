// web/src/keys/KeyBox.tsx - "How they pair up" (SPEC §06): the match mode, the key columns as chips
// (A column ⇄ B column), Add a column, Suggest keys (a job; candidates as chips, chosen on click),
// Check key and its uniqueness line, and a key the two sides write differently - fixed when simple,
// offered when not.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LogEntry } from "../api/client";
import { useJobOfKind } from "../api/useJob";
import { RunDisc } from "../shell/RunDisc";
import { Icon } from "../ui/icons";
import { Button, Callout, LinkButton, Seg } from "../ui/kit";
import { marks } from "../ui/marks";
import { Tips } from "../ui/Tips";
import { errorText, refreshSetup, SETUP_KEY, useSetup, type KeysView, type Said, type SetupView } from "../setup/api";
import { FrameTable } from "../setup/FrameTable";
import "./keys.css";

export const KEYS_KEY = ["setup-keys"];

type Mode = "key" | "position" | "hash";

function Line({ said }: { said: Said }) {
  return said.tone === "caption" ? <p className="caption">{marks(said.text)}</p> : <div className={`note ${said.tone}`}>{marks(said.text)}</div>;
}

/** The figure a suggestion's row says beside its columns - its overlap when the frame has one. */
function overlapOf(columns: string[], row: unknown[] | undefined): string {
  if (!row) return "";
  const i = columns.findIndex((c) => /overlap|%/i.test(c));
  return i >= 0 && row[i] != null && row[i] !== "" ? `${row[i]}${/%/.test(columns[i]) && !String(row[i]).includes("%") ? "%" : ""}` : "";
}

/** The match mode, the key and everything that checks it. */
export function KeyBox() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEYS_KEY, queryFn: () => api.get<KeysView>("/api/setup/keys") });
  const { data: setup } = useSetup();
  const [picks, setPicks] = useState<number[]>([]);
  const [err, setErr] = useState("");
  const [wantKey, setWantKey] = useState(false);      // "On a key" pressed with no key yet: the picker shows
  const [adding, setAdding] = useState(false);
  const keysCall = useMutation({
    mutationFn: ({ method = "POST", path, body }: { method?: "POST" | "DELETE" | "PUT"; path: string; body?: unknown }) =>
      api.send<KeysView>(method, path, body),
    onSuccess: (v) => {
      setErr(v && "error" in v ? v.error : "");
      refreshSetup(qc);
    },
    onError: (e) => setErr(errorText(e)),
  });
  /** Key ticks in the column table, one cell at a time, each sent with the rev the last one answered. */
  const ticks = useMutation({
    mutationFn: async ({ on, off }: { on?: string; off: string[] }) => {
      let s = qc.getQueryData<SetupView>(SETUP_KEY) ?? setup;
      if (!s?.ready) throw new Error("Load both files first.");
      const send = async (name: string, value: boolean) => {
        const row = s!.ready ? s!.rows.findIndex((r) => r["Common name"] === name && r.Key !== value) : -1;
        if (row < 0 || !s!.ready) return;
        s = await api.send<SetupView>("POST", "/api/setup/cell", { rev: s!.rev, row, column: "Key", value });
      };
      for (const name of off) await send(name, false);
      if (on) await send(on, true);
      return s!;
    },
    onSuccess: (s) => { setErr(""); qc.setQueryData(SETUP_KEY, s); refreshSetup(qc); },
    onError: (e) => { setErr(errorText(e)); refreshSetup(qc); },
  });
  const suggest = useMutation({
    mutationFn: () => api.send<LogEntry>("POST", "/api/setup/keys/suggest"),
    onSuccess: (e) => { setErr(""); setPicks([]); follow(e.id); qc.invalidateQueries({ queryKey: ["log"] }); },
    onError: (e) => setErr(errorText(e)),
  });
  const { follow, busy, running } = useJobOfKind("Key search", "Compare", "", (e) => {
    if (e.state === "error") setErr(e.lines.at(-1) ?? e.label);
    qc.invalidateQueries({ queryKey: KEYS_KEY });
  });
  const k = q.data;
  if (!k) return q.error ? <div className="note error">{errorText(q.error)}</div> : null;
  const s = k.suggestions;
  const chosen = s ? [...new Set(picks.flatMap((i) => s.combos[i] ?? []))] : [];
  const rows = setup?.ready ? setup.rows : [];
  const pairOf = (name: string) => rows.find((r) => r["Common name"] === name);
  const addable = rows.filter((r) => r["A column"] && r["B column"] && !r.Key);
  const mode: Mode = k.keys.length || wantKey ? "key" : k.nokey_mode;
  const pending = ticks.isPending || keysCall.isPending;
  const pickMode = (m: Mode) => {
    setErr("");
    if (m === "key") { setWantKey(true); setAdding(true); return; }
    setWantKey(false); setAdding(false);
    const put = () => keysCall.mutate({ method: "PUT", path: "/api/setup/settings", body: { nokey_mode: m } });
    if (k.keys.length) ticks.mutate({ off: k.keys }, { onSuccess: put });
    else put();
  };
  const addKey = (name: string) => { if (name) ticks.mutate({ on: name, off: [] }, { onSuccess: () => { setAdding(false); setWantKey(false); } }); };
  const checking = keysCall.isPending && keysCall.variables?.path === "/api/setup/keys/check";
  return (
    <div className="card pairup">
      <div className="pairup-top">
        <div className="field">
          <span className="lbl">Match rows</span>
          <Seg<Mode> label="Match mode" value={mode} onChange={pickMode}
            options={[{ value: "key", label: "On a key", icon: "key", disabled: pending },
                      { value: "position", label: "By position", disabled: pending, title: k.nokey_modes.position },
                      { value: "hash", label: "By hash of compared columns", disabled: pending, title: k.nokey_modes.hash }]} />
        </div>
        <div className="field pairup-keys">
          <span className="lbl">Key columns</span>
          <div className="row">
            {mode === "key" && k.keys.map((name) => {
              const r = pairOf(name);
              return (
                <span key={name} className="chip key">
                  <Icon name="key" size="sm" />
                  {r && r["A column"] && r["B column"] ? <>{r["A column"]} ⇄ {r["B column"]}</> : name}
                  <button type="button" className="chip-x" aria-label={`Remove ${name} from the key`} disabled={pending}
                          onClick={() => ticks.mutate({ off: [name] })}><Icon name="x" size="sm" /></button>
                </span>
              );
            })}
            {mode !== "key" && <span className="caption">no key - {k.nokey_modes[k.nokey_mode]}</span>}
            {adding ? (
              <select className="in mono" aria-label="Add a key column" value="" disabled={pending} autoFocus
                      onChange={(e) => addKey(e.target.value)} onBlur={() => !wantKey && setAdding(false)}>
                <option value="">Pick a column…</option>
                {addable.map((r) => <option key={r["Common name"]} value={r["Common name"]}>{r["A column"]} ⇄ {r["B column"]}</option>)}
              </select>
            ) : (
              <LinkButton icon="plus" disabled={pending || !addable.length} onClick={() => setAdding(true)}>Add a column</LinkButton>
            )}
            <Button size="sm" icon="sparkle" disabled={busy || suggest.isPending} onClick={() => suggest.mutate()}
                    title="Finds the column combinations that identify a row on both sides, a level at a time - every column, then every pair, then three, then four - counted on the first side and verified on the second, with Desbordante (HyUCC / PyroUCC) when it is installed. Minutes on a wide or big pair. Only runs when pressed.">
              Suggest keys
            </Button>
            <Button size="sm" icon="check" disabled={!k.keys.length || pending} title="Counts distinct key values against rows on each side."
                    onClick={() => keysCall.mutate({ path: "/api/setup/keys/check" })}>
              {checking ? "Counting distinct keys on both sides…" : "Check key"}
            </Button>
          </div>
          {k.report
            ? <div className={`pairup-line ${k.report.said.tone}`}>{marks(k.report.said.text)}</div>
            : <span className="pairup-line">{k.keys.length
                ? <>Rows are matched on <strong>{k.keys.join(" + ")}</strong> · <em>Check key</em> counts its uniqueness and overlap · up to four columns can form a key together</>
                : wantKey ? "Pick a column to match rows on, or press Suggest keys." : "Rows can still be compared without a key."}</span>}
        </div>
      </div>

      {running && <RunDisc entry={running} />}
      {err && <div className="note error">{marks(err)}</div>}

      {s && (
        <div className="pairup-sugg">
          <Line said={s.said} />
          <div className="row" role="group" aria-label="Use these">
            {s.labels.map((l, i) => {
              const on = picks.includes(i);
              const ov = overlapOf(s.columns, s.rows[i]);
              return (
                <button key={i} type="button" className={`chip cand${on ? " on" : ""}`} aria-pressed={on}
                        onClick={() => setPicks(on ? picks.filter((x) => x !== i) : [...picks, i])}>
                  {on && <Icon name="check" size="sm" />}{l}{ov && <span className="ov">{ov}</span>}
                </button>
              );
            })}
          </div>
          {chosen.length > 0 && <p className="caption">{marks(`Key would be **${chosen.join(" + ")}**`)}</p>}
          <div className="row">
            <Button variant="primary" size="sm" disabled={!chosen.length}
                    onClick={() => { keysCall.mutate({ path: "/api/setup/keys/use", body: { picks } }); setPicks([]); setWantKey(false); }}>Use as key</Button>
            <Button size="sm" onClick={() => keysCall.mutate({ method: "DELETE", path: "/api/setup/keys/suggest" })}>Dismiss</Button>
          </div>
          <details className="pairup-more">
            <summary>Every figure of the search</summary>
            <FrameTable label="Suggested keys" frame={s} />
          </details>
        </div>
      )}

      {k.report && <FrameTable label="Key check" frame={k.report} />}

      {k.formats.length > 0 && (
        <div className="pairup-formats">
          {k.formats.map((f, i) => (
            <div key={i} className="row format">
              <Line said={f} />
              {f.apply != null && <Button variant="primary" size="sm" onClick={() => keysCall.mutate({ path: `/api/setup/keys/formats/${f.apply}/apply` })}>Apply</Button>}
            </div>
          ))}
          {k.formats[0].tone !== "caption" && (
            <div><Button size="sm" onClick={() => keysCall.mutate({ method: "DELETE", path: "/api/setup/keys/formats" })}>Dismiss</Button></div>
          )}
        </div>
      )}

      <Callout>
        <span className="pairup-explain"><strong>By position</strong> pairs line 1 with line 1 - for exports that keep their order.{" "}
          <strong>By hash</strong> finds rows that are identical across every compared column - when nothing identifies a row.</span>
        <Tips items={mode === "key" ? k.tips : k.nokey_tips} />
      </Callout>
    </div>
  );
}
