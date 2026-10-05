# Screen specifications

Each section: the mockup, what changes and where, the data behind each element, the states,
and what "done" looks like. Element names refer to `COMPONENTS.md`. API paths are the ones in
`tablecmp/web/routes_*.py`; where a screen needs something the API does not expose, the
section says exactly what to add.

Conventions used below: **A / B** are the two sides (`tag` A, B; the Profile page's single
side is `P`). "Rail" is the step rail (`shell/StepRail.tsx`). "Setup view" is the response of
`GET /api/setup` (`SetupView` in `web/src/setup/api.ts`); "compare state" is `GET /api/compare`.

---

## §0 Shell (every screen)

**Mockup:** the top 118 px of any page.

**Header** (`shell/AppHeader.tsx`, 56 px, white, bottom border):
- Wordmark: `app_name` from `/api/meta`, last word italic in accent (as `Sidebar.tsx` splits it today). Links to the Compare page.
- Mode switch: `Seg`-styled links **Compare** / **Profile**. Must keep `role="radiogroup"` `aria-label="Page"` with two radio inputs labelled `Compare` and `Profiling` (hidden visually if you like) so `tests/e2e` keep passing; visible text is "Profile".
- Right: `Connections` button with the saved-connection count (`GET /api/connections`), `Run from config` (Compare page only), `Log` with the entry count (`GET /api/log`).
- Wraps at narrow widths (flex-wrap).

**Rail** (`shell/StepRail.tsx`, white, bottom border):
- Compare: 1 Sources · 2 Columns · 3 Rows · 4 Results. Profile: 1 Source · 2 Profile.
- Each step: circle (24 px) + title + mono sub-line. States: `todo` (grey ring), `now` (accent ring + accent title), `done` (ink fill + check), `run` (accent ring + dot, title "comparing…").
- Sub-lines come from state: Sources → "HR 3,000 · Payroll 2,985" (`/api/sources` names + row counts, "nothing loaded yet" before); Columns → "6 pairs · key emp_id" (setup view: `specs.length`, keys); Rows → "all rows · no filter" (`/api/setup/filters`); Results → "press Compare" / "comparing…" / "compared in 0.4s" (compare state `run`).
- Steps are links that scroll to their section (01 / 02 / 03) or switch to results.
- Right-side actions by state: before results `Auto · figure it all out` (accessible name stays **Figure it all out and compare** — `aria-label`) + primary `Compare` (both disabled until A and B are loaded); running: `Cancel` + disabled `Comparing…`; results: `Edit setup` + primary `Download report`; Profile: disabled/enabled `Profile`, then `Save to folder` + primary `profile.csv`.
- The old `StatusStrip` (5 cells) and `RunDisc` are retired: the rail carries that state.

**Main column** `.page`: max-width 1384 px, 24/28 px padding, sections headed by a mono numeral eyebrow (`01`, `02`, `03`) + 17 px semibold title + grey sub-line. No hero once anything is loaded.

**Done when:** every page in the app shows this shell; `tests/e2e/test_e2e_page.py` still finds the `Page` radiogroup, `File A` / `File B` regions and the `Figure it all out and compare` button.

---

## §01 Compare · home (nothing loaded)

**Mockup:** `mockups/01-home.html`.

- `shell/Welcome.tsx`: a white card with the eyebrow, the two-line serif headline ("Two tables, *every difference.*" — the `HERO` text in `App.tsx` today), the lede, two buttons (**Try the HR vs Payroll example** → loads `examples/hr_employees.csv` as A and `examples/payroll_employees.csv` as B through `POST /api/sources/{tag}/load` with `how: "path"`; **Run from a saved config** → §17), and a numbered three-step "how it works" list. Shown only while neither side is loaded.
- Sources section: both `SideCard`s in their empty state — name defaults `Left` / `Right` (`DEFAULT_NAMES`), `Upload` selected, dropzone, options row, `Load A` / `Load B` disabled until a file is chosen (button names must start with `Load`).
- Columns section: eyebrow + title + a `Callout` explaining what appears there.

**Done when:** a fresh workspace shows this; choosing a file enables Load; after both loads the Welcome card disappears and §04 appears without a reload.

---

## §02 Connections drawer

**Mockup:** `mockups/02-connections.html`.

