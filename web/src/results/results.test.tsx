// web/src/results/results.test.tsx - the results head (verdict, row outcome, tabs), the Summary tab
// and the One-sided rows tab, on a stubbed API.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import type { CompareState, RunView } from "../compare/types";
import { getView, resetView, setView } from "../shell/view";
import { body, json, mount, type Call } from "../sources/testkit";
import { marks } from "../ui/marks";
import { resetPicks } from "./pickStore";
import { ResultsPage } from "./ResultsPage";
import { ResultsView } from "./ResultsView";

beforeEach(() => { resetPicks(); resetView(); setView({ view: "results" }); });

const RUN: RunView = {
  id: "r1", at: "10:00:00", pair: "HR_compare_Right", mode: "key", names: ["HR", "Right"], keys: ["emp_id"],
  columns: ["department", "salary", "active"], matched: 2960, diff_rows: 649, stale: false,
  verdict: { tone: "bad", word: "Differences", when: "0.4s at 10:00:00", segments: [
    { text: "2,960", bold: true }, { text: " rows matched on ", bold: false }, { text: "emp_id", bold: true },
    { text: " · ", bold: false }, { text: "3", bold: true }, { text: " columns compared · ", bold: false },
    { text: "649", bold: true }, { text: " rows (21.93%) differ in ", bold: false }, { text: "687", bold: true },
    { text: " cells", bold: false }, { text: " · ", bold: false }, { text: "40", bold: true },
    { text: " only in HR · ", bold: false }, { text: "25", bold: true }, { text: " only in Right", bold: false }] },
};
const frame = (columns: string[], rows: unknown[][]) => ({ columns, rows });
const LEDGER_COLS = ["Column", "HR", "Right", "Role", "Read as", "Matched", "Mismatched", "Match %"];
const SUMMARY = {
  mode: "key", keys: ["emp_id"], key_line: "Rows are matched on **emp_id** - **2,960** rows matched", key_warning: null,
  counts: [{ label: "Rows HR", value: 3000 }, { label: "Rows Right", value: 2985 }, { label: "Matched on key", value: 2960 },
           { label: "Only in HR", value: 40 }, { label: "Only in Right", value: 25 },
           { label: "Rows that differ", value: 649, help: "Matched rows where at least one compared column differs" }],
  filter_note: "", unmatched: null,
  column_counts: [{ label: "Key", value: 1 }, { label: "Compared", value: 3 }, { label: "Not compared", value: 0 },
                  { label: "Only in HR", value: 1 }, { label: "Only in Right", value: 1 }],
  one_sided: "", overall: [{ label: "Overall match %", value: "78.07%" }, { label: "Fully matched rows", value: 2311 },
                           { label: "Rows with differences", value: 649 }],
  overall_caption: "Match figures are measured on the 2,960 rows that paired.", hash_caption: "",
  ledger: frame(LEDGER_COLS, [
    ["emp_id", "emp_id", "EmployeeId", "key", "text", null, null, null],
    ["department", "department", "Dept", "compared", "text", 2623, 337, 88.61],
    ["salary", "salary", "Salary", "compared", "number · B: remove thousands separators", 2641, 319, 89.22],
    ["active", "active", "IsActive", "compared", "boolean", 2929, 31, 98.95],
    ["CostCenter", "—", "CostCenter", "only in Right", "not compared", null, null, null],
    ["first_name", "first_name", "—", "only in HR", "not compared", null, null, null]]),
  tones: ["pos", "neg", "neg", "neg", "", ""],
  buckets: [{ id: "matched", label: "Keys matched (2,960)" }, { id: "differ", label: "Matched but different (649)" }],
  default_bucket: "differ", sided_tip: "",
};
const bucketBody = (bucket: string) => ({
  bucket,
  by_key: bucket === "differ" ? {
    title: "**By key value** - where the :red[649 differing rows] sit, per key column of **emp_id**",
    tables: [{ title: "**emp_id** - top 1 values by rows that differ", table: frame(["emp_id", "Matched rows"], [["E1", 1]]) }],
    after: "**Every column across these rows** - top values, counted on each side",
  } : null,
  others: [{ name: "department", label: "department" }], others_title: "Other columns - 1 to add",
  profiles: [{ column: "emp_id", title: "**emp_id** · key", table: frame(["Value", "Rows", "%"], [["E1", 1, 100]]) }],
  empty: "",
  shown: ["emp_id"], groups: [{ title: "Key columns", items: [{ name: "emp_id", label: "emp_id" }] },
                              { title: "Compared columns", items: [{ name: "department", label: "department" }] }],
});
const COLUMNS = {
  hash_caption: "",
  tips: ["Each compared column on the **2,960** rows paired on emp_id - :red[differing first], worst first"],
  differ_error: "**3 column(s) differ**: department (337)",
  rows: null, rest: ["active"], rest_title: "Other columns - 1 not open",
  cards: [{ column: "department", head: ":red[**department** · text - 337 mismatches (11.39%)]", warning: "",
            pairs: frame(["HR · department", "Right · department", "Count", "%"], [["Sales", "Sales EMEA", 130, 38.58]]) }],
  near_match: true,
};
const PAIRS: Record<string, unknown> = {
  department: { column: "department", mismatches: 337, distinct: 3, pairs: [
    { a: "Sales", b: "Sales EMEA", n: 130 }, { a: "Finance", b: "Finance & Control", n: 109 }, { a: "Engineering", b: "Eng", n: 98 }] },
  salary: { column: "salary", mismatches: 319, distinct: 319, pairs: [{ a: "10077.84", b: "10035.42", n: 1 }] },
  active: { column: "active", mismatches: 31, distinct: 2, pairs: [{ a: "true", b: "false", n: 27 }, { a: "false", b: "true", n: 4 }] },
};
const NEAR = frame(["Column", "Mismatches", "Avg edit distance", "Similarity %"], [["salary", 319, 4.39, 39.8]]);
const ROW_A = ["E12961", "Rafael", "Sato", "Support", "11822.28"];
const ROW_B = ["E13001", "New Starter", "People", "3000", "CC-130"];
function oneSided(side: string, limit: number) {
  const A = side === "A", total = A ? 40 : 25;
  return {
    side, file: `HR_compare_Right__${A ? "left" : "right"}_only.csv`, keys: [A ? "emp_id" : "EmployeeId"], total, offset: 0,
    columns: A ? ["emp_id", "first_name", "last_name", "department", "salary"] : ["EmployeeId", "FullName", "Dept", "Salary", "CostCenter"],
    rows: Array.from({ length: Math.min(limit, total) }, () => (A ? ROW_A : ROW_B)),
    constant: A ? [] : [{ column: "FullName", value: "New Starter" }, { column: "CostCenter", value: "CC-130" }],
    groups: A ? [{ title: "Key columns", items: ["emp_id"] }, { title: "Compared columns", items: ["last_name", "department", "salary"] },
                 { title: "Not compared", items: ["first_name"] }]
              : [{ title: "Key columns", items: ["EmployeeId"] }, { title: "Compared columns", items: ["FullName", "Dept", "Salary", "CostCenter"] }],
    shown: A ? ["emp_id", "first_name", "department", "salary"] : ["EmployeeId", "FullName", "Dept", "Salary"],
  };
}
function state(over: Partial<CompareState> = {}): CompareState {
  return {
    gate: "", names: ["HR", "Right"], filter_error: "", sig: "s1", stale: false, busy: false, said: [], run: RUN,
    strip: { cells: { Files: "", Columns: "", Key: "", Compare: "", Result: "" }, tones: {} },
    settings: { display_rows: 1000, auto_rerun: false, out_fmt: "csv", auto_profile: false }, ...over,
  };
}

