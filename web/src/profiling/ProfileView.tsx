// web/src/profiling/ProfileView.tsx - the profile of one table (screen 15): the verdict and a row of
// findings across the table (GET /api/profiling/findings), the Columns panel across the page, then
// what stands out folded into a few findings, the key candidates beside the strongest dependencies
// - then the Outliers, Patterns and Dependencies tables across the page (the dependencies drawn as
// a graph too), the value frequencies and the files.
import { Bar, Callout, Chip, num, Panel, pctText, Pill } from "../ui/kit";
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
import { SaveRow } from "./SaveRow";
import { Findings } from "./column/Findings";
import { standout, useFindings, type DepPair, type Finding, type FindingsBody } from "./standout";
import type { Profile, ProfilingView } from "./types";
import { useCasts, useSaveDefaults } from "./useProfiling";
import "./profiling.css";
import "./overview.css";

export const NOTHING_STANDS_OUT = "Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.";
export const STALE = "This profile is from earlier settings - run it again to refresh.";

type Fold = "Outliers" | "Patterns" | "Dependencies";
const FOLDS: Fold[] = ["Outliers", "Patterns", "Dependencies"];

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

function KeyCandidates({ p }: { p: Profile }) {
  const rows = rowsOf(p.keys.table);
  return (
    <Panel title="Key candidates" sub={`single columns first, then combinations up to ${p.search.key_cols}`
      + (p.search.key_sample ? ` found on a random sample, the best ${p.search.shortlist} checked on every row` : "")
      + ` - the best ${p.search.top_keys}`}>
      <div className="panel-body">
        <KeySearch done={p.search} />
        {p.keys.tone === "success"
          ? <ul className="prof-said prof-keynote">{sentences(p.keys.text).map((x, i) => <li key={i}>{marks(x)}</li>)}</ul>
          : <Callout tone="warn" icon="key"><ul className="prof-said">{sentences(p.keys.text).map((x, i) => <li key={i}>{marks(x)}</li>)}</ul></Callout>}
        {rows.length > 0 && (
          <ul className="prof-keys" aria-label="Key candidates">
            {rows.map((r, i) => {
              const unique = r.Unique === "yes";
              const why = reasons(String(r.Why ?? ""));
              const d = Number(r.Distinct ?? 0), nk = Number(r["Null keys"] ?? 0);
              const all = d + Number(r["Duplicate rows"] ?? 0) + nk;
              return (
                <li key={i}>
                  <span className="head">
                    {String(r["Key columns"]).split(" + ").map((c) => <Chip key={c} tone={unique && i === 0 ? "key" : undefined}>{c}</Chip>)}
                    <span className={unique ? "yes" : "no"}>{unique ? (String(r["Key columns"]).includes(" + ") ? "unique together" : "unique by itself") : "not unique"}</span>
                    <span className="key-sum">· {num(d)} distinct of {num(all)} · {nk ? `${num(nk)} null keys` : "no nulls"}</span>
                  </span>
                  <KeyFigs r={r} />
                  {why.length > 0 && <ul className="why">{why.map((w, k) => <li key={k}>{marks(w)}</li>)}</ul>}
                </li>
              );
            })}
          </ul>
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

/** The verdict, the Columns table across the page, then the findings, frequencies and files -
 *  two to a row on a wide screen, one on a phone. */
export function ProfileView({ view, name }: { view: ProfilingView; name: string }) {
  const p = view.profile!;
  const defaults = useSaveDefaults(name, view.made).data;
  const keys = keyColumns(p);
  const found = standout(p.notes);
  const casts = useCasts(view.made);
  const f = useFindings(view.made, casts.isSuccess).data;
  const pairs = f?.pairs ?? [];
  return (
    <>
      <Verdict p={p} name={name} made={view.made} stale={view.stale} f={f} />
      <div className="prof-stack">
        <ColumnsTable p={p} keyCols={keys} findings={f} />
        <Panel title="What stands out" sub="each finding once, with the columns it is about">
          <div className="panel-body">
            {found.length
              ? <ul className="prof-found">{found.map((f) => <FindingRow key={f.title} f={f} />)}</ul>
              : <ul className="bullets"><li><i className="ok" /><span>{NOTHING_STANDS_OUT}</span></li></ul>}
          </div>
        </Panel>
        <CouldBeTypes made={view.made} />
        <div className={pairs.length ? "prof-duo" : "prof-one"}>
          <KeyCandidates p={p} />
          <DepPairs p={p} pairs={pairs} keys={keys} />
        </div>
        {FOLDS.map((f) => (
          <Panel key={f} className="prof-fold" title={<span id={`fold-${f}`}>{f}</span>}>
            <div className="panel-body" id={`fold-${f}-body`} role="region" aria-labelledby={`fold-${f}`}>
              <FoldBody p={p} fold={f} />
            </div>
          </Panel>
        ))}
        <div className="prof-grid">
          <FreqSection p={p} made={view.made} />
          <div id="profile-files"><Panel title="Files" sub="the statistics as a CSV, or all six tables into a folder">
            <div className="panel-body">
              <div className="row">
                <a className="btn" href={`/api/profiling/profile.csv?name=${encodeURIComponent(name)}`} download={defaults?.csv_name}>
                  <Icon name="download" />Download profile.csv</a>
              </div>
              {defaults && <SaveRow made={view.made} folder={defaults.save_folder} name={name} />}
            </div>
          </Panel></div>
        </div>
      </div>
    </>
  );
}
