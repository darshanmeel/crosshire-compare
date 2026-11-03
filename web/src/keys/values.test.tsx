// web/src/keys/values.test.tsx - "Pick from values" in the Rows to read card's "Build a condition".
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { RowsToReadCard } from "./RowsToReadCard";
import { json, mount, setup, type Call } from "../setup/testkit";
import { body, values, view } from "../sources/testkit";

const OPS = ["=", "!=", "in (comma separated)", "is null"];
const HR = view("A", { loaded: true, name: "HR", rows: 3000, columns: ["emp_id", "department"], snapshot: true });

function stub() {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/sources/A/values?")) return json(values({ values: [{ value: "Sales, EMEA", n: 12 }, { value: "O'Hara", n: 3 }, { value: "Finance", n: 2 }] }));
    if (url === "/api/sources/quick-clause") return json({ where: "\"department\" IN ('Sales, EMEA', 'O''Hara')" });
    if (url === "/api/setup") return json(setup());
    return json(body({ sides: { A: HR, B: view("B"), P: view("P") }, quick_ops: OPS }));
  }));
  return calls;
}
const sentClause = (calls: Call[]) => calls.filter(([u]) => u === "/api/sources/quick-clause").map(([, i]) => JSON.parse(i!.body as string));

test("Build a condition: values with commas and quotes ticked for in, sent as values; Escape closes the list only", async () => {
  const calls = stub();
  mount(<RowsToReadCard tag="A" />);
  const card = await screen.findByRole("region", { name: "Rows to read from HR" });
  await userEvent.click(within(card).getByRole("button", { name: "Build a condition" }));
  await userEvent.selectOptions(within(card).getByLabelText("Column"), "department");
  await userEvent.selectOptions(within(card).getByLabelText("Condition"), "in (comma separated)");
  const pickBtn = within(card).getByRole("button", { name: "Pick from values" });
  await userEvent.click(pickBtn);
  const pop = within(card).getByRole("dialog", { name: "Values of department" });
  expect(within(pop).getByLabelText("Search values")).toHaveFocus();
  await userEvent.click(await within(pop).findByRole("checkbox", { name: "Sales, EMEA 12" }));
  await userEvent.keyboard("{ArrowDown}");                           // the keyboard walks the list
  expect(within(pop).getByRole("checkbox", { name: "O'Hara 3" })).toHaveFocus();
  await userEvent.keyboard(" ");
  await userEvent.keyboard("{Escape}");
  expect(within(card).queryByRole("dialog")).toBeNull();
  expect(pickBtn).toHaveFocus();
  expect(within(card).getByLabelText("Column")).toBeInTheDocument();     // the builder stays
  const chips = within(card).getByRole("list", { name: "Picked values" });
  expect(within(chips).getAllByRole("listitem")).toHaveLength(2);
  await userEvent.click(within(card).getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(within(card).getByLabelText("Filter · WHERE")).toHaveValue("\"department\" IN ('Sales, EMEA', 'O''Hara')"));
  expect(sentClause(calls)[0]).toEqual({ column: "department", op: "in (comma separated)", value: "", values: ["Sales, EMEA", "O'Hara"], where: "" });
});

test("Build a condition: = fills Value from the list; no button for is null", async () => {
  stub();
  mount(<RowsToReadCard tag="A" />);
  const card = await screen.findByRole("region", { name: "Rows to read from HR" });
  await userEvent.click(within(card).getByRole("button", { name: "Build a condition" }));
  await userEvent.click(within(card).getByRole("button", { name: "Pick from values" }));
  await userEvent.click(await within(card).findByRole("button", { name: "Finance 2" }));
  expect(within(card).getByLabelText("Value")).toHaveValue("Finance");
  await userEvent.selectOptions(within(card).getByLabelText("Condition"), "is null");
  expect(within(card).queryByRole("button", { name: "Pick from values" })).toBeNull();
});
