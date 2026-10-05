import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { FiltersBox } from "./FiltersBox";
import { HowValuesRead } from "./HowValuesRead";
import { ValuesEditor } from "./ValuesEditor";
import { getView, resetView, setView } from "../shell/view";
import { json, mount, setup, type Call } from "../setup/testkit";

const META = { steps: { trim: [], "left N characters": ["n"], "replace text": ["a", "b"], "to date": ["fmt"], "custom expression": ["expr"] },
               labels: { n: "N", a: "find", b: "replace with", fmt: "format - blank tries the usual spellings", expr: "expression, x = the value" },
               numeric: ["m", "n"], presets: { "27/08/2026": "%d/%m/%Y" }, types: ["text", "number", "date", "timestamp", "boolean"] };
const TRY = { columns: ["In the file", "After the steps", "Compared as", "Converts"], rows: [["12,686.95", "12686.95", "12686.95", "yes"]], error: "" };
const FILTERS = { rev: "0", rows: [{ "Apply to": "Both", Column: "", Operator: "=", Value: "", Type: "auto" }], columns: ["emp_id", "salary"],
                  apply_to: ["Both", "HR", "PR"], ops: ["=", "between", "is null"], types: ["auto", "string", "number", "date"], error: "" };

function stub(answer: (url: string, init?: RequestInit) => Response | unknown) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const a = answer(url, init);
    return a instanceof Response ? a : json(a);
  }));
  return calls;
}
const bodies = (calls: Call[], url: string) =>
  calls.filter(([u, i]) => u === url && i?.body).map(([, i]) => JSON.parse(i!.body as string));

beforeEach(() => resetView());

const SALARY = { ...setup().specs[1], b_steps: [{ op: "trim", params: {} as Record<string, string> }, { op: "left N characters", params: { n: "10" } }],
                 b_said: ["trim", "left N characters (N=10)"] };
const S = setup({ specs: [setup().specs[0], SALARY] });
const TRY_B = { columns: TRY.columns, rows: [["12,686.95", "12686.95", "12686.95", "yes"], ["7,713.67", "7713.67", "7713.67", "yes"]], error: "" };
const TRY_A = { columns: TRY.columns, rows: [["12686.95", "12686.95", "12686.95", "yes"], ["7713.60", "7713.60", "7713.6", "yes"]], error: "" };
const CHECK = { columns: ["Column", "Side", "Read as", "Values", "Converted", "Failed"],
                rows: [["emp_id", "HR", "date", 3000, 3000, 0], ["emp_id", "PR", "date", 2985, 2980, 5]], said: "" };

/** The server for the editor: the setup, the step meta, both sides' first rows, the check. */
function server(over: (url: string, init?: RequestInit) => unknown = () => undefined) {
  return stub((url, init) => {
    const o = over(url, init);
    if (o !== undefined) return o;
    if (url === "/api/setup/steps" && !init?.method) return META;
    if (url.startsWith("/api/setup/try")) return url.endsWith("which=A") ? TRY_A : TRY_B;
    if (url === "/api/setup/check") return CHECK;
    if (url === "/api/setup/settings") return S.settings;
    return S;
  });
}
const stepBodies = (calls: Call[]) => bodies(calls, "/api/setup/steps");

test("the values editor: the pairs on the left, the chosen pair's steps, the preview of both sides and the match", async () => {
  setView({ view: "values", pair: 1 });
  const calls = server();
  mount(<ValuesEditor />);
  expect(await screen.findByRole("region", { name: "Steps for salary and Salary" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "salary and Salary" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "emp_id and EmployeeId" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByText("B · 2 steps")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "PR steps · 2" })).toHaveAttribute("aria-pressed", "true");
  const list = screen.getByRole("list", { name: "PR steps" });
  expect(list.querySelectorAll(".pstep")).toHaveLength(2);
  expect(list).toHaveTextContent("trim");
  expect(screen.getByLabelText("N, step 2")).toHaveValue(10);
  expect(await screen.findByText("12,686.95")).toBeInTheDocument();
  await waitFor(() => expect(screen.getAllByRole("img", { name: "matches" })).toHaveLength(1));
  expect(screen.getAllByRole("img", { name: "differs" })).toHaveLength(1);
  expect(calls.some(([u]) => u === "/api/setup/try?canon=salary&which=B")).toBe(true);
  expect(calls.some(([u]) => u === "/api/setup/try?canon=salary&which=A")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "HR steps · 0" }));
  expect(screen.getByText(/^No steps - HR reads/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "emp_id and EmployeeId" }));
  expect(getView().pair).toBe(0);
  expect(await screen.findByRole("region", { name: "Steps for emp_id and EmployeeId" })).toBeInTheDocument();
});

