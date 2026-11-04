// web/src/sources/values.test.tsx - "Pick from values" beside the Value box of the card's Rows to read.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { RowsToRead } from "./RowsToRead";
import { SideCard } from "./SideCard";
import { setForm } from "./formStore";
import { body, json, META, mount, values, view, type Call } from "./testkit";

const OPS = ["=", "!=", ">", "contains", "in (comma separated)", "is null", "is not null"];
const HR = view("A", { loaded: true, name: "HR", label: "hr_employees.csv", rows: 3000, columns: ["emp_id", "department"], snapshot: true });

function stub(over: { loaded?: boolean; values?: (url: string) => unknown } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/sources/A/values?")) return json(over.values ? over.values(url) : values());
    if (url === "/api/sources/quick-clause") return json({ where: "WHERE-FROM-SERVER" });
    if (url === "/api/sources/A/schema")
      return json({ label: "hr.csv", kind: "csv", columns: [{ name: "emp_id", type: "VARCHAR" }, { name: "department", type: "VARCHAR" }], error: "" });
    if (url === "/api/sources/folders") return json([]);
    return json(body({ sides: { A: over.loaded === false ? view("A", { staged: "hr.csv" }) : HR, B: view("B"), P: view("P") }, quick_ops: OPS }));
  }));
  return calls;
}
const sentClause = (calls: Call[]) => calls.filter(([u]) => u === "/api/sources/quick-clause").map(([, i]) => JSON.parse(i!.body as string));
const params = (calls: Call[]) => calls.filter(([u]) => u.startsWith("/api/sources/A/values?")).map(([u]) => new URLSearchParams(u.split("?")[1]));

test("= : a picked value fills Value and goes to the server exactly as it is; typing over it sends plain text", async () => {
  const calls = stub();
  mount(<RowsToRead tag="A" cols={["emp_id", "department"]} quickOps={OPS} />);
  await userEvent.selectOptions(screen.getByLabelText("Column"), "department");
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  expect(pickBtn).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(pickBtn);
  expect(pickBtn).toHaveAttribute("aria-expanded", "true");
  const pop = screen.getByRole("dialog", { name: "Values of department" });
  expect(await within(pop).findByText("3 values in 3,000 rows")).toBeInTheDocument();
  expect(within(pop).getByRole("button", { name: "Engineering 1,204" })).toBeInTheDocument();
  expect(within(pop).getByText("null").tagName).toBe("EM");
  expect(params(calls)[0].get("column")).toBe("department");
  expect(params(calls)[0].get("limit")).toBe("200");
  await userEvent.click(within(pop).getByRole("button", { name: "Finance 380" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByLabelText("Value")).toHaveValue("Finance");
  await userEvent.click(screen.getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(screen.getByLabelText("Filter (WHERE)")).toHaveValue("WHERE-FROM-SERVER"));
  expect(sentClause(calls)[0]).toEqual({ column: "department", op: "=", value: "Finance", values: ["Finance"], where: "" });
  await userEvent.type(screen.getByLabelText("Value"), "HR");             // free text still works, and sends no values
  await userEvent.click(screen.getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(sentClause(calls)).toHaveLength(2));
  expect(sentClause(calls)[1]).toEqual({ column: "department", op: "=", value: "HR", where: "WHERE-FROM-SERVER" });
});

test("null picked under = becomes is null, and the button goes for the null conditions", async () => {
  stub();
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  await userEvent.click(await screen.findByRole("button", { name: "null 2" }));
  expect(screen.getByLabelText("Condition")).toHaveValue("is null");
  expect(screen.queryByRole("button", { name: "Pick from values" })).toBeNull();
});

test("in: ticked values show as chips, one is removed, Add sends the rest as values with what was typed", async () => {
  const calls = stub();
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "in (comma separated)");
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  const pop = screen.getByRole("dialog", { name: "Values of department" });
  await userEvent.click(await within(pop).findByRole("checkbox", { name: "Engineering 1,204" }));
  await userEvent.click(within(pop).getByRole("checkbox", { name: "Finance 380" }));
  expect(within(pop).getByRole("checkbox", { name: "null 2" })).toBeDisabled();
  expect(within(pop).getByText("2 picked")).toBeInTheDocument();
  await userEvent.click(within(pop).getByRole("button", { name: "Done" }));
  expect(pickBtn).toHaveFocus();
  const chips = screen.getByRole("list", { name: "Picked values" });
  expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Engineering", "Finance"]);
  await userEvent.click(within(chips).getByRole("button", { name: "Remove Engineering" }));
  await userEvent.type(screen.getByLabelText("Value"), "Sales, HR");
  await userEvent.click(screen.getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(sentClause(calls)).toHaveLength(1));
  expect(sentClause(calls)[0]).toEqual({ column: "department", op: "in (comma separated)", value: "Sales, HR", values: ["Finance"], where: "" });
  await waitFor(() => expect(screen.queryByRole("list", { name: "Picked values" })).toBeNull());   // emptied for the next one
});

test("search is asked of the server once typing stops; more than the list says so", async () => {
  const calls = stub({ values: (u) => new URLSearchParams(u.split("?")[1]).get("search")
    ? values({ distinct: 1, values: [{ value: "Finance", n: 380 }] })
    : values({ distinct: 2400, more: true }) });
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  expect(await screen.findByText("showing 3 of 2,400 - type to search")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Search values"), "fin");
  expect(await screen.findByText('1 value with "fin"')).toBeInTheDocument();
  expect(params(calls).map((p) => p.get("search"))).toEqual(["", "fin"]);       // not one call per key
  await userEvent.keyboard("{ArrowDown}");
  expect(screen.getByRole("button", { name: "Finance 380" })).toHaveFocus();
});

test("the button waits for the side to be loaded", async () => {
  stub({ loaded: false });
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toHaveAttribute("title", "Load this side to pick from its values"));
  expect(pickBtn).toBeDisabled();
});

test("in the side card, Escape closes the values and leaves Rows to read open", async () => {
  stub();
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: /^Rows to read/ }));
  const pickBtn = await screen.findByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  expect(await screen.findByRole("dialog", { name: "Values of emp_id" })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(pickBtn).toHaveFocus();
  expect(screen.getByLabelText("Filter (WHERE)")).toBeInTheDocument();
});

