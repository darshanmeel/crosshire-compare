// web/src/keys/filters.test.tsx - "Filters at compare" (values/FiltersBox.tsx) as the rows page shows it.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { FiltersBox } from "../values/FiltersBox";
import type { FiltersView } from "../setup/api";
import { json, mount, type Call } from "../setup/testkit";

const VIEW: FiltersView = { rows: [], rev: "0", columns: ["emp_id", "salary"], apply_to: ["Both", "HR", "PR"],
                            ops: ["=", "between"], types: ["auto", "number"], error: "" };

test("Filters at compare: open with none, a row added and filled, the count, then removed", async () => {
  let view = VIEW;
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (init?.method === "PUT") view = { ...view, rev: String(Number(view.rev) + 1), rows: JSON.parse(init.body as string).rows };
    return json(view);
  }));
  mount(<FiltersBox />);
  expect(await screen.findByRole("heading", { name: "Filters at compare" })).toBeInTheDocument();
  expect(screen.getByText("none")).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Filters" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Add a filter" }));
  const table = await screen.findByRole("table", { name: "Filters" });
  await userEvent.selectOptions(within(table).getByLabelText("Column, filter 1"), "salary");
  await userEvent.selectOptions(within(table).getByLabelText("Type, filter 1"), "number");
  await userEvent.type(within(table).getByLabelText("Value, filter 1"), "100{Enter}");
  await waitFor(() => expect(screen.getByText("1 applied")).toBeInTheDocument());
  const last = () => JSON.parse(calls.filter(([, i]) => i?.method === "PUT").at(-1)![1]!.body as string);
  await waitFor(() => expect(last().rows[0]).toMatchObject({ Column: "salary", Type: "number", Value: "100", "Apply to": "Both" }));
  await userEvent.click(screen.getByRole("button", { name: "Remove filter 1" }));
  await waitFor(() => expect(last().rows).toEqual([]));
});

test("Filters at compare: what the server cannot read is said", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ ...VIEW, rows: [{ "Apply to": "Both", Column: "salary", Operator: "between", Value: "1", Type: "auto" }],
                                                  error: "'between' on salary needs two values" })));
  mount(<FiltersBox />);
  expect(await screen.findByText("'between' on salary needs two values")).toBeInTheDocument();
});
