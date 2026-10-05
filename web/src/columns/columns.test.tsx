import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { ColumnsSection } from "./ColumnsSection";
import { VIRTUAL_FROM } from "./ColumnTable";
import { getView, resetView } from "../shell/view";
import { IDLE, json, mount, row, setup, type Call } from "../setup/testkit";
import type { SetupView } from "../setup/api";

afterEach(() => resetView());

/** Every fetch answered: GET /api/setup with `view`, writes by `answer`, the rest idle. */
function stub(view: SetupView, answer: (url: string, init?: RequestInit) => unknown = () => view,
              extra: { compare?: unknown; log?: unknown } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/compare") return json(extra.compare ?? IDLE.compare);
    if (url === "/api/log") return json(extra.log ?? IDLE.log);
    if (url === "/api/setup" && (!init?.method || init.method === "GET")) return json(view);
    const a = answer(url, init);
    return a instanceof Response ? a : json(a);
  }));
  return calls;
}
const writes = (calls: Call[], url: string) => calls.filter(([u, i]) => u === url && i?.method && i.method !== "GET");
const sent = (calls: Call[], url: string, n = 0) => JSON.parse(writes(calls, url)[n][1]!.body as string);
const reads = (calls: Call[]) => calls.filter(([u, i]) => u === "/api/setup" && (!i?.method || i.method === "GET")).length;
const board = () => screen.findByRole("table", { name: "Column table" });

test("before both sides load, the section explains what will appear", async () => {
  stub({ ready: false, names: ["HR", "PR"] });
  mount(<ColumnsSection />);
  expect(await screen.findByText(/Every column from either file lands in one table/)).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Columns" })).toHaveAttribute("id", "columns");
  expect(screen.queryByRole("table")).toBeNull();
});

