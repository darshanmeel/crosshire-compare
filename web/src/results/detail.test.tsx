// web/src/results/detail.test.tsx - the Differing rows tab (SPEC §09): one row per key, filters,
// search, the Show menu, paging and the near-match analysis.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { RunView } from "../compare/types";
import { json, mount, type Call } from "../sources/testkit";
import { serveValues } from "./testkit";
import { pivot, type DiffRowsPage } from "./detailApi";
import { DiffRowsTab } from "./DiffRowsTab";

const RUN: RunView = {
  id: "r1", at: "10:00:00", pair: "X", mode: "key", names: ["HR", "Payroll"], keys: ["emp_id"],
  columns: ["last_name", "department", "salary", "hire_date"], matched: 2960, diff_rows: 3, stale: false,
  verdict: { tone: "warn", word: "Differences", when: "", segments: [] },
};
const COLS = ["Side", "emp_id", "last_name", "department", "salary", "hire_date", "first_name", "CostCenter"];
const pair = (k: string, a: unknown[], b: unknown[]) => [["A", k, ...a, null], ["B", k, ...b.slice(0, 4), null, b[4]]];

function page(over: Partial<DiffRowsPage> = {}): DiffRowsPage {
  return {
    keys: ["emp_id"], columns: ["last_name", "department", "salary", "hire_date"], only_a: ["first_name"], only_b: ["CostCenter"],
    by_column: [{ column: "department", n: 2 }, { column: "salary", n: 2 }], column: "", total: 3, offset: 0,
    frame: { columns: COLS, rows: [
      ...pair("E10402", ["Moreau", "Sales", "14879.7", "2023-10-02", "Anna"], ["Moreau", "Sales EMEA", "14836.87", "2023-10-02", "CC-110"]),
      ...pair("E10466", ["Ibrahim", "Legal", "8453", "2025-03-17", "Omar"], ["Ibrahim", "Legal", "8500", "2025-03-17", "CC-220"]),
    ] },
    marks: [["department", "salary"], ["salary"]], cells: [2, 1], file: "X__cell_diffs.csv", note: "", ...over,
  };
}
const PAGE2 = page({ offset: 2, frame: { columns: COLS, rows: pair("E10500", ["Rossi", "Sales", "1", "2020-01-01", "Lia"], ["Rossi", "Eng", "1", "2020-01-01", null]) },
                     marks: [["department"]], cells: [1] });

function serve(calls: Call[]) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const vc = serveValues(url);
    if (vc) return vc;
    const u = new URL(url, "http://x");
    if (u.pathname === "/api/results/r1/diff-rows") {
      const col = u.searchParams.get("column");
      if (col) return json(page({ column: col, total: 1, frame: { columns: COLS, rows: page().frame.rows.slice(0, 2) }, marks: [["department", "salary"]], cells: [2] }));
      return json(u.searchParams.get("offset") === "2" ? PAGE2 : page());
    }
    if (u.pathname === "/api/results/r1/near-match") {
      return json({ columns: ["Column", "Mismatches", "Avg edit distance", "Similarity %"], rows: [["department", 2, 4.5, 61.2], ["salary", 2, 1, 88.9]] });
    }
    return json({ detail: "not here" }, 404);
  });
}

test("pivot turns the A/B pairs into one row per key", () => {
  const rows = pivot(page());
  expect(rows).toHaveLength(2);
  expect(rows[0]).toMatchObject({ key: ["E10402"], n: 2 });
  expect(rows[0].a.department).toBe("Sales");
  expect(rows[0].b.department).toBe("Sales EMEA");
  expect([...rows[0].diff]).toEqual(["department", "salary"]);
  expect(rows[0].a.first_name).toBe("Anna");
  expect(rows[0].b.CostCenter).toBe("CC-110");
});

test("one row per key: differing cells read A → B, matching cells stay plain, one-sided columns one tick away", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<DiffRowsTab run={RUN} />);
  const table = await screen.findByRole("table", { name: "Rows that differ" });
  const rows = () => within(table).getAllByRole("row");
  const head = () => within(rows()[0]).getAllByRole("columnheader").map((h) => h.textContent);
  expect(rows()).toHaveLength(3);                                        // head + one per key
  // the columns only one side has can never differ, so they start hidden
  expect(head()).toEqual([" emp_id", "last_name", "department", "salary", "hire_date", "Cells"]);
  let moreau = within(rows()[1]).getAllByRole("cell");
  expect(moreau[0]).toHaveTextContent("E10402");
  expect(moreau[1]).toHaveTextContent("Moreau");
  expect(moreau[1].querySelector(".diff")).toBeNull();
  expect(moreau[2].querySelector(".diff")).toHaveTextContent("SalesSales EMEA");
  expect(moreau[3].querySelector(".diff")).toHaveTextContent("14,879.714,836.87");   // separators, decimals as given
  expect(moreau[5]).toHaveTextContent("2");
  expect(moreau[5]).toHaveClass("neg-n");
  await userEvent.click(screen.getByRole("button", { name: /Show: all compared columns/ }));
  const one = screen.getByRole("group", { name: "On one side only" });
  await userEvent.click(within(one).getByRole("checkbox", { name: /first_name/ }));
  await userEvent.click(within(one).getByRole("checkbox", { name: /CostCenter/ }));
  expect(head()).toEqual([" emp_id", "last_name", "department", "salary", "hire_date", "first_name only in HR", "CostCenter only in Payroll", "Cells"]);
  moreau = within(rows()[1]).getAllByRole("cell");
  expect(moreau[5]).toHaveTextContent("Anna");
  expect(moreau[6]).toHaveTextContent("CC-110");
  expect(screen.getByText(/Showing/).closest("span")).toHaveTextContent("Showing 2 of 3 rows");
  expect(screen.getByRole("link", { name: "cell_diffs.csv" })).toHaveAttribute("href", "/api/results/r1/file/X__cell_diffs.csv");
});

