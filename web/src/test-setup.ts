import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { resetKept } from "./profiling/SaveRow";
import { resetPicks } from "./results/pickStore";
import { resetView } from "./shell/view";
import { resetForms } from "./sources/formStore";
import { resetLoadTimes } from "./sources/loadTime";

// Every module-level store back to its start after each test, so no file has to list them.
afterEach(() => {
  resetForms();
  resetView();
  resetPicks();
  resetKept();
  resetLoadTimes();
  location.hash = "";
  try { localStorage.clear(); } catch { /* none */ }
});