- `connections/ConnectionsDrawer.tsx` (from `ConnectionsManager.tsx` + `ConnectionForm.tsx`): a 420 px right-hand panel over the page (grid `1fr 420px`; on narrow widths it stacks). Opened by the header button; `Esc` and the × close it; focus moves into it.
- Saved connections as `.conn` cards: name, kind `Chip`, status `Pill` (Connected / Not tested / Failed — from the last `POST /api/connections/test` result kept in component state), Edit. Under it the URI (password never shown — the API already redacts) and, for DuckDB, the schemas from `/api/sources/{tag}/schema` if cheap, else omit.
- Add a connection: Name, Driver select (`kinds` from `/api/meta`), URI, password location `Seg` (In the file / Environment variable, with the `COMPARE_CONN_<NAME>` hint), password field, **Test connection** / **Save** (`PUT /api/connections/{name}`). The form fields come from `/api/meta` `form` as today.
- Foot note: file location (`COMPARE_CONNECTIONS`), `COMPARE_DATA_DIR`.

**Done when:** `connections.test.tsx` passes with the new structure; the fake-password grep in `tests/test_web_flows.py` still finds nothing.

---

## §03 Side B from a database table

**Mockup:** `mockups/03-source-database.html`.

- `SideCard` with `Database` selected (`sources/DatabaseBox.tsx` inside the card): connection select + **Manage** (opens §02); `Seg` **A table** / **SQL query**; schema and table selects filled by `POST /api/sources/{tag}/schema`; for SQL a textarea; Top N; "Snapshot to Parquet" tick if the API exposes that option (else omit); Load.
- Foot line: `payroll.employees · 2,985 rows × 7 columns · sample.duckdb`.
- Columns header's B column reads the table name (`payroll.employees`) when the side is a table.
- `Callout` under the cards explaining table vs query, once per page (dismissable).

**Done when:** the database e2e flow (`tests/test_web_flows.py`, `fetch_and_load`) passes unchanged.

---

## §04 Setup · both loaded, columns paired

**Mockup:** `mockups/04-loaded.html`.

**Sources** — two `SideCard`s (region names `File A` / `File B`):
- Head: side badge (A blue / B clay), `Name` input (drives `PUT /api/setup/names` as today), status `Pill` `Loaded · 0.3s` (time from the load job).
- Source `Seg`, path row (`Path to CSV or JSON` label kept, `Browse…` → `POST /api/sources/browse` when `filepick` is available), options row (Delimiter, First row is a header, Rows to read, Advanced).
- Foot: file name · rows × columns · column names · **Preview 10 rows** (`GET /api/sources/{tag}/preview`, inline collapsible).

**Columns** — `columns/PairingTable.tsx` (from `ColumnTable.tsx`), a `DataTable` with columns Role · HR column · ⇄ · Payroll column · Read as · Transform · Matched by · Case:
- Role: `Seg` mini (Key / Compare / Skip) → `POST /api/setup/cell` as the current role controls do.
- Column chips: `Select` styled per side (`.sel.a` / `.sel.b`), native `<select>` under the hood with the side's column list; "no partner" dashed when empty.
- Read as: type chip select (text / number / date / timestamp / boolean) → `POST /api/setup/type`.
- Transform: mono summary of the side's steps (`B · part 2, split by " "`), a link to §05; `+ Add` when none.
- Matched by: `name` / `similarity` / `guess · check` (warn colour) / `only in HR` / `only in Payroll` (neg colour). **Data:** the setup view must say how each pair was made. If `SetupView.specs[i]` has no such field, add `origin: "name" | "similarity" | "values" | "manual" | "one-sided"` to the spec the matcher returns (`tablecmp/columns.py` / `routes_setup.py`), with a unit test.
- Case: exact / ignore / — (text pairs only), from the spec's `case` (blank = follows *Ignore case in values*).
- One-sided columns are muted rows at the bottom with role Skip.
- Actions: **Match by data** (dark) → `POST /api/setup/match` then `/match/apply`; **Reset to name matches** → `/reset`; **Save mapping** → `GET /api/setup/mapping` as a download; **Load mapping…** → file input → `POST /api/setup/mapping`.
- Foot: `Key emp_id · Compare 5 columns · Skip 2 one-sided` and the "1 pair is a guess from the values — check last_name ⇄ FullName" line when any pair has `origin: "values"`.

**Rows** — one-line summary card (match rows on key · filter · profile by bucket) with **Edit rows** → §06.