test("in: changing the condition drops the ticked values; the Value box then asks only for more", async () => {
  stub();
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "in (comma separated)");
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  await userEvent.click(await screen.findByRole("checkbox", { name: "Finance 380" }));
  await userEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.getByLabelText("Value")).toHaveAttribute("placeholder", "more values, comma separated (optional)");
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "=");
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "in (comma separated)");
  expect(screen.queryByRole("list", { name: "Picked values" })).toBeNull();
  expect(screen.getByLabelText("Value")).toHaveAttribute("placeholder", "2026-07-20 · Finance · 100");
});

test("tabbing past the last control closes the values", async () => {
  stub();
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "in (comma separated)");
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  await userEvent.click(await screen.findByRole("checkbox", { name: "Finance 380" }));   // a value, so Add takes focus
  screen.getByRole("button", { name: "Done" }).focus();
  await userEvent.tab();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Add to filter" })).toHaveFocus();
});

test("in the side card, a path that now names another file turns the button off", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/sources/A/schema") {
      const other = JSON.parse(init!.body as string).path.includes("other");
      return json({ label: "x.csv", kind: "csv", columns: (other ? ["id", "dept"] : ["emp_id", "department"]).map((name) => ({ name, type: "VARCHAR" })), error: "" });
    }
    if (url.startsWith("/api/sources/A/values?")) return json(values());
    if (url === "/api/sources/folders") return json([]);
    return json(body({ sides: { A: HR, B: view("B"), P: view("P") }, quick_ops: OPS }));
  }));
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: /^Rows to read/ }));
  const pickBtn = await screen.findByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  setForm("A", { path: "D:/x/other.csv" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Pick from values" })).toBeDisabled(), { timeout: 3000 });
  expect(screen.getByRole("button", { name: "Pick from values" })).toHaveAttribute("title", "Load this side again to pick from its values");
});

