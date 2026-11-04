// web/src/results/results.test.tsx - the results head (verdict, row outcome, tabs), the Summary tab
// and the One-sided rows tab, on a stubbed API.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import type { CompareState, RunView } from "../compare/types";
import { getView, setView } from "../shell/view";
import { compareState } from "../setup/testkit";
import { body, json, mount, type Call } from "../sources/testkit";
import { serveKeyValues, serveValues, valuesBody } from "./testkit";
import { BucketProfile } from "./BucketProfile";
import { RankKey, StackStrip } from "./TopValues";
import { marks } from "../ui/marks";
import { ResultsPage } from "./ResultsPage";
import { ResultsView } from "./ResultsView";

beforeEach(() => setView({ view: "results" }));

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
  bucket, subset: { left: "only_a", right: "only_b" }[bucket] ?? bucket,
  by_key: bucket === "differ" ? {
    title: "**By key value** - where the :red[649 differing rows] sit, per key column of **emp_id**",
    tables: [{ column: "emp_id", title: "**emp_id** - top 2 values by rows that differ", table: frame(
      ["emp_id", "Matched rows", "Rows that differ", "% of those rows", "Cells that differ", "Columns that differ"],
      [["E1", 40, 12, 30, 15, "salary, department"], ["E2-a-very-long-key-value-that-must-not-break-the-row", 8, 8, 100, 8, "salary"]]) }],
    after: "**Every column across these rows** - its values, counted on each side",
  } : null,
  columns: [{ column: "emp_id", title: "**emp_id** · key", sides: bucket === "left" ? ["a"] : ["a", "b"] }],
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
  return compareState({ names: ["HR", "Right"], run: RUN, ...over });
}

function serve(calls: Call[], st: () => CompareState = () => state()) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const vc = serveValues(url) ?? serveKeyValues(url);
    if (vc) return vc;
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
  // the key line is said once, in the caption under the tiles
  expect(screen.getByText("emp_id", { selector: ".summary > .caption b" }).parentElement).toHaveTextContent(
    "Rows are matched on emp_id - 2,960 rows matched · Match figures are measured on the 2,960 rows that paired.");
  expect(screen.queryByRole("group", { name: "Bucket" })).toBeNull();          // Profile by bucket is a closed fold
  await userEvent.click(screen.getByText("Profile by bucket"));
  const bucket = await screen.findByRole("group", { name: "Bucket" });
  expect(within(bucket).getByRole("button", { name: "Matched but different (649)" })).toHaveAttribute("aria-pressed", "true");
  expect(await screen.findByText("Every column across these rows")).toBeInTheDocument();
  // by key value: the table's values in its order, a bar each for matched and differing rows, the numbers beside them
  const keyBars = screen.getByRole("list", { name: "emp_id - rows that differ by value" });
  const items = within(keyBars).getAllByRole("listitem");
  expect(items.map((li) => li.querySelector(".kb-val .m")!.textContent)).toEqual(["E1", "E2-a-very-long-key-value-that-must-not-break-the-row"]);
  expect(items[0]).toHaveTextContent("40 matched12 differ · 30.00%");
  expect(items[0]).toHaveTextContent("15 cells: salary, department");
  expect(items[1].querySelector(".kb-val .m")).toHaveAttribute("title", "E2-a-very-long-key-value-that-must-not-break-the-row");
  expect((items[0].querySelector(".kb-m") as HTMLElement).style.width).toBe("80%");     // 40 of an axis to 50
  expect((items[0].querySelector(".kb-d") as HTMLElement).style.width).toBe("24%");
  // under the bars every key value, 25 a page, searchable
  const keys = await screen.findByRole("table", { name: "Every value of emp_id with rows that differ" });
  expect(within(keys).getAllByRole("row")).toHaveLength(26);
  expect(within(keys).getAllByRole("row")[1]).toHaveTextContent("E1403075.00%35department, salary");
  expect(keys.closest(".vc-all")).toHaveTextContent("Values 1–25 of 30");
  await userEvent.click(within(screen.getByRole("navigation", { name: "Pages of emp_id key values" })).getByRole("button", { name: "Next" }));
  await waitFor(() => expect(within(keys).getAllByRole("row")).toHaveLength(6));
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a value of emp_id" }), "E3");
  await waitFor(() => expect(calls.some(([u]) => u === "/api/results/r1/key-values?column=emp_id&search=E3&page=1&size=25")).toBe(true));
  // each ticked column as an opened row of the Columns table, on this bucket's rows
  expect(await screen.findByRole("list", { name: "Top values of emp_id in Matched but different" })).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/values?column=emp_id&subset=differ&side=both&basis=all&size=10");
  expect(screen.getByRole("table", { name: "Values of emp_id in Matched but different" })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Percent of for emp_id in Matched but different" })).toBeInTheDocument();
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

test("Profile by bucket on one side's rows shows that side alone", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<BucketProfile run={RUN} buckets={[{ id: "left", label: "Only in HR (40)" }]} first="left" sidedTip="" />);
  await userEvent.click(screen.getByText("Profile by bucket"));
  const chart = await screen.findByRole("list", { name: "Top values of emp_id in Only in HR" });
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/values?column=emp_id&subset=only_a&side=a&basis=all&size=10");
  expect(within(chart).getAllByRole("listitem")[0].querySelectorAll(".vc-share")).toHaveLength(1);
  const all = await screen.findByRole("table", { name: "Values of emp_id in Only in HR" });
  expect(within(all).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Value", "HR rows", "HR %"]);
  expect(screen.queryByRole("table", { name: /with rows that differ/ })).toBeNull();
});

