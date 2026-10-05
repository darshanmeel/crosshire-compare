// web/src/profiling/testkit.ts - what the profiling tests share (not a test file itself)
import type { Frame, Profile, ProfilingView, SaveDefaults } from "./types";

export const T = (columns: string[], rows: unknown[][] = []): Frame => ({ columns, rows });

export function profile(over: Partial<Profile> = {}): Profile {
  return {
    headline: "3,000 rows × 7 columns · key: emp_id · 0 duplicate rows",
    keys: { tone: "success", text: "Key: **emp_id** - unique on every row. Found by measuring every column.",
            table: T(["Key columns", "Distinct", "Unique"], [["emp_id", 3000, "yes"]]) },
    stats: T(["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled", "Distinct % of rows", "Top value", "Top %",
              "Min", "Max", "Mean", "Avg length", "Min length", "Max length"],
             [["emp_id", "text", 3000, 0, 0.0, 3000, 100.0, 100.0, "E10001", 0.03, "E10001", "E13000", "", 6.0, 6, 6],
              ["department", "text", 3000, 0, 0.0, 8, 0.27, 0.27, "Support", 13.73, "Engineering", "Support", "", 7.5, 5, 11]]),
    notes: ["key: emp_id - unique on every row", "department: 8 values - Support, Marketing"],
    outliers: T(["Column", "Type", "P1"], [["salary", "number", 41000]]),
    patterns: T(["Column", "Pattern", "Collapsed", "Count", "%", "Example"]),
    deps: T(["Determines", "Determined", "Kind", "Distinct"]),
    corr: T(["Column A", "Column B", "r"]),
    matrix: T(["Column"]), matrix_note: "", search: { key_cols: 5, top_keys: 5, key_sample: 100_000, shortlist: 10 },
    freq: { columns: ["emp_id", "department", "a/b %"], picked: ["emp_id"],
            titles: { emp_id: "**emp_id** - text · 3,000 distinct · 0.0% null",
                      department: "**department** - text · 8 distinct · 0.0% null",
                      "a/b %": "**a/b %** - text · 2 distinct · 0.0% null" } },
    ...over,
  };
}

export function profiling(over: Partial<ProfilingView> = {}): ProfilingView {
  return { profile: profile(), stale: false, made: "20261004-120000", ...over };
}

export const defaults = (over: Partial<SaveDefaults> = {}): SaveDefaults =>
  ({ csv_name: "HR__profile.csv", save_folder: "D:/out/HR__20261004-120000", ...over });

export const entry = (id: string, state: string, label: string, lines: string[] = []) =>
  ({ id, at: "10:00:00", kind: "Profile", label, state, seconds: null, lines, page: "Profiling" });
