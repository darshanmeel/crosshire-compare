// web/src/sources/database.test.tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { SideCard } from "./SideCard";
import { SourcesSection } from "./SourcesSection";
import { getView, resetView } from "../shell/view";
import { getForm, resetForms, setForm } from "./formStore";
import { body, json, META, mount, view, type Call } from "./testkit";

beforeEach(() => { resetForms(); resetView(); try { localStorage.clear(); } catch { /* none */ } });

const CONNS = [
  { name: "PG", kind: "postgresql", label: "Postgres", where: "db/hr", source: "file", origin_file: "", is_folder: false, editable: true, password: "asked" },
  { name: "DATA", kind: "folder", label: "Folder", where: "D:/x", source: "file", origin_file: "", is_folder: true, editable: true, password: "folder" },
];
const entry = (id: string, state: string, label: string) => ({ id, at: "10:00:00", kind: "Fetch", label, state, seconds: null, lines: [], page: "Compare" });

test("a database side asks for the password, fetches as a job, then holds the fetch", async () => {
  const calls: Call[] = [];
  let fetched = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/connections") return json(CONNS);
    if (url === "/api/sources/A/db")
      return json({ sql: "SELECT * FROM \"hr\".\"employees\"", error: "",
                    warning: fetched ? "" : "A cap without an ORDER BY can give the two sides different rows - add ORDER BY, or fetch everything.",
                    held: fetched ? { at: "10:00:00", rows: 3000, capped: false } : null, password: fetched ? "held" : "asked" });
    if (url === "/api/sources/A/fetch") return json(entry("j1", "running", "Fetching from PG…"));
    if (url === "/api/jobs/j1") { fetched = true; return json(entry("j1", "done", "Fetched 3,000 rows in 0.4s")); }
    if (url === "/api/sources/A/schema") return json({ label: "PG.parquet", kind: "parquet", columns: [], error: "" });
    return json(body());
  }));
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(screen.getByRole("radio", { name: "Database" }));
  expect(await screen.findByRole("option", { name: "PG · Postgres · db/hr" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /DATA/ })).toBeNull();          // a folder is picked under Path on disk
  await userEvent.type(screen.getByLabelText("Table"), "hr.employees");
  await userEvent.type(await screen.findByLabelText("Password"), "typed");
  expect(screen.getByText(/A cap without an ORDER BY/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Fetch A" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/fetch")).toBe(true));
  const sent = JSON.parse(calls.find(([u]) => u === "/api/sources/A/fetch")![1]!.body as string);
  expect(sent).toMatchObject({ connection: "PG", mode: "table", table: "hr.employees", cap: 1000000, password: "typed" });
  expect(await screen.findByText("Fetched at 10:00:00 - 3,000 rows")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Fetch again" })).toBeInTheDocument();
});

test("Same SQL as A copies A's connection, SQL and cap to B", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/connections" ? json(CONNS)
      : url.endsWith("/db") ? json({ sql: "SELECT 1", error: "", warning: "", held: null, password: "none" })
      : json(body())));
  setForm("A", { how: "database", connection: "PG", db_mode: "sql", sql: "SELECT 1", cap: 5 });
  mount(<SideCard tag="B" meta={META} />);
  await userEvent.click(screen.getByRole("radio", { name: "Database" }));
  await userEvent.click(await screen.findByRole("button", { name: "Same SQL as A" }));
  expect(getForm("B")).toMatchObject({ connection: "PG", db_mode: "sql", sql: "SELECT 1", cap: 5 });
  expect(screen.getByLabelText("SQL")).toHaveValue("SELECT 1");
});

