import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { LogView } from "./LogView";
import { logText } from "./LogPanel";
import { getView, setView, toggleLog } from "./view";

const E = (id: string, kind: string, label: string, lines: string[] = [], state = "done") =>
  ({ id, at: "15:48:40", kind, label, state, seconds: 0.3 as number | null, lines, page: "Compare" });
const ENTRIES = [
  E("1", "Load", "HR · hr_employees.csv · 3,000 rows × 7 columns", ["delimiter \",\" · header row"]),
  E("2", "Compare", "HR against Payroll · 2,960 rows differ", ["department 337", "salary 319"]),
  E("3", "Fetch", "Fetching from PG…", [], "running"),
  E("4", "Profile", "Could not read it", ["no such file"], "error"),
];

type Calls = [string, RequestInit | undefined][];
function server(calls: Calls, entries = ENTRIES) {
  let now = entries;
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url === "/api/log" && init?.method === "DELETE") { now = []; return json({ entries: [], last: {} }); }
    if (url === "/api/log") return json({ entries: now, last: {} });
    return json({});
  });
}
const mount = () => render(<QueryClientProvider client={new QueryClient()}><LogView /></QueryClientProvider>);

test("every entry shows its time, kind, line and grey sub-lines, oldest first, with a count in the head", async () => {
  vi.stubGlobal("fetch", server([]));
  mount();
  const list = await screen.findByRole("list", { name: "Log entries" });
  const items = within(list).getAllByRole("listitem").reverse();     // the server sends newest first; the page reads newest last
  expect(items).toHaveLength(4);
  expect(within(items[0]).getByText("15:48:40")).toBeInTheDocument();
  expect(within(items[0]).getByText("Load")).toBeInTheDocument();
  expect(within(items[0]).getByText(/hr_employees\.csv/)).toBeInTheDocument();
  expect(within(items[1]).getByText("salary 319")).toHaveClass("sub");
  expect(within(items[2]).getByText("running")).toBeInTheDocument();
  expect(within(items[3]).getByText("error")).toBeInTheDocument();
  expect(screen.getByText(/newest last · 4 entries/)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Log" })).toHaveFocus();
});

test("a job's trace folds behind its step count once it is done; running, failed and note lines stay open", async () => {
  const note = { ...E("5", "Auto decisions", "2 decisions", ["key: `emp_id`"]), seconds: null };
  vi.stubGlobal("fetch", server([], [note, ...ENTRIES]));
  mount();
  const list = await screen.findByRole("list", { name: "Log entries" });
  const [auto, load, compare, fetch, profile] = within(list).getAllByRole("listitem").reverse();     // as the server sends them
  expect(within(compare).getByText("2 steps").closest("details")).not.toHaveAttribute("open");
  expect(within(load).getByText("1 step")).toBeInTheDocument();
  expect(within(profile).getByText("1 step").closest("details")).toHaveAttribute("open");
  expect(within(fetch).queryByText(/step/)).toBeNull();                       // no lines yet - nothing to fold
  expect(within(auto).queryByText(/step/)).toBeNull();                         // a note says its lines, unfolded
  expect(within(auto).getByText("emp_id").tagName).toBe("CODE");              // the engine's markup renders
  expect(within(compare).getByText(/HR against Payroll/).tagName).toBe("STRONG");
});

test("Clear empties the Log on the server and here", async () => {
  const calls: Calls = [];
  vi.stubGlobal("fetch", server(calls));
  mount();
  await screen.findByRole("list", { name: "Log entries" });
  await userEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
  expect(calls.some(([u, i]) => u === "/api/log" && i?.method === "DELETE")).toBe(true);
  expect(screen.getByText(/0 entries/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clear" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Copy as text" })).toBeDisabled();
});

test("Copy as text puts every entry and its sub-lines on the clipboard", async () => {
  vi.stubGlobal("fetch", server([]));
  const writeText = vi.fn(async () => undefined);
  const user = userEvent.setup();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  mount();
  await screen.findByRole("list", { name: "Log entries" });
  await user.click(screen.getByRole("button", { name: "Copy as text" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(logText([...ENTRIES].reverse() as never)));     // in the order shown
  expect(await screen.findByText("Copied")).toBeInTheDocument();
  expect(logText(ENTRIES as never)).toContain("15:48:40  Compare  HR against Payroll · 2,960 rows differ\n    department 337\n    salary 319");
});

test("without a clipboard API the copy falls back to a hidden text area", async () => {
  vi.stubGlobal("fetch", server([]));
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  const exec = vi.fn(() => true);
  Object.defineProperty(document, "execCommand", { value: exec, configurable: true });
  mount();
  await screen.findByRole("list", { name: "Log entries" });
  await userEvent.click(screen.getByRole("button", { name: "Copy as text" }));
  expect(exec).toHaveBeenCalledWith("copy");
  expect(await screen.findByText("Copied")).toBeInTheDocument();
});

test("Close goes back to the setup", async () => {
  vi.stubGlobal("fetch", server([]));
  toggleLog();
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(getView().view).toBe("setup");
});

test("Close goes back to the results the Log was opened from", async () => {
  vi.stubGlobal("fetch", server([]));
  setView({ view: "results", tab: "rows" });
  toggleLog();
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(getView()).toMatchObject({ view: "results", tab: "rows" });
});