**Bottom:** primary `Compare HR against Payroll` (names from the sides) + the helper line.

**Done when:** `columns.test.tsx` and `setup/*.test.tsx` pass; the sample pair reaches 6 pairs / key `emp_id` through Auto exactly as `tests/COUNTS.md` expects.

---

## §05 Transform & convert values

**Mockup:** `mockups/05-transform.html`.

- `values/ValuesEditor.tsx` replaces `TransformBox.tsx`. Left panel: the pairs as a compact table (HR · Payroll · Read as · Steps), the selected pair highlighted; under it **How values are read** (`HowValuesRead.tsx`: null tokens, Empty string is null, Trim whitespace, **Ignore case in values** — label unchanged —, Numeric tolerance) → `PUT /api/setup/settings`.
- Right panel: pair head (A chip ⇄ B chip, type chip, case chip, origin pill), a one-line explanation, side `Seg` (`HR steps · n` / `Payroll steps · n`), the numbered pipeline (`.pstep`: op name, parameter inputs per `PARAM_LABELS`, the DuckDB expression as a mono hint, move up / remove), **Add a step** chips from `GET /api/setup/functions` (the `STEPS` keys — never a hard-coded list), the **Preview** table (`GET /api/setup/try`: before, after last step, the other side's value, match tick) with the match count from `POST /api/setup/check`.
- Foot: "Other conversions this run" chips.
- Reached from the Transform column in §04 and from the rail's Columns step when steps exist.

**Done when:** adding `part N split by S` with `" "` / `2` on FullName reproduces the mockup preview; `values.test.tsx` passes.

---

## §06 Rows

**Mockup:** `mockups/06-rows.html`.

- **How they pair up** card: match mode `Seg` (On a key / By position / By hash of compared columns) → `PUT /api/compare/settings` `nokey_mode` + the key list (`/api/setup/keys`); key chips, **Add a column**, **Suggest keys** → `POST /api/setup/keys/suggest` (candidates shown as chips with overlap %, chosen on click); the uniqueness/overlap line.
- **Rows to read** cards per side (`RowsToRead.tsx` content): WHERE textarea, Order by, Top N, resulting count `Pill` (`3,000 of 3,000 rows`), **Apply to HR**, **Copy to Payroll**. Applies via the load route's rows options as today.
- **Profile by bucket**: tick + column select (pairs only) → the existing `auto_profile` / bucket setting (`ProfileBox.tsx`).
- Bottom primary Compare.

**Done when:** `keys.test.tsx` passes; the e2e "settings kept across the page switch" run passes.

---

## §07 Running

**Mockup:** `mockups/07-running.html`.

- `compare/RunningPanel.tsx` replaces `RunDisc`: disc with a soft ring, "Working it out…" serif headline, the job's current line (`entry.line` as the log shows it), `step n of m · elapsed`, progress bar, and the **task list**. **Data:** the job entry from `GET /api/jobs/{id}` / `useLog().data.last`. Render the lines the job has reported as `done` items and the current line as `run`; add `todo` items only if the job reports its remaining steps — do not invent them. Cancel if the API has it; else omit the button.
- Below: both `SideCard`s collapsed to one line (badge, name, file · rows × columns, Loaded pill) and the pairing table with the pairs known so far; a `pairing…` pill replaces the B chip for pairs Auto is still deciding.
- Rail: step 4 in `run` state; right actions disabled.

**Done when:** pressing Auto on the sample pair shows this panel until the compare finishes, then §08 without a reload.

---

## §08 Results · Summary

**Mockup:** `mockups/08-results-summary.html`.

**Persistent head** (`results/ResultsHead.tsx`, on every results tab):
- Verdict: eyebrow `Result · HR against Payroll · date · time`, then the engine's sentence in Fraunces 30 px with the counts bold (differing counts in `neg`): the text `.verdict` renders today, restyled.
- **Row outcome**: stacked bar (fully matched / differ / only in A / only in B over distinct keys = matched + only A + only B) + legend with counts. Colours `--fs-pos`-ish green, amber, A blue, B brown — all four differ in lightness.
- `Tabs`: Summary · Differing rows *n* · One-sided rows *n* · Report · Downloads (replaces the radio group in `ResultsView.tsx`).

**Summary tab:**
- Tiles: Rows A, Rows B, Matched on key, Fully matched, Overall match %, Columns compared (of n · key k) — all from `GET /api/results/{run}/summary`.
- **Columns** panel: `DataTable` A · B · Read as (type chip + step summary) · Matched · Mismatched · Match % with `Bar` (green at 100, light green ≥ 95, amber below); key row shows the key chip. From `/summary` `columns` (or `/columns`).
- Foot: "Not compared — present on one side only".
- **By bucket · <column>** table when a bucket is set: Bucket · Rows paired · Differ · Match % bar · What differs — from `GET /api/results/{run}/buckets/{bucket}`.
- **Why they differ** panel: per differing column, the most frequent (A value → B value) pairs with counts and bars. **Data:** the summary's "value frequencies by category" if it carries value pairs; otherwise add `GET /api/results/{run}/pairs/{column}?limit=5` returning `[{a, b, n}]` from the run's `differences` parquet (DuckDB `GROUP BY a, b ORDER BY n DESC`). Text lines for columns whose pairs are all distinct ("Amounts differ after … — real differences, not formatting" comes from `/near-match`). The one-sided pattern line (all 25 read "New Starter"…) only when `/near-match` or frequencies support it — otherwise omit the block.
- **See the n rows** → Differing rows tab.

**Done when:** every number on the tab equals `tests/COUNTS.md` for the sample pair; `results.test.tsx` passes.

---

## §09 Results · Differing rows

**Mockup:** `mockups/09-results-diffs.html`.

- Toolbar: filter chips `All differing n` + one per differing column with its mismatch count (from the summary), search (filters loaded rows client-side; server search only if the paired route supports it), **Show: all compared columns** menu (hide matching columns), **differences.csv** (`/api/results/{run}/file/<pair>__differences.csv`).
- Panel note line with the `A value → B value` legend.
- `DataTable`: key column(s) first (mono, medium weight), then every compared column, then **Cells** (count of differing cells, neg colour). **One row per key**: the paired frame from `POST /api/results/{run}/paired` arrives as A/B row pairs (`Side` column) — pivot client-side into one row; a cell whose A and B values differ renders as `DiffCell` (A value blue → B value clay on the diff tint); equal cells plain grey. Sort by cells-differing desc as the engine already orders "worst first".
- Foot: `Showing 12 of 649 rows`, **Load 50 more** (the route's paging), **Near-match analysis — formatting or real?** (`/near-match`, opens a panel under the table).

**Done when:** E10402 Moreau shows two diff cells (department, salary); the row count equals `rows_differ` in `COUNTS.md`.

---

## §10 Results · One-sided rows

**Mockup:** `mockups/10-results-onesided.html`.

- Two panels side by side: **Only in HR** (count badge, sub-line, `one_sided_HR.csv` button) and **Only in Payroll**, each a `DataTable` of the first rows + **Show all n**. **Data:** the run's `one_sided_<side>.csv` via `/api/results/{run}/file/{name}` parsed client-side (they are small), or a `GET /api/results/{run}/one-sided/{side}?offset&limit` frame endpoint if the files can be large — add the endpoint if `COUNTS.md`-sized runs are not the ceiling.
- Pattern `Callout` at the top only when a column's frequency makes one true (all values equal); otherwise omit.
- Key `Callout` at the bottom (static copy).

---

## §11 Results · Report

**Mockup:** `mockups/11-results-report.html`.

- Toolbar: explanation line, **Engine report** (`/api/results/{run}/report?engine=1` if that is how the engine's own HTML is served today; keep the current two-button behaviour), primary **Download report**.
- Run-folder row: path input, **Save report to folder** (`POST /api/results/{run}/save`), viewer height select (Fit / 820 / 1200).
- `.report-frame`: chrome line with the file name, then an `<iframe>` of `/api/results/{run}/report` at the chosen height. (The mockup draws the report inline only because it is static.)

---

## §12 Results · Downloads

**Mockup:** `mockups/12-results-downloads.html`.

- Toolbar: run folder path + **Open folder** (where `filepick` allows), **Download selected · n**, primary **Everything as one zip** (`POST /api/results/{run}/zip`).
- Files list (`.files`): one row per file from `GET /api/results/{run}/files` with a checkbox, mono name, a one-line description (static map by suffix: report / summary.json / summary.csv / differences.csv / differences.parquet / one_sided_A / one_sided_B / config.json / columns.csv / profile.csv) and the right-hand fact (row count where the API gives it, else "opens anywhere" / "machine-readable" / "re-runnable"). `profile.csv` greyed when not produced.
- Two callouts: the headless rerun command (`python -m tablecmp.run <config> --left … --right … --out …`), and Save mapping / Run from config links.

---

## §13 Log

**Mockup:** `mockups/13-log.html`.

- Opened from the header `Log` button; full-width page section (or drawer — either, consistently). Head: title, "n entries", **Copy as text**, **Clear** (`DELETE /api/log`), Close.
- `.log .entry`: time (mono grey) · kind (accent: load / auto / values / compare / write / profile) · the line, with sub-lines in grey. From `GET /api/log` `entries` as `LogPanel.tsx` reads them today.
- The rail stays; the Log count in the header updates.

---

## §14 Profile · home

**Mockup:** `mockups/14-profile-home.html`.

- Welcome card with the Profile headline ("One table, *every column.*"), **Try it on hr_employees.csv**, **Compare two tables instead**, and the three-step list.
- One `SideCard` (region name `File`, tag `P`, default name `Table`) in its empty state, max-width 720 px. Load disabled until a file is chosen; `Profile` button (name exact) appears in the rail once loaded.

---

## §15 Profile · result

**Mockup:** `mockups/15-profile-result.html`.

- Compact source card (one row: badge, Name, source `Seg`, Path, Browse, Loaded pill; foot: file · rows × columns · Parquet snapshot · delimiter · Rows to read · Advanced · Preview 10 rows · **Profile again**).
- Verdict: `Key emp_id — unique on every row · 3,000 rows × 7 columns · 0 duplicate rows · 0 nulls` from `GET /api/profiling` `profile` (headline, keys, duplicate count).
- **Columns** panel (`profiling/FrameTable.tsx` restyled): Column (key icon on key columns) · Type chip · Nulls · Distinct (`Bar` of distinct-% of rows + `n · %`) · Min · Max · Top value (+ %). Rows link to §16.
- Side: **Key candidates** (the chosen key as a key chip + "unique by itself" + why; the desbordante note), **What stands out** (the profile's notes as bullets; green dot for the all-clear line), **Value frequencies** (`GET /api/profiling/freq?column=`, column picker chip, 8 bars).

**Done when:** the profile e2e run passes and the text `3,000 rows × 7 columns · key: emp_id` (asserted by `tests/e2e`) is still present somewhere visible — keep that exact string in the verdict's sub-line.

---

## §16 Profile · column detail

**Mockup:** `mockups/16-profile-column.html`.

- Route: the Profile page with `?column=salary` (keep `usePage`); head row: **All columns** back link, column name (mono 20 px), type chip, "column 5 of 7 · name · file · n values", Previous / Next.
- Stat grid: Rows, Nulls, Distinct, Min, Q1, Median, Mean, Q3, Max, Std dev — whichever the profile frame has for the column (text columns get fewer).
- **Distribution** (numbers and dates): 10-bin histogram + bin table. **Data:** if the profile payload has no bins, add `GET /api/profiling/hist?column=&bins=10` returning `[{lo, hi, n}]` computed in DuckDB on the loaded snapshot (`width_bucket`). Flat/clustered sentence only when a simple rule fires (max/min bin ratio).
- **Outliers**: the profile's outlier list (1.5 × IQR) or the green "None" callout.
- **Shapes**: the profile's shape patterns (`9999.99` …) as bars; the one-decimal callout only when a shape with one decimal exists.
- **Most and least frequent**: from `/api/profiling/freq`.
- **Dependencies**: the profile's dependency findings as bullets; "trivially, the key" for the key.

---

## §17 Run from a saved config

**Mockup:** `mockups/17-run-from-config.html`.

- `sources/ConfigPanel.tsx` → a page section opened from the header: **Config** card (Upload / Path `Seg`, path + Browse, read pill "Read · 7 pairs · key emp_id", foot listing sources / pairs / steps / rows from the parsed config — `POST /api/sources/config` with a dry-run/preview if available, else parse client-side), **This run** card (Left / Right / Out overrides, **Run this config** → the config job, **Open in the setup instead**).
- **Batch** panel: a pairs table (left / right / name / out) + the `--pairs pairs.csv` command + **Load a pairs.csv** (client-side preview only; batch runs stay a CLI feature unless the API grows one).
