import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { resetView, setView } from "../shell/view";
import { resetForms } from "../sources/formStore";
import { body, json, mount, view, type Call } from "../sources/testkit";
import { ProfilingPage, STALE } from "./ProfilingPage";
import { NOTHING_STANDS_OUT } from "./ProfileView";
import { resetPicks } from "./picks";
import { resetKept } from "./SaveRow";
import { defaults, entry, profile, profiling, T } from "./testkit";

beforeEach(() => { resetForms(); resetView(); resetPicks(); resetKept(); });

const FREQ = { column: "emp_id", title: "", top: T(["Value", "Count", "%"], [["Support", 412, 13.73]]), bottom: T(["Value", "Count", "%"], [["Legal", 355, 11.83]]) };
const CASTS = { columns: [{ column: "department", kind: "text", filled: 3000,
  number: { any: 2990, form: "with , removed", n: 2990, before: 4, after: 2 } }] };
const loaded = () => body({ sides: { ...body().sides,
  P: view("P", { loaded: true, label: "hr.csv", rows: 3000, columns: ["emp_id", "department"] }) } });

function stub(calls: Call[], over: (url: string) => Response | undefined = () => undefined) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const o = over(url);
    if (o) return o;
    if (url === "/api/sources") return json(loaded());
    if (url.startsWith("/api/profiling/defaults?")) return json(defaults());
    if (url === "/api/profiling") return json(profiling());
    if (url.startsWith("/api/profiling/freq?")) return json(FREQ);
    if (url === "/api/profiling/casts") return json(CASTS);
    if (url.startsWith("/api/profiling/parts?column=salary")) return json({ column: "salary", kind: "number", groups: [
      { title: "Digits before the point", total: 3000, rows: [{ label: "4-6", n: 3000 }] }, { title: "Places after the point", total: 3000, rows: [{ label: "1-3", n: 3000 }] }] });
    if (url.startsWith("/api/profiling/keycheck?column=emp_id")) return json({ column: "emp_id", rows: 3000, filled: 3000, nulls: 0, blanks: 0,
      distinct: 3000, duplicates: 0, case_variants: 0, spaces: 0, width: { min: 6, max: 6 }, shapes: [{ shape: "A99999", n: 3000, example: "E10001" }],
      prefix: { text: "E", n: 3000 }, number: { min: 10001, max: 13000, distinct: 3000, gaps: 0, leading_zeros: 0 }, order: "ascending", next_id: "E13001" });
    if (url.startsWith("/api/profiling/spelling?column=department")) return json({ column: "department", distinct: 8, folded: 8, padded: 0 });
    if (url.startsWith("/api/profiling/spelling?")) return json({ column: "emp_id", distinct: 3000, folded: 3000, padded: 0 });
    if (url.startsWith("/api/profiling/hist?")) return json({ column: "salary", kind: "number", bins: [{ lo: 0, hi: 5, n: 2 }, { lo: 5, hi: 10, n: 8 }] });
    return json({ entries: [], last: {} });
  }));
}

