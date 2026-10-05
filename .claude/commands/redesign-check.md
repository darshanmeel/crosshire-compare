---
description: Run every check for the redesign (vitest, build, pytest, screenshots) and report what differs from the mockups
---

Run the full check for the CrossHire Compare redesign and report; fix nothing unless asked.

1. `cd web && npm test` — report failures by test file.
2. `cd web && npm run build` — type errors and build errors verbatim.
3. `python -m pytest tests -q` — failures with the assertion line. `tests/test_web_build.py` failing means the build in `tablecmp/web_dist` is older than `web/src`: say so.
4. `python design/scripts/snap.py` — list which screens were captured in `design/progress/` and which were skipped.
5. For each captured screen, open it next to `design/mockups/screenshots/<same name>.png` and note the differences that matter: missing elements, wrong order, wrong state, colours used for the wrong role (side A blue / side B clay / differing amber / key ink), text that still reads like the old page, anything below 4.5:1 contrast, controls that are not real buttons/inputs.
6. Summarise: green/red per check, screens done vs. remaining per `design/PLAN.md`, and the three most valuable fixes to make next.
