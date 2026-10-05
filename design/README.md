# The redesign — what is in this folder

A full visual and structural redesign of the CrossHire Compare page, as 17 static mockups
built on the repo's own example data, plus everything Claude Code needs to implement them.

| File | Use it for |
|---|---|
| `PLAN.md` | The order of work, as phases with checkboxes. Tick as you go. |
| `SPEC.md` | One section per screen: the mockup, what changes in which React module, which API calls feed it, the states, the acceptance checks. |
| `COMPONENTS.md` | The shared UI pieces (buttons, pills, chips, segmented control, rail, tabs, panel, table, bar, diff cell…) — their props and the mockup CSS they come from. Build these once in phase 0. |
| `tokens.css` | The design tokens as `--fs-*` custom properties: `paper` (light, the new default) and the dark mapping. The names line up with `tablecmp/theme.py`. |
| `theme_paper.py` | The same tokens as a Python dict ready to paste into `tablecmp/theme.py` (`THEMES["paper"]`, `LIGHT["paper"]`, the extra `_CSS_VARS`). |
| `mockups/` | `index.html` → all 17 pages. Each page is self-contained HTML + `style.css` + bundled fonts; `screenshots/` has the PNG of each at 1440 px. Open them in a browser; the links walk the flow. |
| `scripts/snap.py` | Starts the real app on a free port, loads the example pair through the API, runs Auto + Compare + Profile, and screenshots every screen into `progress/` for a side-by-side with `mockups/screenshots/`. |
| `progress/` | Written by `snap.py`; git-ignored. |

## The design in one paragraph

A light "paper" workbench instead of the dark editorial page: a 56 px header (wordmark, Compare / Profile switch, Connections, Run from config, Log), a **step rail** (Sources → Columns → Rows → Results, each step showing its state, the primary action at the right) in place of the hero and the 5-cell status strip, and the two sources as **A / B cards side by side** in the main column instead of stacked in a sidebar. Side A is blue, side B is clay, and that colour coding carries through every table. The column table becomes a pairing board (role segmented control, column chips, read-as chip, transform summary, "matched by" confidence). Results open with the engine's one-sentence verdict, a stacked row-outcome bar, and tabs; the differing-rows view shows **one row per key** with changed cells reading `HR value → Payroll value`. Profile gets the same shell, a stats table with inline bars, and a per-column drill-in. Typography: Fraunces for the wordmark and verdicts only, IBM Plex Sans for UI, IBM Plex Mono for labels, values and code.

## The screens

| # | Page | Mockup |
|---|---|---|
| 01 | Compare · home, nothing loaded | `mockups/01-home.html` |
| 02 | Connections drawer | `mockups/02-connections.html` |
| 03 | Side B from a database table | `mockups/03-source-database.html` |
| 04 | Setup · both loaded, columns paired | `mockups/04-loaded.html` |
| 05 | Transform & convert values | `mockups/05-transform.html` |
| 06 | Rows · match mode, rows to read, buckets | `mockups/06-rows.html` |
| 07 | Running | `mockups/07-running.html` |
| 08 | Results · Summary | `mockups/08-results-summary.html` |
| 09 | Results · Differing rows | `mockups/09-results-diffs.html` |
| 10 | Results · One-sided rows | `mockups/10-results-onesided.html` |
| 11 | Results · Report | `mockups/11-results-report.html` |
| 12 | Results · Downloads | `mockups/12-results-downloads.html` |
| 13 | Log | `mockups/13-log.html` |
| 14 | Profile · home | `mockups/14-profile-home.html` |
| 15 | Profile · result | `mockups/15-profile-result.html` |
| 16 | Profile · column detail | `mockups/16-profile-column.html` |
| 17 | Run from a saved config | `mockups/17-run-from-config.html` |

Everything in the mockups that is a number comes from `examples/` and reconciles with
`tests/COUNTS.md` (649 rows differ, 687 cells, department 337 / salary 319 / active 31, 40 and
25 one-sided). The only placeholders are the second saved connection and the batch file paths.

## Working with Claude Code

- `/redesign-screen 04` — implements screen 04 from `SPEC.md` §04 and its mockup, runs the checks, ticks `PLAN.md`.
- `/redesign-check` — vitest + build + pytest, then `snap.py`, then a short report of what differs from the mockups.
- `/redesign-status` — reads `PLAN.md`, says what is done and what to do next.

Start with phase 0 in `PLAN.md`: tokens, fonts, shared components and the new shell. Nothing
else fits until that is in.
