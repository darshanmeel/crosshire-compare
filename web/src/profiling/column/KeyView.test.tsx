import { afterEach, expect, test, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../../sources/testkit";
import { getView, resetView } from "../../shell/view";
import { statsOf } from "../frame";
import { profile } from "../testkit";
import { KeyView, saysId, type KeyCheck } from "./KeyView";

afterEach(() => { vi.unstubAllGlobals(); resetView(); location.hash = ""; });

const CLEAN: KeyCheck = {
  column: "emp_id", rows: 3000, filled: 3000, nulls: 0, blanks: 0, distinct: 3000, duplicates: 0, case_variants: 0, spaces: 0,
  width: { min: 6, max: 6 }, shapes: [{ shape: "A99999", n: 3000, example: "E10001" }], prefix: { text: "E", n: 3000 },
  number: { min: 10001, max: 13000, distinct: 3000, gaps: 0, leading_zeros: 0 }, order: "ascending", next_id: "E13001",
};

const row = (a: string, b: string, key: boolean) => ({ "A column": a, "B column": b, "Common name": a, Type: "text", Key: key, Compare: !key,
  Case: "", "Matched by": "name", "A detected": "", "A looks like": "", "B detected": "", "B looks like": "", Role: "", tone: "" });

function stub(check: KeyCheck, setup: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.startsWith("/api/profiling/keycheck?column=emp_id")) return json(check);
    if (url === "/api/setup") return json(setup);
    return json({});
  }));
}

function show() {
  const p = profile();
  mount(<KeyView p={p} column="emp_id" made="20261004-120000" st={statsOf(p, "emp_id")!} as="text" />);
}

test("a clean key: cards, the banner, the key check, the sequence, what is left out, its pair in Compare", async () => {
  stub(CLEAN, { ready: true, names: ["Left", "Right"], rows: [row("emp_id", "EmployeeNo", true), row("dept", "dept", false)], keys: ["emp_id"] });
  show();
  expect(await screen.findByText("100% - unique")).toBeInTheDocument();
  expect(screen.getByText("fixed · every value")).toBeInTheDocument();
  expect(screen.getByText("A99999")).toBeInTheDocument();
  expect(screen.getByText(/Unique on every row, no nulls, fixed width, one shape/)).toBeInTheDocument();
  expect(screen.getByText(/with no gaps, ascending in file order - 3,000 ids for 3,000 rows/)).toBeInTheDocument();
  expect(screen.getByText(/Read as text - a leading zero is kept/)).toBeInTheDocument();
  const check = screen.getByRole("list", { name: "Key check" });
  expect(within(check).getByText("3,000 distinct of 3,000")).toBeInTheDocument();
  expect(within(check).getByText("none at risk")).toBeInTheDocument();
  expect(within(check).getByText("says identifier")).toBeInTheDocument();
  const seq = screen.getByRole("list", { name: "Shape and sequence" });
  expect(within(seq).getByText("A99999 · 3,000 · 100.00%")).toBeInTheDocument();
  expect(within(seq).getByText("1 letter · 5 digits")).toBeInTheDocument();
  expect(within(seq).getByText(/10001 → 13000 · contiguous · 0 gaps/)).toBeInTheDocument();
  expect(within(seq).getByText("E13001")).toBeInTheDocument();
  const off = screen.getByRole("list", { name: "Not shown for this column" });
  expect(within(off).getByText("every value once - nothing to rank")).toBeInTheDocument();
  expect(within(off).getByText("the shape above says it: 1 letter · 5 digits")).toBeInTheDocument();
  const cmp = await screen.findByRole("list", { name: "In Compare" });
  expect(within(cmp).getByText("key")).toBeInTheDocument();
  expect(within(cmp).getByText("Right · EmployeeNo")).toBeInTheDocument();
  location.hash = "#profiling";
  await userEvent.click(screen.getByRole("button", { name: "Open the compare setup" }));
  expect(location.hash).toBe("");
  expect(getView()).toMatchObject({ view: "setup", column: null });
});

test("a key with gaps, a duplicate and mixed case says so, and no comparison yet", async () => {
  stub({ ...CLEAN, distinct: 2999, duplicates: 1, case_variants: 2, nulls: 1, filled: 2999,
         number: { min: 3, max: 3010, distinct: 2990, gaps: 18, leading_zeros: 0 }, order: "neither",
         shapes: [{ shape: "A99999", n: 2990, example: "E10001" }, { shape: "a9999", n: 9, example: "e1001" }] },
       { ready: false, names: ["Left", "Right"] });
  show();
  expect(await screen.findByText(/1 duplicate, 1 null or blank/)).toBeInTheDocument();
  const check = screen.getByRole("list", { name: "Key check" });
  expect(within(check).getByText("1 value repeat")).toBeInTheDocument();
  expect(within(check).getByText(/differ only in case/)).toBeInTheDocument();
  const seq = screen.getByRole("list", { name: "Shape and sequence" });
  expect(within(seq).getByText(/3 → 3010 · 18 gaps/)).toBeInTheDocument();
  expect(within(seq).getByText("the file is not sorted on the key")).toBeInTheDocument();
  expect(await screen.findByText(/No comparison is set up yet/)).toBeInTheDocument();
});

test("names that say identifier", () => {
  for (const n of ["emp_id", "EmployeeId", "order_no", "CustomerKey", "id", "part-number"]) expect(saysId(n)).toBe(true);
  for (const n of ["salary", "valid", "kidney", "piano"]) expect(saysId(n)).toBe(false);
});
