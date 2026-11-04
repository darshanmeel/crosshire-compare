# CrossHire Compare — working notes for Claude Code

CrossHire Compare reads two tables (CSV / JSON / Parquet / Excel / a database table) into DuckDB,
pairs their columns, matches rows on a key and reports every difference. A second page
profiles one table. Backend: FastAPI + DuckDB in `tablecmp/`. Frontend: React 19 + Vite +
TypeScript in `web/`, built into `tablecmp/web_dist/` and served by FastAPI.

## Commands

```bash
# once
python -m pip install -r requirements-dev.txt          # app + pytest + pytest-playwright
python -m playwright install chromium                   # for tests/e2e (they skip without it), or: pytest tests/e2e --browser-channel msedge
cd web && npm install && cd ..

# develop
python compare_app.py --no-browser                      # API + built page on http://127.0.0.1:8501
cd web && npm run dev                                   # hot reload on http://localhost:5173, proxies /api and /theme.css to 8501

# check — run all three before calling a change done
cd web && npm test && cd ..                             # vitest (web/src/**/*.test.tsx)
cd web && npm run build && cd ..                        # tsc --noEmit + vite build → tablecmp/web_dist + source hash
python -m pytest tests -q                               # 725 tests; tests/test_web_build.py fails if web_dist is older than web/src
```

## Where things are

| Path | What |
|---|---|
| `tablecmp/theme.py` | **Every colour, font and radius.** Served to the page as `/theme.css` (`--fs-*` custom properties) and inlined into the HTML report. Flavours `paper` (default, opens light), `aurora` and `violet` (open dark); `COMPARE_THEME` picks one. |
| `tablecmp/web/routes_*.py` | The API: `/api/sources`, `/api/setup`, `/api/compare`, `/api/auto`, `/api/results`, `/api/profiling`, `/api/connections`, `/api/log`, `/api/jobs/{id}`. Long work runs as jobs; the page polls. |
| `tablecmp/report.py` | The standalone HTML report (same tokens). |
| `tablecmp/values.py` | `STEPS` — the transform operations and their DuckDB templates. The UI lists these; never hard-code the list. |
| `tablecmp/loading.py` | Rows to read: `QUICK_OPS` and the quick clause the filter builder adds. |
| `web/src/App.tsx` | Page shell: header (`shell/AppHeader.tsx`) + step rail (`shell/StepRail.tsx`), welcome panel before anything is loaded. |
| `web/src/{sources,columns,values,keys,compare,results,profiling,connections,shell,setup,ui}` | One folder per section of the page; most have their `.css` and `.test.tsx`. Keep that layout. |
| `web/src/sources/ValuePicker.tsx` | "Pick from values" beside a Rows-to-read filter's Value box (`GET /api/sources/{tag}/values`); used on the source card and the Rows page card. |
| `web/src/results/{TopValues,DistinctValues,valuesApi}.ts(x)` | Value views on the results (`GET /api/results/{run}/values`): Summary top-value strips and the opened detail; *Distinct values · count(\*)* on Differing and One-sided rows. |
| `web/src/results/{DiffRowsTab,BucketProfile}.tsx` | Differing rows (key + differing columns, Columns menu); Profile by bucket with the by-key-value bars. |
| `web/src/profiling/KeyCombo.tsx`, `profiling/column/KeyView.tsx` | Check a key on any columns (`GET /api/profiling/keycombo`); the key column's page (`routes_col_key.py`). |
| `web/src/ui/{kit,icons}.tsx`, `web/src/styles.css` | Shared controls, the icon set, global CSS on the `--fs-*` tokens. Section CSS stays in the section's file. |
| `web/src/api/client.ts` + `types.ts` (or next to the call, e.g. `setup/api.ts`) | API client and **hand-written** response types. |
| `tests/` | pytest: unit tests per module, HTTP flows (`tests/webflow.py`, `tests/test_web_flows.py`), browser runs in `tests/e2e/`. `tests/COUNTS.md` holds the expected counts for the sample pair. |
| `examples/` | `hr_employees.csv` vs `payroll_employees.csv` (3,000 vs 2,985 rows, key `emp_id`, 649 differing rows) and `sample.duckdb` (`hr.employees`, `payroll.employees`). |

## Rules

1. **Colours and fonts live in `tablecmp/theme.py`, nowhere else.** CSS uses `var(--fs-…)`; a literal hex in `web/src` is a bug. Keep all three flavours loading.
2. **Keep accessible names stable** so `tests/e2e` and the vitest suites keep passing: regions `File A` / `File B` / `File`, radiogroup `Page` (Compare / Profiling), button `Figure it all out and compare`, label `Path on disk`, label `Path to CSV or JSON`, label `Ignore case in values`, buttons starting with `Load`, button `Profile`. Visible text may differ — keep the old name as `aria-label`. If a name must change, change its test in the same change and say why.
3. **Real controls.** `<button>`, `<a href>`, `<input>` + `<label>`, `aria-label` on icon-only buttons, `aria-pressed` on toggles, `role="group"` on segmented controls. No `onClick` on a `div`. Tab order follows the visual order.
4. **Icons are inline SVG** from `web/src/ui/icons.tsx` (stroke, `currentColor`, 14 px / 12 px). No icon fonts, no emoji.
5. **Numbers** right-aligned in tables, `font-variant-numeric: tabular-nums`, thousands separators from `Intl.NumberFormat`. Percentages to two decimals.
6. **Readability.** Text contrast ≥ 4.5:1 (3:1 at ≥ 24 px). Colours that must be told apart (side A vs B, matched vs differing) also differ in lightness. Hit targets ≥ 32 px in tables, ≥ 36 px elsewhere. Works at 1440 px and 390 px (menus stack, toolbars wrap, wide tables scroll inside their panel).
7. **API types are hand-written.** `npm run gen:api` is broken with TypeScript 7; when a shape changes, update the type next to the call. A new endpoint is read-only where it can be and tested in `tests/`.
8. **Tests mock the API** with the `testkit` stubs in each folder; add a stub when you add a call.
9. **Do not** edit `tablecmp/web_dist/` by hand, add a CSS framework or a component library, or bring in new fonts beyond Fraunces, IBM Plex Sans and IBM Plex Mono (paper's; aurora and violet keep their Inter and JetBrains Mono).

## Conventions you will meet in the code

- Server state through TanStack Query; the setup and compare views are refreshed with `refreshSetup(qc)` after any change (`web/src/setup/api.ts`). Form state for the two sides is in `sources/formStore.ts`; picks that survive a page switch (view, bucket, columns opened) in `results/pickStore.ts`.
- Jobs: `POST` returns `{id, kind, state}`; poll `GET /api/jobs/{id}` until `state !== "running"`. `useLog()` exposes the last entry per page; the running panel is built on it.
- Copy style: sentence case, en dashes written as " - " in the engine's strings, numbers always formatted. Tooltips and inline help are short.

## Checking in this environment

- Playwright's Chromium may be missing: for screenshots launch the system Edge, `p.chromium.launch(channel="msedge")`.
- Screenshots stay out of git; write them to a temp folder.
