// web/src/results/detail.test.tsx - the Differing rows tab (SPEC §09): one row per key, filters,
// search, the Show menu, paging and the near-match analysis.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { RunView } from "../compare/types";
import { json, mount, type Call } from "../sources/testkit";
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

test("one row per key: differing cells read A → B, matching cells stay plain, one-sided columns marked", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<DiffRowsTab run={RUN} limit={1000} />);
  const table = await screen.findByRole("table", { name: "Rows that differ" });
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(3);                                          // head + one per key
  const head = within(rows[0]).getAllByRole("columnheader").map((h) => h.textContent);
  expect(head).toEqual(["emp_id", "last_name", "department", "salary", "hire_date", "first_name only in HR", "CostCenter only in Payroll", "Cells"].map((h, i) => (i === 0 ? ` ${h}` : h)));
  const moreau = within(rows[1]).getAllByRole("cell");
  expect(moreau[0]).toHaveTextContent("E10402");
  expect(moreau[1]).toHaveTextContent("Moreau");
  expect(moreau[1].querySelector(".diff")).toBeNull();
  expect(moreau[2].querySelector(".diff")).toHaveTextContent("SalesSales EMEA");
  expect(moreau[3].querySelector(".diff")).toHaveTextContent("14879.714836.87");
  expect(moreau[5]).toHaveTextContent("Anna");
  expect(moreau[6]).toHaveTextContent("CC-110");
  expect(moreau[7]).toHaveTextContent("2");
  expect(screen.getByText(/Showing/).closest("span")).toHaveTextContent("Showing 2 of 3 rows");
  expect(screen.getByRole("link", { name: "cell_diffs.csv" })).toHaveAttribute("href", "/api/results/r1/file/X__cell_diffs.csv");
});

test("Load more fetches the next page and adds its rows", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<DiffRowsTab run={RUN} limit={1000} />);
  await userEvent.click(await screen.findByRole("button", { name: "Load 1 more" }));
  expect(await screen.findByText("E10500")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/diff-rows?offset=2&limit=50");
  expect(screen.queryByRole("button", { name: /^Load/ })).toBeNull();
  expect(screen.getByText(/Showing/).closest("span")).toHaveTextContent("Showing 3 of 3 rows");
});

test("a column chip keeps the rows where that column differs", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls));
  mount(<DiffRowsTab run={RUN} limit={1000} />);
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
  mount(<DiffRowsTab run={RUN} limit={1000} />);
  await screen.findByText("E10402");
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a key or value" }), "emea");
  expect(screen.queryByText("E10466")).toBeNull();
  expect(screen.getByText("E10402")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("1 of the 2 loaded rows match");
  await userEvent.clear(screen.getByRole("searchbox", { name: "Find a key or value" }));
  await userEvent.type(screen.getByRole("searchbox", { name: "Find a key or value" }), "nowhere");
  expect(screen.getByText(/Nothing in the 2 loaded rows matches/)).toBeInTheDocument();
});

test("the Show menu hides matching columns, or any column", async () => {
  vi.stubGlobal("fetch", serve([]));
  mount(<DiffRowsTab run={RUN} limit={1000} />);
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
  mount(<DiffRowsTab run={RUN} limit={1000} />);
  await userEvent.click(await screen.findByRole("button", { name: "Near-match analysis - formatting or real?" }));
  const panel = await screen.findByRole("region", { name: "Near-match analysis" });
  expect(await within(panel).findByText("88.9%")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/results/r1/near-match");
  await userEvent.click(within(panel).getByRole("button", { name: "Close near-match analysis" }));
  expect(screen.queryByRole("region", { name: "Near-match analysis" })).toBeNull();
});

test("hashing has no differing rows to show - the note says why", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(page({ note: "With hashing there are no matched-but-different rows.", total: 0, frame: { columns: [], rows: [] }, marks: [], cells: [] }))));
  mount(<DiffRowsTab run={{ ...RUN, mode: "hash" }} limit={1000} />);
  expect(await screen.findByText("With hashing there are no matched-but-different rows.")).toBeInTheDocument();
});

test("no differing rows says so", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(page({ total: 0, by_column: [], frame: { columns: [], rows: [] }, marks: [], cells: [] }))));
  mount(<DiffRowsTab run={{ ...RUN, diff_rows: 0 }} limit={1000} />);
  expect(await screen.findByText(/No rows differ/)).toBeInTheDocument();
});
