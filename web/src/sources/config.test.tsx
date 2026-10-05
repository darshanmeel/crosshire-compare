// web/src/sources/config.test.tsx - Run from a saved config (SPEC §17).
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { ConfigSync } from "./ConfigPanel";
import { ConfigView } from "./ConfigView";
import { readPairs, summarise, readConf } from "./configRead";
import { getView, resetView, setView } from "../shell/view";
import { getForm, resetForms } from "./formStore";
import { body, json, META, mount, type Call } from "./testkit";

beforeEach(() => { resetForms(); resetView(); });

const entry = (id: string, state: string, label: string) => ({ id, at: "10:00:00", kind: "Config", label, state, seconds: null, lines: [], page: "Compare" });
const CONFIG = { n: 1, said: [{ tone: "success", text: "Loaded - HR against PR, 1 pairs" }],
  boxes: { settings: {}, A: { name: "HR", how: "path", path: "D:/x/hr.csv" }, B: { name: "PR", how: "database", connection: "SAMPLE", db_mode: "sql", sql: "SELECT 1", cap: 0 } } };
const CONF = {
  kind: "crosshire-compare config", version: 1,
  sides: { A: { name: "HR", path: "D:\\data\\hr_employees.csv" }, B: { name: "Payroll", path: "D:\\data\\payroll_employees.csv" } },
  columns: [
    { a: "emp_id", b: "EmployeeId", key: true, compare: true, a_steps: [], b_steps: [] },
    { a: "salary", b: "Salary", key: false, compare: true, a_steps: [], b_steps: [{ op: "remove_thousands" }] },
  ],
  settings: { mode: "key" }, filters: [],
};

function server(calls: Call[]) {
  let done = false;
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/meta") return json({ ...META, filepick: true });
    if (url === "/api/sources/config") return json(entry("c1", "running", "Loading the config…"));
    if (url === "/api/jobs/c1") { done = true; return json(entry("c1", "done", "Loading the config in 0.2s")); }
    if (url === "/api/sources/browse") return json({ path: "D:/runs/picked__config.json", file: "" });
    if (url === "/api/log") return json({ entries: [], last: {} });
    return json(body(done ? { config: CONFIG } as never : {}));
  });
}

test("a path runs as a job, says what the load said, and fills both sides' boxes", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", server(calls));
  mount(<ConfigView />);
  expect(screen.getByRole("heading", { name: "Run from a config" })).toBeInTheDocument();
  const card = screen.getByRole("region", { name: "Config" });
  await userEvent.click(within(card).getByRole("button", { name: "Path on disk" }));
  expect(screen.getByRole("button", { name: "Run this config" })).toBeDisabled();
  await userEvent.type(within(card).getByLabelText("Path"), "D:/runs/x__config.json");
  await userEvent.click(screen.getByRole("button", { name: "Run this config" }));
  expect(await screen.findByText("Loaded - HR against PR, 1 pairs")).toBeInTheDocument();
  expect(JSON.parse(calls.find(([u]) => u === "/api/sources/config")![1]!.body as string)).toEqual({ path: "D:/runs/x__config.json" });
  await waitFor(() => expect(getForm("A")).toMatchObject({ name: "HR", how: "path", path: "D:/x/hr.csv" }));
  expect(getForm("B")).toMatchObject({ how: "database", connection: "SAMPLE", sql: "SELECT 1" });
  expect(within(card).getByText("Loaded")).toBeInTheDocument();
});

test("Browse… fills the path from the file dialog where the app runs", async () => {
  vi.stubGlobal("fetch", server([]));
  mount(<ConfigView />);
  const card = screen.getByRole("region", { name: "Config" });
  await userEvent.click(within(card).getByRole("button", { name: "Path on disk" }));
  await userEvent.click(await within(card).findByRole("button", { name: "Browse…" }));
  await waitFor(() => expect(within(card).getByLabelText("Path")).toHaveValue("D:/runs/picked__config.json"));
});