test("in the side card, an Excel sheet whose Load found more columns than the first rows show keeps the button on", async () => {
  const wide = view("A", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", sheet: "Sheet1", rows: 3000, columns: ["emp_id", "department", "column2"] });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources/A/schema")       // the first rows only: column2 starts lower down
      return json({ label: "hr.xlsx", kind: "excel", columns: [{ name: "emp_id", type: "VARCHAR" }, { name: "department", type: "VARCHAR" }], error: "", sheets: ["Sheet1"], sheet: "Sheet1" });
    if (url.startsWith("/api/sources/A/values?")) return json(values());
    if (url === "/api/sources/folders") return json([]);
    return json(body({ sides: { A: wide, B: view("B"), P: view("P") }, quick_ops: OPS }));
  }));
  setForm("A", { how: "path", path: "D:/x/hr.xlsx" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: /^Rows to read/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Pick from values" })).toBeEnabled());
  expect(within(screen.getByLabelText("Column")).getAllByRole("option").map((o) => o.textContent)).toEqual(["emp_id", "department", "column2"]);
});

test("Add to filter waits for a value, a picked one or a null condition", async () => {
  const calls = stub();
  mount(<RowsToRead tag="A" cols={["emp_id", "department"]} quickOps={OPS} />);
  const add = screen.getByRole("button", { name: "Add to filter" });
  expect(add).toBeDisabled();                                         // not IN ('') / = ''
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "in (comma separated)");
  expect(add).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Value"), "  ");
  expect(add).toBeDisabled();
  await userEvent.selectOptions(screen.getByLabelText("Condition"), "is null");
  expect(add).toBeEnabled();
  expect(sentClause(calls)).toEqual([]);
});

test("the empty value picked under = is a value: Add sends it", async () => {
  const calls = stub({ values: () => values({ values: [{ value: "", n: 7 }, { value: "Finance", n: 380 }] }) });
  mount(<RowsToRead tag="A" cols={["department"]} quickOps={OPS} />);
  const pickBtn = screen.getByRole("button", { name: "Pick from values" });
  await waitFor(() => expect(pickBtn).toBeEnabled());
  await userEvent.click(pickBtn);
  await userEvent.click(await screen.findByRole("button", { name: "empty 7" }));
  const add = screen.getByRole("button", { name: "Add to filter" });
  expect(add).toBeEnabled();
  await userEvent.click(add);
  await waitFor(() => expect(sentClause(calls)).toHaveLength(1));
  expect(sentClause(calls)[0]).toMatchObject({ column: "department", op: "=", value: "", values: [""] });
});

test("in the side card, a first-rows list that is a prefix still turns the button off on another sheet or named extra columns", async () => {
  const run = async (loaded: Record<string, unknown>, sheet: string) => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/sources/A/schema")
        return json({ label: "hr.xlsx", kind: "excel", columns: [{ name: "emp_id", type: "VARCHAR" }], error: "", sheets: ["Jan", "Feb"], sheet });
      if (url.startsWith("/api/sources/A/values?")) return json(values());
      if (url === "/api/sources/folders") return json([]);
      return json(body({ sides: { A: view("A", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", rows: 30, ...loaded }), B: view("B"), P: view("P") }, quick_ops: OPS }));
    }));
    setForm("A", { how: "path", path: "D:/x/hr.xlsx", sheet });
    const { unmount } = mount(<SideCard tag="A" meta={META} />);
    await userEvent.click(await screen.findByRole("button", { name: /^Rows to read/ }));
    await waitFor(() => expect(screen.getByLabelText("Column")).toBeInTheDocument());
    const opts = within(screen.getByLabelText("Column")).getAllByRole("option").map((o) => o.textContent);
    unmount();
    return opts;
  };
  expect(await run({ sheet: "Jan", columns: ["emp_id", "column1"] }, "Feb")).toEqual(["emp_id"]);   // another sheet
  expect(await run({ sheet: "Jan", columns: ["emp_id", "notes"] }, "Jan")).toEqual(["emp_id"]);      // a named column is not a wider row
  expect(await run({ sheet: "Jan", columns: ["emp_id", "column1"] }, "Jan")).toEqual(["emp_id", "column1"]);
});