test("Profile by bucket: a bucket opened for the first time never shows another bucket's counts", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<BucketProfile run={RUN} first="left" sidedTip=""
    buckets={[{ id: "left", label: "Only in HR (40)" }, { id: "matched", label: "Keys matched (2,960)" }]} />);
  await userEvent.click(screen.getByText("Profile by bucket"));
  await screen.findByRole("list", { name: "Top values of emp_id in Only in HR" });
  await userEvent.click(within(screen.getByRole("group", { name: "Bucket" })).getByRole("button", { name: "Keys matched (2,960)" }));
  const chart = await screen.findByRole("list", { name: "Top values of emp_id in Keys matched" });
  expect(within(chart).getAllByRole("listitem")[0].querySelectorAll(".vc-share")).toHaveLength(2);
  expect(screen.queryByRole("list", { name: "Top values of emp_id in Only in HR" })).toBeNull();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/values?column=emp_id&subset=matched&side=both&basis=all&size=10");
  expect(calls.map(([u]) => u)).not.toContain("/api/results/r1/values?column=emp_id&subset=only_a&side=both&basis=all&size=10");
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
  const file = within(a).getByRole("link", { name: "HR_compare_Right__left_only.csv" });   // the full name as its name
  expect(file).toHaveAttribute("href", "/api/results/r1/file/HR_compare_Right__left_only.csv");
  expect(file).toHaveTextContent(/^left_only\.csv$/);
  expect(within(a).getAllByRole("row")).toHaveLength(7);
  expect(a.querySelector(".panel-foot")).toHaveTextContent("Showing 6 of 40");
  expect(within(a).getAllByText("11,822.28")[0]).toHaveClass("num");
  expect(within(a).getAllByText("E12961")[0]).toHaveClass("keycell");
  const cols = () => within(a).getAllByRole("columnheader").map((h) => h.textContent);
  expect(cols()).toEqual(["emp_id", "first_name", "last_name", "department", "salary"]);   // every column to begin with
  expect(within(a).queryByRole("group", { name: "Columns to show" })).toBeNull();          // the picker waits in the head
  await userEvent.click(within(a).getByRole("button", { name: "Columns (5 of 5)" }));
  const show = within(a).getByRole("group", { name: "Columns to show" });
  await userEvent.click(within(show).getByRole("checkbox", { name: "last_name" }));
  expect(cols()).toEqual(["emp_id", "first_name", "department", "salary"]);
  await userEvent.click(within(show).getByRole("checkbox", { name: "last_name" }));
  expect(cols()).toEqual(["emp_id", "first_name", "department", "salary", "last_name"]);   // added at the end
  await userEvent.click(within(show).getByRole("checkbox", { name: "first_name" }));
  expect(cols()).toEqual(["emp_id", "department", "salary", "last_name"]);
  expect(within(a).getByRole("button", { name: "Columns (4 of 5)" })).toBeInTheDocument();
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

