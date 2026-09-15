<p align="center"><img src="docs/banner.svg" alt="CrossHire Compare" width="100%"></p>

# CrossHire Compare

Two tables, every difference, in one page.

A Streamlit front end over DuckDB that compares two tables row by row. Load a CSV or a JSON file on either side, pair their columns in one table, set the type once, add transform steps where a side needs them, tick the key and press **Compare** - or press **Auto** and let it work the whole thing out, narrating each step. It is built for reconciling two exports of the same data: two systems, two dates, two vendors. The result is one self-contained HTML report you can hand to someone who never opened the app.

![Streamlit 1.49+](https://img.shields.io/badge/Streamlit-1.49%2B-f4b87c?style=flat-square&labelColor=0e0d0b)
![DuckDB 1.1+](https://img.shields.io/badge/DuckDB-1.1%2B-f4b87c?style=flat-square&labelColor=0e0d0b)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-f4b87c?style=flat-square&labelColor=0e0d0b)
![MIT](https://img.shields.io/badge/License-MIT-f4b87c?style=flat-square&labelColor=0e0d0b)

## Contents

- [What it looks like](#what-it-looks-like)
- [Install and run](#install-and-run)
- [Try it on the sample pair](#try-it-on-the-sample-pair)
- [How a run goes](#how-a-run-goes)
- [What it does](#what-it-does): [Files](#files), [The column table](#the-column-table), [Values](#values), [The key](#the-key), [Rows](#rows), [Compare and results](#compare-and-results), [Auto](#auto)
- [The report](#the-report)
- [Outputs](#outputs)
- [Speed](#speed)
- [Settings](#settings)
- [Theme](#theme)
- [The files](#the-files)
- [The engine on its own](#the-engine-on-its-own)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Related](#related)
- [License](#license)

## What it looks like

Every screenshot below is the app or its report on the sample pair in `examples/` (3,000 orders on the Left, 2,985 on the Right, every column renamed, amounts with thousands separators, dates as dd/mm/yyyy, booleans as Y/N), run with nothing but the **Figure it all out and compare** button.

Both files loaded. The sidebar holds the files; the page walks down numbered sections and the strip under the headline says where things stand.

![The app with both files loaded](docs/app-loaded.png)

The column table: one row per column from either file, its counterpart, the common name, the type both sides are converted to, and the Key and Compare ticks. `ccy` has no counterpart yet - **Match by data** will pair it with `Currency` from its values.

![The column table](docs/app-columns.png)

The result. The verdict line, the row counts, the column counts, and the one-sided column called out, before any table.

![The Summary tab after Auto](docs/app-result.png)

Columns & values: the rows that differ, Left above Right, differing cells marked. Left rows are black, Right rows are cream, everywhere the two sides sit together.

![Rows that differ, Left above Right](docs/app-rows.png)

The Report tab shows the same report the download button hands out, in the page.

![The Report tab](docs/app-report-tab.png)

The report itself, opened on its own: the headline, the verdict and the setup.

![The report, Aurora theme](docs/report-aurora.png)

Its column sheet (every column from either file, its role, how it was read, matched / mismatched / match %) and its rows-that-differ section.

![The report's column sheet](docs/report-columns.png)

![The report's rows that differ](docs/report-rows.png)

The same report with `COMPARE_THEME=violet`.

![The report, violet theme](docs/report-violet.png)

## Install and run

```
pip install streamlit duckdb pandas pyarrow
pip install desbordante        # optional - exact key discovery (HyUCC / PyroUCC)

python compare_app.py          # starts the app with its own settings: theme, 4 GB uploads
streamlit run compare_app.py   # also works; uploads are then capped at Streamlit's 200 MB default
```

Or `pip install -r requirements.txt`. Python 3.11 or newer; Streamlit 1.49 and DuckDB 1.1 are the floors the app checks at start.

Keep `compare_app.py`, `csvdiff.py` (the comparison engine) and the `tablecmp/` folder together - the app stops with a clear message if any of them is missing. There is no config file and no `.streamlit/` folder: the app applies its theme itself when it starts (`python compare_app.py` passes the settings to Streamlit's bootstrap; `streamlit run` sets them on the first script run and reruns once). Streamlit does not hot-reload files inside `tablecmp/`, so restart the app after updating them.

## Try it on the sample pair

`examples/left.csv` and `examples/right.csv` are the same 3,000 orders as exported by two systems. Right renames every column (`order_id` is `OrderId`), writes amounts as `4,739.85`, dates as `12/01/2026`, booleans as `Y`/`N`, carries a column Left does not have (`Region`), is missing the last 40 orders, has 25 orders of its own, and has a few changed values. `examples/make_sample.py` regenerates both files.

1. Start the app. In the sidebar pick **Path on disk** for File A and give the full path to `examples/left.csv`; press **Load A**. Same for File B with `right.csv`.
2. Press **Figure it all out and compare**.

Auto pairs `ccy` with `Currency` by their values, reads `amount` as a number with a *remove thousands separators* step on the Right, `trade_date` as a date with *to date (%d/%m/%Y)* on the Right, `active` as a boolean, finds the key `order_id + trade_date`, and compares. The verdict is:

```
2,960 rows matched on order_id + trade_date - 4 columns compared - 956 rows (32.3%) differ in 1,046 cells - 40 only in Left - 25 only in Right
```

`customer` differs on 678 rows (the Right upper-cases some names), `amount` on 338, `ccy` on 30 (a few `GBP`), `active` on none. Those are the numbers the screenshots above show and the numbers the headless test in [Development](#development) asserts.

## How a run goes

1. **Load A and B in the sidebar.** Upload or give a path. Each side has a name (Left and Right by default) that is shown everywhere. For a big file open *Rows to read* first and cut it down. Both files get a 10-row preview and nothing else runs.
2. **Check the column table, press Confirm columns.** Pairs by name are already made. Fix the rest with the dropdowns, set Type, tick Key and Compare. Confirm folds the table away and shows the setup card: the key, what is compared, what is missing on each side.
3. **Transform where a side needs it.** Pick a column and a side, add steps - trim, left 10, to date (%d/%m/%Y) - previewed on the first five rows.
4. **Press Compare.** Progress is shown step by step. The result stays on screen until the next run - a failure never wipes it, a settings change only marks it stale.

Or press **Figure it all out and compare** in the sidebar. Auto pairs the columns, works out every type and date spelling, finds the key, compares - narrating each step and listing every decision as a cell you can change.

## What it does

### Files

Each side takes a **CSV** (any delimiter) or a **JSON** file - an array of objects, or one object per line (`.jsonl` / `.ndjson`) - by upload or by path; a JSON value that is itself an object or list arrives as text, in DuckDB's own spelling of the object or list rather than as JSON. Each side has a name (shown everywhere), for CSV a delimiter and a *First row is a header* tick, and **Rows to read**: a WHERE filter on the file's own column names, an order, a top N. All three are applied by DuckDB as the file is read - this is how a 20 GB file becomes the 100,000 rows you actually want. The column / condition / value pickers build the filter for you.

**Snapshot the rows read to Parquet** (under *Advanced*, on by default) reads the file once with its cut and keeps the rows as a compact Parquet file in the temp folder. Everything after - previews, key search, comparison - reads that instead of re-parsing the file. Untick it only for small files you are re-loading constantly.

Also under **Advanced**, a comma-separated list of column names overrides a header row that is missing or short. The app warns when the header looks like a data row, or names fewer columns than the data has.

### The column table

Every column from either file is a row; one place to decide everything.

| Column | What it is |
|---|---|
| Left column, Right column | Dropdowns. Each row is one column from either file with its counterpart on the other side, or blank. Pick a counterpart for a blank row and the two rows merge; pick a column already used elsewhere and it moves - the row you edited wins. A column never appears twice and never disappears: an unpaired one gets its own row back. |
| Common name | What the pair is called from here on: in transforms, filters, results, downloads. |
| Type, both sides | What both sides are converted to before comparing: `text`, `number`, `date`, `timestamp`, `boolean`. `number`: 100.00 = 100 = 1e2. `date`: 27/08/2026 = 2026-08-27. `timestamp` keeps the time of day. `boolean`: 1 = yes = true. A value that will not convert keeps its text, so it shows as a difference rather than vanishing. The type is a property of the pair. |
| Key | Part of the row key. Several ticks make a compound key. |
| Compare | Compare this column. Ignored on key columns. |
| Matched by, Left detected, Right detected | Information: how the pair was made (`name`, `similar name`, `guess - check`, `data`, `you`, `file`) and the type DuckDB sniffed in each file. |

**Match by data** reads a sample of both files and pairs the unpaired columns that hold the same values, whatever they are called - `Ccy` with `currency_code`. **Reset to name matches** starts the table over. **Save mapping** writes the paired rows - common names, types, key and compare ticks, transform steps - as JSON; the upload box under it loads one back for the next run of the same two feeds, and rebuilds the unpaired rows from the files.

**Confirm columns** folds the table away. The **setup card** under it always shows what the table amounts to: how many pairs, the key, the compare list, how every typed or transformed column is read, and the columns that exist on one side only - those are null on the other side and are not compared.

### Values

Both files are read as text. Every value on every side goes through the same four stages and comes out as canonical text, so both sides compare on the same thing:

1. the side's transform steps
2. null folding (empty, `NULL`, `\N`, `N/A`, `NA`, `NaN`, `None`, `(null)`)
3. trim
4. the pair's Type

Open **Transform and convert values**, pick a column and a side, and add steps. Each step runs on the result of the one before.

| Group | Steps |
|---|---|
| Text | trim, upper, lower, left N characters, right N characters, characters from N, M long, replace text, regex replace, remove spaces, collapse repeated spaces, strip leading zeros, pad left to N with C, digits only, letters and digits only, part N split by S, remove thousands separators |
| Conversions | to number, to timestamp (format), to date (format), to boolean. A conversion step sets the pair's Type for you. Formats come from a picker of what the value looks like - `27/08/2026` becomes `%d/%m/%Y` - or are typed in; blank tries the usual spellings. |
| Custom expression | Any DuckDB expression with `x` as the value - `upper(split_part(x, '-', 1))`. A searchable catalog of DuckDB's own text, regex and date functions sits next to it, with a template, a description and an example for each. |

The preview shows the first five rows of that file: in the file, after the steps, compared as - and whether the type conversion succeeds. **Check this column on all rows** counts the values on each side that do not convert, with examples. **Copy to Right** (or **Copy to Left**) repeats the same steps on the other side; **Remove last** and **Clear** undo them.

An example: `trade_ts` holds `2026-08-27 10:11:12.123` on Left and `27/08/2026 10:11` on Right, and you only care about the day. Right: *left 10*, then *to date (%d/%m/%Y)*. Type becomes `date`; Left's ISO text converts on its own. Both compare as `2026-08-27`.

**How values are read** holds the global switches: *Trim whitespace*, *Empty = null*, *Ignore case in values*, *Numeric tolerance*, and the list of tokens folded to null.

### The key

Tick **Key** in the table and rows are matched on it. Nothing measures the key until you ask. **Check key** counts distinct key values against rows on each side. **Suggest keys** finds the combinations of up to four columns that identify a row on both sides - with Desbordante when it is installed (HyUCC for exact keys on the first 200,000 rows of each side, verified on every row; PyroUCC's almost-unique combinations when nothing is exact), otherwise by measuring every column and growing the most selective ones. The best key is in the status line when it finishes; pick rows from the list and press **Use as key**.

With no key ticked, choose how rows are paired:

| Mode | How | When |
|---|---|---|
| hash | Every row is hashed over the compared columns and the two multisets are matched. Identical rows pair; the rest are one-sided. The result also says, per column, how many distinct values exist on one side only - where the one-sided rows differ. | No key at all, or you want to know whether the two files are the same set of rows. |
| position | Line 1 against line 1. | Both files sorted identically, same row count. |

If everything differs: a key that pairs every row and then finds every row different usually means the key columns are spelled differently on the two sides - `o00001 ` against `O00001`. The summary shows sample unmatched key values; give the key column a Type or an *upper* / *trim* step.

### Rows

**Filters** apply to both sides, or one, after types: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`, `between`, `like`, `is null`, `is not null`, on the common names. To shrink a big file before it is even read, use *Rows to read* in the sidebar instead.

**Profile both files** runs only when pressed: per column per file, null %, distinct count, min, max, mean, average length - side by side with the gap - and the 10 most and 10 least frequent values, on the same typed values the comparison uses.

### Compare and results

Press **Compare**. Both sides are materialised once as DuckDB tables under the common names with the canonical values applied, then the engine (or the hash matcher) runs on those. The status line narrates: reading Left, reading Right, matching on the key, comparing N columns, writing the summary. **Re-run on every change** is off by default - the last result stays on screen and is marked stale when settings change. *Rows to display per section* (100 to 10,000, default 1,000) caps the tables on screen; downloads always contain everything.

| Tab | What it holds |
|---|---|
| Summary | Row counts; then every column from either file on one sheet - its name on each side, its role (key, compared, paired but not compared, only in Left, only in Right), how it was read, and for compared columns matched / mismatched / match % - with the one-sided columns called out above it. **Profile by bucket**: the top values of every column for the rows whose keys matched, matched but differ, or exist on one side only, key columns first. The matched-but-different bucket opens with **differences by key value** - the rows that paired on the key but disagree, grouped by each key column's value, with the columns that differ. The key is identical on both sides for these rows: this is where the differences sit, not what they are. |
| Columns & values | The rows that differ, Left above Right, differing cells marked. Then every compared column, worst first: the value pairs behind the count, the distribution on each side. **Near-match analysis** says whether differences are formatting or data. |
| Report | The house-style HTML report, viewed in the page and downloaded with one button; **Download engine report** is the second button. |
| Downloads | Cell differences, one-sided rows, summary CSV and JSON - complete, not just the rows displayed - and a paired side-by-side export. |

### Auto

Two files in, the rest worked out - brute force, narrated. It reads both files several times over, so on big files cut them first with *Rows to read*.

1. **Pair columns.** By name, then similar name, then by their values for whatever is left over.
2. **Analyse types.** One pass over the first 50,000 rows of each side: how many values read as a number, a number once commas go, an ISO date, day-first, month-first, any known spelling, with a time of day, a boolean. Each pair gets a Type; a side that needs it gets a step - *remove thousands separators*, *to date (%d/%m/%Y)*. Two spellings are only merged when both sides read cleanly.
3. **Check case.** Text pairs whose sides only agree once case is ignored get an *upper* step on both.
4. **Find the key.** Same as Suggest keys. The status line shows the key it chose; if nothing is unique, the closest is used and said so; if nothing at all, hash mode.
5. **Compare.** Every paired non-key column, immediately. Every decision is listed under Columns as a bullet, and is a cell in the table or a step in the transform section.

## The report

The Report tab shows the report in the page. **Download report** saves it through the browser as `<pair>__report.html`. **Save report to folder** writes it straight to the folder in the box beside it (next to file A by default, or your Downloads folder for an upload) and prints the path - the reliable route for big runs. The Downloads tab has the same **Save everything to folder** for all the CSVs and both reports at once.

It is one self-contained file - fonts from Google, everything else inline - so it can be mailed or dropped in a ticket and opens without the app. It is written for the person who did not run the comparison: what was compared, how, and where it went wrong, in that order.

| Section | What it says |
|---|---|
| Header | The two files and the verdict in one line: rows matched, columns compared, rows that differ. The footer records when the run happened and how long it took. |
| The setup | The two files and the rows read from each (with the *Rows to read* cut, if any), how rows were paired - the key, *by hashing the compared columns* or *by position* - which columns were compared, the transform steps and types each column was read with, and the filters. Enough to re-run it by hand. |
| Row counts | Rows read on each side, rows paired, rows only in Left, rows only in Right, rows that differ - as figures, with the verdict under them. |
| Every column | The same sheet as the Summary tab: every column from either file with its name on each side, role, how it was read, and matched / mismatched / match % (as a bar) for the compared ones, worst first. Columns present on one side only are listed in a note above the table so a missing or extra column is never silent. In hash mode the match figures become the number of distinct values present on one side only. |
| Differences by key value | For rows that paired on the key but disagree: each key column's values with how many rows differ under each value and in which columns. Tells you *where* the differences cluster - one account, one date - before you look at what they are. If the key is not unique the section says so up front: rows sharing a key are paired in file order, and a difference under a repeated key may be two rows swapped rather than a changed value. Below it, every column across the differing rows: top values counted on each side. |
| Rows that differ | The paired rows, Left above Right, key columns first. **Left rows are black with cream text, Right rows are cream with black text**, and the cells that differ are picked out in the trouble colour on both. A legend sits above the table. Capped at the *Rows to display* setting (at most 2,000 in the report); the CSVs hold everything. |
| Only in Left / Only in Right | The one-sided rows on the same black and cream - the paired columns under their common names, key columns included; a column present on one side only is not in them - each section opening with the top values per column, key columns first - the key values are the reason those rows found no partner. Capped the same way. |

**Download engine report** is the second button: the comparison engine's own side-by-side HTML (`<pair>__diff.html`) with its tabs, row search and *only columns with differences* toggle. Same numbers, different presentation; keep whichever the reader prefers.

## Outputs

Every run gets a pair name from file A - `orders.csv` against anything gives the pair `orders` - and writes into a temp folder that the app cleans up on the next run. The Downloads tab hands each file out; the names are always:

```
orders__report.html       the house-style report (Download report)
orders__diff.html         the engine's own side-by-side report (Download engine report)
orders__cell_diffs.csv    one line per differing cell: the key columns (the row number in position
                          mode; an extra occurrence column when a key value repeats), column_name,
                          left_value, right_value
orders__left_only.csv     rows found only in Left: the paired columns under their common names, key
                          columns included; one-sided columns are not in these files
orders__right_only.csv    rows found only in Right, the same way
orders__paired.csv        every paired row, Left above Right - built on demand from Export the
                          side-by-side view, capped by its Max rows box; not written to the folder
orders__summary.csv       the counts as one row
orders__summary.json      the counts plus every setting the run used - key, pairs, steps, filters
```

In key and position mode the engine writes `left_only` / `right_only` only when there are such rows; hash mode always writes both. In hash mode there is no `cell_diffs` file and no engine report - rows either match whole or land in `left_only` / `right_only`. The engine's CSVs are complete; only the tables on screen and in the report are capped by *Rows to display*.

## Speed

Nothing heavy runs unless you press it.

- Loading sniffs the schema from a sample and takes one pass to snapshot and count. The 10-row preview stops after 10 rows.
- A plain rerun - editing the table, opening an expander - runs nothing beyond the two 10-row previews and the five-row transform preview.
- Key suggestion, key check, profile, type check and the comparison run only on their buttons. Auto runs them all, once, on purpose.
- The comparison and the key search materialise each side as a DuckDB table under the common names, so the engine reads each file once. Numbers go through a fast 8-decimal decimal first and the wide one only when needed.
- A one-off measurement, 500,000 rows x 6 columns with the real engine: load 1.2 s a side, the comparison itself 7 s (both sides materialised, keyed join, cell differences written), the whole Auto run 16 s including Desbordante and the report. Treat it as an order of magnitude; there is no benchmark script in the repo. The sample pair above compares in well under a second.
- For a very big file, cut it in *Rows to read* first - a date filter or a top N - and keep the Parquet snapshot on.

## Settings

There is no settings file. Everything is either in the page or an environment variable read when the app starts:

| Variable | Default | What it does |
|---|---|---|
| `COMPARE_THEME` | `aurora` | `violet` switches the whole look - app, report, Streamlit's own widgets - to the violet variant. Anything else falls back to Aurora. |
| `COMPARE_APP_NAME` | `CrossHire Compare` | The name in the browser tab, the sidebar mark, the page eyebrow and the report header. |
| `COMPARE_APP_TAGLINE` | `Tables, side by side` | The line under the name in the sidebar mark. |

```
set COMPARE_THEME=violet                     (Windows)
export COMPARE_APP_NAME="Acme Table Check"   (macOS / Linux)
```

The upload limit (4 GB under `python compare_app.py`) and the radii, fonts and colours live in `tablecmp/theme.py`.

## Theme

The look is the Crosshire apps theme - the same colour and type tokens the Crosshire web apps use, carried here as `--fs-*` CSS variables: a warm near-black ground, cream text, an amber accent, Fraunces for headlines, Inter for text and JetBrains Mono for figures, labels and code. **Aurora** is the default; **violet** is the second palette (`COMPARE_THEME=violet`), with Inter for the headlines as well.

Every colour and font is defined once, in `THEMES` in `tablecmp/theme.py`. `tokens_css()` turns the active palette into a `:root` block; the app's CSS, the report and `README.html` all start with it and refer only to the variables, so the three read as one thing and a palette change is one edit. Streamlit's own widgets (grids, menus, code, focus rings) take the same colours through `STREAMLIT_THEME`, which `compare_app.py` passes to Streamlit at start - no `.streamlit/config.toml`.

Left is black (page background, cream text) and Right is cream (cream background, black text) everywhere rows are shown side by side - in the app's grids, in the report, in the legend. Under the violet palette "cream" is a cool off-white; the legend keeps the word.

## The files

```
compare_app.py        entry point: bootstrap, theme, the page flow
csvdiff.py            the comparison engine (a black box to the app; runs on its own, see below)
README.html           how it works, in the house style - the same content as this file, for the app's users
README.md             this file
requirements.txt      streamlit, duckdb, pandas, pyarrow (desbordante optional)
docs/                 banner and screenshots
examples/             left.csv, right.csv and the script that makes them
tablecmp/
  theme.py            colours, fonts, page CSS, STREAMLIT_THEME, status strip, cards - the only place to change the look
  sql.py              quoting, connections
  state.py            session defaults
  sources.py          one CSV or JSON file and which of its rows to read; schema sniff, snapshot, preview
  values.py           transform steps, null folding, types, canonical text, registration, type check
  columns.py          the column table: pairing, normalisation, specs, mapping JSON, match by data
  keys.py             key uniqueness, affinity, Desbordante / DuckDB suggestion
  profile.py          statistics and value frequencies
  compare.py          running a comparison (engine, position, hash) and reading it back
  report.py           the HTML report
  auto.py             two files in, the rest worked out
  ui_sidebar.py       the sidebar: loading files, the Auto button
  ui_columns.py       the column table and the setup card
  ui_transform.py     transform steps with the five-row preview
  ui_keys.py          Suggest keys, Check key, hash / position without a key
  ui_results.py       the verdict and the four result tabs
```

The engine is a black box to the app: it receives two DuckDB tables named `src_a` and `src_b` with the common column names and canonical values already applied, and the app reads back its counts and its CSV outputs. Only the `ui_*.py` modules, `compare_app.py` and `state.py` touch Streamlit; everything else is plain Python over DuckDB and pandas, which is what makes the headless test below possible.

## The engine on its own

`csvdiff.py` is a generic, config-driven CSV comparison powered by DuckDB, and it runs on its own from the command line - two CSV files, or two folders of them. Everything runs inside DuckDB, so files much larger than RAM are fine. It reports rows present only on the left or only on the right, cell-level differences for rows that matched, and schema differences.

```
python csvdiff.py file  a.csv b.csv --keys id --out out/
python csvdiff.py folder dir_a dir_b --out out/ --keys id
python csvdiff.py config diff_config.yaml --out out/
python csvdiff.py init-config dir_a dir_b -o diff_config.yaml
```

Matching strategies: `key` (join on one or more business-key columns, recommended), `row_number` (line 1 against line 1), `multiset` (order-independent set comparison with duplicate counts), `auto` (key if keys are configured, else row_number). Exit codes: 0 = identical, 1 = differences found, 2 = error.

## Development

Small, verified steps. Before handing over a change:

1. `python -m py_compile compare_app.py tablecmp/*.py` - everything must compile.
2. Drive the app headlessly with Streamlit's `AppTest` and check the numbers, not just that it ran:

```python
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("compare_app.py", default_timeout=300); at.run()
for tag, path in (("A", "examples/left.csv"), ("B", "examples/right.csv")):
    at.sidebar.radio(key=f"how_{tag}").set_value("Path on disk"); at.run()
    at.sidebar.text_input(key=f"pt_{tag}").set_value(path); at.run()
    at.sidebar.button(key=f"load_{tag}").click(); at.run()
at.sidebar.button(key="auto_btn").click(); at.run()
assert not at.exception
res = at.session_state["result"]["result"]          # the Outcome
assert (res.matched_rows, res.only_left, res.only_right, res.diff_rows, res.cell_diffs) == (2960, 40, 25, 956, 1046)
```

Re-fetch widgets after every `at.run()`; elements go stale. Widget keys worth knowing: `how_A` / `how_B`, `pt_A` / `pt_B`, `load_A` / `load_B`, `auto_btn`, `go` (Compare), `disp_rows`, `auto_rerun`, `bucket_pick`, `save_report`, `save_all`. Under `streamlit run` the app does one `st.rerun()` on its first run to apply the theme; AppTest handles it. Set `COMPARE_THEME=violet` in the environment and run the same test to cover the second palette.

3. For anything visible, look at it: `streamlit run compare_app.py --server.headless true` and a Playwright screenshot, or the app in a browser. The screenshots in `docs/` were taken that way.

Conventions the code keeps: identifiers go through `sql.ident`, literals through `sql.lit`, never f-strings into SQL; plain, human wording in the UI with captions that say why, and no emojis anywhere; tables shown to people use thousands separators, blank for not-applicable and a null glyph for a real null; `README.html` is updated when behaviour changes; `csvdiff.py` is not modified by the app's changes; no config file and no `.streamlit/` folder, ever.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every matched row differs on one column | Two different fields paired by mistake, or a value that converts on one side only. Check *Matched by* in the table; open the column in the transform section and press *Check this column on all rows*. |
| Few rows match on the key | Key values spelled differently - case, padding, a date format. The summary lists sample unmatched values. Give the key column a Type or a step. |
| A date column shows as text | Add *to date* with the right format on the side that needs it, or pick the Type and let the built-in spellings read it. Ambiguous day/month order needs the format spelled out. |
| Auto picked a key that is not unique | It says so. Suggest keys shows the alternatives; or add a column in the table. |
| The comparison failed | The message is shown and the previous result stays on screen. Usually a filter value or a custom expression DuckDB cannot read - the preview shows DuckDB's own message. |
| Header names look like data | Untick *First row is a header* and load again; give names under Advanced if you have them. |
| An upload over 200 MB is refused | Start the app with `python compare_app.py` (4 GB limit) instead of `streamlit run`, or load the file by path. |
| A change to a file in `tablecmp/` does nothing | Streamlit does not reload that folder; restart the app. |
| streamlit / duckdb too old | `pip install -U streamlit duckdb`. Streamlit 1.49+ and DuckDB 1.1+ are needed. |

## Related

- [crosshire.ch](https://crosshire.ch), [learn.crosshire.ch](https://learn.crosshire.ch), [blogs.crosshire.ch](https://blogs.crosshire.ch)
- Sibling repos: [crosshire-audit-snowflake-admin](https://github.com/darshanmeel/crosshire-audit-snowflake-admin) - who can actually read a table, transitively; [crosshire-audit-databricks-admin](https://github.com/darshanmeel/crosshire-audit-databricks-admin) - a query library over Databricks system tables.

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Darshan Singh / Crosshire.
