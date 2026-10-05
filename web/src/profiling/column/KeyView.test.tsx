import { afterEach, expect, test, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../../sources/testkit";
import { getView, resetView } from "../../shell/view";
import { statsOf } from "../frame";
import { profile } from "../testkit";
import { KeyView, keyForm, saysId, type KeyCheck, type KeyCompare } from "./KeyView";

afterEach(() => { vi.unstubAllGlobals(); resetView(); location.hash = ""; });

const CLEAN: KeyCheck = {
  column: "emp_id", rows: 3000, filled: 3000, nulls: 0, blanks: 0, distinct: 3000, duplicates: 0, case_variants: 0, spaces: 0,
  width: { min: 6, max: 6 }, shapes: [{ shape: "A99999", n: 3000, example: "E10001" }], prefix: { text: "E", n: 3000 },
  number: { min: 10001, max: 13000, distinct: 3000, gaps: 0, leading_zeros: 0 }, order: "ascending", next_id: "E13001",
  runs: [{ from: 10001, to: 13000, kind: "run", n: 3000, holes: 0, id_from: "E10001", id_to: "E13000" }],
  gaps: { count: 0, ids: 0, shown: 0 }, beyond: null,
};

// a key with one hole and a run past it, as the payroll sample has
const HOLED: KeyCheck = {
  ...CLEAN, rows: 2985, filled: 2985, distinct: 2985, shapes: [{ shape: "A99999", n: 2985, example: "E10001" }],
  prefix: { text: "E", n: 2985 }, number: { min: 10001, max: 13025, distinct: 2985, gaps: 40, leading_zeros: 0 }, next_id: "E13026",
  runs: [{ from: 10001, to: 12960, kind: "run", n: 2960, holes: 0, id_from: "E10001", id_to: "E12960" },
         { from: 12961, to: 13000, kind: "gap", n: 40, holes: 0, id_from: "E12961", id_to: "E13000" },
         { from: 13001, to: 13025, kind: "run", n: 25, holes: 0, id_from: "E13001", id_to: "E13025" }],
  gaps: { count: 1, ids: 40, shown: 1 },
  beyond: { from: 13001, to: 13025, n: 25, id_from: "E13001", id_to: "E13025", rows: 25, shared: [{ column: "FullName", value: "New Starter" }] },
};

const RUN: KeyCompare = {
  run: "r1", names: ["Left", "Right"], stale: false,
  key: { canon: "emp_id", columns: ["emp_id", "EmployeeId"], side: "B", matched: 2960, rows: [3000, 2985],
         only: [{ side: "A", n: 40, filled: 40, min: "E12961", max: "E13000" }, { side: "B", n: 25, filled: 25, min: "E13001", max: "E13025" }] },
};

const row = (a: string, b: string, key: boolean) => ({ "A column": a, "B column": b, "Common name": a, Type: "text", Key: key, Compare: !key,
  Case: "", "Matched by": "name", "A detected": "", "A looks like": "", "B detected": "", "B looks like": "", Role: "", tone: "" });

function stub(check: KeyCheck, setup: unknown, cmp: KeyCompare = { run: null, key: null }) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.startsWith("/api/profiling/keycheck?column=")) return json(check);
    if (url.startsWith("/api/profiling/keycompare?column=")) return json(cmp);
    if (url === "/api/setup") return json(setup);
    return json({});
  }));
}

function show(column = "emp_id") {
  const p = profile();
  mount(<KeyView p={p} column={column} made="20261004-120000" st={statsOf(p, "emp_id")!} as="text" />);
}

test("a clean key: findings, cards, the banner, the key check, the sequence, what is left out, its pair in Compare", async () => {
  stub(CLEAN, { ready: true, names: ["Left", "Right"], rows: [row("emp_id", "EmployeeNo", true), row("dept", "dept", false)], keys: ["emp_id"] });
  show();
  const found = await screen.findByRole("list", { name: "Findings" });
  expect(within(found).getByText("Unique")).toBeInTheDocument();
  expect(within(found).getByText("3,000 of 3,000 · the key")).toBeInTheDocument();
  expect(within(found).getByText("Contiguous")).toBeInTheDocument();
  expect(within(found).getByText("One shape · fixed width 6")).toBeInTheDocument();
  expect(within(found).getByText("No nulls · no case or whitespace variants")).toBeInTheDocument();
  expect(screen.getByText("100% - unique")).toBeInTheDocument();
  expect(screen.getByText("fixed · every value")).toBeInTheDocument();
  expect(screen.getByText("The key.")).toBeInTheDocument();
  expect(screen.getByText(/every number is used, ascending in file order/)).toBeInTheDocument();
  const check = screen.getByRole("list", { name: "Key check" });
  expect(within(check).getByText("3,000 distinct of 3,000")).toBeInTheDocument();
  expect(within(check).getByText("none at risk")).toBeInTheDocument();
  expect(within(check).getByText("says identifier")).toBeInTheDocument();
  expect(screen.getByText("Sequence · Parts")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /E10001 - E13000: 3,000 ids/ })).toBeInTheDocument();
  const seq = screen.getByRole("list", { name: "Shape and sequence" });
  expect(within(seq).getByText("A99999 · 3,000 · 100.00%")).toBeInTheDocument();
  expect(within(seq).getByText("1 letter · 5 digits")).toBeInTheDocument();
  expect(within(seq).getByText("every number from the lowest to the highest is used")).toBeInTheDocument();
  expect(within(seq).getByText("E13001")).toBeInTheDocument();
  const off = screen.getByRole("list", { name: "Not shown for this column" });
  expect(within(off).getByText("every value once - nothing to rank")).toBeInTheDocument();
  expect(within(off).queryByText("Parts")).toBeNull();
  const cmp = await screen.findByRole("list", { name: "In Compare" });
  expect(within(cmp).getByText("key")).toBeInTheDocument();
  expect(within(cmp).getByText("Right · EmployeeNo")).toBeInTheDocument();
  location.hash = "#profiling";
  await userEvent.click(screen.getByRole("button", { name: "Open the compare setup" }));
  expect(location.hash).toBe("");
  expect(getView()).toMatchObject({ view: "setup", column: null });
});

