---
description: Where the redesign stands — ticked vs open items in design/PLAN.md and the next step
---

Read `design/PLAN.md` and `git log --oneline -20`. Report:

- Each phase with done / total items, and the open items by number.
- Whether the last commit's checks were green (look for a red check in the most recent commit message or run `cd web && npm test` quickly if unsure).
- The single next item to do, with its SPEC section and mockup file, and the command to start it: `/redesign-screen <item>`.
- Anything in PLAN.md that is ticked but whose files no longer exist or whose test is red (a stale tick).

Keep it under 20 lines.
