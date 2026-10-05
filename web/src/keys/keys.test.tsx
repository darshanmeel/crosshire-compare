// web/src/keys/keys.test.tsx - the rows page (SPEC §06) and the setup's Rows card.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { KeyBox } from "./KeyBox";
import { ProfileBox, setFreqPicks } from "./ProfileBox";
import { RowsToReadCard } from "./RowsToReadCard";
import { BucketCard } from "./BucketCard";
import { RunSettingsCard } from "./RunSettingsCard";
import { RowsSummary } from "./RowsSummary";
import { RowsEditor } from "./RowsEditor";
import type { KeysView, SetupReady } from "../setup/api";
import { json, mount, row, setup, type Call } from "../setup/testkit";
import { getForm, resetForms, setForm } from "../sources/formStore";
import { blankForm, type SideView, type SourcesBody } from "../sources/types";
import { resetPicks, usePick } from "../results/pickStore";
import { getView, resetView } from "../shell/view";
import type { CompareState } from "../compare/types";

beforeEach(() => { setFreqPicks(null); resetForms(); resetPicks(); resetView(); });

const KEYS: KeysView = {
  keys: [], mode: "hash", nokey_mode: "hash",
  nokey_modes: { hash: "match identical rows by hashing the compared columns", position: "pair by position - line 1 against line 1" },
  tips: ["**Suggest keys** tries single columns"], nokey_tips: ["**hash** - rows identical"],
  suggestions: null, report: null, formats: [], error: "",
};
const KEYED: SetupReady = setup({
  keys: ["emp_id"], compare: ["salary"],
  rows: [row("emp_id", "EmployeeId", { "Common name": "emp_id", Key: true, Compare: false }), row("salary", "Salary", { Type: "number" }),
         row("department", ""), row("", "Dept")],
});
const entry = (id: string, state: string, label: string, kind = "Key search") =>
  ({ id, at: "10:00:00", kind, label, state, seconds: null, lines: ["Measuring every column of HR…"], page: "Compare" });
const side = (tag: "A" | "B", over: Partial<SideView> = {}): SideView => ({
  tag, loaded: true, name: tag === "A" ? "HR" : "PR", label: "", origin: "", kind: "csv", rows: tag === "A" ? 3000 : 2985,
  columns: tag === "A" ? ["emp_id", "salary", "department"] : ["EmployeeId", "Salary", "Dept"], cut: "", is_database: false,
  conn: "", fetched_at: "", snapshot: true, caption: "", notes: [], staged: "", fetched: null, ...over });
const SOURCES = (over: Partial<SourcesBody["sides"]> = {}): SourcesBody => ({
  sides: { A: side("A"), B: side("B"), P: { ...side("A"), tag: "P", loaded: false }, ...over },
  defaults: { A: "Left", B: "Right", P: "Table" }, quick_ops: ["=", "!=", "is null"], name_help: { side: "", table: "" },
  upload_types: [], config: null });
const COMPARE = (over: Partial<CompareState> = {}): CompareState => ({
  gate: "", names: ["HR", "PR"], strip: { cells: { Files: "", Columns: "", Key: "", Compare: "", Result: "" }, tones: {} },
  settings: { display_rows: 1000, auto_rerun: false, out_fmt: "csv", auto_profile: false },
  filter_error: "", sig: "s", stale: false, busy: false, said: [], run: null, ...over });
const FILTERS = { rows: [], rev: "0", columns: ["emp_id", "salary"], apply_to: ["Both", "HR", "PR"], ops: ["="], types: ["auto"], error: "" };

/** fetch answered per path (and method) - "PUT /api/x" before "/api/x"; anything else {}. */
function stub(routes: Record<string, (init?: RequestInit) => unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const path = url.split("?")[0];
    const f = routes[`${init?.method ?? "GET"} ${path}`] ?? routes[path] ?? routes[url];
    return json(f ? f(init) : {});
  }));
  return calls;
}
const sent = (calls: Call[], url: string, method = "POST") =>
  calls.filter(([u, i]) => u === url && (i?.method ?? "GET") === method).map(([, i]) => JSON.parse(i!.body as string));

