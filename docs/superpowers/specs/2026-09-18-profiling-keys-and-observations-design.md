# Profiling page: keys, what stands out, outliers, patterns, dependencies - design

Date: 2026-09-18. Status: approved in conversation ("do outliers as well and something else,
try to do everything").

## 1. Goal

The Profiling page measures one table and today shows the statistics table and, per column,
the 10 most and 10 least frequent values. It should also say what a person opening an
unfamiliar table wants to know first: which column (or combination) identifies a row, what
stands out (empty, constant, nearly unique, dominant value, nulls, whitespace, case variants,
duplicate rows, what looks-like decided), where the numbers and dates run wild (outliers,
percentiles, negatives, zeros, future dates), what shape the text values take, and which
columns determine which (functional dependencies, one-to-one pairs, correlated numbers). The
statistics table shows the distinct share both ways - of the non-null rows and of all rows -
and the top value with its share.

The Compare page is untouched except for the statistics table it shares (`stats_table`),
which gains the same columns on both pages.

## 2. Rules that hold throughout

- Everything measured through DuckDB on the table `register` builds - canonical text per
  column, so numbers are read with `try_cast(c AS DOUBLE)` and dates with
  `try_cast(c AS DATE)` / `AS TIMESTAMP`, the way `stats_table` already does. The raw source
  (`raw_text(side, col)` over `source_expr(side)`) is read only for the two checks that need
  the untrimmed value: leading/trailing spaces and case variants.
- One read of the table. `profile_single` opens one scratch connection, registers the table
  once (`materialize=True`), and every measure - statistics, frequencies, keys, observations,
  outliers, patterns, dependencies - runs on that connection. Nothing keeps the connection
  after it returns: the profile dict holds only DataFrames, lists, strings and ints, because
  it lives in `st.session_state`.
- `st.*` only in `ui_profile.py`. `profile.py`, `observe.py`, `keys.py` stay plain Python.
- Plain wording, the house style: lower-case reasons joined with ` · `, no emojis, numbers
  with thousands separators, percentages with one decimal in prose and two in tables.
- Identifiers through `sql.ident`, literals through `sql.lit`.
- Every list the engine cuts (candidate keys, dependency pairs, pattern rows) says so in its
  note, never silently.
- Existing tests keep passing untouched except where a column list changed (`STATS_COLS`).
- The Log gets the run as now, and a note entry with the What-stands-out lines, the way Auto's
  decisions are logged (`ui_log.note`).

## 3. The statistics table - `profile.py`

`STATS_COLS` becomes:

```
Column, Type, Rows, Nulls, Null %, Distinct, Distinct % of filled, Distinct % of rows,
Top value, Top %, Min, Max, Mean, Avg length, Min length, Max length
```

- `Distinct % of filled` = distinct ÷ non-null rows (what `Distinct %` was).
- `Distinct % of rows` = distinct ÷ all rows.
- `Top value`, `Top %`: the most frequent value (nulls counted as a value, shown as `∅ null`)
  and its share of all rows - filled in `measure` from the frequency tables, which already
  hold it (`top.iloc[0]`), so no extra query.
- `Min length`, `Max length`: `min(length(c))`, `max(length(c))` in the same `UNION ALL`.

`outputs.profile_frame` (the pair's `profile.csv` / `summary.json`) keeps `distinct_pct` (of
filled) and adds `distinct_pct_rows`, `top_value`, `top_pct`, `min_length`, `max_length`.

The Compare page's Profile section (`compare_app.profile_section`) renders `pa`/`pb` as they
are, so it shows the new columns with no change; its *Both sides* sheet is built by hand and
is left alone.

## 4. Keys for one table - `keys.py`

`suggest_keys(A, B, ...)` keeps its signature and behaviour. Its candidate search is pulled
out into a helper that runs over any number of side views, so the one-table version shares
the code rather than copying it:

```python
def suggest_keys_single(P: Side, specs: list[ColSpec], name: str, opts: ReadOptions,
                        progress=None, max_cols: int = 4, want: int = 8,
                        con=None, view: str | None = None, stats: pd.DataFrame | None = None
                        ) -> tuple[pd.DataFrame, list[list[str]], str]:
```

- `con` + `view`: an open connection with the table already registered (the profile's). When
  `con` is None it probes on its own, as `suggest_keys` does, so it is usable standalone.
- `stats`: the statistics table of the same columns; when given, the single-column distinct
  and null counts come from it (`Distinct`, `Nulls`), and the note says
  `- single-column figures from the profile`.
- The search is the one `suggest_keys` runs: every column that is unique by itself, then
  combinations grown from the most selective columns (affinity-ranked, up to `max_cols`),
  Desbordante HyUCC / PyroUCC on the first 200,000 rows when installed and verified on
  every row. A column with one value (or none) is never a candidate. A combination that only
  adds columns to a key that is already unique ranks below it and says so.
- No overlap (there is no other side). Ranking: unique first, non-redundant first, affinity
  sum, fewer columns, selectivity.
- Table columns: `Key columns · Distinct · Unique · Duplicate rows · Null keys · Looks like a key · Why`.
  `Distinct` is the distinct count of the combination; `Duplicate rows` = rows − null-key
  rows − distinct; `Null keys` = rows where any key column is null; `Unique` = yes when both
  are 0.
- `Why` reads as on the Compare page, for one table:
  `name says identifier · no nulls · 3,000 distinct of 3,000 · unique by itself`,
  `salary: a measure, decimal - never a key · …`, `2 nulls · 2,998 distinct of 3,000 · 2 rows share it · grown from the most selective column`,
  `adds nothing - emp_id is already unique`.
  `key_reasons` is generalised (one or two sides) rather than duplicated; the two-side
  wording is unchanged, byte for byte, so `test_keys.py` passes as is.

## 5. What stands out, outliers, patterns, dependencies - new module `observe.py`

```python
def observe(con, table: str, side: Side, specs: list[ColSpec], stats: pd.DataFrame,
            freq: dict[str, tuple[pd.DataFrame, pd.DataFrame]], opts: ReadOptions,
            looks: dict[str, str], keys: tuple[pd.DataFrame, list[list[str]], str] | None,
            say=None) -> dict
```

Returns:

```python
{"notes": list[str],          # What stands out - the lines, table-level first, then per column in table order
 "duplicates": int,           # exact duplicate rows (every column the same, nulls equal)
 "outliers": pd.DataFrame,    # one row per number / date / timestamp column
 "patterns": pd.DataFrame,    # top shapes per text column
 "deps": pd.DataFrame,        # functional dependencies and one-to-one pairs
 "corr": pd.DataFrame,        # correlated number pairs
 "headline": str}             # the one-line summary
```

### 5.1 Outliers - number, date and timestamp columns

Per column, one row: `Column · Type · P1 · P5 · P25 · Median · P75 · P95 · P99 · Std dev ·
Low fence · High fence · Outliers · Outlier % · Lowest · Highest · Zeros · Negatives`.

- Numbers: `quantile_cont(x, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])` and `stddev_samp`
  on `try_cast(c AS DOUBLE)`. Fences are Tukey's: `P25 − 1.5 × IQR`, `P75 + 1.5 × IQR`.
  `Outliers` counts values outside the fences; `Lowest` / `Highest` are the extreme values
  (the same as Min / Max, repeated here so the row reads on its own). `Zeros`, `Negatives`
  count exactly that. Std dev, Zeros and Negatives are blank for dates.
- Dates and timestamps: the same quantiles on the typed value (`quantile_cont` accepts DATE
  and TIMESTAMP in DuckDB 1.2+; if a version does not, fall back to `quantile_disc`), fences
  computed on `epoch`-seconds and shown as dates. Two extra counts feed the notes only:
  values after today (`> current_date`) and before 1900-01-01.
- Values are shown the way the stats table shows them (`profile.show`): integers without a
  trailing `.0`, dates as ISO.

### 5.2 Patterns - text columns

Shape of a value: every letter (any script, `\p{L}`) becomes `A`, every digit `9`, anything
else stays. `E1234` → `A9999`, `2026-01-12` → `9999-99-99`, `Finance & Control` →
`AAAAAAA & AAAAAAA`. Also a collapsed shape with runs folded: `A+9+`, `9+-9+-9+`, `A+ & A+`.

Per text column, `GROUP BY` shape over the whole column (nulls skipped), keep the top 3 exact
shapes: `Column · Pattern · Collapsed · Count · % · Example` - `%` of non-null values,
`Example` the first value with that shape in file order (`arg_min(v, rowid)` or `min(v)`).
The DataFrame holds every text column's top 3; the note says when more shapes exist.

### 5.3 Functional dependencies and correlations

- Candidates for a determinant X: every column that is not unique and not constant, ordered
  by distinct count ascending (the fewest values first, the most informative), capped at 40
  determinants; the note says when the cap cut columns. For each X one query counts, for
  every other non-constant column Y, `count(DISTINCT X) = count(DISTINCT (X, Y))` (X, Y
  combined with `keys.combo`, so nulls are one value). Rows of `deps`:
  `Determines · Determined · Kind · Distinct` where Kind is `one-to-one` when Y → X holds as
  well, else `many-to-one`. A one-to-one pair is listed once (X first by table order).
  A Y that is determined because X is nearly unique is not interesting, so X with
  `Distinct % of filled ≥ 99` are excluded too.
- Correlations: for number columns (at most 30, the first in table order, noted when cut),
  one query of `corr(x, y)` for every pair; keep |r| ≥ 0.7: `Column A · Column B · r`.

### 5.4 What stands out - the notes

One line each, only when it applies, in this order. Table level first:

- `12 exact duplicate rows - the same values in every column`
- key line: `key: emp_id - unique on every row` when the best candidate is unique, else
  `no single column or combination up to 4 is unique - closest: first_name + last_name (2,998 distinct of 3,000)`
- `department → cost_center: every department has one cost_center` for each many-to-one
  dependency, `emp_id ↔ email: one-to-one` for each pair, at most 10 lines then
  `… and 5 more in Dependencies`
- `salary ~ bonus: correlated, r = 0.93` at most 5 lines then `… and n more`

Then per column, in table order, any of:

- `notes: empty - null on every row`
- `CostCenter: constant - one value on every row (CC-100)`, or
  `CostCenter: constant - one value on every filled row (CC-100)` when the column also has
  nulls
- `manager_id: null on 10.0% of rows` (Null % ≥ 5, or any null at all in a column
  whose name says identifier - `keys.ID_WORDS`); `emp_id: null on 1 row of 3,000` when the
  share rounds below 0.1%
- `emp_id: nearly unique - 3 rows share a value with another` (Distinct % of filled ≥ 99 and
  not unique)
- `order_id: says identifier but 120 rows share a value` (`ID_WORDS` name, not unique, not
  nearly unique)
- `department: 8 values - Engineering, Finance, Sales, …` (2 ≤ Distinct ≤ 20 and
  Distinct % of rows ≤ 50; values by count descending, all of them up to 12 then `…`)
- `active: Y on 97.3% of rows` (Top % ≥ 95 and Distinct > 1)
- `Salary: read as a number - 4,739.85 has thousands separators` /
  `HireDate: read as a date - 12/01/2026 → %d/%m/%Y` / `IsActive: read as a boolean - Y/N`
  (one per column where `looks` made a suggestion, in the suggestion's own words)
- `zip: reads as a number but 120 values have leading zeros - keep it as text` (a column
  looks-like typed number whose raw values match `^0[0-9]`)
- `department: 5 values differ only in case - Finance / finance / FINANCE` (raw text;
  `count(DISTINCT lower(v)) < count(DISTINCT v)`; one example group of up to 3 spellings)
- `name: 12 values have leading or trailing spaces` + ` - trimmed before measuring` when
  `opts.trim` (raw text, `v <> trim(v)`)
- `salary: 12 outliers - below 1,200 or above 250,000 (1.5 × IQR) · highest 1,000,000`
  (Outliers > 0; one side only when the other fence is not crossed; a date fence that
  falls outside the calendar is blank in the table and not named here - the extreme is:
  `valid_to: 10 outliers (1.5 × IQR) · highest 99999-01-01`)
- `ratio: 2 values are NaN or infinite - left out of the outliers` (number columns; they
  are read as null by the outlier, std dev and correlation measures and counted apart)
- `salary: 3 negative values · 40 zeros` (either > 0, number columns)
- `hire_date: 12 dates after today` / `birth_date: 3 dates before 1900`
- `emp_id: 99.7% of values are A9999 - 9 are not (e1234, E12, …)` (top shape ≥ 90% and < 100%
  of non-null values; up to 3 examples of the others)

### 5.5 The headline

`3,000 rows × 7 columns · key: emp_id · 0 duplicate rows · 1 empty column · 1 constant column · 2 columns with outliers`
- parts that are zero are dropped except `duplicate rows`, which is always said; with no
  unique key: `no key up to 4 columns`.

## 6. The profile dict - `profile.py`

```python
def profile_single(side: Side, specs: list[ColSpec], opts: ReadOptions, progress=None,
                   name: str = "", looks: dict[str, str] | None = None) -> dict
```

Returns `{"stats", "freq", "specs"}` as now plus `"keys": (table, combos, note)`,
`"notes"`, `"duplicates"`, `"outliers"`, `"patterns"`, `"deps"`, `"corr"`, `"headline"`.
Steps, each narrated through `progress`: reading · statistics · value frequencies · keys ·
what stands out (duplicates, raw-text checks, outliers, patterns, dependencies). `keys.py`
is imported inside the function (keys imports profile for `profile_singles`).

`profile_tables` (the pair) is unchanged beyond the shared stats columns.

## 7. The page - `ui_profile.py`

After **Profile**, top to bottom:

1. **File** - as now, with *First 10 rows*.
2. **Profile** heading, then the headline as a caption.
3. **Keys** - the success line (`Key: emp_id - unique on every row. Found by …`) or the
   warning (`Nothing up to four columns is unique - the closest are below. …`), then the
   candidate table.
4. **What stands out** - the notes as a Markdown bullet list; when empty,
   *Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.*
5. **Statistics** - the stats table, then the download / save row. **Download profile.csv**
   as now. **Save to folder** writes `<Table>__profile.csv`, `<Table>__keys.csv`,
   `<Table>__notes.txt` (the headline, then one note per line), `<Table>__outliers.csv`,
   `<Table>__patterns.csv`, `<Table>__dependencies.csv` (deps and corr stacked, with a
   `Kind` column telling them apart) - empty tables write a header-only file.
6. **Outliers**, **Patterns**, **Dependencies** - three expanders, collapsed, each holding
   its table (Dependencies holds deps then corr with a caption each); an empty one says so in
   a caption instead of the table.
7. **Value frequencies** - the folds, as now, last.

The run disc says *Looking for keys…*, *What stands out…* on the way and ends on
*Profile ready - key: emp_id* (or *Profile ready - no key*). After the run,
`ui_log.note("Profile notes", "<n> things stand out", notes)`.

`make_profile` passes `NP` as the name and the `looks` dict through.

## 8. Tests

- `test_profile.py`: `STATS_COLS` order; `Distinct % of filled` vs `of rows` on a column with
  nulls (`manager_id` in `directory_employees.json`: 10% null); `Top value`/`Top %`; min/max
  length; `profile_single` returns every new key with the right types and the headline names
  `emp_id`.
- `test_observe.py` (new): a synthetic CSV in `tmp_path` planting each observation once -
  an empty column, a constant column, a 10% null column, a nearly unique id, an id name that
  is not unique, an 8-value category, a 97% dominant value, a Salary with thousands
  separators, a zip with leading zeros, a department with case variants, a name with stray
  spaces, a salary with two high outliers, a negative and zeros, a hire_date with a 2099 row
  and an 1899 row, an emp_id with 3 malformed values, a department → cost_center dependency,
  an id ↔ email one-to-one pair, two correlated number columns, and 4 exact duplicate rows -
  and asserts each line appears with its numbers, the tables have the right rows, and a
  clean table yields no notes. Percentile and fence values checked on a known list.
- `test_keys.py`: `suggest_keys_single` on `hr_employees.csv` - `emp_id` first, unique, the
  reasons in one-table wording, the note; with `stats` given the figures match and the note
  says so; a table with no unique column grows a combination; the two-side tests unchanged.
- `test_apptest.py::test_profiling_page`: after **Profile** the keys table, the notes and
  the three expanders are on the page; **Save to folder** writes the six files.
- `test_outputs.py`: `profile_frame` carries the new fields.

## 9. README

The Profiling section lists the new sections in the order they appear, the statistics
columns, the saved files, and what each note means; `docs/app-profiling.png` is regenerated
if the screenshot route is available, else noted as stale in the commit message.
