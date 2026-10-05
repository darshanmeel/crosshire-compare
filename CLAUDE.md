# CrossHire Compare — working notes for Claude Code

CrossHire Compare reads two tables (CSV / JSON / Parquet / a database table) into DuckDB,
pairs their columns, matches rows on a key and reports every difference. A second page
profiles one table. Backend: FastAPI + DuckDB in `tablecmp/`. Frontend: React 19 + Vite +
TypeScript in `web/`, built into `tablecmp/web_dist/` and served by FastAPI.

**Current job: implement the UI redesign in `design/`.** The engine, the API and the file
outputs stay as they are; the page is rebuilt to the mockups. Read `design/README.md` first,
then work through `design/PLAN.md` one phase at a time. `/redesign-screen <nn>` implements one
screen; `/redesign-check` runs every check; `/redesign-status` says what is left.

## Commands

```bash
# once
python -m pip install -r requirements-dev.txt          # app + pytest + pytest-playwright
python -m playwright install chromium                   # for tests/e2e and design/scripts/snap.py
cd web && npm install && cd ..

# develop
python compare_app.py --no-browser                      # API + built page on http://127.0.0.1:8501
cd web && npm run dev                                   # hot reload on http://localhost:5173, proxies /api and /theme.css to 8501

# check — run all three before calling any screen done
cd web && npm test && cd ..                             # vitest (web/src/**/*.test.tsx)
cd web && npm run build && cd ..                        # tsc --noEmit + vite build → tablecmp/web_dist + source hash
python -m pytest tests -q                               # 537 tests; tests/test_web_build.py fails if web_dist is older than web/src

# when an API shape changes (rare in this job)
cd web && npm run gen:api                               # regenerates src/api/schema.d.ts from the FastAPI OpenAPI

# mockup-vs-app comparison
python design/scripts/snap.py                           # screenshots the running app into design/progress/
```

## Where things are

| Path | What |
|---|---|
| `tablecmp/theme.py` | **Every colour, font and radius.** Served to the page as `/theme.css` (`--fs-*` custom properties) and inlined into the HTML report. Two flavours (`aurora`, `violet`), each with a dark and a light set; `COMPARE_THEME` picks one. |
| `tablecmp/web/routes_*.py` | The API: `/api/sources`, `/api/setup`, `/api/compare`, `/api/auto`, `/api/results`, `/api/profiling`, `/api/connections`, `/api/log`, `/api/jobs/{id}`. Long work runs as jobs; the page polls. |
| `tablecmp/report.py` | The standalone HTML report (same tokens). Restyling it is the **last** phase, not the first. |
| `tablecmp/values.py` | `STEPS` — the transform operations and their DuckDB templates. The UI lists these; never hard-code the list. |
| `web/src/App.tsx` | Page shell: today a 340 px sidebar (`shell/Sidebar.tsx`) + long-scroll main with a hero. The redesign replaces this with a header + step rail (see `design/SPEC.md` §0). |
| `web/src/{sources,columns,values,keys,compare,results,profiling,connections,shell,setup,ui}` | One folder per section of the page; each has its `.css` and `.test.tsx`. Keep that layout. |
| `web/src/styles.css` | Global CSS on the `--fs-*` tokens. The redesign's shared classes go here; section-specific CSS stays in the section's file. |
| `web/src/api/client.ts`, `schema.d.ts` | Typed API client; `schema.d.ts` is generated — do not edit by hand. |
| `tests/` | pytest: unit tests per module, HTTP flows (`tests/webflow.py`, `tests/test_web_flows.py`), browser runs in `tests/e2e/`. `tests/COUNTS.md` holds the expected counts for the sample pair. |
| `examples/` | `hr_employees.csv` vs `payroll_employees.csv` (3,000 vs 2,985 rows, key `emp_id`, 649 differing rows) and `sample.duckdb` (`hr.employees`, `payroll.employees`). Every mockup uses this data. |
| `design/` | The redesign: spec, plan, tokens, 17 HTML mockups with screenshots, snapshot script. |