// ---- How they pair up -----------------------------------------------------------------------
test("no key: the match mode says hash, By position is kept on the server and Check key waits for a key", async () => {
  const calls = stub({ "/api/setup/keys": () => KEYS, "/api/setup": () => setup(), "PUT /api/setup/settings": () => ({ nokey_mode: "position" }) });
  mount(<KeyBox />);
  const mode = await screen.findByRole("group", { name: "Match mode" });
  expect(within(mode).getByRole("button", { name: "By hash of compared columns" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(mode).getByRole("button", { name: "By position" }));
  await waitFor(() => expect(sent(calls, "/api/setup/settings", "PUT")).toEqual([{ nokey_mode: "position" }]));
  expect(calls.some(([u]) => u === "/api/setup/cell")).toBe(false);
  expect(screen.getByRole("button", { name: "Check key" })).toBeDisabled();
  expect(screen.getByText("hash", { selector: "b" })).toBeInTheDocument();          // the tips without a key
});

test("On a key with no key: the picker opens and the column picked is ticked Key in the table", async () => {
  const calls = stub({ "/api/setup/keys": () => KEYS, "/api/setup": () => setup(), "/api/setup/cell": () => KEYED });
  mount(<KeyBox />);
  await userEvent.click(await screen.findByRole("button", { name: "On a key" }));
  expect(screen.getByRole("button", { name: "On a key" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.selectOptions(await screen.findByLabelText("Add a key column"), "salary");
  await waitFor(() => expect(sent(calls, "/api/setup/cell")).toEqual([{ rev: "1.a", row: 1, column: "Key", value: true }]));
});

test("a key: its chip reads A ⇄ B, it can be removed, and By hash unticks it before the mode is set", async () => {
  const unkeyed = setup({ rev: "2.b" });
  const calls = stub({ "/api/setup/keys": () => ({ ...KEYS, keys: ["emp_id"], mode: "key" }), "/api/setup": () => KEYED,
                       "/api/setup/cell": () => unkeyed, "PUT /api/setup/settings": () => ({ nokey_mode: "hash" }) });
  mount(<KeyBox />);
  expect(await screen.findByText("emp_id ⇄ EmployeeId")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "On a key" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "By hash of compared columns" }));
  await waitFor(() => expect(sent(calls, "/api/setup/settings", "PUT")).toEqual([{ nokey_mode: "hash" }]));
  expect(sent(calls, "/api/setup/cell")).toEqual([{ rev: "1.a", row: 0, column: "Key", value: false }]);
  await userEvent.click(screen.getByRole("button", { name: "Remove emp_id from the key" }));
  await waitFor(() => expect(sent(calls, "/api/setup/cell")).toHaveLength(2));
});

test("Suggest keys runs as a job with its disc; the candidates are chips picked on click, then Use as key", async () => {
  let done = false;
  const found: KeysView = { ...KEYS, suggestions: {
    said: { tone: "success", text: "1 combination(s) identify a single row on both sides - best: **emp_id**. Found." },
    columns: ["Key columns", "Unique on both", "Overlap %"], rows: [["emp_id", "yes", 98.7], ["last_name + salary", "yes", 90]],
    combos: [["emp_id"], ["last_name", "salary"]], labels: ["emp_id", "last_name + salary"] } };
  const calls = stub({
    "/api/setup/keys/suggest": () => entry("k1", "running", "Looking for keys…"),
    "/api/jobs/k1": () => { done = true; return entry("k1", "done", "Best key: emp_id in 0.2s"); },
    "/api/setup/keys/use": () => ({ ...KEYS, keys: ["emp_id"], mode: "key" }),
    "/api/setup/keys": () => (done ? found : KEYS), "/api/setup": () => setup(),
  });
  mount(<KeyBox />);
  await userEvent.click(await screen.findByRole("button", { name: "Suggest keys" }));
  const picks = await screen.findByRole("group", { name: "Use these" });
  expect(screen.getByRole("table", { name: "Suggested keys", hidden: true })).toBeInTheDocument();
  expect(within(picks).getByRole("button", { name: /emp_id\s*98\.7%/ })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "Use as key" })).toBeDisabled();
  await userEvent.click(within(picks).getByRole("button", { name: /last_name \+ salary/ }));
  await userEvent.click(within(picks).getByRole("button", { name: /^emp_id/ }));
  expect(screen.getByText("last_name + salary + emp_id", { selector: "b" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Use as key" }));
  await waitFor(() => expect(sent(calls, "/api/setup/keys/use")).toEqual([{ picks: [1, 0] }]));
});

test("a checked key: the uniqueness line and its table; a key written differently: Apply, and Dismiss", async () => {
  const checked: KeysView = { ...KEYS, keys: ["emp_id"], mode: "key",
    report: { said: { tone: "success", text: "**emp_id** identifies a single row on both sides." },
              columns: ["Side", "Rows"], rows: [["HR", 40], ["PR", 40]] },
    formats: [{ tone: "success", text: ":green[**Applied**] · emp_id: spaces", apply: null },
              { tone: "warning", text: ":orange[**Suggested**] · ref: a prefix R- on A", apply: 1 }] };
  const calls = stub({ "/api/setup/keys": () => checked, "/api/setup": () => KEYED, "/api/setup/keys/check": () => checked,
                       "/api/setup/keys/formats/1/apply": () => checked, "DELETE /api/setup/keys/formats": () => checked });
  mount(<KeyBox />);
  expect(await screen.findByRole("table", { name: "Key check" })).toBeInTheDocument();
  expect(screen.getByText("identifies a single row on both sides.", { exact: false })).toBeInTheDocument();
  expect(screen.getByText("Applied").closest(".pos")).not.toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/setup/keys/formats/1/apply" && i?.method === "POST")).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "Check key" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/setup/keys/check")).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/setup/keys/formats" && i?.method === "DELETE")).toBe(true));
});

// ---- Profile both files ---------------------------------------------------------------------
test("Profile both files runs as a job; the tabs, the stale line and the frequencies picked as chips", async () => {
  let made = false;
  const prof = { stale: true, names: ["HR", "PR"], stale_said: "This profile is from earlier settings - run it again to refresh.",
                 both: { columns: ["Column", "Null % gap"], rows: [["salary", 0]] }, A: { columns: ["Column", "Type", "Nulls", "Distinct"], rows: [["salary", "number", 0, 3000]] },
                 B: { columns: ["Column", "Type", "Nulls", "Distinct"], rows: [["salary", "number", 0, 2985]] }, freq_columns: ["emp_id", "salary"], freq_default: ["emp_id"] };
  const freq = { title: "**emp_id** · key - text · HR: 3,000 distinct · PR: 2,985 distinct",
                 A: { top: { columns: ["Value", "Count", "%"], rows: [["E1", 1, 0.03]] }, bottom: { columns: ["Value"], rows: [] } },
                 B: { top: { columns: ["Value", "Count", "%"], rows: [["E1", 1, 0.03]] }, bottom: { columns: ["Value"], rows: [] } } };
  const calls = stub({
    "POST /api/setup/profile": () => entry("p1", "running", "Profiling…", "Profile"),
    "/api/setup/profile": () => (made ? prof : null),
    "/api/jobs/p1": () => { made = true; return entry("p1", "done", "Profile ready in 0.3s", "Profile"); },
    "/api/setup/profile/freq": () => freq,
  });
  mount(<ProfileBox />);
  await userEvent.click(screen.getByRole("button", { name: "Profile both files" }));
  expect(await screen.findByText("This profile is from earlier settings - run it again to refresh.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Profile again" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "PR" }));
  expect(screen.getByRole("tab", { name: "PR" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("2,985")).toBeInTheDocument();
  expect(await screen.findByText("emp_id", { selector: "b" })).toBeInTheDocument();          // the default: the key
  expect(calls.some(([u]) => u === "/api/setup/profile/freq?col=emp_id")).toBe(true);
  const list = screen.getByRole("group", { name: "Columns to list" });
  expect(within(list).getByRole("button", { name: "emp_id" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(list).getByRole("button", { name: "salary" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/setup/profile/freq?col=salary")).toBe(true));
});

// ---- Rows to read ---------------------------------------------------------------------------
test("Rows to read: the rows pill, a condition built, Apply loads the side again with the rows options", async () => {
  setForm("A", { how: "path", path: "D:/x/hr.csv", name: "HR" });
  const calls = stub({ "/api/sources": () => SOURCES(), "/api/setup": () => KEYED,
                       "/api/sources/quick-clause": () => ({ where: "salary > '100'" }),
                       "/api/sources/A/load": () => ({ side: side("A", { rows: 120, cut: "where salary > '100'" }), warnings: ["Heads up"] }) });
  mount(<RowsToReadCard tag="A" />);
  const card = await screen.findByRole("region", { name: "Rows to read from HR" });
  expect(await within(card).findByText("3,000 rows")).toBeInTheDocument();
  await userEvent.click(within(card).getByText("Build a condition"));
  await userEvent.selectOptions(within(card).getByLabelText("Column"), "salary");
  await userEvent.type(within(card).getByLabelText("Value"), "100");
  await userEvent.click(within(card).getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(within(card).getByLabelText("Filter · WHERE")).toHaveValue("salary > '100'"));
  expect(sent(calls, "/api/sources/quick-clause")[0]).toMatchObject({ column: "salary", value: "100", where: "" });
  await userEvent.type(within(card).getByLabelText("Order by"), "salary");
  await userEvent.click(within(card).getByLabelText("Descending"));
  await userEvent.type(within(card).getByLabelText("Top N"), "500");
  await userEvent.click(within(card).getByRole("button", { name: "Apply to HR" }));
  await waitFor(() => expect(sent(calls, "/api/sources/A/load")).toHaveLength(1));
  expect(sent(calls, "/api/sources/A/load")[0]).toMatchObject({ how: "path", path: "D:/x/hr.csv", name: "HR", where: "salary > '100'",
                                                               order_by: ["salary"], desc: true, limit: 500 });
  expect(await within(card).findByText("Heads up")).toBeInTheDocument();
});

test("Rows to read: Copy to the other side takes the cut, the order's columns become their partners", async () => {
  setForm("A", { where: "salary > 1", order_by: ["salary", "nope"], desc: true, limit: 10 });
  stub({ "/api/sources": () => SOURCES({ A: side("A", { cut: "where salary > 1" }) }), "/api/setup": () => KEYED });
  mount(<RowsToReadCard tag="A" />);
  expect(await screen.findByText("3,000 rows · cut")).toBeInTheDocument();
  expect(screen.getByText("HR has no column nope - the load will say so.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Copy to PR" }));
  expect(getForm("B")).toMatchObject({ where: "salary > 1", order_by: ["Salary", "nope"], desc: true, limit: 10 });
  expect(getForm("B").path).toBe(blankForm("B").path);
});

// ---- Profile by bucket, Run settings ------------------------------------------------------
function Held({ k }: { k: string }) { const [v] = usePick<string[]>(k, []); return <output aria-label={k}>{v.join(",")}</output>; }

test("Profile by bucket: the tick and the column go into every bucket's kept columns, and come out again", async () => {
  stub({ "/api/setup": () => KEYED });
  mount(<><BucketCard /><Held k="bucket_cols_differ" /><Held k="bucket_cols_left" /></>);
  const tick = await screen.findByLabelText("Count a column in every bucket");
  expect(screen.getByLabelText("Bucket column")).toBeDisabled();
  await userEvent.click(tick);
  expect(screen.getByLabelText("bucket_cols_differ")).toHaveTextContent("salary");     // the first that is not the key
  await userEvent.selectOptions(screen.getByLabelText("Bucket column"), "emp_id");
  expect(screen.getByLabelText("bucket_cols_left")).toHaveTextContent(/^emp_id$/);
  await userEvent.click(tick);
  expect(screen.getByLabelText("bucket_cols_differ")).toHaveTextContent(/^$/);
});

test("Run settings: Re-run on every change, Profile both sides first and Rows to display go to the compare settings", async () => {
  const calls = stub({ "/api/compare": () => COMPARE(), "PUT /api/compare/settings": () => COMPARE().settings });
  mount(<RunSettingsCard />);
  await userEvent.click(await screen.findByLabelText("Re-run on every change"));
  await userEvent.click(screen.getByLabelText("Profile both sides first"));
  const rows = screen.getByLabelText("Rows to display per section");
  await userEvent.clear(rows);
  await userEvent.type(rows, "2049{Enter}");
  await waitFor(() => expect(sent(calls, "/api/compare/settings", "PUT")).toEqual([{ auto_rerun: true }, { auto_profile: true }, { display_rows: 2000 }]));
});

// ---- the setup's Rows card and the rows page ------------------------------------------------
test("the Rows card: hidden until a pair is set up, then the key, no filter, bucket off, and Edit rows", async () => {
  let ready = false;
  stub({ "/api/setup": () => (ready ? KEYED : { ready: false, names: ["HR", "PR"] }), "/api/setup/keys": () => KEYS,
         "/api/setup/filters": () => FILTERS, "/api/sources": () => SOURCES() });
  mount(<RowsSummary />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: "Edit rows" })).toBeNull();
  ready = true;
  resetView();
  mount(<RowsSummary />);
  const sec = await screen.findByRole("region", { name: "Rows" });
  expect(within(sec).getByText("emp_id", { selector: "code" })).toBeInTheDocument();
  expect(await within(sec).findByText("none - all 3,000 and 2,985 rows")).toBeInTheDocument();
  expect(within(sec).getByText("off")).toBeInTheDocument();
  await userEvent.click(within(sec).getByRole("button", { name: "Edit rows" }));
  expect(getView().view).toBe("rows");
});

test("the Rows card without a key says how rows pair, and counts the filters and the cut sides", async () => {
  stub({ "/api/setup": () => setup(), "/api/setup/keys": () => ({ ...KEYS, nokey_mode: "position" }),
         "/api/setup/filters": () => ({ ...FILTERS, rows: [{ "Apply to": "Both", Column: "salary", Operator: "=", Value: "1", Type: "auto" }] }),
         "/api/sources": () => SOURCES({ B: side("B", { rows: 50, cut: "top 50" }) }) });
  mount(<RowsSummary />);
  expect(await screen.findByText("by position")).toBeInTheDocument();
  expect(await screen.findByText("1 filter at compare · PR read to 50 rows")).toBeInTheDocument();
});

test("the rows page: its parts in order, Back to the setup, and Compare HR against PR starts the run", async () => {
  const calls = stub({ "/api/setup": () => KEYED, "/api/setup/keys": () => ({ ...KEYS, keys: ["emp_id"], mode: "key" }),
                       "/api/setup/filters": () => FILTERS, "/api/sources": () => SOURCES(), "/api/compare": () => COMPARE(),
                       "/api/setup/profile": () => null, "POST /api/compare": () => entry("c1", "running", "Comparing…", "Compare") });
  mount(<RowsEditor />);
  expect(await screen.findByRole("region", { name: "Rows · how they pair up" })).toBeInTheDocument();
  expect(await screen.findByRole("region", { name: "Rows to read from HR" })).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Rows to read from PR" })).toBeInTheDocument();
  expect(await screen.findByText("Filters at compare")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Profile by bucket" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Profile both files" })).toBeInTheDocument();
  expect(await screen.findByLabelText("Rows to display per section")).toBeInTheDocument();
  expect(await screen.findByText("1 column on key emp_id · no filters applied")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Compare HR against PR" }));
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/compare" && i?.method === "POST")).toBe(true));
  await userEvent.click(screen.getByRole("button", { name: "Back to the setup" }));
  expect(getView()).toMatchObject({ view: "setup", anchor: "rows" });
});