test("a key with a hole: the gap, the ids past it, and the run that says they are the one-sided rows", async () => {
  stub(HOLED, { ready: true, names: ["Left", "Right"], rows: [], keys: [] }, RUN);
  show("EmployeeId");
  const found = await screen.findByRole("list", { name: "Findings" });
  expect(within(found).getByText("Sequence gap")).toBeInTheDocument();
  expect(within(found).getByText("E12961 - E13000 · 40 ids missing")).toBeInTheDocument();
  expect(within(found).getByText("25 ids past the gap")).toBeInTheDocument();
  expect(within(found).getByText("E13001 - E13025 · all New Starter")).toBeInTheDocument();
  expect(screen.getByText("The key - with a hole in it.")).toBeInTheDocument();
  expect(screen.getByText("40 ids from E12961 - E13000")).toBeInTheDocument();
  expect(await screen.findByText(/Against Left, those are exactly the 40 Left-only ids and the 25 Right-only ids/)).toBeInTheDocument();
  const legend = screen.getByRole("list", { name: "Sequence" });
  expect(within(legend).getByText("40 missing")).toBeInTheDocument();
  expect(within(legend).getByText("all New Starter in FullName")).toBeInTheDocument();
  expect(within(legend).getByText("E13001 - E13025").closest("li")).toHaveClass("past");
  const seq = screen.getByRole("list", { name: "Shape and sequence" });
  expect(within(seq).getByText("1 · 40 ids · E12961 - E13000")).toBeInTheDocument();
  expect(within(seq).getByText("one contiguous hole")).toBeInTheDocument();
  const cmp = screen.getByRole("list", { name: "In Compare" });
  expect(within(cmp).getByText("Left · emp_id")).toBeInTheDocument();
  expect(within(cmp).getByText("2,960 rows matched on it · 99.16% of Right")).toBeInTheDocument();
  expect(within(cmp).getByText("the missing ids in the gap above")).toBeInTheDocument();
  expect(within(cmp).getByText("the ids past the gap above")).toBeInTheDocument();
  expect(screen.getByText("against Left · emp_id")).toBeInTheDocument();
  location.hash = "#profiling";
  await userEvent.click(screen.getByRole("button", { name: "See the one-sided rows" }));
  expect(location.hash).toBe("");
  expect(getView()).toMatchObject({ view: "results", tab: "onesided", column: null });
});

test("a key with gaps, a duplicate and mixed case says so, and no comparison yet", async () => {
  const runs: KeyCheck["runs"] = [];
  for (let i = 0; i < 6; i++) {
    runs.push({ from: i * 100, to: i * 100 + 89, kind: "run", n: 90, holes: 0, id_from: `E${i * 100}`, id_to: `E${i * 100 + 89}` });
    runs.push({ from: i * 100 + 90, to: i * 100 + 99, kind: "gap", n: 10 - i, holes: 0, id_from: `E${i * 100 + 90}`, id_to: `E${i * 100 + 99}` });
  }
  stub({ ...CLEAN, distinct: 2999, duplicates: 1, case_variants: 2, nulls: 1, filled: 2999,
         number: { min: 3, max: 3010, distinct: 2990, gaps: 18, leading_zeros: 0 }, order: "neither",
         shapes: [{ shape: "A99999", n: 2990, example: "E10001" }, { shape: "a9999", n: 9, example: "e1001" }],
         runs, gaps: { count: 9, ids: 18, shown: 6 } },
       { ready: false, names: ["Left", "Right"] });
  show();
  const found = await screen.findByRole("list", { name: "Findings" });
  expect(within(found).getByText("Not unique")).toBeInTheDocument();
  expect(within(found).getByText("1 repeat · 1 null or blank")).toBeInTheDocument();
  expect(within(found).getByText("9 gaps · 18 ids missing")).toBeInTheDocument();
  expect(within(found).getByText("2 shapes")).toBeInTheDocument();
  expect(screen.getByText("The key - not unique.")).toBeInTheDocument();
  const check = screen.getByRole("list", { name: "Key check" });
  expect(within(check).getByText("1 value repeat")).toBeInTheDocument();
  expect(within(check).getByText(/differ only in case/)).toBeInTheDocument();
  const seq = screen.getByRole("list", { name: "Shape and sequence" });
  expect(within(seq).getByText("9 · 18 ids")).toBeInTheDocument();
  expect(within(seq).getByText(/the 6 largest are drawn above/)).toBeInTheDocument();
  expect(within(seq).getByText("the file is not sorted on the key")).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Sequence" })).getByText("2 smaller gaps drawn, not listed")).toBeInTheDocument();
  expect(await screen.findByText(/No comparison is set up yet/)).toBeInTheDocument();
});

test("names that say identifier, and the form beside read as", () => {
  for (const n of ["emp_id", "EmployeeId", "order_no", "CustomerKey", "id", "part-number"]) expect(saysId(n)).toBe(true);
  for (const n of ["salary", "valid", "kidney", "piano"]) expect(saysId(n)).toBe(false);
  expect(keyForm("text")).toBe("keep leading zeros");
  expect(keyForm("number")).toBe("whole");
});