test("One-sided rows: B's panel reads B's own column names, from the Summary's ledger", async () => {
  const base = serve([]);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const m = url.match(/^\/api\/results\/r1\/one-sided\/B\?limit=(\d+)$/);
    if (!m) return base(url, init);
    const d = oneSided("B", Number(m[1]));                    // the right_only file carries A's names
    return json({ ...d, keys: ["emp_id"], columns: ["emp_id", "last_name", "department", "salary", "CostCenter"],
                  constant: [{ column: "department", value: "People" }],
                  groups: [{ title: "Key columns", items: ["emp_id"] }, { title: "Compared columns", items: ["last_name", "department", "salary"] },
                           { title: "Not compared", items: ["CostCenter"], tone: "nc" }] });
  }));
  setView({ tab: "onesided" });
  mount(<ResultsView run={RUN} limit={1000} />);
  const b = await screen.findByRole("region", { name: "Only in Right" });
  await within(b).findByText("no HR row with that EmployeeId");
  await waitFor(() => expect(within(b).getAllByRole("columnheader").map((h) => h.textContent))
    .toEqual(["EmployeeId", "last_name", "Dept", "Salary", "CostCenter"]));
  expect(within(b).getByRole("link", { name: "HR_compare_Right__right_only.csv" })).toHaveTextContent(/^right_only\.csv$/);
  expect(await screen.findByText("Pattern in the rows only in Right:")).toBeInTheDocument();
  expect(screen.getByText("Dept", { selector: ".pattern span" })).toBeInTheDocument();
});

test("the Summary's two folds start closed and stay as they were left", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<ResultsView run={RUN} limit={1000} />);
  await screen.findByRole("table", { name: "Columns" });
  const fold = (name: string) => screen.getByRole("region", { name }).querySelector("details")!;
  expect(fold("Profile by bucket").open).toBe(false);
  expect(fold("Columns & values").open).toBe(false);
  await userEvent.click(screen.getByText("Profile by bucket"));
  expect(fold("Profile by bucket").open).toBe(true);
  cleanup();
  mount(<ResultsView run={RUN} limit={1000} />);
  await screen.findByRole("table", { name: "Columns" });
  expect(fold("Profile by bucket").open).toBe(true);
  expect(fold("Columns & values").open).toBe(false);
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
  await userEvent.click(await screen.findByText("Profile by bucket"));
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

const asked = (calls: Call[], part: string) => calls.some(([u]) => u.startsWith("/api/results/r1/values?") && u.includes(part));

test("the Summary's top values: a strip of five a side, a histogram for numbers, and a row opens every value", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<ResultsView run={RUN} limit={1000} />);
  const table = await screen.findByRole("table", { name: "Columns" });
  expect(within(table).getByRole("columnheader", { name: "Top values · % of all rows" })).toBeInTheDocument();
  expect(await within(table).findByRole("img", { name: "Top values of department on HR: Alpha 30.00%, Bravo 23.33%, Charlie 16.67%, Delta 10.00%, Echo 3.33%, 35 more 14.00%, null 2.67%" })).toBeInTheDocument();
  expect(await within(table).findByRole("img", { name: /^Top values of department on Right: Alpha 29\.94%/ })).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/values?column=department&side=a&basis=nonnull&size=5&bins=12");
  const dept = within(table).getAllByRole("row")[2];
  expect(within(dept).getByText("+35 more 14.00%")).toBeInTheDocument();
  expect(within(dept).getAllByText(/^Echo/)).toHaveLength(2);
  expect(within(dept).getByText("null 2.67%")).toBeInTheDocument();
  expect(await within(table).findByRole("img", { name: "salary on HR: 2,152.33 to 14,979.57, median 8,672.87" })).toBeInTheDocument();
  expect(within(table).getAllByText("median 8,672.87")).toHaveLength(2);
  // a row opens its values: the top ten as bars for both sides with every value in a paged table under them, % of non-null, then the table alone
  const open = within(dept).getByRole("button", { name: "Values of department" });
  expect(open).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(open);
  expect(open).toHaveAttribute("aria-expanded", "true");
  const list = await screen.findByRole("list", { name: "Top values of department" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(10);
  expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent("Alpha900 · 30.00%880 · 29.94%");
  // the shades fade 1st to 5th, null is hatched, the rest take the other values' grey
  const tones = within(list).getAllByRole("listitem").map((li) => li.querySelector(".vc-seg.a")!.classList[1]);
  expect(tones).toEqual(["r1", "r2", "r3", "r4", "r5", "rnull", "ro", "ro", "ro", "ro"]);
  expect(screen.getByText(/^Top 10 of 41 values cover 87\.60% of HR rows and/)).toHaveTextContent("Axis scaled to 50%.");
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/values?column=department&side=both&basis=all&size=10");
  const every = await screen.findByRole("table", { name: "Values of department" });
  expect(asked(calls, "column=department&side=both&basis=all&page=1&size=25")).toBe(true);
  expect(within(every).getAllByRole("row")).toHaveLength(26);
  expect(screen.getByText(/^Values/, { selector: ".vc-all-foot span" })).toHaveTextContent("Values 1–25 of 41");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(within(every).getAllByRole("row")).toHaveLength(17));
  expect(asked(calls, "column=department&side=both&basis=all&page=2&size=25")).toBe(true);
  expect(screen.getByRole("navigation", { name: "Pages of department" })).toHaveTextContent("Page 2 of 2");
  await userEvent.click(screen.getByRole("button", { name: "% of non-null" }));
  await waitFor(() => expect(asked(calls, "column=department&side=both&basis=nonnull&size=10")).toBe(true));
  await waitFor(() => expect(asked(calls, "column=department&side=both&basis=nonnull&page=1&size=25")).toBe(true));   // back to page one
  await userEvent.click(within(screen.getByRole("group", { name: "Show values as" })).getByRole("button", { name: "Table" }));
  expect(screen.queryByRole("list", { name: "Top values of department" })).toBeNull();
  const values = await screen.findByRole("table", { name: "Values of department" });
  expect(within(values).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Value", "HR rows", "HR %", "Right rows", "Right %"]);
  expect(within(values).getAllByRole("row")[1]).toHaveTextContent("Alpha90030.82%88030.61%");
  await userEvent.click(open);
  expect(screen.queryByRole("table", { name: "Values of department" })).toBeNull();
});

