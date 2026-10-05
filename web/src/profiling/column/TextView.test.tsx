import { afterEach, expect, test, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../../sources/testkit";
import type { Row } from "../frame";
import { profile, T } from "../testkit";
import { TextView, textForm, type SimilarBody } from "./TextView";

afterEach(() => { vi.unstubAllGlobals(); });

const VALUES = [["Support", 406], ["Marketing", 385], ["People", 378], ["Operations", 368], ["Legal", 353], ["Engineering", 270],
  ["Finance", 255], ["Sales", 233], ["Sales EMEA", 130], ["Finance & Control", 109], ["Eng", 98]].map(([value, n]) => ({ value: String(value), n: Number(n) }));
const grp = (keep: string, other: string, rows: number, cc: string) => ({
  members: [VALUES.find((v) => v.value === keep)!, VALUES.find((v) => v.value === other)!], keep, rows,
  why: `both only in CostCenter ${cc}`, on: { column: "CostCenter", value: cc } });

const SAME: SimilarBody = {
  column: "Dept", kind: "text", method: "same", counts: { fingerprint: 0, ngram: 0, prefix: 3, same: 3 },
  groups: [grp("Engineering", "Eng", 368, "CC-220"), grp("Finance", "Finance & Control", 364, "CC-110"), grp("Sales", "Sales EMEA", 363, "CC-310")],
  by: "CostCenter", threshold: 0.5, distinct: 11, filled: 2985, scanned: 11, capped: false, values: VALUES, more: 0,
  shortest: "Eng", longest: "Finance & Control",
};

const st: Row = { Column: "Dept", Type: "text", Rows: 2985, Nulls: 0, "Null %": 0, Distinct: 11, "Distinct % of filled": 0.37,
  "Distinct % of rows": 0.37, "Top value": "Support", "Top %": 13.6, "Min length": 3, "Max length": 17, "Avg length": 7.9 };

const P = profile({
  stats: T(["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of rows"],
    [["EmployeeId", "text", 2985, 0, 0, 2985, 100], ["Dept", "text", 2985, 0, 0, 11, 0.37], ["CostCenter", "text", 2985, 0, 0, 8, 0.27]]),
  keys: { tone: "success", text: "", table: T(["Key columns", "Distinct", "Unique"], [["EmployeeId", 2985, "yes"]]) },
  matrix: T(["Column", "Dept", "CostCenter"], [["CostCenter", 90.22, null], ["Dept", null, 100]]),
  patterns: T(["Column", "Pattern", "Collapsed", "Count", "%", "Example"]),
});

function stub(sim: (url: string) => SimilarBody, calls: string[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.startsWith("/api/profiling/similar?")) return json(sim(url));
    if (url.startsWith("/api/profiling/spelling?")) return json({ column: "Dept", distinct: 11, folded: 11, padded: 0 });
    if (url === "/api/profiling/casts") return json({ columns: [] });
    if (url.startsWith("/api/profiling/parts?")) return json({ column: "FullName", kind: "text", groups: [
      { title: "First 3 characters", total: 2985, rows: [{ label: "Oma", n: 300 }] }] });
    if (url.startsWith("/api/profiling/freq?")) return json({ column: "FullName", title: "", top: T(["Value", "Count", "%"]), bottom: T(["Value", "Count", "%"], [["Ana Li", 1, 0.03]]) });
    return json({});
  }));
}

