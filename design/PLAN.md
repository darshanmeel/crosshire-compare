# Implementation plan

Work top to bottom. Each box is one commit; each phase ends green on `npm test`, `npm run build`
and `python -m pytest tests -q`. Tick boxes as you finish them (`- [x]`). `SPEC.md` has the
detail for every item; `COMPONENTS.md` for the shared pieces.

## Phase 0 — foundations (nothing else fits until this is in)

- [x] 0.1 `tablecmp/theme.py`: add the `paper` flavour from `theme_paper.py` (dark + light sets), the new keys (`ground`, `side_a*`, `side_b*`, `diff_bg`, `diff_edge`, `pos_bg`, `neg_bg`, `warn_bg`, `accent_fill`, `accent_edge`) in `_CSS_VARS`, make `paper` the default `COMPARE_THEME`, and flip the mode default to light (`<html data-fs-mode="light">` unless the user chose dark; `ModeToggle` keeps working). `tests/test_web_meta.py` / `test_no_streamlit.py` assert on `--fs-bg` and the light selector — keep them passing.
- [x] 0.2 Fonts: `theme.FONTS` → Fraunces (400, 400 italic, 500) + IBM Plex Sans (400, 500, 600) + IBM Plex Mono (400, 500); `--font-display` Fraunces, `--font-sans` IBM Plex Sans, `--font-mono` IBM Plex Mono for `paper`. The report inherits them.
- [x] 0.3 `web/src/ui/icons.tsx`: the inline SVG icon set listed in `COMPONENTS.md`.
- [x] 0.4 `web/src/ui/`: `Button`, `Pill`, `Chip`, `Seg` (segmented control), `Field`/`Input`, `Card`, `Panel`, `Bar`, `Tabs`, `Tile`, `Callout`, `DiffCell`, `DataTable` wrapper — props as in `COMPONENTS.md`; global classes in `styles.css` ported from `mockups/style.css`. Delete the old `.btn`/`.expander`/`.note` rules only when nothing uses them.
- [x] 0.5 Shell: `shell/AppHeader.tsx` (wordmark, Compare/Profile switch with the `Page` radiogroup semantics, Connections / Run from config / Log buttons with counts) and `shell/StepRail.tsx` (steps + state + right-side actions). `App.tsx` drops `Sidebar`, the hero and `StatusStrip`; the main column becomes `.page` with sections 01 / 02 / 03. Keep `usePage` and the e2e radiogroup name `Page`.
- [x] 0.6 Empty state (screen 01): `shell/Welcome.tsx` card shown only while nothing is loaded; "Try the HR vs Payroll example" loads `examples/` through the existing path flow.

## Phase 1 — sources

