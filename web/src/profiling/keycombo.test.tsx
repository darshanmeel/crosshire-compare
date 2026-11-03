// web/src/profiling/keycombo.test.tsx - Check a key on the Profile page
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { json, mount, type Call } from "../sources/testkit";
import { splitKey } from "./frame";
import { ProfileView } from "./ProfileView";
import { keyCombo, profile, profiling, T } from "./testkit";

function stub(calls: Call[], combo: (cols: string[]) => Response = (cols) => json(keyCombo(cols))) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/profiling/keycombo?")) return combo(new URLSearchParams(url.split("?")[1]).getAll("columns"));
    if (url.startsWith("/api/profiling/freq?"))
      return json({ column: "department", title: "", top: T(["Value", "Count", "%"]), bottom: T(["Value", "Count", "%"]) });
    return json({});
  }));
}

const add = async (col: string) => {
  await userEvent.selectOptions(screen.getByLabelText("Add a column"), col);
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
};

test("pick columns, Check, and the result says how unique they are with the most repeated values", async () => {
  const calls: Call[] = [];
  stub(calls);
  mount(<ProfileView view={profiling()} name="HR" />);
  const pick = screen.getByLabelText("Add a column");
  expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["Add a column…", "emp_id", "department"]);
  expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  const check = screen.getByRole("button", { name: "Check" });
  expect(check).toBeDisabled();
  await userEvent.selectOptions(pick, "department");
  expect(screen.queryByRole("button", { name: "Remove department" })).toBeNull();   // choosing alone adds nothing
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  await add("emp_id");
  expect(screen.queryByLabelText("Add a column")).toBeNull();                 // every column picked
  await userEvent.click(screen.getByRole("button", { name: "Remove emp_id" }));
  await userEvent.click(check);
  const line = await screen.findByText("3,000 rows · 8 distinct · 2,992 duplicate rows · 0 with a null, each its own key");
  expect(within(line.parentElement!).getByText("Not unique")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/profiling/keycombo?columns=department&nulls=apart");
  const top = screen.getByRole("table", { name: "Most repeated" });
  expect(within(top).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Rows", "department"]);
  const rows = within(top).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));
  expect(rows).toEqual([["1,355", "department-1"], ["412", "department-2"]]);
  expect(within(top).getAllByRole("cell")[0]).toHaveClass("num");
  await add("emp_id");                                                       // the chips change: the old result goes
  expect(screen.queryByText("3,000 rows · 8 distinct · 2,992 duplicate rows · 0 with a null, each its own key")).toBeNull();
  expect(screen.queryByRole("table", { name: "Most repeated" })).toBeNull();
});

test("a key candidate loads itself into the checker and is checked at once", async () => {
  const calls: Call[] = [];
  stub(calls);
  mount(<ProfileView view={profiling()} name="HR" />);
  await userEvent.click(screen.getByRole("button", { name: "Check emp_id" }));
  const line = await screen.findByText("3,000 rows · 3,000 distinct · 0 duplicate rows · 0 with a null, each its own key");
  expect(within(line.parentElement!).getByText("Unique")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove emp_id" })).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Most repeated" })).toBeNull();
  expect(calls.map(([u]) => u)).toContain("/api/profiling/keycombo?columns=emp_id&nulls=apart");
});

test("a failed check shows the server's reason, and Check asks again", async () => {
  const calls: Call[] = [];
  let fail = true;
  stub(calls, (cols) => fail ? json({ detail: "Nothing profiled yet." }, 409) : json(keyCombo(cols)));
  mount(<ProfileView view={profiling()} name="HR" />);
  await add("department");
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(await screen.findByText("Nothing profiled yet.")).toBeInTheDocument();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(await screen.findByText("3,000 rows · 8 distinct · 2,992 duplicate rows · 0 with a null, each its own key")).toBeInTheDocument();
  expect(calls.filter(([u]) => u.startsWith("/api/profiling/keycombo?")).length).toBe(2);
});

test("a candidate whose column name holds ' + ' loads that column whole", async () => {
  expect(splitKey("a + b + c", ["a + b", "c"])).toEqual(["a + b", "c"]);
  expect(splitKey("x + y", ["a"])).toEqual(["x", "y"]);
  const calls: Call[] = [];
  stub(calls);
  const p = profile({ keys: { tone: "warning", text: "", table: T(["Key columns", "Distinct", "Unique"], [["a + b + department", 8, "no"]]) },
                      stats: T(["Column", "Type"], [["a + b", "text"], ["department", "text"]]) });
  mount(<ProfileView view={profiling({ profile: p })} name="HR" />);
  await userEvent.click(screen.getByRole("button", { name: "Check a + b + department" }));
  expect(screen.getByRole("button", { name: "Remove a + b" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove department" })).toBeInTheDocument();
});

test("a key with nulls says so and names the columns that hold them", async () => {
  const calls: Call[] = [];
  stub(calls, (cols) => json({ ...keyCombo(cols), null_keys: 176, nulls_by_column: { department: 176 } }));
  mount(<ProfileView view={profiling()} name="HR" />);
  await add("department");
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(await screen.findByText("Has nulls in department (176)")).toBeInTheDocument();
});

test("Null = null asks again with nulls=same and says so, and back again", async () => {
  const calls: Call[] = [];
  const same = () => calls[calls.length - 1][0].includes("nulls=same");
  stub(calls, (cols) => json({ ...keyCombo(cols), distinct: same() ? 8 : 9, null_keys: 2, nulls_by_column: { department: 2 } }));
  mount(<ProfileView view={profiling()} name="HR" />);
  await add("department");
  await userEvent.click(screen.getByRole("button", { name: "Check" }));
  expect(await screen.findByText(/with a null, each its own key/)).toBeInTheDocument();
  expect(calls.some(([u]) => u.includes("nulls=apart"))).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Null = null" }));
  expect(await screen.findByText(/with a null, null = null/)).toBeInTheDocument();
  expect(calls.some(([u]) => u.includes("nulls=same"))).toBe(true);
  expect(screen.getByRole("button", { name: "Null = null" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/rows · 8 distinct .* null = null/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Null: each its own key" }));
  expect(await screen.findByText(/rows · 9 distinct .* with a null, each its own key/)).toBeInTheDocument();
});