test("renamed spellings: findings, merged distinct, groups by another column, the values indented, merge off", async () => {
  const calls: string[] = [];
  stub((url) => (url.includes("method=prefix") ? { ...SAME, method: "prefix", by: "", groups: SAME.groups.map((g) => ({ ...g, why: "all begin", on: undefined })) } : SAME), calls);
  mount(<TextView p={P} column="Dept" made="20261004-120000" st={st} as="text" />);
  const findings = await screen.findByRole("list", { name: "Findings" });
  expect(await within(findings).findByText("Near-duplicates")).toBeInTheDocument();
  expect(findings).toHaveTextContent("3 groups · 11 values that are really 8");
  expect(findings).toHaveTextContent("Decided by CostCenter");
  expect(findings).toHaveTextContent("U 90.22%");
  expect(findings).toHaveTextContent("Balanced");
  expect(findings).toHaveTextContent("No nulls");
  expect(await within(findings).findByText("Clean case and whitespace")).toBeInTheDocument();
  expect(findings).toHaveTextContent("Not high-cardinality");
  const grid = document.querySelector<HTMLElement>(".stat-grid")!;
  expect(within(grid).getByText("Distinct").parentElement).toHaveTextContent("11 → 8after merging duplicates");
  expect(within(grid).getByText("Top value").parentElement).toHaveTextContent("406 · 13.60%");
  expect(within(grid).getByText("Length").parentElement).toHaveTextContent("3 - 17Eng … Finance & Control");
  expect(screen.getByText("A category with near-duplicates.").parentElement).toHaveTextContent("11 values, 8 once the 3 groups");
  // the groups: the method the server opened on, each group's why with the other column's value
  expect(screen.getByRole("button", { name: "Same CostCenter" })).toHaveAttribute("aria-pressed", "true");
  const groups = screen.getByRole("list", { name: "Similar value groups" });
  const first = within(groups).getAllByRole("listitem")[0];
  expect(first).toHaveTextContent("Group 1·368 rows·both only in CostCenter CC-220");
  expect(within(first).getByRole("button", { name: "Merge into Engineering" })).toBeDisabled();
  expect(screen.getByRole("button", { name: /Merge all 3 · 11 → 8 values/ })).toBeDisabled();
  // values: grouped members under the kept one
  const values = screen.getByRole("list", { name: "Values of Dept" });
  const lines = within(values).getAllByRole("listitem").map((li) => li.textContent);
  expect(lines.slice(5, 7)).toEqual([expect.stringContaining("Engineering"), expect.stringContaining("↳ Eng")]);
  expect(screen.getByText("After merging, the 8 values run 353 - 406 rows each.")).toBeInTheDocument();
  // click a member: it is kept instead, and the values list follows
  await userEvent.click(within(first).getByRole("button", { name: "Eng, 98 rows" }));
  expect(within(first).getByRole("button", { name: "Eng, 98 rows" })).toHaveAttribute("aria-pressed", "true");
  expect(within(first).getByRole("button", { name: "Merge into Eng" })).toBeDisabled();
  const after = within(values).getAllByRole("listitem").map((li) => li.textContent);
  expect(after.findIndex((t) => t?.includes("↳ Engineering"))).toBe(after.findIndex((t) => t?.startsWith("Eng98")) + 1);
  // another method
  await userEvent.click(screen.getByRole("button", { name: "Shared prefix" }));
  expect(calls.some((u) => u.includes("method=prefix"))).toBe(true);
  expect(await screen.findByRole("button", { name: "Shared prefix" })).toHaveAttribute("aria-pressed", "true");
  // a category: parts said to be left out, least frequent too as every value is listed
  const not = screen.getByRole("list", { name: "Not shown for this column" });
  expect(not).toHaveTextContent(/Parts.*Outliers.*Least frequent/);
  expect(screen.queryByRole("heading", { name: "Parts" })).toBeNull();
});

test("free text: no groups, a parts panel, the least frequent, high-cardinality", async () => {
  const free: SimilarBody = { ...SAME, column: "FullName", method: "fingerprint", counts: { fingerprint: 0, ngram: 0, prefix: 0, same: 0 },
    groups: [], by: "", distinct: 361, scanned: 361, values: [{ value: "Omar Okafor", n: 20 }], more: 360, shortest: "Ana Li", longest: "Amara Schmidt" };
  stub(() => free);
  const s: Row = { ...st, Column: "FullName", Distinct: 361, "Distinct % of filled": 12.09, "Top value": "Omar Okafor", "Top %": 0.67 };
  mount(<TextView p={P} column="FullName" made="20261004-120000" st={s} as="text" />);
  expect(await screen.findByText("No values look alike this way.")).toBeInTheDocument();
  const findings = screen.getByRole("list", { name: "Findings" });
  expect(findings).toHaveTextContent("High-cardinality361 distinct · 12.09% of filled");
  expect(findings).not.toHaveTextContent("Near-duplicates");
  expect(await screen.findByRole("heading", { name: "Parts" })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "First 3 characters" })).toHaveTextContent("Oma");
  expect(await screen.findByRole("list", { name: "Least frequent values of FullName" })).toHaveTextContent("Ana Li");
  expect(screen.getByRole("list", { name: "Not shown for this column" })).not.toHaveTextContent("Parts");
});

test("the header form beside read as", () => {
  expect(textForm(st, { column: "Dept", distinct: 11, folded: 11, padded: 0 })).toBe("exact · 2,985 rows");
  expect(textForm(st, { column: "Dept", distinct: 11, folded: 9, padded: 0 })).toBe("2 case variants · 2,985 rows");
  expect(textForm(st)).toBe("2,985 rows");
});