test("an uploaded config is read first - what it holds shows before it runs - and its text is what runs", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", server(calls));
  mount(<ConfigView />);
  const card = screen.getByRole("region", { name: "Config" });
  const text = JSON.stringify(CONF);
  await userEvent.upload(within(card).getByLabelText("Config file"), new File([text], "HR__config.json", { type: "application/json" }));
  expect(await within(card).findByText("Read · 2 pairs · key emp_id")).toBeInTheDocument();
  expect(within(card).getByText(/emp_id ⇄ EmployeeId \(key\)/)).toBeInTheDocument();
  expect(within(card).getByText(/Payroll: Salary remove thousands/)).toBeInTheDocument();
  expect(screen.getByText(/python -m tablecmp\.run HR__config\.json --pairs pairs\.csv/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Run this config" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/config")).toBe(true));
  expect(JSON.parse(calls.find(([u]) => u === "/api/sources/config")![1]!.body as string)).toEqual({ text });
});

test("a file that is not a config says so and cannot run", async () => {
  vi.stubGlobal("fetch", server([]));
  mount(<ConfigView />);
  const card = screen.getByRole("region", { name: "Config" });
  await userEvent.upload(within(card).getByLabelText("Config file"), new File(['{"a": 1}'], "other.json", { type: "application/json" }));
  expect(await within(card).findByText(/Not a config file/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run this config" })).toBeDisabled();
});

test("a server refusal is shown", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/sources/config"
    ? json({ detail: "Not under an allowed folder (COMPARE_DATA_DIR)." }, 400)
    : url === "/api/log" ? json({ entries: [], last: {} }) : json(body())));
  mount(<ConfigView />);
  const card = screen.getByRole("region", { name: "Config" });
  await userEvent.click(within(card).getByRole("button", { name: "Path on disk" }));
  await userEvent.type(within(card).getByLabelText("Path"), "C:/elsewhere/c.json");
  await userEvent.click(screen.getByRole("button", { name: "Run this config" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Not under an allowed folder (COMPARE_DATA_DIR).");
});

test("Back and Open in the setup instead go to the setup", async () => {
  vi.stubGlobal("fetch", server([]));
  setView({ view: "config" });
  mount(<ConfigView />);
  await userEvent.click(screen.getByRole("button", { name: "Open in the setup instead" }));
  expect(getView().view).toBe("setup");
  setView({ view: "config" });
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(getView().view).toBe("setup");
});

test("a pairs.csv is previewed in the batch table and named in the command", async () => {
  vi.stubGlobal("fetch", server([]));
  mount(<ConfigView />);
  const csv = "left,right,name_left\nexports/hr_08.csv,exports/payroll_08.csv,Aug\n\"exports/hr, 09.csv\",exports/payroll_09.csv,\n";
  await userEvent.upload(screen.getByLabelText("Pairs file"), new File([csv], "months.csv", { type: "text/csv" }));
  const table = await screen.findByRole("table", { name: "Pairs in months.csv" });
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(table).getByText("exports/hr, 09.csv")).toBeInTheDocument();
  expect(within(table).getByText("Aug")).toBeInTheDocument();
  expect(screen.getByText(/--pairs months\.csv --out results/)).toBeInTheDocument();
});

test("a pairs file without left and right is refused", () => {
  expect(readPairs("a,b\n1,2").error).toMatch(/left and a right/);
  expect(readPairs("left,right\n,\nx,y").rows).toEqual([{ left: "x", right: "y", name_left: "", name_right: "" }]);
  expect(readConf("{}").error).toMatch(/Not a config/);
  expect(summarise(readConf(JSON.stringify(CONF)).conf!).rows).toBe("match on key emp_id · no filter · all rows");
});

test("the boxes fill from a loaded config even with the config page closed (ConfigSync)", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(body({ config: CONFIG } as never))));
  mount(<ConfigSync />);
  await waitFor(() => expect(getForm("A")).toMatchObject({ name: "HR", path: "D:/x/hr.csv" }));
});