function serve(calls: Call[], st: () => CompareState = () => state()) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/compare") return json(st());
    if (url === "/api/sources") return json(body());
    if (url === "/api/log") return json({ entries: [], last: {} });
    if (url === "/api/results/r1/summary") return json(SUMMARY);
    const fx = url.match(/^\/api\/results\/r1\/buckets\/(\w+)\/facts/);
    if (fx) return json(FACTS(fx[1]));
    const b = url.match(/^\/api\/results\/r1\/buckets\/(\w+)/);
    if (b) return json(bucketBody(b[1]));
    const p = url.match(/^\/api\/results\/r1\/pairs\/(\w+)\?limit=5$/);
    if (p) return json(PAIRS[p[1]]);
    const o = url.match(/^\/api\/results\/r1\/one-sided\/([AB])\?limit=(\d+)$/);
    if (o) return json(oneSided(o[1], Number(o[2])));
    if (url.startsWith("/api/results/r1/columns")) return json(COLUMNS);
    if (url === "/api/results/r1/near-match") return json(NEAR);
    return json({ detail: "not here" }, 404);
  });
}

const side = (side: "A" | "B", label: string, nulls: number) => ({
  side, label, rows: 649, nulls, null_pct: nulls ? 1.54 : 0, distinct: 649, top: { value: "E1", n: 1, pct: 0.15 },
  length: { min: 2, max: 5 }, number: null, date: null, shapes: [{ shape: "A9999", n: 640, pct: 98.61 }],
  prefixes: [{ value: "E10", n: 100, pct: 15.41 }], suffixes: [{ value: "-UK", n: 300, pct: 46.22 }],
  spellings: side === "B" ? [{ members: ["Finance", "finance"], rows: 12, why: "differ only in case" }] : [],
});
const FACTS = (bucket: string) => ({ bucket, columns: [{ column: "emp_id", sides: [side("A", "HR", 0), side("B", "Right", 10)] }] });

