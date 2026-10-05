// web/src/sources/cards.test.tsx - the redesign's source cards: states, the radio-backed source choice,
// the dropzone, Rows to read / Advanced, the Profile page's card and the one-line card of a run.
import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { getForm, resetForms, setForm } from "./formStore";
import { resetLoadTimes } from "./loadTime";
import { SideCard } from "./SideCard";
import { SideLine } from "./SideLine";
import { ProfileSource, SourcesSection } from "./SourcesSection";
import { body, json, META, mount, view, type Call } from "./testkit";

beforeEach(() => { resetForms(); resetLoadTimes(); });

const SCHEMA = { label: "hr.csv", kind: "csv", columns: [{ name: "emp_id", type: "VARCHAR" }, { name: "department", type: "VARCHAR" }], error: "" };
const HR = view("A", { loaded: true, name: "HR", label: "hr_employees.csv", rows: 3000, columns: ["emp_id", "first_name"], snapshot: true });

test("an empty card: region, Name, Not loaded, the source radios, and Load only once a file is picked", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/sources/A/schema" ? json(SCHEMA) : url === "/api/sources/folders" ? json([]) : json(body())));
  mount(<SideCard tag="A" meta={META} />);
  const A = screen.getByRole("region", { name: "File A" });
  expect(within(A).getByLabelText("Name")).toHaveValue("Left");
  expect(within(A).getByRole("status")).toHaveTextContent("Not loaded");
  const choice = within(A).getByRole("radiogroup", { name: "Source for A" });
  expect(within(choice).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["Upload", "Path on disk", "Database"]);
  expect(within(A).getByRole("radio", { name: "Upload" })).toBeChecked();
  expect(within(A).getByLabelText("CSV or JSON file")).toBeInTheDocument();          // the dropzone's file input
  expect(within(A).getByRole("button", { name: "Load A" })).toBeDisabled();
  await userEvent.click(within(A).getByLabelText("Path on disk"));                   // a label a test can check
  expect(getForm("A").how).toBe("path");
  await userEvent.type(within(A).getByLabelText("Path to CSV or JSON"), "D:/x/hr.csv");
  expect(await within(A).findByText("2 columns: emp_id, department")).toBeInTheDocument();
  expect(within(A).getByRole("button", { name: "Load A" })).toBeEnabled();
});

test("a file dropped on the dropzone is uploaded, and the card says it is staged", async () => {
  const calls: Call[] = [];
  let staged = "";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/sources/B/upload")) { staged = "payroll.csv"; return json(view("B", { staged })); }
    if (url === "/api/sources/B/schema") return json(SCHEMA);
    return json(body({ sides: { A: view("A"), B: view("B", { staged }), P: view("P") } }));
  }));
  mount(<SideCard tag="B" meta={META} />);
  const file = new File(["EmployeeId\nE1\n"], "payroll.csv", { type: "text/csv" });
  const drop = screen.getByText("Drop a CSV, JSON or Parquet file").closest(".drop")!;
  fireEvent.drop(drop, { dataTransfer: { files: [file] } });
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/B/upload?filename=payroll.csv")).toBe(true));
  expect(await screen.findByText("payroll.csv")).toHaveClass("staged");
});