test("before a profile: no Profile button of its own (it is in the rail), the tips say what it will do", async () => {
  stub([], (url) => (url === "/api/profiling" ? json(profiling({ profile: null, made: "" })) : undefined));
  mount(<ProfilingPage />);
  expect(await screen.findByText(/Every column is measured/)).toBeInTheDocument();
  expect(screen.getByText("Ready to profile")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Profile" })).toBeNull();
});

test("the profile: verdict with the engine's headline, columns, key candidates, what stands out, the folds", async () => {
  stub([]);
  mount(<ProfilingPage />);
  expect(await screen.findByText("3,000 rows × 7 columns · key: emp_id · 0 duplicate rows")).toBeInTheDocument();
  const verdict = screen.getByRole("region", { name: "Profile result" });
  expect(verdict).toHaveTextContent(/Key emp_id — unique on every row · 3,000 rows × 2 columns · 0 duplicate rows · 0 nulls/);
  // Columns: a row per column, the key marked, the name opens the detail
  const table = screen.getByRole("table", { name: "Columns" });
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(table).getByRole("img", { name: "key" })).toBeInTheDocument();
  expect(within(table).getByText("100.00%", { exact: false })).toBeInTheDocument();
  // Key candidates: the chosen key, why, and the engine's sentence
  const keys = screen.getByRole("list", { name: "Key candidates" });
  expect(within(keys).getByText("unique by itself")).toBeInTheDocument();
  // the engine's note, a bullet per sentence
  expect(screen.getByText("Found by measuring every column")).toBeInTheDocument();
  // What stands out: the key and a column's list of values are said elsewhere, so nothing is left
  expect(screen.getByText(NOTHING_STANDS_OUT)).toBeInTheDocument();
  // Outliers, Patterns and Dependencies: always shown, each a region of its own
  const outliers = screen.getByRole("region", { name: "Outliers" });
  expect(within(outliers).getByText(/One row per number, date and timestamp column/)).toBeInTheDocument();
  expect(within(outliers).getByText("41,000")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Patterns" })).getByText("No text or number columns with values - no shapes to show.")).toBeInTheDocument();
  const deps = screen.getByRole("region", { name: "Dependencies" });
  expect(within(deps).getByText("No column determines another.")).toBeInTheDocument();
  expect(within(deps).getByText("No correlated number columns.")).toBeInTheDocument();
  expect(screen.queryByText(STALE)).toBeNull();
  // a text column that could be another type, listed on the overview
  expect(await screen.findByRole("list", { name: "Could be another type" })).toHaveTextContent("DECIMAL(6, 2)");
});

test("a failed Profile says why and keeps the last profile; a stale one says so; no key is a warning", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources") return json(loaded());
    if (url.startsWith("/api/profiling/defaults?")) return json(defaults());
    if (url === "/api/profiling")
      return json(profiling({ stale: true, profile: profile({ notes: [],
        keys: { tone: "warning", text: "Nothing up to 4 columns is unique. n.", table: T(["Key columns"]) } }) }));
    if (url === "/api/profiling/run") return json(entry("p2", "running", "Profiling…"));
    if (url === "/api/jobs/p2")
      return json(entry("p2", "error", "Profiling - could not finish", ["Looking at the values…", "date value out of range"]));
    if (url.startsWith("/api/profiling/freq?")) return json(FREQ);
    return json({ entries: [], last: {} });
  }));
  // the rail's Profile button shares useRunProfile with the page; drive it the same way here
  const { useRunProfile } = await import("./actions");
  function RailButton() { const { go } = useRunProfile("Table"); return <button onClick={go}>Profile</button>; }
  mount(<><RailButton /><ProfilingPage /></>);
  expect(await screen.findByText(STALE)).toBeInTheDocument();
  expect(screen.getByText("Nothing up to 4 columns is unique").closest(".callout")).toHaveClass("warn");
  expect(screen.getByText(/No key — nothing up to four columns is unique/)).toBeInTheDocument();
  expect(screen.getByText("Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Profile" }));
  expect(await screen.findByText("Profile failed: date value out of range")).toHaveClass("note", "error");
  expect(screen.getByRole("region", { name: "Profile result" })).toBeInTheDocument();     // the last profile stays
});

test("with no table loaded nothing is drawn and nothing is asked for", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push([url, undefined]); return json(body()); }));
  mount(<ProfilingPage />);
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources")).toBe(true));
  expect(screen.queryByRole("button", { name: "Profile" })).toBeNull();
  expect(calls.some(([u]) => u.startsWith("/api/profiling"))).toBe(false);
});

const WIDE = () => profile({
  stats: T(["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled", "Distinct % of rows", "Top value", "Top %",
            "Min", "Max", "Mean", "Avg length", "Min length", "Max length"],
    [["emp_id", "text", 3000, 0, 0, 3000, 100, 100, "E10001", 0.03, "E10001", "E13000", "", 6, 6, 6],
     ["department", "text", 3000, 0, 0, 8, 0.27, 0.27, "Support", 13.73, "Engineering", "Support", "", 7.5, 5, 11],
     ["salary", "number", 3000, 0, 0, 2995, 99.83, 99.83, "11837.57", 0.07, "2152.33", "14979.57", "8619.0124", 7.3, 4, 8]]),
  outliers: T(["Column", "Type", "P1", "P25", "Median", "P75", "P99", "Std dev", "Low fence", "High fence", "Outliers", "Outlier %", "Lowest", "Highest", "Zeros", "Negatives"],
    [["salary", "number", "2276.2", "5384.155", "8672.865", "11826.135", "14866.7", "3714.9289", "-4278.815", "21489.105", 0, 0, "2152.33", "14979.57", 0, 0]]),
  patterns: T(["Column", "Pattern", "Collapsed", "Count", "%", "Example"], [["department", "AAAAAAA", "A+", 782, 26.07, "Finance"]]),
  deps: T(["Determines", "Determined", "Kind", "Distinct"], [["department", "salary", "many-to-one", 8]]),
});