test("the head reads the verdict, the row outcome and the tabs, bound to the view", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<ResultsPage />);
  const verdict = await screen.findByRole("region", { name: "Result" });
  expect(verdict).toHaveClass("verdict");
  expect(verdict).toHaveTextContent("2,960 rows matched on emp_id");
  expect(within(verdict).getByText("emp_id").tagName).toBe("CODE");
  expect(within(verdict).getByText("649")).toHaveClass("neg");
  expect(within(verdict).getByText("687")).toHaveClass("neg");
  expect(within(verdict).getByText("(21.93%)")).toHaveClass("pct");
  expect(within(verdict).getByText("HR against Right · 10:00:00 · 0.4s")).toBeInTheDocument();
  expect(within(verdict).getByText("Differences")).toHaveClass("pill", "neg");
  const legend = (await screen.findByText("Fully matched", { selector: ".legend li" })).closest("ul")!;
  expect(within(legend).getByText("2,311")).toBeInTheDocument();
  expect(legend).toHaveTextContent("Only in HR 40");
  expect(legend).toHaveTextContent("Only in Right 25");
  expect(screen.getByText("3,025 distinct keys across both files")).toBeInTheDocument();
  const tabs = screen.getByRole("tablist", { name: "Result views" });
  expect(within(tabs).getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  expect(within(tabs).getByRole("tab", { name: /^Differing rows\s*649$/ })).toBeInTheDocument();
  await userEvent.click(within(tabs).getByRole("tab", { name: /^One-sided rows\s*65$/ }));
  expect(getView().tab).toBe("onesided");
  expect(await screen.findByRole("region", { name: "Only in HR" })).toBeInTheDocument();
  cleanup();
  mount(<ResultsPage />);                                    // the tab picked is kept when drawn again
  expect(await screen.findByRole("tab", { name: /^One-sided rows\s*65$/ })).toHaveAttribute("aria-selected", "true");
});

test("a stale run says so, with what the last run said and why a press was refused", async () => {
  vi.stubGlobal("fetch", serve([], () => state({ stale: true, run: { ...RUN, stale: true }, filter_error: "Bad filter on HR",
                                                 said: [{ tone: "warning", text: "Auto picked **emp_id**" }] })));
  mount(<ResultsPage />);
  expect(await screen.findByText("Stale - settings changed since")).toBeInTheDocument();
  expect(screen.getByText(/Settings have changed since this comparison ran/)).toBeInTheDocument();
  expect(screen.getByText("Bad filter on HR")).toHaveClass("note", "error");
  expect(screen.getByText(/Auto picked/)).toHaveClass("note", "warning");
});