test("Rows to read and Advanced open inside the card, and what they hold goes with Load", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/A/schema") return json(SCHEMA);
    if (url === "/api/sources/A/load") return json({ side: HR, warnings: [] });
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  const rows = await screen.findByRole("button", { name: /^Rows to read: all/ });
  expect(rows).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(rows);
  expect(rows).toHaveAttribute("aria-expanded", "true");
  await userEvent.type(screen.getByLabelText("Filter (WHERE)"), "salary > 0");
  await userEvent.clear(screen.getByLabelText("Top N rows (0 = all)"));
  await userEvent.type(screen.getByLabelText("Top N rows (0 = all)"), "1000");
  expect(screen.getByRole("button", { name: /^Rows to read: filtered · top 1,000/ })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Advanced" }));
  expect(screen.queryByLabelText("Filter (WHERE)")).toBeNull();                       // one panel at a time
  await userEvent.type(screen.getByLabelText("Column names"), "a, b");
  await userEvent.click(screen.getByLabelText("Snapshot the rows read to Parquet"));
  await userEvent.click(await screen.findByRole("button", { name: "Load A" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/load")).toBe(true));
  const sent = JSON.parse(calls.find(([u]) => u === "/api/sources/A/load")![1]!.body as string);
  expect(sent).toMatchObject({ how: "path", path: "D:/x/hr.csv", where: "salary > 0", limit: 1000, column_names: "a, b", snapshot: false });
});

test("once loaded, Load moves to the foot; a changed choice brings it back with a line saying so", async () => {
  let loaded = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources/A/schema") return json({ ...SCHEMA, columns: [{ name: "emp_id", type: "VARCHAR" }, { name: "first_name", type: "VARCHAR" }] });
    if (url === "/api/sources/A/load") { loaded = true; return json({ side: HR, warnings: [] }); }
    if (url === "/api/sources/folders") return json([]);
    return json(body(loaded ? { sides: { A: HR, B: view("B"), P: view("P") } } : {}));
  }));
  setForm("A", { how: "path", path: "D:/x/hr_employees.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Load A" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/^Loaded · /));
  expect(screen.queryByText("The choices above changed since the last Load")).toBeNull();
  expect(screen.getByRole("button", { name: "Load A" }).closest(".card-foot")).not.toBeNull();
  await userEvent.clear(screen.getByLabelText("Delimiter"));
  await userEvent.type(screen.getByLabelText("Delimiter"), ";");
  expect(screen.getByText("The choices above changed since the last Load")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Load A" }).closest(".card-foot")).toBeNull();
});

test("a Load the server refuses turns the pill to Error and says why", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources/A/schema") return json(SCHEMA);
    if (url === "/api/sources/A/load") return json({ detail: "The file is locked by another program." }, 400);
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Load A" }));
  expect(await screen.findByText("The file is locked by another program.")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Error");
});

test("the Profile page: one card 'File' with Load while empty, then a compact card with the same region", async () => {
  let P = view("P");
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/sources/folders" ? json([])
      : url === "/api/sources/P/schema" ? json(SCHEMA)
      : json(body({ sides: { A: view("A"), B: view("B"), P } }))));
  const { unmount } = mountAndKeep(<ProfileSource meta={META} />);
  const file = await screen.findByRole("region", { name: "File" });
  expect(screen.getByRole("region", { name: "Source" })).toBeInTheDocument();         // section 01 while empty
  expect(within(file).getByLabelText("Name")).toHaveValue("Table");
  expect(within(file).getByRole("button", { name: "Load" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /^Profile/ })).toBeNull();               // Profile is the rail's alone
  unmount();
  P = view("P", { loaded: true, name: "HR", label: "hr_employees.csv", rows: 3000, columns: ["emp_id", "first_name"], snapshot: true });
  setForm("P", { how: "path", path: "D:/x/hr_employees.csv" });
  mount(<ProfileSource meta={META} />);
  await waitFor(() => expect(screen.getByRole("region", { name: "File" })).toHaveClass("compact"));
  const card = screen.getByRole("region", { name: "File" });
  expect(screen.queryByRole("region", { name: "Source" })).toBeNull();
  expect(within(card).getByText("hr_employees.csv")).toBeInTheDocument();
  expect(within(card).getByText("· 3,000 rows × 2 columns · Parquet snapshot")).toBeInTheDocument();
  expect(within(card).getByText("delimiter , · first row is a header")).toBeInTheDocument();
  expect(within(card).getAllByRole("button", { name: /^Load/ })).toHaveLength(1);
  expect(within(card).getByRole("button", { name: "Preview 10 rows" })).toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: "Advanced" }));
  expect(within(card).getByLabelText("Delimiter")).toHaveValue(",");                 // delimiter and header live in Advanced here
  expect(within(card).getByLabelText("First row is a header")).toBeChecked();
});

test("while a run is going the sides collapse to one line each, keeping their regions", async () => {
  const B = view("B", { loaded: true, name: "Payroll", label: "payroll_employees.csv", rows: 2985, columns: ["EmployeeId"] });
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/compare" ? json({ busy: true }) : json(body({ sides: { A: HR, B, P: view("P") } }))));
  setForm("A", { name: "HR" });
  setForm("B", { name: "Payroll" });
  mount(<SourcesSection meta={META} />);
  await waitFor(() => expect(screen.getByRole("region", { name: "File A" })).toHaveClass("side-line"));
  const A = screen.getByRole("region", { name: "File A" });
  expect(within(A).getByText("HR")).toBeInTheDocument();
  expect(within(A).getByText("hr_employees.csv · 3,000 rows × 2 columns · Parquet snapshot")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "File B" })).getByText("Loaded")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Load/ })).toBeNull();
});

test("SideLine alone names a side that is not loaded yet", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(body())));
  mount(<SideLine tag="B" />);
  const B = screen.getByRole("region", { name: "File B" });
  expect(await within(B).findByText("Not loaded")).toBeInTheDocument();
  expect(within(B).getByText("Right")).toBeInTheDocument();
});

// mount, but hand back unmount so a test can draw the same component again on new data
function mountAndKeep(ui: ReactElement) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}