test("the board: one row per pair, then the one-sided columns muted with role Skip", async () => {
  stub(setup());
  mount(<ColumnsSection />);
  const t = await board();
  expect(screen.getByText("2 pairs · 1 only in HR · 1 only in PR")).toBeInTheDocument();
  expect(within(t).getByRole("columnheader", { name: "HR column" })).toBeInTheDocument();
  expect(within(t).getByRole("columnheader", { name: "PR column" })).toBeInTheDocument();
  expect(screen.getByLabelText("HR column, row 1")).toHaveValue("emp_id");
  expect(screen.getByLabelText("PR column, row 1")).toHaveValue("EmployeeId");
  expect(screen.getByLabelText("PR column, row 1")).toHaveClass("sel", "b");
  expect(screen.getByLabelText("PR column, row 3")).toHaveClass("sel", "none");
  expect(within(screen.getByLabelText("PR column, row 3")).getByRole("option", { name: "no partner" })).toBeInTheDocument();
  expect(screen.getByLabelText("Type, row 2")).toHaveValue("number");
  const one = screen.getByText("only in HR").closest("tr")!;
  expect(one).toHaveClass("muted");
  expect(within(one).getByRole("button", { name: "Skip" })).toHaveAttribute("aria-pressed", "true");
  expect(within(one).getByRole("button", { name: "Key" })).toBeDisabled();
  expect(screen.getByText("only in PR")).toHaveClass("neg");
  expect(within(screen.getByRole("group", { name: "Role, row 1" })).getByRole("button", { name: "Compare" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByText("name")).toHaveLength(2);
});

test("the foot sums it up, and Summary opens the setup card and the chips", async () => {
  stub(setup());
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByText("none - rows are matched by hashing")).toBeInTheDocument();
  expect(screen.getByText("2 columns")).toBeInTheDocument();
  expect(screen.getByText("2 one-sided")).toBeInTheDocument();
  expect(screen.queryByLabelText("Setup")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Summary" }));
  expect(within(screen.getByLabelText("Setup")).getByText("1 only in HR, 1 only in PR")).toHaveClass("m");
  expect(screen.getByText("Dept · only in PR")).toHaveClass("chip", "neg");
});

test("a changed column, type or case goes to the server with the table's version", async () => {
  const calls = stub(setup());
  mount(<ColumnsSection />);
  await board();
  await userEvent.selectOptions(screen.getByLabelText("PR column, row 2"), "");
  await waitFor(() => expect(writes(calls, "/api/setup/cell")).toHaveLength(1));
  expect(sent(calls, "/api/setup/cell")).toEqual({ rev: "1.a", row: 1, column: "B column", value: "" });
  await userEvent.selectOptions(screen.getByLabelText("Type, row 1"), "number");
  await waitFor(() => expect(writes(calls, "/api/setup/cell")).toHaveLength(2));
  expect(sent(calls, "/api/setup/cell", 1)).toMatchObject({ row: 0, column: "Type", value: "number" });
  await userEvent.selectOptions(screen.getByLabelText("Case, row 1"), "ignore");
  await waitFor(() => expect(writes(calls, "/api/setup/cell")).toHaveLength(3));
  expect(sent(calls, "/api/setup/cell", 2)).toMatchObject({ row: 0, column: "Case", value: "ignore" });
});

test("Case is offered on text pairs only; blank says what the switch makes it", async () => {
  stub(setup());
  mount(<ColumnsSection />);
  await board();
  expect(within(screen.getByLabelText("Case, row 1")).getByRole("option", { name: "exact · default" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Case, row 2")).toBeNull();          // salary reads as a number
});

test("the role buttons write the Key and Compare ticks, the second with the version the first answered", async () => {
  const keyed = setup({ rows: [row("emp_id", "EmployeeId", { "Common name": "emp_id", Key: true, Role: "key", tone: "pos" }), ...setup().rows.slice(1)],
                        keys: ["emp_id"], compare: ["salary"] });
  const calls = stub(keyed, () => setup({ rev: "2.b", rows: keyed.rows }));
  mount(<ColumnsSection />);
  await board();
  await userEvent.click(within(screen.getByRole("group", { name: "Role, row 1" })).getByRole("button", { name: "Skip" }));
  await waitFor(() => expect(writes(calls, "/api/setup/cell")).toHaveLength(2));
  expect(sent(calls, "/api/setup/cell", 0)).toEqual({ rev: "1.a", row: 0, column: "Key", value: false });
  expect(sent(calls, "/api/setup/cell", 1)).toEqual({ rev: "2.b", row: 0, column: "Compare", value: false });
});

test("Key on a compared pair is one tick", async () => {
  const calls = stub(setup());
  mount(<ColumnsSection />);
  await board();
  await userEvent.click(within(screen.getByRole("group", { name: "Role, row 2" })).getByRole("button", { name: "Key" }));
  await waitFor(() => expect(writes(calls, "/api/setup/cell")).toHaveLength(1));
  expect(sent(calls, "/api/setup/cell")).toEqual({ rev: "1.a", row: 1, column: "Key", value: true });
});

test("the row detail holds the common name, sent when the box is left, and what each side looks like", async () => {
  const s = setup({ rows: [row("emp_id", "EmployeeId", { "Common name": "emp_id", "A looks like": "integer" }), ...setup().rows.slice(1)] });
  const calls = stub(s);
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByLabelText("HR column, row 1")).toHaveAttribute("title", "detected VARCHAR · looks like integer");
  await userEvent.click(screen.getByRole("button", { name: /More on row 1/ }));
  expect(screen.getByRole("button", { name: /More on row 1/ })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("integer").parentElement).toHaveAttribute("title", expect.stringContaining("sample"));
  await userEvent.click(screen.getByRole("button", { name: /More on row 2/ }));
  const box = screen.getByLabelText("Common name, row 2");
  await userEvent.clear(box);
  await userEvent.type(box, "pay");
  expect(writes(calls, "/api/setup/cell")).toHaveLength(0);
  await userEvent.tab();
  await waitFor(() => expect(sent(calls, "/api/setup/cell")).toMatchObject({ row: 1, column: "Common name", value: "pay" }));
});

test("a pair's steps read in one line and open the values editor; none offers + Add", async () => {
  const s = setup();
  s.specs[1] = { ...s.specs[1], b_said: ["remove thousands separators"] };
  stub(s);
  mount(<ColumnsSection />);
  await board();
  await userEvent.click(screen.getByRole("button", { name: "Steps for salary: B · remove thousands separators" }));
  expect(getView()).toMatchObject({ view: "values", pair: 1 });
  await userEvent.click(screen.getByRole("button", { name: "Add a step to emp_id" }));
  expect(getView()).toMatchObject({ view: "values", pair: 0 });
});

test("how each pair was made, and the guess line in the foot", async () => {
  stub(setup({ rows: [row("emp_id", "EmployeeId"), row("last_name", "FullName", { "Matched by": "data" }),
                      row("hire_date", "HireDate", { "Matched by": "similar name" }), row("x", "y", { "Matched by": "you" })] }));
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByText("guess · check")).toHaveClass("warn");
  expect(screen.getByText("similarity")).toBeInTheDocument();
  expect(screen.getByText("you")).toBeInTheDocument();
  expect(screen.getByText(/1 pair is a guess from the values — check/)).toBeInTheDocument();
  expect(screen.getByText("last_name ⇄ FullName")).toBeInTheDocument();
});

test("Match by data asks the server, shows what it found, and Apply sends it", async () => {
  const found = setup({ data_match: { columns: ["HR column", "PR column", "Values in common"], rows: [["department", "Dept", 100]], pairs: 1 } });
  const calls = stub(setup(), (url, init) => (url === "/api/setup/match" && init?.method === "POST" ? found : setup()));
  mount(<ColumnsSection />);
  await board();
  await userEvent.click(screen.getByRole("button", { name: "Match by data" }));
  expect(await screen.findByText("1 pair(s) of columns hold the same values.")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Match by data" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Apply these pairs" }));
  await waitFor(() => expect(writes(calls, "/api/setup/match/apply")).toHaveLength(1));
});

test("Dismiss drops the data match, and nothing found says so", async () => {
  const none = setup({ data_match: { columns: [], rows: [], pairs: 0 } });
  const calls = stub(none, () => setup());
  mount(<ColumnsSection />);
  expect(await screen.findByText(/they look like genuinely different fields/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Apply these pairs" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/setup/match" && i?.method === "DELETE")).toBe(true));
});