test("a column name opens its detail: stats, histogram, outliers, frequencies, dependencies, previous / next", async () => {
  const calls: Call[] = [];
  stub(calls, (url) => (url === "/api/profiling" ? json(profiling({ profile: WIDE() })) : undefined));
  mount(<ProfilingPage />);
  await userEvent.click(await screen.findByRole("button", { name: "salary" }));
  expect(await screen.findByRole("heading", { name: "salary" })).toBeInTheDocument();
  expect(screen.getByText("column 3 of 3 · Table · hr.csv · 3,000 values")).toBeInTheDocument();
  for (const [label, value] of [["Q1", "5,384.16"], ["Median", "8,672.87"], ["Mean", "8,619.01"], ["Q3", "11,826.14"], ["Std dev", "3,714.93"], ["Max", "14,979.57"]])
    expect(within(document.querySelector<HTMLElement>(".stat-grid")!).getByText(label).nextSibling).toHaveTextContent(value);
  // the histogram from /hist
  expect(await screen.findByRole("img", { name: /Histogram of salary: 0 - 5 2, 5 - 10 8/ })).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/profiling/hist?column=salary&bins=10");
  // a number column has its own page (NumberView, tested there): the form from /numform
  expect(calls.map(([u]) => u)).toContain("/api/profiling/numform?column=salary");
  // dependencies: the key trivially, and the one the profile found
  expect(screen.getByText(/trivially, emp_id is the key/)).toBeInTheDocument();
  expect(screen.getByText(/many-to-one · 8 distinct/)).toBeInTheDocument();
  // previous / next walk the columns; Next is off on the last one
  expect(screen.getByRole("button", { name: /^Next/ })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Previous · department" }));
  expect(await screen.findByRole("heading", { name: "department" })).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /Histogram/ })).toBeNull();           // text: no distribution
  // a category of 8 values: a verdict, its shapes folded into its values, parts and outliers said to be left out
  expect(await screen.findByText("A clean category.")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Shape findings" })).toHaveTextContent("7 letters");
  expect(screen.getByRole("list", { name: "Not shown for this column" })).toHaveTextContent(/Parts.*Outliers/);
  expect(await screen.findByText("clean")).toBeInTheDocument();                 // case · spaces
  // read as text, but its values would read as numbers: how many, and the type they would take
  const could = await screen.findByRole("list", { name: "Could be read as" });
  expect(could).toHaveTextContent("2,990");
  expect(could).toHaveTextContent("DECIMAL(6, 2) · with , removed · 10 would not convert");
  // read as: its own type, or the number its values would take
  expect(screen.getByRole("combobox", { name: /read as/ })).toHaveValue("text");
  // the key (emp_id) has its own page (KeyView, tested there): the key check from /keycheck
  await userEvent.click(screen.getByRole("button", { name: "Previous · emp_id" }));
  expect(await screen.findByRole("list", { name: "Key check" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "All columns" }));
  expect(await screen.findByRole("table", { name: "Columns" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "emp_id - open its detail" })).toBeInTheDocument();   // the last one opened stays marked
});

test("a column the profile no longer has goes back to the list", async () => {
  stub([]);
  act(() => setView({ column: "gone" }));
  mount(<ProfilingPage />);
  expect(await screen.findByRole("table", { name: "Columns" })).toBeInTheDocument();
});

test("a shape reads as runs of letters and digits", async () => {
  const { readShape } = await import("./ColumnDetail");
  expect(readShape("AA999999AA999999999999999")).toBe("2 letters · 6 digits · 2 letters · 15 digits");
  expect(readShape("A9-99 A")).toBe("1 letter · 1-2 digits · space · 1 letter");
  expect(readShape("99999999 99:99:99.999999A")).toBe("8 digits · space · 2:2:2 digits · point · 6 digits · 1 letter");
  expect(readShape("9999-99-99")).toBe("4-2-2 digits");
});
