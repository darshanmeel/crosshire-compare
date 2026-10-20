// web/src/profiling/ProfileView.tsx - the profile of one table (screen 15): the verdict and a row of
// findings across the table (GET /api/profiling/findings), then two columns - the Columns panel and
// Could be another type on the left; key candidates, what stands out and the value frequencies on
// the right. Under What stands out, Outliers, Patterns and Dependencies are chips that open their
// tables across the page below (the dependencies with their strongest pairs and graph). The files
// are in the rail.
import { useState } from "react";
import { usePick } from "../results/pickStore";
import { Bar, Button, Callout, Chip, LinkButton, MenuButton, num, Panel, pctText, Pill } from "../ui/kit";
import { Icon } from "../ui/icons";
import { marks } from "../ui/marks";
import { castsOf, castType } from "./casts";
import { ColumnsTable, openColumn } from "./ColumnsTable";
import { DepGraph } from "./DepGraph";
import { DepMatrix, SHOWN as STRONG } from "./DepMatrix";
import { keyColumns, madeAt, rowsOf } from "./frame";
import { FrameTable } from "./FrameTable";
import { FreqSection } from "./FreqSection";
import { KeySearch } from "./KeySearch";
import { useKeySearch, useRunProfile } from "./actions";
import { Findings } from "./column/Findings";
import { standout, useFindings, type DepPair, type Finding, type FindingsBody } from "./standout";
import type { Profile, ProfilingView } from "./types";
import { useCasts } from "./useProfiling";
import "./profiling.css";
import "./overview.css";

export const NOTHING_STANDS_OUT = "Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.";
export const STALE = "This profile is from earlier settings - run it again to refresh.";

type Fold = "Outliers" | "Patterns" | "Dependencies";
const FOLDS: Fold[] = ["Outliers", "Patterns", "Dependencies"];
const FOLD_SAYS: Record<Fold, string> = { Outliers: "columns measured", Patterns: "shapes", Dependencies: "dependencies and correlations" };
const foldCount = (p: Profile, f: Fold) =>
  f === "Outliers" ? p.outliers.rows.length : f === "Patterns" ? p.patterns.rows.length : p.deps.rows.length + p.corr.rows.length;

function Verdict({ p, name, made, stale, f }: { p: Profile; name: string; made: string; stale: boolean; f?: FindingsBody }) {
  const stats = rowsOf(p.stats);
  const keys = keyColumns(p);
  const rows = Number(stats[0]?.Rows ?? 0);
  const nulls = stats.reduce((s, r) => s + Number(r.Nulls ?? 0), 0);
  const dup = /([\d,]+) duplicate rows?/.exec(p.headline)?.[1];
  const looks = (f?.looks ?? []).filter((l) => l.kind === "text").length;
  return (
    <section className="verdict prof-verdict" aria-label="Profile result">
      <div className="meta">
        <span className="eyebrow accent">Profile</span><span className="eyebrow">{name} · {madeAt(made)}</span>
        {stale && <Pill tone="warn">{STALE}</Pill>}
      </div>
      <p>
        {keys.length
          ? <>Key {keys.map((k, i) => <span key={k}>{i > 0 && " + "}<code>{k}</code></span>)} — unique on every row</>
          : <>No key — nothing up to four columns is unique</>}
        {" · "}<strong>{num(rows)}</strong> rows × <strong>{num(stats.length)}</strong> columns
        {" · "}<strong className={nulls ? "neg" : undefined}>{num(nulls)}</strong> nulls
        {dup !== undefined && <> · <strong className={dup !== "0" ? "neg" : undefined}>{dup}</strong> duplicate rows</>}
        {looks > 0 && <> · <strong className="neg">{num(looks)}</strong> {looks === 1 ? "column reads" : "columns read"} as text that {looks === 1 ? "looks" : "look"} like something else</>}
      </p>
      <span className="sub">{p.headline}</span>
      {f?.items?.length ? <Findings label="Table findings" items={f.items.map((i) => ({ tone: i.tone, label: i.label, detail: i.detail }))} /> : null}
    </section>
  );
}

/** A candidate's reasons, one per bullet - the figures already on its head line left out. */
function reasons(why: string): string[] {
  const shown = /^(\d[\d,]* nulls|[\d,]+ distinct of [\d,]+|[\d,]+ rows share it|no nulls)$/;
  return [...new Set(why.split(" · ").map((x) => x.trim()).filter((x) => x && !shown.test(x)))];
}