test("each card's foot says what was read, warns of two sides of one name, and previews its first rows inline", async () => {
  const a = view("A", { loaded: true, name: "SAMPLE", is_database: true, conn: "SAMPLE", origin: "DuckDB file · hr.employees", rows: 3000, columns: ["emp_id", "first_name"] });
  const b = view("B", { loaded: true, name: "SAMPLE", is_database: true, conn: "SAMPLE", origin: "DuckDB file · payroll.employees", rows: 2985, columns: ["emp_id", "first_name"],
                        notes: [{ tone: "warning", text: "The fetch returned no rows." }] });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/preview?n=10")
    ? json({ columns: ["emp_id", "first_name"], rows: [["E1", "Omar"], ["E2", null]] })
    : url === "/api/connections" ? json([])
    : json(body({ sides: { A: a, B: b, P: view("P") } }))));
  mount(<SourcesSection meta={META} />);
  const A = await screen.findByRole("region", { name: "File A" });
  const B = screen.getByRole("region", { name: "File B" });
  expect(await within(A).findByText("DuckDB file · hr.employees")).toBeInTheDocument();
  expect(within(A).getByText("· 3,000 rows × 2 columns")).toBeInTheDocument();
  expect(within(A).getByText("emp_id, first_name")).toBeInTheDocument();
  expect(within(A).getByText("Both sides are called SAMPLE")).toBeInTheDocument();
  expect(within(B).getByText("The fetch returned no rows.")).toBeInTheDocument();
  expect(screen.getByText("CSV, JSON, Parquet or a database table on either side")).toBeInTheDocument();
  const toggle = within(A).getByRole("button", { name: "Preview 10 rows" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(await within(A).findByText("Omar")).toBeInTheDocument();
  expect(within(B).queryByText("Omar")).toBeNull();                  // only the side asked
  await userEvent.click(toggle);
  expect(within(A).queryByText("Omar")).toBeNull();
});

test("Manage opens the Connections drawer, also when there is no connection yet; the table-vs-query note can be dismissed", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/connections" ? json([]) : json(body())));
  setForm("B", { how: "database" });
  mount(<SourcesSection meta={META} />);
  expect(screen.getByText("load both sides to continue")).toBeInTheDocument();
  const B = await screen.findByRole("region", { name: "File B" });
  expect(await within(B).findByText(/No database connections yet/)).toBeInTheDocument();
  await userEvent.click(within(B).getByRole("button", { name: "Manage" }));
  expect(getView().drawer).toBe("connections");
  expect(screen.getByText(/reads exactly what you write/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText(/reads exactly what you write/)).toBeNull();
});

test("with a connection, Manage sits beside its select", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/connections" ? json(CONNS)
      : url.endsWith("/db") ? json({ sql: "SELECT 1", error: "", warning: "", held: null, password: "none" })
      : json(body())));
  setForm("A", { how: "database" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Manage connections" }));
  expect(getView().drawer).toBe("connections");
  expect(screen.getByLabelText("Snapshot the rows read to Parquet")).toBeChecked();   // in the options row on a database side
  expect(screen.queryByLabelText("Delimiter")).toBeNull();
});

test("a held password can be changed: Change password forgets it on the server and shows the box again", async () => {
  const calls: Call[] = [];
  let held = true;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/connections") return json(CONNS);
    if (url === "/api/connections/PG/password") { held = false; return json({ ok: true }); }
    if (url === "/api/sources/A/db")
      return json({ sql: "SELECT 1", error: "", warning: "", held: null, password: held ? "held" : "asked" });
    return json(body());
  }));
  setForm("A", { how: "database", connection: "PG", db_mode: "sql", sql: "SELECT 1", password: "wrong" });
  mount(<SideCard tag="A" meta={META} />);
  expect(await screen.findByText("Password held for this session")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByLabelText("Password")).toHaveValue("");
  const [, init] = calls.find(([u]) => u === "/api/connections/PG/password")!;
  expect(init!.method).toBe("DELETE");
  expect(getForm("A").password).toBe("");
});

test("a fetch that fails on the login says to type the password again", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/connections") return json(CONNS);
    if (url === "/api/sources/A/db") return json({ sql: "SELECT 1", error: "", warning: "", held: null, password: "asked" });
    if (url === "/api/sources/A/fetch") return json(entry("j1", "running", "Fetching from PG…"));
    if (url === "/api/jobs/j1") return json({ ...entry("j1", "error", "Fetching from PG…"), lines: ["The fetch failed - password authentication failed for user u"] });
    return json(body());
  }));
  setForm("A", { how: "database", connection: "PG", db_mode: "sql", sql: "SELECT 1" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Fetch A" }));
  expect(await screen.findByText(/password authentication failed/)).toBeInTheDocument();
  expect(screen.getByText(/Type the password again/)).toBeInTheDocument();
});