test("with no run yet the page points back at the setup", async () => {
  vi.stubGlobal("fetch", serve([], () => state({ gate: "tick", run: null })));
  mount(<ResultsPage />);
  expect(await screen.findByText(/No result yet/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Back to the setup" }));
  expect(getView()).toMatchObject({ view: "setup", anchor: "sources" });
});

test("the Summary: tiles, the Columns panel with its one-sided foot, and Profile by bucket", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<ResultsView run={RUN} limit={1000} />);
  const tiles = (await screen.findByText("Rows HR")).closest(".tiles") as HTMLElement;
  for (const t of ["3,000", "2,985", "2,960", "2,311", "78.07%"]) expect(within(tiles).getByText(t)).toBeInTheDocument();
  expect(within(tiles).getByText("of 6 · key 1")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Columns" });
  const rows = within(table).getAllByRole("row");
  expect(within(rows[1]).getByText("key")).toHaveClass("chip", "key");
  expect(within(rows[1]).getByText("EmployeeId")).toHaveClass("cb");
  expect(within(rows[2]).getByText("337")).toHaveClass("neg-n");
  expect(within(rows[2]).getByText("88.61%")).toBeInTheDocument();
  expect(within(rows[3]).getByText("B: remove thousands separators")).toBeInTheDocument();
  expect(rows).toHaveLength(5);                              // header + key + 3 compared; one-sided ones in the foot
  const foot = screen.getByText("Not compared").closest(".panel-foot") as HTMLElement;
  expect(foot).toHaveTextContent("first_name · only in HR");
  expect(foot).toHaveTextContent("CostCenter · only in Right");
  expect(screen.getByText("emp_id", { selector: ".panel-note b" })).toBeInTheDocument();
  const bucket = screen.getByRole("group", { name: "Bucket" });
  expect(within(bucket).getByRole("button", { name: "Matched but different (649)" })).toHaveAttribute("aria-pressed", "true");
  expect(await screen.findByText("Every column across these rows")).toBeInTheDocument();
  await userEvent.click(within(bucket).getByRole("button", { name: "Keys matched (2,960)" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/buckets/matched")).toBe(true));
  const pick = await screen.findByRole("group", { name: "Columns to count" });
  expect(within(pick).getByText("1 of 2 ticked")).toBeInTheDocument();
  expect(within(pick).getByRole("checkbox", { name: "emp_id" })).toBeChecked();
  await userEvent.click(within(pick).getByRole("checkbox", { name: "department" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/buckets/matched?add=emp_id&add=department&exact=true")).toBe(true));
  expect(within(pick).getByRole("checkbox", { name: "department" })).toBeChecked();
  expect(within(pick).getByText("2 of 2 ticked")).toBeInTheDocument();
  await userEvent.click(within(pick).getByRole("button", { name: "Clear" }));
  expect(within(pick).getByRole("checkbox", { name: "department" })).not.toBeChecked();
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/buckets/matched?exact=true")).toBe(true));
  await userEvent.click(within(pick).getByRole("button", { name: "Default" }));
  expect(within(pick).getByRole("checkbox", { name: "emp_id" })).toBeChecked();
});

test("Why they differ: the value pairs, near-match for all-different values, the one-sided pattern", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<ResultsView run={RUN} limit={1000} />);
  const why = await screen.findByRole("region", { name: "Why they differ" });
  const dept = await within(why).findByRole("list", { name: "Value pairs for department" });
  expect(within(dept).getAllByRole("listitem")).toHaveLength(3);
  expect(within(dept).getByText("Sales EMEA")).toHaveClass("cb");
  expect(within(dept).getByText("130")).toBeInTheDocument();
  expect(within(why).getByText("- 3 value pairs account for all of them")).toBeInTheDocument();
  expect(await within(why).findByText(/real differences, not formatting/)).toBeInTheDocument();
  expect(await within(why).findByText(/All 25 rows only in Right read/)).toHaveTextContent("FullName New Starter, CostCenter CC-130");
  expect(within(why).queryByText(/rows only in HR read/)).toBeNull();
  expect(within(why).getByRole("button", { name: "See the one-sided rows" })).toBeInTheDocument();
  await userEvent.click(within(why).getByRole("button", { name: "See the 649 rows" }));
  expect(getView().tab).toBe("rows");
});

test("Columns & values opens on request: a card per column, more columns, near-match", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<ResultsView run={RUN} limit={1000} />);
  await screen.findByRole("table", { name: "Columns" });
  expect(calls.some(([u]) => u.startsWith("/api/results/r1/columns"))).toBe(false);
  await userEvent.click(screen.getByText("Columns & values"));
  await userEvent.click(await screen.findByText((_, el) => el?.tagName === "SUMMARY" && el.textContent === "department · text - 337 mismatches (11.39%)"));
  expect(within(screen.getByRole("table", { name: "Where department differs" })).getByText("Sales EMEA")).toBeInTheDocument();
  expect(screen.getByText("Profile by bucket")).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("group", { name: "Other columns - 1 not open" })).getByRole("checkbox", { name: "active" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/columns?open=active")).toBe(true));
  // Why they differ read near-match already (salary's pairs are all different), so it is shown at once
  expect(await screen.findByRole("table", { name: "Near-match analysis" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run near-match analysis" })).toBeNull();
});

test("One-sided rows: two panels, their files, show all, the pattern and the key note", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  setView({ tab: "onesided" });
  mount(<ResultsView run={RUN} limit={1000} />);
  const a = await screen.findByRole("region", { name: "Only in HR" });
  const b = screen.getByRole("region", { name: "Only in Right" });
  expect(await within(a).findByText("40", { selector: ".count" })).toBeInTheDocument();
  expect(within(a).getByText("no Right row with that emp_id")).toBeInTheDocument();
  expect(within(a).getByRole("link", { name: "HR_compare_Right__left_only.csv" }))
    .toHaveAttribute("href", "/api/results/r1/file/HR_compare_Right__left_only.csv");
  expect(within(a).getAllByRole("row")).toHaveLength(7);
  expect(a.querySelector(".panel-foot")).toHaveTextContent("Showing 6 of 40");
  expect(within(a).getAllByText("11822.28")[0]).toHaveClass("num");
  expect(within(a).getAllByText("E12961")[0]).toHaveClass("keycell");
  const cols = () => within(a).getAllByRole("columnheader").map((h) => h.textContent);
  expect(cols()).toEqual(["emp_id", "first_name", "department", "salary"]);   // the key and three; last_name ticked off
  const show = within(a).getByRole("group", { name: "Columns to show" });
  await userEvent.click(within(show).getByRole("checkbox", { name: "last_name" }));
  expect(cols()).toEqual(["emp_id", "first_name", "department", "salary", "last_name"]);   // added at the end
  await userEvent.click(within(show).getByRole("checkbox", { name: "first_name" }));
  expect(cols()).toEqual(["emp_id", "department", "salary", "last_name"]);
  await userEvent.click(within(a).getByRole("button", { name: "Show all 40" }));
  await waitFor(() => expect(within(a).getAllByRole("row")).toHaveLength(41));
  expect(calls.some(([u]) => u === "/api/results/r1/one-sided/A?limit=40")).toBe(true);
  expect(await within(b).findByText("no HR row with that EmployeeId")).toBeInTheDocument();
  const pattern = screen.getByText("Pattern in the rows only in Right:");
  expect(pattern.closest(".callout")).toHaveClass("warn");
  expect(screen.queryByText("Pattern in the rows only in HR:")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Suggest keys under Rows" }));
  expect(getView()).toMatchObject({ view: "setup", anchor: "rows" });
});

test("marks reads *italic* as well", () => {
  render(<p>{marks("see *Other columns* and **bold**")}</p>);
  expect(screen.getByText("Other columns").tagName).toBe("EM");
  expect(screen.getByText("bold").tagName).toBe("B");
});

test("near-match runs on its button when nothing has read it yet", async () => {
  vi.stubGlobal("fetch", serve([]));
  const { ColumnsView } = await import("./ColumnsView");
  mount(<ColumnsView run={RUN} />);
  await userEvent.click(await screen.findByRole("button", { name: "Run near-match analysis" }));
  expect(await screen.findByRole("table", { name: "Near-match analysis" })).toBeInTheDocument();
});

test("Profile by bucket: Simple by default, Extended reads each column's facts as pills a side each", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<ResultsView run={RUN} limit={1000} />);
  const depth = await screen.findByRole("group", { name: "Column profile" });
  expect(within(depth).getByRole("button", { name: "Simple" })).toHaveAttribute("aria-pressed", "true");
  await screen.findByText("Every column across these rows");
  expect(calls.some(([u]) => u.includes("/facts"))).toBe(false);          // simple asks nothing more
  await userEvent.click(within(depth).getByRole("button", { name: "Extended" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/buckets/differ/facts")).toBe(true));
  const a = await screen.findByRole("list", { name: "Facts · HR" });
  expect(a).toHaveTextContent("Nullsnone");
  expect(a).toHaveTextContent("TopE1 · 0.15%");
  expect(a).toHaveTextContent("ShapeA9999 · 98.61%");
  expect(a).toHaveTextContent("Ends…-UK · 46.22%");
  const b = screen.getByRole("list", { name: "Facts · Right" });
  expect(within(b).getByText("Nulls").closest("li")).toHaveClass("warn");
  expect(b).toHaveTextContent("10 · 1.54%");
  expect(b).toHaveTextContent("2 spellingsFinance / finance");
  expect(within(depth).getByRole("button", { name: "Extended" })).toHaveAttribute("aria-pressed", "true");
});