test("Add a step: a chip with parameters opens the new step, one without adds at once; Copy goes to the other side", async () => {
  setView({ pair: 1 });
  const calls = server();
  mount(<ValuesEditor />);
  const add = await screen.findByRole("group", { name: "Add a step" });
  expect([...add.querySelectorAll("button")].map((b) => b.textContent)).toEqual(
    ["trim", "left N characters…", "replace text…", "to date…", "custom expression…"]);
  await userEvent.click(screen.getByRole("button", { name: "left N characters…" }));
  expect(screen.getByLabelText("N")).toHaveValue(6);
  await userEvent.click(screen.getByRole("button", { name: "Add step" }));
  await waitFor(() => expect(stepBodies(calls)[0]).toEqual(
    { canon: "salary", which: "B", action: "add", step: { op: "left N characters", params: { n: "6" } } }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Add step" })).toBeNull());
  await userEvent.click(screen.getByRole("button", { name: "trim" }));
  await waitFor(() => expect(stepBodies(calls)[1]).toEqual({ canon: "salary", which: "B", action: "add", step: { op: "trim", params: {} } }));
  await userEvent.click(screen.getByRole("button", { name: "Copy to HR" }));
  await waitFor(() => expect(stepBodies(calls)[2]).toMatchObject({ action: "copy", which: "B", step: null }));
  await userEvent.click(screen.getByRole("button", { name: "Clear" }));
  await waitFor(() => expect(stepBodies(calls)[3]).toMatchObject({ action: "clear", which: "B" }));
});

test("move up, remove and a changed parameter send the side's steps again in their new order", async () => {
  setView({ pair: 1 });
  const calls = server();
  mount(<ValuesEditor />);
  expect(await screen.findByRole("button", { name: "Move step 1 up" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Move step 2 up" }));
  await waitFor(() => expect(stepBodies(calls)).toHaveLength(3));
  expect(stepBodies(calls).map((b) => [b.action, b.step?.op ?? null])).toEqual(
    [["clear", null], ["add", "left N characters"], ["add", "trim"]]);
  await waitFor(() => expect(screen.getByRole("button", { name: "Remove step 2" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Remove step 2" }));
  await waitFor(() => expect(stepBodies(calls)).toHaveLength(4));
  expect(stepBodies(calls)[3]).toMatchObject({ action: "pop", which: "B" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Remove step 1" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Remove step 1" }));
  await waitFor(() => expect(stepBodies(calls)).toHaveLength(6));
  expect(stepBodies(calls).slice(4).map((b) => [b.action, b.step?.op ?? null])).toEqual([["clear", null], ["add", "left N characters"]]);
  const n = screen.getByLabelText("N, step 2");
  await userEvent.clear(n);
  await userEvent.type(n, "12");
  await userEvent.tab();
  await waitFor(() => expect(stepBodies(calls)).toHaveLength(9));
  expect(stepBodies(calls).at(-1)).toEqual({ canon: "salary", which: "B", action: "add", step: { op: "left N characters", params: { n: "12" } } });
});

test("a step the server refuses is said, and a date step offers the spellings", async () => {
  server((url, init) => url === "/api/setup/steps" && init?.method === "POST"
    ? json({ detail: "Type the find first - one space counts." }, 400) : undefined);
  mount(<ValuesEditor />);
  await userEvent.click(await screen.findByRole("button", { name: "to date…" }));
  await userEvent.selectOptions(screen.getByLabelText("What the value looks like"), "27/08/2026");
  expect(screen.getByLabelText("or a format")).toHaveValue("%d/%m/%Y");
  await userEvent.click(screen.getByRole("button", { name: "replace text…" }));
  expect(screen.getByLabelText("find")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add step" }));
  expect(await screen.findByText("Type the find first - one space counts.")).toBeInTheDocument();
});

test("the custom expression step searches DuckDB's functions", async () => {
  const FNS = { columns: ["name", "template", "description", "example"],
                rows: [["split_part", "split_part(x, 'sep', 2)", "Splits the string", "split_part('a b', ' ', 2)"]] };
  server((url) => (url === "/api/setup/functions" ? FNS : undefined));
  mount(<ValuesEditor />);
  await userEvent.click(await screen.findByRole("button", { name: "custom expression…" }));
  expect(screen.getByLabelText("expression, x = the value")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("DuckDB functions"), "split_part");
  expect(await screen.findByText(/Splits the string/)).toBeInTheDocument();
});

test("the head changes the type, Check counts what converts, and the other conversions open their pair", async () => {
  const calls = server();
  mount(<ValuesEditor />);
  await userEvent.selectOptions(await screen.findByLabelText("Type · both sides"), "date");
  await waitFor(() => expect(bodies(calls, "/api/setup/type")[0]).toEqual({ canon: "emp_id", kind: "date" }));
  expect(screen.getByText("paired by name")).toBeInTheDocument();
  expect(screen.getByText("exact case")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Check this column on all rows" }));
  expect(await screen.findByText("HR: 3,000 of 3,000 convert · PR: 2,980 of 2,985 convert")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Conversion check" })).toBeInTheDocument();
  expect(bodies(calls, "/api/setup/check")[0]).toEqual({ canon: "emp_id" });
  expect(screen.getByText("trim → left N characters (N=10) → number")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Edit salary and Salary" }));
  expect(getView().pair).toBe(1);
  expect(await screen.findByRole("region", { name: "Steps for salary and Salary" })).toBeInTheDocument();
});

test("before both sides are loaded the editor says so, and Back goes to the column table", async () => {
  server((url) => (url === "/api/setup" ? { ready: false, names: ["HR", "PR"] } : undefined));
  mount(<ValuesEditor />);
  expect(await screen.findByText(/^Load both sides first/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Back to the column table" }));
  expect(getView()).toMatchObject({ view: "setup", anchor: "columns" });
});

test("How values are read sits in the editor: a switch is sent at once, a typed box when it is left", async () => {
  const calls = stub(() => setup().settings);
  mount(<HowValuesRead settings={setup().settings} />);
  expect(screen.getByRole("group", { name: "How values are read" })).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Ignore case in values"));
  await waitFor(() => expect(bodies(calls, "/api/setup/settings")[0]).toEqual({ ignore_case: true }));
  await userEvent.click(screen.getByLabelText("Empty string is null"));
  await waitFor(() => expect(bodies(calls, "/api/setup/settings")[1]).toEqual({ empty_as_null: false }));
  await userEvent.click(screen.getByLabelText("Trim whitespace"));
  await waitFor(() => expect(bodies(calls, "/api/setup/settings")[2]).toEqual({ trim: false }));
  const tol = screen.getByLabelText("Numeric tolerance");
  await userEvent.clear(tol);
  await userEvent.type(tol, "0.5");
  expect(bodies(calls, "/api/setup/settings")).toHaveLength(3);
  await userEvent.tab();
  await waitFor(() => expect(bodies(calls, "/api/setup/settings")[3]).toEqual({ tolerance: 0.5 }));
  const nulls = screen.getByLabelText("Null tokens");
  expect(nulls).toHaveValue("NULL, N/A");
  await userEvent.type(nulls, ", -");
  await userEvent.tab();
  await waitFor(() => expect(bodies(calls, "/api/setup/settings")[4]).toEqual({ null_tokens: "NULL, N/A, -" }));
  expect(calls.every(([, i]) => (i?.headers as Record<string, string>)["X-Compare"] === "1")).toBe(true);
});

test("the filters: a row added, a value typed, and what the server cannot read said", async () => {
  let view = FILTERS;
  const calls = stub((url, init) => {
    if (url === "/api/setup/filters" && init?.method === "PUT") {
      const rows = JSON.parse(init.body as string).rows;
      view = { ...FILTERS, rows, error: rows.some((r: { Operator: string; Value: string }) => r.Operator === "between" && !r.Value.includes(","))
        ? "'between' on salary needs two values, e.g. 2026-07-20, 2026-07-31" : "" };
    }
    return view;
  });
  mount(<FiltersBox />);
  await userEvent.click(await screen.findByText("Filters - which rows take part, on the common names"));
  await userEvent.selectOptions(screen.getByLabelText("Column, filter 1"), "salary");
  await userEvent.selectOptions(screen.getByLabelText("Operator, filter 1"), "between");
  await userEvent.type(screen.getByLabelText("Value, filter 1"), "1");
  await userEvent.tab();
  expect(await screen.findByText(/'between' on salary needs two values/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add a filter" }));
  await waitFor(() => expect(screen.getByLabelText("Column, filter 2")).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "Remove filter 1" }));
  await waitFor(() => expect(bodies(calls, "/api/setup/filters").at(-1)!.rows).toHaveLength(1));
});

test("the filters: a typed value and an Operator changed at once are sent one after the other, from the latest rows", async () => {
  let view = FILTERS;
  const calls = stub((url, init) => {
    if (url === "/api/setup/filters" && init?.method === "PUT") {
      const body = JSON.parse(init.body as string);
      view = { ...FILTERS, rev: String(Number(view.rev) + 1), rows: body.rows };
    }
    return view;
  });
  mount(<FiltersBox />);
  await userEvent.click(await screen.findByText("Filters - which rows take part, on the common names"));
  await userEvent.type(screen.getByLabelText("Value, filter 1"), "2026-01-01");
  await userEvent.selectOptions(screen.getByLabelText("Operator, filter 1"), "between");     // the blur and this change race
  await waitFor(() => expect(bodies(calls, "/api/setup/filters")).toHaveLength(2));
  const last = bodies(calls, "/api/setup/filters").at(-1)!;
  expect(last.rows[0]).toMatchObject({ Operator: "between", Value: "2026-01-01" });
  expect(last.rev).toBe("1");
});

test("the filters: a 409 shows the filters as they are now and says why", async () => {
  let held = FILTERS;
  stub((url, init) => {
    if (url === "/api/setup/filters" && init?.method === "PUT") {
      held = { ...FILTERS, rev: "5", rows: [{ ...FILTERS.rows[0], Value: "elsewhere" }] };
      return new Response(JSON.stringify({ detail: "The filters changed since - they are shown again as they are now." }),
                          { status: 409, headers: { "Content-Type": "application/json" } });
    }
    return held;
  });
  mount(<FiltersBox />);
  await userEvent.click(await screen.findByText("Filters - which rows take part, on the common names"));
  await userEvent.selectOptions(screen.getByLabelText("Operator, filter 1"), "between");
  expect(await screen.findByText(/The filters changed since/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("Value, filter 1")).toHaveValue("elsewhere"));
});