test("Match by data waits for a column left over on both sides", async () => {
  stub(setup({ can_match: false }));
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByRole("button", { name: "Match by data" })).toBeDisabled();
});

test("Reset, Save mapping and Load mapping; a refusal is said", async () => {
  const calls = stub(setup(), (url) => (url === "/api/setup/mapping" ? json({ detail: "Could not read the mapping file: no columns" }, 400) : setup()));
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByRole("link", { name: "Save mapping" })).toHaveAttribute("href", "/api/setup/mapping");
  await userEvent.click(screen.getByRole("button", { name: "Reset to name matches" }));
  await waitFor(() => expect(writes(calls, "/api/setup/reset")).toHaveLength(1));
  await userEvent.upload(screen.getByLabelText("Load mapping"), new File(['{"columns": []}'], "mapping.json", { type: "application/json" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not read the mapping file: no columns");
  expect(sent(calls, "/api/setup/mapping")).toEqual({ text: '{"columns": []}' });
});

test("a table changed since is said, and fetched again", async () => {
  const calls = stub(setup(), () => json({ detail: "The column table changed since - it is shown again as it is now." }, 409));
  mount(<ColumnsSection />);
  await board();
  const before = reads(calls);
  await userEvent.selectOptions(screen.getByLabelText("Type, row 1"), "date");
  expect(await screen.findByRole("alert")).toHaveTextContent("The column table changed since");
  await waitFor(() => expect(reads(calls)).toBeGreaterThan(before));
});

test("the engine's notes, duplicate names and nothing paired are said", async () => {
  stub(setup({ said: [{ tone: "warning", text: "hire_date looks like a date" }], duplicates: ["name"], specs: [] }));
  mount(<ColumnsSection />);
  await board();
  expect(screen.getByText("hire_date looks like a date")).toHaveClass("note", "warning");
  expect(screen.getByText(/Common name used more than once/)).toBeInTheDocument();
  expect(screen.getByText("Nothing is paired yet - pick a counterpart for at least one column in the table.")).toBeInTheDocument();
});

test("a wide pair draws only the rows in sight", async () => {
  const many = Array.from({ length: VIRTUAL_FROM + 50 }, (_, i) => row(`a${i}`, `b${i}`));
  stub(setup({ rows: many }));
  mount(<ColumnsSection />);
  await board();
  expect(screen.getAllByRole("row").length).toBeLessThan(60);
});

test("while Auto runs, the pairs known so far are read-only and the leftovers say pairing by values", async () => {
  stub(setup(), undefined, { compare: { ...IDLE.compare, busy: true },
                             log: { entries: [{ id: "1", at: "", kind: "Auto", label: "", state: "running", seconds: null, lines: [], page: "Compare" }] } });
  mount(<ColumnsSection />);
  expect(await screen.findByText("pairing…")).toBeInTheDocument();
  expect(screen.getAllByText("pairing by values…")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Match by data" })).toBeNull();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.getByText("EmployeeId")).toHaveClass("cb");
});
