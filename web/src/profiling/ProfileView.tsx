// web/src/profiling/ProfileView.tsx - the profile of one table (screen 15): the verdict, the Columns
// panel across the page, then what stands out folded into a few findings, then the key candidates,
// each across the page - then the Outliers, Patterns and Dependencies tables across the page (the
// dependencies drawn as a graph too), the value frequencies and the files.
import { Bar, Callout, Chip, num, Panel, pctText, Pill } from "../ui/kit";
import { Icon } from "../ui/icons";
import { marks } from "../ui/marks";
import { castsOf, castType } from "./casts";
import { ColumnsTable, openColumn } from "./ColumnsTable";
import { DepGraph } from "./DepGraph";
import { DepMatrix } from "./DepMatrix";
import { keyColumns, madeAt, rowsOf } from "./frame";
import { FrameTable } from "./FrameTable";
import { FreqSection } from "./FreqSection";
import { KeySearch } from "./KeySearch";
import { SaveRow } from "./SaveRow";
import { standout, type Finding } from "./standout";
import type { Profile, ProfilingView } from "./types";
import { useCasts, useSaveDefaults } from "./useProfiling";
import "./profiling.css";

export const NOTHING_STANDS_OUT = "Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.";
export const STALE = "This profile is from earlier settings - run it again to refresh.";

type Fold = "Outliers" | "Patterns" | "Dependencies";
const FOLDS: Fold[] = ["Outliers", "Patterns", "Dependencies"];

function Verdict({ p, name, made, stale }: { p: Profile; name: string; made: string; stale: boolean }) {
  const stats = rowsOf(p.stats);
  const keys = keyColumns(p);
  const rows = Number(stats[0]?.Rows ?? 0);
  const nulls = stats.reduce((s, r) => s + Number(r.Nulls ?? 0), 0);
  const dup = /([\d,]+) duplicate rows?/.exec(p.headline)?.[1];
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
        {dup !== undefined && <> · <strong>{dup}</strong> duplicate rows</>}
        {" · "}<strong className={nulls ? "neg" : undefined}>{num(nulls)}</strong> nulls
      </p>
      <span className="sub">{p.headline}</span>
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
              return (
                <li key={i}>
                  <span className="head">
                    {String(r["Key columns"]).split(" + ").map((c) => <Chip key={c} tone={unique && i === 0 ? "key" : undefined}>{c}</Chip>)}
                    <span className={unique ? "yes" : "no"}>{unique ? (String(r["Key columns"]).includes(" + ") ? "unique together" : "unique by itself") : "not unique"}</span>
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

/** The verdict, the Columns table across the page, then the findings, frequencies and files -
 *  two to a row on a wide screen, one on a phone. */
export function ProfileView({ view, name }: { view: ProfilingView; name: string }) {
  const p = view.profile!;
  const defaults = useSaveDefaults(name, view.made).data;
  const keys = keyColumns(p);
  const found = standout(p.notes);
  return (
    <>
      <Verdict p={p} name={name} made={view.made} stale={view.stale} />
      <div className="prof-stack">
        <ColumnsTable p={p} keyCols={keys} />
        <Panel title="What stands out" sub="each finding once, with the columns it is about">
          <div className="panel-body">
            {found.length
              ? <ul className="prof-found">{found.map((f) => <FindingRow key={f.title} f={f} />)}</ul>
              : <ul className="bullets"><li><i className="ok" /><span>{NOTHING_STANDS_OUT}</span></li></ul>}
          </div>
        </Panel>
        <CouldBeTypes made={view.made} />
        <KeyCandidates p={p} />
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
