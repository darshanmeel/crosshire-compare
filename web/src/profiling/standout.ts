// web/src/profiling/standout.ts - what stands out, made short: the profile's notes folded into a
// few findings, each about a column or a set of columns - every empty column on one line, every
// column with outliers on another - in place of one line per note. What the page already shows
// elsewhere is left out: the key (Key candidates), a column's value list (its own page), a type
// read as suggested (the Columns table) and the lines that say where a cap cut a list.

export interface Hit { col: string; fig?: string }
export interface Finding { title: string; hits: Hit[]; more?: number }

// A column's note is "<column>: <what>"; the first rule that matches wins. `fig` returns the figure
// shown beside the column, null to drop the note.
type Rule = { title: string; test: RegExp; fig?: (m: RegExpMatchArray) => string | undefined | null };

const COLUMN: Rule[] = [
  { title: "Empty - null on every row", test: /^empty - / },
  { title: "One value only", test: /^constant - .*\((.*)\)$/, fig: (m) => m[1] },
  { title: "Has nulls", test: /^null on (.+?)(?: of [\d,]+)?$/, fig: (m) => m[1].replace(/ of rows$/, "") },
  { title: "One value on nearly every row", test: /^(.+) on ([\d.]+)% of rows$/, fig: (m) => `${m[1]} · ${m[2]}%` },
  { title: "Named like an ID but repeats", test: /^says identifier but ([\d,]+) rows?/, fig: (m) => `${m[1]} rows` },
  { title: "Nearly unique - a few values repeat", test: /^nearly unique - ([\d,]+) rows?/, fig: (m) => `${m[1]} rows` },
  { title: "Looks like another type", test: /^looks like an? (\S+).* - read as (\S+)$/, fig: (m) => `${m[1]}, read as ${m[2]}` },
  { title: "Leading zeros - keep as text", test: /^reads as a number but ([\d,]+) values?/, fig: (m) => m[1] },
  { title: "Differ only in case", test: /^[\d,]+ values? differ only in case - (.+)$/, fig: (m) => m[1] },
  { title: "Leading or trailing spaces", test: /^([\d,]+) values? (?:has|have) leading or trailing/, fig: (m) => m[1] },
  { title: "Outliers (1.5 × IQR)", test: /^([\d,]+) outliers?/, fig: (m) => m[1] },
  { title: "NaN or infinite", test: /^([\d,]+) values? (?:is|are) (?:NaN|infinite)/, fig: (m) => m[1] },
  { title: "Negative values", test: /^(?:([\d,]+) negative values?)?(?: · )?(?:[\d,]+ zeros?)?$/, fig: (m) => m[1] ?? null },
  { title: "Dates after today or before 1900", test: /(?:after today|before 1900)/, fig: (m) => m.input },
  { title: "Mostly one shape - a few do not fit", test: /^[\d.]+% of values are (\S+) - ([\d,]+) (?:is|are) not/, fig: (m) => `${m[2]} not ${m[1]}` },
  // shown elsewhere: the value list, a type read as suggested
  { title: "", test: /^\d+ values - |^read as an? /, fig: () => null },
];

const SKIP = /^key: |^no single column|^patterns: |^dependencies: only|^correlations: only|^… and \d+ more$/;

/** The notes as findings, in the order of `COLUMN`, the table-wide ones first. */
export function standout(notes: string[]): Finding[] {
  const dup: Finding = { title: "Exact duplicate rows", hits: [] };
  const deps: Finding = { title: "One column decides another", hits: [] };
  const corr: Finding = { title: "Numbers that move together", hits: [] };
  const byRule = COLUMN.map((r) => ({ title: r.title, hits: [] as Hit[] }));
  const other: Finding = { title: "Also", hits: [] };
  for (const n of notes) {
    if (SKIP.test(n)) continue;
    let m: RegExpMatchArray | null;
    if ((m = n.match(/^([\d,]+) exact duplicate rows? - /))) { dup.hits.push({ col: "every column", fig: `${m[1]} rows` }); continue; }
    if ((m = n.match(/^… and (\d+) more in Dependencies$/))) { deps.more = Number(m[1]); continue; }
    if ((m = n.match(/^(.+) (→|↔) (.+?): /))) { deps.hits.push({ col: `${m[1]} ${m[2]} ${m[3]}` }); continue; }
    if ((m = n.match(/^(.+) ~ (.+): correlated, r = (.+)$/))) { corr.hits.push({ col: `${m[1]} ~ ${m[2]}`, fig: `r = ${m[3]}` }); continue; }
    const at = n.indexOf(": ");
    const col = at > 0 ? n.slice(0, at) : "";
    const what = at > 0 ? n.slice(at + 2) : n;
    const k = col ? COLUMN.findIndex((r) => r.test.test(what)) : -1;
    if (k < 0) { other.hits.push({ col: n }); continue; }
    const fig = COLUMN[k].fig ? COLUMN[k].fig!(what.match(COLUMN[k].test)!) : undefined;
    if (fig !== null) byRule[k].hits.push({ col, fig });
  }
  return [dup, ...byRule, deps, corr, other].filter((f) => f.hits.length);
}