/** The key note split into its sentences, each once. */
function sentences(text: string): string[] {
  return [...new Set(text.split(/\.\s+|\s+-\s+(?=[A-Za-z`*])/).map((x) => x.trim().replace(/\.$/, "")).filter(Boolean))];
}

/** A candidate's counts, each a bar with its count and share: distinct of the rows with no null in
 *  the key, and the duplicate and null-key rows of all rows. */
function KeyFigs({ r }: { r: Record<string, unknown> }) {
  const d = Number(r.Distinct ?? 0), dup = Number(r["Duplicate rows"] ?? 0), nk = Number(r["Null keys"] ?? 0);
  const filled = d + dup, rows = filled + nk;
  const fig = (label: string, n: number, of: number, tone: "ok" | "accent" | "warn", title: string) => {
    const p = of ? (n / of) * 100 : 0;
    return (
      <span className="kfig" title={`${num(n)} ${title} of ${num(of)}`}>
        {label}<span className="n">{num(n)}</span><Bar pct={p} tone={tone} label={`${pctText(n, of)}%`} />
      </span>
    );
  };
  return (
    <span className="kfigs">
      {fig("distinct", d, filled, d === filled ? "ok" : "accent", "distinct of the non-null rows")}
      {fig("duplicates", dup, rows, dup ? "warn" : "ok", "duplicate rows")}
      {fig("null keys", nk, rows, nk ? "warn" : "ok", "rows with a null in the key")}
    </span>
  );
}

/** One key candidate: its columns, whether they are unique and its counts on one line. The winner
 *  says its reasons in its box; the others keep their figures and reasons a "why" click away. */
function KeyRow({ r, win }: { r: Record<string, unknown>; win: boolean }) {
  const [open, setOpen] = useState(false);
  const unique = r.Unique === "yes";
  const why = reasons(String(r.Why ?? ""));
  const d = Number(r.Distinct ?? 0), dup = Number(r["Duplicate rows"] ?? 0), nk = Number(r["Null keys"] ?? 0);
  const all = d + dup + nk;
  const cols = String(r["Key columns"]);
  return (
    <li className={win ? "win" : undefined}>
      <span className="head">
        {cols.split(" + ").map((c) => <Chip key={c} tone={win ? "key" : undefined}>{c}</Chip>)}
        <span className={unique ? "yes" : "no"}>{unique ? (cols.includes(" + ") ? "unique together" : "unique by itself") : "not unique"}</span>
        <span className="key-sum">· {num(d)} distinct of {num(all)} · {nk ? `${num(nk)} null keys` : "no nulls"}</span>
        {!win && <LinkButton className={open ? "why-btn open" : "why-btn"} iconAfter="chevron" aria-expanded={open}
                             aria-label={`why - ${cols}`} onClick={() => setOpen(!open)}>why</LinkButton>}
      </span>
      {win && <span className="why-line">· {[`${num(dup)} duplicate rows`, ...why].map((w, k) => <span key={k}>{k > 0 && " · "}{marks(w)}</span>)}</span>}
      {!win && open && <div className="why-body">
        <KeyFigs r={r} />
        {why.length > 0 && <ul className="why">{why.map((w, k) => <li key={k}>{marks(w)}</li>)}</ul>}
      </div>}
    </li>
  );
}

/** The key: the winner in one box, every other candidate on one line; the engine's note, its first
 *  sentence shown and the rest a click away; how far the search goes in a popover, with Profile
 *  again beside the note when the settings changed. */
function KeyCandidates({ p, name }: { p: Profile; name: string }) {
  const rows = rowsOf(p.keys.table);
  const [s] = useKeySearch();
  const { go, busy } = useRunProfile(name);
  const [more, setMore] = useState(false);
  const done = p.search;
  const differs = done.key_cols !== s.key_cols || done.top_keys !== s.top_keys || done.shortlist !== s.shortlist;
  const said = sentences(p.keys.text);
  return (
    <Panel title="Key candidates" sub={`single columns first, then combinations up to ${done.key_cols}`}
      actions={<MenuButton label="Search settings" group="Key search settings" wide>
        <p className="caption">This profile: combinations up to {done.key_cols}
          {done.key_sample ? <> found on a random sample of {num(done.key_sample)} rows, the best {done.shortlist} checked on every row</> : null}
          {" "}- the best {done.top_keys} listed.</p>
        <KeySearch />
      </MenuButton>}>
      <div className="panel-body">
        {rows.length > 0 && (
          <ul className="prof-keys" aria-label="Key candidates">
            {rows.map((r, i) => <KeyRow key={i} r={r} win={r.Unique === "yes" && i === 0} />)}
          </ul>
        )}
        {p.keys.tone === "success"
          ? <p className="caption prof-keynote">
              {said.slice(0, more ? said.length : 1).map((x, i) => <span key={i}><span>{marks(x)}</span>. </span>)}
              {said.length > 1 && <LinkButton aria-expanded={more} onClick={() => setMore(!more)}>{more ? "less" : "how it was found"}</LinkButton>}
            </p>
          : <Callout tone="warn" icon="key"><ul className="prof-said">{said.map((x, i) => <li key={i}>{marks(x)}</li>)}</ul></Callout>}
        {differs && (
          <div className="row key-differs">
            <span className="caption">this profile used up to {done.key_cols} · the best {done.shortlist} checked · {done.top_keys} listed - the search settings differ</span>
            <Button size="sm" icon="refresh" disabled={busy} onClick={go}>Profile again</Button>
          </div>
        )}
      </div>
    </Panel>
  );
}

const SHOWN = 8;

/** One finding: what it is, then the columns it is about, each with its figure. */
function FindingRow({ f }: { f: Finding }) {
  const extra = f.hits.length - SHOWN + (f.more ?? 0);
  return (
    <li>
      <span className="what">{f.title}</span>
      <span className="cols">
        {f.hits.slice(0, SHOWN).map((h, i) => (
          <span key={i} className="hit"><code>{h.col}</code>{h.fig && <span className="fig">{h.fig}</span>}</span>
        ))}
        {extra > 0 && <span className="fig">and {num(extra)} more</span>}
      </span>
    </li>
  );
}

function FoldBody({ p, fold }: { p: Profile; fold: Fold }) {
  if (fold === "Outliers")
    return p.outliers.rows.length
      ? <><p className="caption">One row per number, date and timestamp column: percentiles, Tukey's fences (1.5 × IQR) and the values outside them, zeros and negatives.</p>
          <FrameTable t={p.outliers} label="Outliers" /></>
      : <p className="caption">No number, date or timestamp columns - nothing to measure.</p>;
  if (fold === "Patterns")
    return p.patterns.rows.length
      ? <><p className="caption">The three most common shapes of each text and number column - a letter is A, a digit 9, the rest as written, so a number shows its digits before and after the point - with the first value of each shape.</p>
          <FrameTable t={p.patterns} label="Patterns" /></>
      : <p className="caption">No text or number columns with values - no shapes to show.</p>;
  return (
    <>
      <DepMatrix m={p.matrix} note={p.matrix_note} />
      {p.deps.rows.length
        ? <><DepGraph deps={p.deps} corr={p.corr} />
            <p className="caption">Functional dependencies - X → Y: every X has one Y; one-to-one when it holds the other way too.</p>
            <FrameTable t={p.deps} label="Dependencies" /></>
        : <>{p.corr.rows.length > 0 && <DepGraph deps={p.deps} corr={p.corr} />}<p className="caption">No column determines another.</p></>}
      {p.corr.rows.length
        ? <><p className="caption">Correlated number columns - |r| ≥ 0.7, the strongest first.</p>
            <FrameTable t={p.corr} label="Correlations" /></>
        : <p className="caption">No correlated number columns.</p>}
    </>
  );
}

/** Text columns that would read as another type: the column, the type it would take, how many
 *  of its values would - the column opens its detail. */
function CouldBeTypes({ made }: { made: string }) {
  const rows = useCasts(made).data?.columns ?? [];
  if (!rows.length) return null;
  return (
    <Panel title="Could be another type" sub="read as text or a number, but the values read as a number, a date or a timestamp">
      <div className="panel-body">
        <ul className="prof-points" aria-label="Could be another type">
          {rows.map((r) => {
            const [{ kind, hit }] = castsOf(r);
            const { type, form } = castType(kind, hit);
            const p = (100 * hit.any) / r.filled;
            return (
              <li key={r.column} className={hit.any === r.filled ? "ok" : "warn"}>
                <span className="dot" aria-hidden="true" />
                <span className="l"><button type="button" className="col-open" onClick={() => openColumn(r.column)}>{r.column}</button></span>
                <span className="v"><Bar pct={p} tone={hit.any === r.filled ? "ok" : "warn"} label={<>{num(hit.any)} <span className="pc">· {pctText(hit.any, r.filled)}%</span></>} /></span>
                <span className="n">{r.kind} → <code>{type}</code>{form && <> · <code>{form}</code></>}{hit.any < r.filled ? ` · ${num(r.filled - hit.any)} would not convert` : ""}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </Panel>
  );
}

/** The strongest pairs of the dependency matrix, the key left out: X → Y, a bar for how far X
 *  decides Y beyond chance, faint under STRONG; and what the strongest full pair is, in counts. */
function DepPairs({ p, pairs, keys }: { p: Profile; pairs: DepPair[]; keys: string[] }) {
  if (!pairs.length) return null;
  const distinct = Object.fromEntries(rowsOf(p.stats).map((r) => [String(r.Column), Number(r.Distinct ?? 0)]));
  const full = pairs.find((x) => x.v >= 100);
  const back = full && pairs.find((x) => x.x === full.y && x.y === full.x);
  return (
    <Panel className="dep-pairs" title="Dependencies across the table" sub="how far one column decides another beyond chance · 0 is chance, 100% every value has one">
      <div className="panel-body">
        <ul className="dep-pairs-list" aria-label="Strongest dependencies">
          {pairs.map((x) => (
            <li key={`${x.x}>${x.y}`} className={x.v < STRONG ? "faint" : undefined}>
              <span className="xy"><code>{x.x}</code><Icon name="arrow" size="sm" /><code>{x.y}</code></span>
              <Bar pct={x.v} tone={x.v >= 100 ? "ok" : "accent"} />
              <span className="v">{x.v.toFixed(2)}%</span>
            </li>
          ))}
        </ul>
        <p className="caption">
          {keys.length > 0 && <>The key ({keys.join(" + ")}) decides every column by being unique and is left out. </>}
          {full && <>Every {full.x} has one {full.y}: {num(distinct[full.x] ?? 0)} values of {full.x} go with {num(distinct[full.y] ?? 0)} of {full.y}
            {back ? <>; the other way, {full.y} decides {full.x} {back.v.toFixed(2)}%</> : null}. </>}
          Under {STRONG}% is faint - not conclusive.{p.matrix_note && <> Measured {p.matrix_note}.</>}
        </p>
      </div>
    </Panel>
  );
}

/** The verdict, then the Columns table beside the key, what stands out and the frequencies - one
 *  column below 1100 px - and the table a chip opened, across the page. */
export function ProfileView({ view, name }: { view: ProfilingView; name: string }) {
  const p = view.profile!;
  const keys = keyColumns(p);
  const found = standout(p.notes);
  const casts = useCasts(view.made);
  const f = useFindings(view.made, casts.isSuccess).data;
  const pairs = f?.pairs ?? [];
  const [fold, setFold] = usePick<string>("prof_fold", "");
  const open = FOLDS.find((x) => x === fold);
  return (
    <>
      <Verdict p={p} name={name} made={view.made} stale={view.stale} f={f} />
      <div className="split prof-split">
        <div className="main">
          <ColumnsTable p={p} keyCols={keys} findings={f} />
          <CouldBeTypes made={view.made} />
        </div>
        <div className="side">
          <KeyCandidates p={p} name={name} />
          <Panel title="What stands out" sub="each finding once, with the columns it is about">
            <div className="panel-body">
              {found.length
                ? <ul className="prof-found">{found.map((f) => <FindingRow key={f.title} f={f} />)}</ul>
                : <ul className="bullets"><li><i className="ok" /><span>{NOTHING_STANDS_OUT}</span></li></ul>}
              <div className="prof-chips" role="group" aria-label="Tables">
                {FOLDS.map((x) => {
                  const n = foldCount(p, x);
                  return (
                    <button key={x} type="button" className="fchip" aria-expanded={open === x} aria-controls={`fold-${x}-body`}
                            title={`${num(n)} ${FOLD_SAYS[x]}`} onClick={() => setFold(open === x ? "" : x)}>
                      <span>{x}</span>{" "}<span className="c">{num(n)}</span><Icon name="chevron" size="sm" />
                    </button>
                  );
                })}
              </div>
            </div>
          </Panel>
          <FreqSection p={p} made={view.made} />
        </div>
      </div>
      {open && (
        <div className="prof-stack prof-opened">
          {open === "Dependencies" && <DepPairs p={p} pairs={pairs} keys={keys} />}
          <Panel className="prof-fold" title={<span id={`fold-${open}`}>{open}</span>}>
            <div className="panel-body" id={`fold-${open}-body`} role="region" aria-labelledby={`fold-${open}`}>
              <FoldBody p={p} fold={open} />
            </div>
          </Panel>
        </div>
      )}
    </>
  );
}