test("One-sided rows: each panel groups its rows by a column", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  setView({ tab: "onesided" });
  mount(<ResultsView run={RUN} limit={1000} />);
  const a = await screen.findByRole("region", { name: "Only in HR" });
  await within(a).findByText("40", { selector: ".count" });
  await userEvent.click(within(within(a).getByRole("group", { name: "Rows view" })).getByRole("button", { name: "Distinct values · count(*)" }));
  const t = await within(a).findByRole("table", { name: "Distinct values of first_name" });
  expect(asked(calls, "column=first_name&subset=only_a&side=a&page=1&size=25")).toBe(true);
  expect(within(t).getAllByRole("row")).toHaveLength(26);
  expect(within(a).getByText("GROUP BY first_name → 41 distinct across 3,000 rows")).toBeInTheDocument();
  expect(within(a).queryByRole("table", { name: "Only in HR" })).toBeNull();
  await userEvent.selectOptions(within(a).getByRole("combobox", { name: "Group by column" }), "department");
  expect(await within(a).findByRole("table", { name: "Distinct values of department" })).toBeInTheDocument();
  const b = screen.getByRole("region", { name: "Only in Right" });
  await within(b).findByText("25", { selector: ".count" });
  await userEvent.click(within(b).getByRole("button", { name: "Distinct values · count(*)" }));
  expect(await within(b).findByRole("table", { name: "Distinct values of FullName" })).toBeInTheDocument();
  expect(asked(calls, "column=FullName&subset=only_b&side=b")).toBe(true);
  await userEvent.click(within(a).getByRole("button", { name: "Every row" }));
  expect(within(a).getByRole("table", { name: "Only in HR" })).toBeInTheDocument();
});

test("the key names the five shades, the other values and null", () => {
  render(<RankKey />);
  expect(within(screen.getByRole("list", { name: "Top values key" })).getAllByRole("listitem").map((li) => li.textContent))
    .toEqual(["1st", "2nd", "3rd", "4th", "5th", "other values", "null"]);
});

test("a strip is drawn up to five values that never repeat, and six read as every value distinct", () => {
  const strip = (n: number) => {
    const rows = Array.from({ length: n }, (_, k) => ({ rank: k + 1, value: `v${k + 1}`, n: [1], cum: [k + 1] }));
    const body = valuesBody({ sides: [{ side: "a", rows: n, nulls: 0, distinct: n, top: 1 }], values: n, rows: rows.slice(0, 5) });
    return render(<StackStrip body={body} side="a" column="id" name="HR" />);
  };
  strip(5);
  expect(screen.getByRole("img", { name: "Top values of id on HR: v1 20.00%, v2 20.00%, v3 20.00%, v4 20.00%, v5 20.00%" })).toBeInTheDocument();
  cleanup();
  strip(6);
  expect(screen.getByRole("img", { name: "Top values of id on HR: every value distinct · 6 values" })).toBeInTheDocument();
});