test("Load more fetches the next page and adds its rows", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<DiffRowsTab run={RUN} />);
  await userEvent.click(await screen.findByRole("button", { name: "Load 1 more" }));
  expect(await screen.findByText("E10500")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/diff-rows?offset=2&limit=50");
  expect(screen.queryByRole("button", { name: /^Load/ })).toBeNull();
  expect(screen.getByText(/Showing/).closest("span")).toHaveTextContent("Showing 3 of 3 rows");
});

test("a column chip keeps the rows where that column differs", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<DiffRowsTab run={RUN} />);
  const chips = within(await screen.findByRole("group", { name: "Filter by column" }));
  expect(chips.getByRole("button", { name: "All differing 3" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(chips.getByRole("button", { name: "department 2" }));
  expect(chips.getByRole("button", { name: "department 2" })).toHaveAttribute("aria-pressed", "true");
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/diff-rows?offset=0&limit=50&column=department");
  expect(await screen.findByText(/that differ on/)).toBeInTheDocument();
  expect(screen.queryByText("E10466")).toBeNull();
  await userEvent.click(chips.getByRole("button", { name: "All differing 3" }));
  expect(await screen.findByText("E10466")).toBeInTheDocument();
});

test("search narrows the loaded rows by key or value", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<DiffRowsTab run={RUN} />);
  await screen.findByText("E10402");
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a key or value" }), "emea");
  expect(screen.queryByText("E10466")).toBeNull();
  expect(screen.getByText("E10402")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("1 of the 2 loaded rows match");
  await userEvent.clear(screen.getByRole("searchbox", { name: "Find a key or value" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a key or value" }), "nowhere");
  expect(screen.getByText(/Nothing in the 2 loaded rows matches/)).toBeInTheDocument();
});

test("search finds a number as it is shown, with its thousands separator, and as it is stored", async () => {
  const rows = [...pair("E10402", ["Moreau", "Sales", 10240.93, "2023-10-02", "Anna"], ["Moreau", "Sales", 10250, "2023-10-02", "CC-110"]),
                ...pair("E10466", ["Ibrahim", "Legal", 8453, "2025-03-17", "Omar"], ["Ibrahim", "Legal", 8500, "2025-03-17", "CC-220"])];
  vi.stubGlobal("fetch", vi.fn(async () => json(page({ frame: { columns: COLS, rows } }))));
  mount(<DiffRowsTab run={RUN} />);
  const box = await screen.findByRole("searchbox", { name: "Find a key or value" });
  await screen.findByText("E10402");
  await userEvent.type(box, "10,240.93");
  expect(screen.queryByText("E10466")).toBeNull();
  expect(screen.getByText("E10402")).toBeInTheDocument();
  await userEvent.clear(box);
  await userEvent.type(box, "10240.93");
  expect(screen.getByRole("status")).toHaveTextContent("1 of the 2 loaded rows match");
});

test("the Show menu hides matching columns, or any column", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<DiffRowsTab run={RUN} />);
  const table = await screen.findByRole("table", { name: "Rows that differ" });
  const menu = screen.getByRole("button", { name: /Show: all compared columns/ });
  await userEvent.click(menu);
  expect(menu).toHaveAttribute("aria-expanded", "true");
  await userEvent.click(screen.getByRole("button", { name: /Only columns that differ/ }));
  const head = () => within(table).getAllByRole("columnheader").map((h) => h.textContent);
  expect(head()).toEqual([" emp_id", "department", "salary", "Cells"]);
  expect(screen.getByRole("button", { name: /Show: columns that differ/ })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: /last_name/ }));
  expect(head()).toContain("last_name");
  expect(screen.getByRole("button", { name: /Show: 3 of 6 columns/ })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("group", { name: "Columns to show" })).toBeNull();
});

