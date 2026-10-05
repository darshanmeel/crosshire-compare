---
description: Implement one redesign screen from design/SPEC.md and its mockup, run the checks, tick PLAN.md
argument-hint: <screen number 01–17, or a PLAN.md item like 0.4>
---

Implement redesign item **$ARGUMENTS** of CrossHire Compare. Follow CLAUDE.md's rules throughout.

1. Read `design/PLAN.md` and find the item. If it is a phase-0 item (tokens, fonts, icons, shared components, shell), do that item; if it is a screen number, do every PLAN item that screen needs and confirm phase 0 is already ticked — if it is not, stop and say so.
2. Read the screen's section in `design/SPEC.md`, open `design/mockups/<nn>-*.html` (read the HTML — it is the exact layout and copy) and look at `design/mockups/screenshots/<nn>-*.png`. Read `design/COMPONENTS.md` for the shared pieces the screen uses.
3. Read the React modules the spec names before changing them, and their `*.test.tsx`. Note every accessible name the tests and `tests/e2e` rely on (CLAUDE.md rule 4) and keep it.
4. Implement. Shared pieces go in `web/src/ui/`; screen code stays in its section folder; styles on `var(--fs-*)` only. If the spec says an endpoint is missing, add it in the matching `tablecmp/web/routes_*.py` with a pytest and run `cd web && npm run gen:api`.
5. Check, in this order, and fix until green: `cd web && npm test`, `cd web && npm run build`, `python -m pytest tests -q`. Then `python design/scripts/snap.py` and compare `design/progress/<nn>-*.png` with the mockup screenshot; fix layout differences that matter (structure, order, states, spacing, colour roles), not pixel noise.
6. Tick the item(s) in `design/PLAN.md`. Commit with the item in the subject, e.g. `ui(09): differing rows as one row per key`. Do not commit a red check.
7. Report in a few lines: what changed (files), anything the spec needed that the API did not have, any accessible name you had to change and the test you updated with it, and what is next in PLAN.md.
