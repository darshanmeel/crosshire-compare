// web/src/setup/testkit.tsx - what the setup tests share (not a test file itself)
import type { CompareState } from "../compare/types";
import type { Row, SetupReady } from "./api";

export { json, mount, type Call } from "../sources/testkit";

export function row(a: string, b: string, over: Partial<Row> = {}): Row {
  const paired = !!(a && b);
  return { "A column": a, "B column": b, "Common name": (a || b).toLowerCase(), Type: "text", Key: false,
           Compare: paired, Case: "", "Matched by": paired ? "name" : "", "A detected": a ? "VARCHAR" : "",
           "A looks like": "", "B detected": b ? "VARCHAR" : "", "B looks like": "",
           Role: paired ? "compared" : `only in ${a ? "HR" : "PR"}`, tone: paired ? "" : "neg", ...over };
}

/** HR against PR: emp_id and salary paired, department on HR alone, Dept on PR alone. */
export function setup(over: Partial<SetupReady> = {}): SetupReady {
  return {
    ready: true, names: ["HR", "PR"], rev: "1.a", columns: { A: ["emp_id", "salary", "department"], B: ["EmployeeId", "Salary", "Dept"] },
    types: ["text", "number", "date", "timestamp", "boolean"], cases: ["", "ignore", "exact"],
    rows: [row("emp_id", "EmployeeId", { "Common name": "emp_id" }), row("salary", "Salary", { Type: "number" }),
           row("department", ""), row("", "Dept")],
    pairs: 2, chips: [{ text: "emp_id", cls: "" }, { text: "salary", cls: "" }, { text: "department · only in HR", cls: "off" },
                      { text: "Dept · only in PR", cls: "off" }],
    duplicates: [], card: [{ label: "Paired", html: '2 columns · <span class="m">1 only in HR, 1 only in PR</span>' },
                           { label: "Key", html: '<span class="warn">none ticked</span>' }],
    specs: [{ canon: "emp_id", kind: "text", a_src: "emp_id", b_src: "EmployeeId", a_steps: [], b_steps: [], case: "", describe: "text", a_said: [], b_said: [] },
            { canon: "salary", kind: "number", a_src: "salary", b_src: "Salary", a_steps: [], b_steps: [], case: "", describe: "number", a_said: [], b_said: [] }],
    keys: [], compare: ["emp_id", "salary"], only_a: ["department"], only_b: ["Dept"], can_match: true, data_match: null,
    said: [], settings: { trim: true, empty_as_null: true, ignore_case: false, tolerance: 0, null_tokens: "NULL, N/A", nokey_mode: "hash" },
    looks_help: "What a sample of this side's values looks like", ...over,
  };
}

/** GET /api/compare with no gate, no run and the default settings. */
export function compareState(over: Partial<CompareState> = {}): CompareState {
  return {
    gate: "", names: ["HR", "PR"], filter_error: "", sig: "s1", stale: false, busy: false, said: [], run: null,
    strip: { cells: { Files: "", Columns: "", Key: "", Compare: "", Result: "" }, tones: {} },
    settings: { display_rows: 1000, auto_rerun: false, out_fmt: "csv", auto_profile: false }, ...over,
  };
}

/** What the Compare page's sections read besides the setup: no run going, an empty log. */
export const IDLE = {
  compare: { busy: false, run: null, said: [], stale: false },
  log: { entries: [] },
};