test("near-match analysis opens a panel under the table", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<DiffRowsTab run={RUN} />);
  await userEvent.click(await screen.findByRole("button", { name: "Near-match analysis - formatting or real?" }));
  const panel = await screen.findByRole("region", { name: "Near-match analysis" });
  expect(await within(panel).findByText("88.9%")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/near-match");
  await userEvent.click(within(panel).getByRole("button", { name: "Close near-match analysis" }));
  expect(screen.queryByRole("region", { name: "Near-match analysis" })).toBeNull();
});

test("hashing has no differing rows to show - the note says why", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(page({ note: "With hashing there are no matched-but-different rows.", total: 0, frame: { columns: [], rows: [] }, marks: [], cells: [] }))));
  mount(<DiffRowsTab run={{ ...RUN, mode: "hash" }} />);
  expect(await screen.findByText("With hashing there are no matched-but-different rows.")).toBeInTheDocument();
});

test("no differing rows says so", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(page({ total: 0, by_column: [], frame: { columns: [], rows: [] }, marks: [], cells: [] }))));
  mount(<DiffRowsTab run={{ ...RUN, diff_rows: 0 }} />);
  expect(await screen.findByText(/No rows differ/)).toBeInTheDocument();
});

/** The tab on Distinct values, and whether a values call carrying `part` was made. */
async function distinct() {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  const asked = (part: string) => calls.some(([u]) => u.startsWith("/api/results/r1/values?") && u.includes(part));
  mount(<DiffRowsTab run={RUN} />);
  await screen.findByRole("table", { name: "Rows that differ" });
  await userEvent.click(screen.getByRole("button", { name: "Distinct values · count(*)" }));
  const t = await screen.findByRole("table", { name: "Distinct values of department" });
  return { t, asked };
}

test("Distinct values: the differing rows grouped by a column, as A → B pairs", async () => {
  const { t, asked } = await distinct();
  expect(asked("column=department&subset=differ&side=pair&page=1&size=25")).toBe(true);
  expect(screen.queryByRole("table", { name: "Rows that differ" })).toBeNull();
  expect(screen.queryByRole("searchbox", { name: "Find a key or value" })).toBeNull();
  expect(screen.getByText("GROUP BY department (HR → Payroll) → 41 distinct across 3,000 rows")).toBeInTheDocument();
  expect(within(t).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(
    ["#", "HR → Payroll", "Count(*) ", "% of rows", "Cumulative", "Share · axis 0–50%"]);
  const first = within(t).getAllByRole("row")[1];
  expect(first).toHaveTextContent("1AlphaAlpha EMEA90030.00%30.00%");
  expect(first.querySelector(".diff")).not.toBeNull();
  expect(within(t).getByText("null").tagName).toBe("EM");
  expect(within(t).getAllByText("unchanged")).toHaveLength(2);           // Delta and null read the same on both sides
});

test("Distinct values: paging, rows per page and search", async () => {
  const { asked } = await distinct();
  const pages = screen.getByRole("navigation", { name: "Pages" });
  expect(within(pages).getByRole("status")).toHaveTextContent("Page 1 of 2");
  expect(within(pages).getByRole("button", { name: "Prev" })).toBeDisabled();
  expect(screen.getByText(/^Values/)).toHaveTextContent("Values 1–25 of 41 distinct (3,000 rows)");
  await userEvent.click(within(pages).getByRole("button", { name: "Next" }));
  await waitFor(() => expect(within(pages).getByRole("status")).toHaveTextContent("Page 2 of 2"));
  expect(asked("side=pair&page=2&size=25")).toBe(true);
  expect(within(pages).getByRole("button", { name: "Last" })).toBeDisabled();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Rows per page" }), "50");
  await waitFor(() => expect(asked("side=pair&page=1&size=50")).toBe(true));
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a value" }), "alp");
  await waitFor(() => expect(asked("side=pair&search=alp&page=1&size=50")).toBe(true));
  await waitFor(() => expect(within(screen.getByRole("table", { name: "Distinct values of department" })).getAllByRole("row")).toHaveLength(2));
});

test("Distinct values: the side, a column chip and the column grouped by", async () => {
  const { asked } = await distinct();
  await userEvent.click(within(screen.getByRole("group", { name: "Value from" })).getByRole("button", { name: "HR" }));
  await waitFor(() => expect(asked("column=department&subset=differ&side=a&page=1&size=25")).toBe(true));
  // a column chip narrows the rows grouped to those that differ on it, and groups by that column
  await userEvent.click(screen.getByRole("button", { name: /^salary/ }));
  await waitFor(() => expect(asked("column=salary&subset=differ&side=a&differs=salary")).toBe(true));
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by column" }), "emp_id");
  await waitFor(() => expect(asked("column=emp_id&subset=differ&side=a&differs=salary")).toBe(true));
  expect(screen.queryByRole("group", { name: "Value from" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Every row" }));
  expect(await screen.findByRole("table", { name: "Rows that differ" })).toBeInTheDocument();
});