## Rules for the redesign

1. **Frontend only.** Do not change what the engine computes, the API's shapes or the files a run writes. If a screen needs data the API does not expose yet (see `design/SPEC.md` for the two or three cases), add a small read-only endpoint in the matching `routes_*.py`, test it in `tests/`, run `npm run gen:api`, and say so in the commit.
2. **Colours and fonts live in `tablecmp/theme.py`, nowhere else.** Add the new `paper` flavour from `design/theme_paper.py`, extend `_CSS_VARS` for the new tokens, and make `paper` the default. CSS uses `var(--fs-…)`; a literal hex in `web/src` is a bug. Keep `aurora` and `violet` loading without errors (they become the dark looks).
3. **Match the mockups, not the old page.** `design/mockups/<nn>-….html` is the source of truth for layout, copy and states; `design/SPEC.md` says which React modules change and which API calls feed each element. When the mockup and the spec disagree, the mockup wins for looks and the spec wins for behaviour.
4. **Keep accessible names stable** so `tests/e2e` and the vitest suites keep passing: regions `File A` / `File B` / `File`, radiogroup `Page` (Compare / Profiling), button `Figure it all out and compare`, label `Path on disk`, label `Path to CSV or JSON`, label `Ignore case in values`, buttons starting with `Load`, button `Profile`. Visible text may change (the mockups say *Auto · figure it all out*) — put the old name in `aria-label` or keep it as the accessible name. If a name truly must change, change the test in the same commit and say why.
5. **Real controls.** `<button>`, `<a href>`, `<input>` + `<label>`, `aria-label` on icon-only buttons, `aria-pressed` on toggles, `role="group"` on segmented controls. No `onClick` on a `div`. Tab order must follow the visual order.
6. **Icons are inline SVG** from one module `web/src/ui/icons.tsx` (stroke, `currentColor`, 14 px / 12 px). No icon fonts, no emoji.
7. **Numbers** are right-aligned in tables, `font-variant-numeric: tabular-nums`, thousands separators from `Intl.NumberFormat`. Percentages to two decimals, as the engine reports them.
8. **One screen per commit.** Implement, run the three checks, tick the box in `design/PLAN.md`, commit with the screen number in the subject (`ui(04): sources cards side by side`). Do not start the next screen with a red check.
9. **Do not** edit `tablecmp/web_dist/` by hand, reintroduce the hero above loaded data, add a CSS framework or a component library, or bring in new fonts beyond Fraunces, IBM Plex Sans and IBM Plex Mono.
10. **Readability first.** Text contrast ≥ 4.5:1 (3:1 at ≥ 24 px). Colours that must be told apart (side A vs B, matched vs differing) also differ in lightness. Hit targets ≥ 32 px inside tables, ≥ 36 px elsewhere.

## Conventions you will meet in the code

- Server state through TanStack Query; the setup and compare views are refreshed with `refreshSetup(qc)` after any change (see `web/src/setup/api.ts`). Form state for the two sides is in `sources/formStore.ts`.
- Jobs: `POST` returns `{id, kind, state}`; poll `GET /api/jobs/{id}` until `state !== "running"`. `useLog()` exposes the last entry per page — the running screen (`design/SPEC.md` §07) is built on it.
- Tests mock the API with the `testkit.tsx` stubs in each folder; add a stub when you add a call.
- Copy style: sentence case, en dashes written as " - " in the engine's strings, numbers always formatted. Tooltips and inline help are short; the mockups removed the paragraphs of instructions on purpose.

## Definition of done for a screen

- Looks like its mockup at 1440 px and still works at 390 px (menus stack, toolbars wrap, wide tables scroll inside their panel).
- `npm test`, `npm run build`, `python -m pytest tests -q` all green.
- `python design/scripts/snap.py` produces the screen in `design/progress/` and it reads the same as `design/mockups/screenshots/<nn>-….png`.
- `design/PLAN.md` ticked; commit message names the screen.