- [x] 1.1 `sources/SourcePanel.tsx` → `sources/SideCard.tsx`: A / B cards side by side (screen 04), region names `File A` / `File B` / `File` kept. Name input, source `Seg` (Upload / Path on disk / Database), status `Pill` (Not loaded / Loading / Loaded · time / Error), options row (delimiter, header, Rows to read, Advanced), foot line (file · rows × columns · column names · Preview 10 rows).
- [x] 1.2 Upload dropzone (screen 01): drag-and-drop + "choose a file", on top of `UploadBox.tsx`.
- [x] 1.3 Database box (screen 03): connection select + Manage, Table / SQL query `Seg`, schema + table selects from `/api/sources/{tag}/schema`, Top N, snapshot tick; foot line names `schema.table`. *(Built without the schema / table selects: no API lists a connection's tables, so the card keeps one Table box.)*
- [x] 1.4 Preview 10 rows: `PreviewTable.tsx` opens inline under the card (collapsible), not a separate section.
- [x] 1.5 Rows to read popover (`RowsToRead.tsx`): WHERE / order / top N in a popover from the card; the full editor is screen 06.

## Phase 2 — columns

- [x] 2.1 `columns/ColumnTable.tsx` → pairing board (screen 04): role `Seg` (Key / Compare / Skip) per row, side-coloured column `Select` chips, read-as chip, transform summary (links to the editor), **Matched by** column (name / similarity / guess · check / only in A / only in B — from the setup view's per-pair origin; add it to `SetupView` if missing), case column. One-sided rows muted at the bottom.
- [x] 2.2 Actions bar: Match by data (dark), Reset to name matches, Save mapping, Load mapping… — existing `/api/setup/match`, `/reset`, `/mapping`.
- [x] 2.3 Panel foot: Key · Compare n · Skip n · the "guess — check" warning.

## Phase 3 — values

- [x] 3.1 `values/TransformBox.tsx` → `values/ValuesEditor.tsx` (screen 05): pairs list (left) + editor (right) with side `Seg`, numbered pipeline (`/api/setup/steps`), add-a-step chips from `/api/setup/functions` (never hard-coded), parameter inputs per op (`PARAM_LABELS`), preview table from `/api/setup/try`, match count from `/api/setup/check`.
- [x] 3.2 `HowValuesRead.tsx` moves under the pairs list: null tokens, empty-is-null, trim, ignore case (label unchanged), numeric tolerance.

## Phase 4 — rows

- [x] 4.1 `keys/KeyBox.tsx` → match mode `Seg` (On a key / By position / By hash) + key chips + Suggest keys (screen 06).
- [x] 4.2 `values/FiltersBox.tsx` + `sources/RowsToRead.tsx` → per-side "Rows to read" cards (WHERE, order by, top N, resulting count pill).
- [x] 4.3 `keys/ProfileBox.tsx` → "Profile by bucket" row (tick + column select).
- [x] 4.4 Compact Rows summary row on the setup page (screen 04 §03) linking to the editor.

## Phase 5 — running

- [x] 5.1 `shell/RunDisc.tsx` → `compare/RunningPanel.tsx` (screen 07): headline, current line, progress, the job's reported steps as a list (done / running / to do), Cancel. *(No Cancel: the jobs API has none, as SPEC §07 allows.)* Rail step 4 shows `run` state.

## Phase 6 — results

- [x] 6.1 `results/ResultsView.tsx`: verdict sentence (existing `.verdict` text, restyled), **row outcome** stacked bar + legend, `Tabs` (Summary / Differing rows n / One-sided rows n / Report / Downloads) replacing the radio switch.
- [x] 6.2 Summary (screen 08): tiles, per-column match table with bars, "Not compared" foot, **By bucket** table (`/api/results/{run}/buckets/{bucket}`), **Why they differ** panel (value pairs per column — `SPEC.md` §08 says where the data comes from).
- [x] 6.3 Differing rows (screen 09): one row per key, `DiffCell` for changed cells, column filter chips with counts, search, show-columns menu, differences.csv button, load more, near-match button (`/near-match`).
- [x] 6.4 One-sided rows (screen 10): two panels with the first rows and "show all", the pattern callout when the engine's near-match/frequency data supports one.
- [x] 6.5 Report (screen 11): toolbar, run-folder row with Save to folder, viewer height select, the report in an iframe (`/api/results/{run}/report`).
- [x] 6.6 Downloads (screen 12): file list with descriptions and row counts (`/files`), selected download, zip (`/zip`), the headless rerun callout.

## Phase 7 — drawers and panels

- [x] 7.1 `shell/LogPanel.tsx` → log page/drawer (screen 13) opened from the header; entries with kind, time, line and sub-lines; Copy as text, Clear (`DELETE /api/log`).
- [x] 7.2 `connections/ConnectionsManager.tsx` → right-hand drawer (screen 02): saved connections as cards (kind chip, status pill, Edit), add-a-connection form from `/api/meta` `form`, Test / Save, password in file vs environment variable.
- [x] 7.3 `sources/ConfigPanel.tsx` → Run from config page (screen 17): config card with what it holds, override files, Run; batch pairs table + command.

## Phase 8 — profile

- [x] 8.1 Profile home (screen 14): same shell, `profile-empty` rail, single source card with dropzone.
- [x] 8.2 Profile result (screen 15): compact source card, verdict, stats table with distinct bars (`profiling/FrameTable.tsx`), Key candidates, What stands out, Value frequencies (`/api/profiling/freq`).
- [x] 8.3 Column detail (screen 16): route `?column=`; stat grid, histogram (see `SPEC.md` §16 for the one new endpoint), outliers, shapes, most/least frequent, dependencies; previous / next column.

## Phase 9 — report and docs

- [x] 9.1 `tablecmp/report.py`: restyle on the `paper` tokens (verdict, tiles, per-column table, diff cells as `A → B`) so the report matches the page. `tests/test_report.py` must stay green.
- [ ] 9.2 `docs/*.png`: regenerate with `design/scripts/snap.py`; update the README's screenshots and the sidebar wording it describes.
- [x] 9.3 Remove dead CSS and components (`Sidebar.tsx`, `StatusStrip.tsx`, old `.expander` rules) once nothing imports them.
