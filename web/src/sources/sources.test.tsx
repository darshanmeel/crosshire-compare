import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { SideCard } from "./SideCard";
import { getForm, resetForms, setForm } from "./formStore";
import { nameHint, sideLabels, sideName } from "./names";
import { body, json, META, mount, view, type Call } from "./testkit";

beforeEach(() => resetForms());

test("an upload sends the file itself, with the write header", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/sources/A/upload")) return json(view("A", { staged: "hr.csv" }));
    return json(body());
  }));
  mount(<SideCard tag="A" meta={META} />);
  const file = new File(["emp_id\nE1\n"], "hr.csv", { type: "text/csv" });
  await userEvent.upload(await screen.findByLabelText("CSV or JSON file"), file);
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/upload?filename=hr.csv")).toBe(true));
  const [, init] = calls.find(([u]) => u.startsWith("/api/sources/A/upload"))!;
  expect(init!.method).toBe("POST");
  expect(init!.body).toBe(file);
  expect((init!.headers as Record<string, string>)["X-Compare"]).toBe("1");
});

const LOADED_A = view("A", { loaded: true, name: "A", label: "payroll.csv", rows: 2985, columns: ["EmployeeId", "Dept"], caption: ":green[**✓ A**] · payroll.csv · 2,985 rows × 2 columns" });

test("a folder's file is picked by name, and Load sends the pick and says what came back", async () => {
  const calls: Call[] = [];
  let loaded = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/folders") return json([{ name: "DATA", host: "D:/exports" }]);
    if (url === "/api/sources/folders/DATA/files") return json({ root: "D:/exports", files: ["hr.csv", "sub/payroll.csv"], note: null });
    if (url === "/api/sources/A/schema")
      return json({ label: "payroll.csv", kind: "csv", columns: [{ name: "EmployeeId", type: "VARCHAR" }, { name: "Dept", type: "VARCHAR" }], error: "" });
    if (url === "/api/sources/A/load") {
      loaded = true;
      return json({ side: LOADED_A, warnings: ["You gave 3 names but the file has 2 columns - the surplus was ignored / the shortfall kept its original name."] });
    }
    if (url === "/api/sources")
      return json(body(loaded ? { sides: { A: LOADED_A, B: view("B"), P: view("P") } } : {}));
    return json({});
  }));
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(screen.getByRole("radio", { name: "Path on disk" }));
  await userEvent.selectOptions(await screen.findByLabelText("Folder"), "DATA");
  await userEvent.type(screen.getByLabelText("File in DATA"), "sub/payroll.csv");
  expect(await screen.findByText("2 columns: EmployeeId, Dept")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Load A" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/load")).toBe(true));
  const sent = JSON.parse(calls.find(([u]) => u === "/api/sources/A/load")![1]!.body as string);
  expect(sent).toMatchObject({ how: "path", folder: "DATA", file: "sub/payroll.csv", name: "Left", delimiter: ",", header: true, snapshot: true });
  expect(await screen.findByText(/You gave 3 names/)).toBeInTheDocument();
  expect(await screen.findByText("payroll.csv")).toBeInTheDocument();        // the foot: what was read
  expect(screen.getByText("· 2,985 rows × 2 columns")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/^Loaded · \d/);   // timed by the page
});

test("Add to filter writes the server's clause into the WHERE box", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources/A/schema") return json({ label: "hr.csv", kind: "csv", columns: [{ name: "department", type: "VARCHAR" }], error: "" });
    if (url === "/api/sources/quick-clause") return json({ where: "\"department\" ILIKE '%Fin%'" });
    return json(body({ sides: { A: view("A", { staged: "hr.csv" }), B: view("B"), P: view("P") } }));
  }));
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: /^Rows to read: all/ }));
  await userEvent.selectOptions(await screen.findByLabelText("Condition"), "contains");
  await userEvent.type(screen.getByLabelText("Value"), "Fin");
  await userEvent.click(screen.getByRole("button", { name: "Add to filter" }));
  await waitFor(() => expect(screen.getByLabelText("Filter (WHERE)")).toHaveValue("\"department\" ILIKE '%Fin%'"));
});

test("the names: the box wins, and two sides of one name are told apart", () => {
  const db = view("A", { loaded: true, name: "SAMPLE", is_database: true, conn: "SAMPLE" });
  expect(sideName("A", "Left", db)).toBe("SAMPLE");
  expect(sideName("A", " HR ", db)).toBe("HR");
  expect(sideLabels("SAMPLE", "SAMPLE")).toEqual(["A · SAMPLE", "B · SAMPLE"]);
  expect(nameHint("A", "Left", db, "SAMPLE", "SAMPLE")).toMatch(/^:orange\[Both sides are called SAMPLE\]/);
  expect(nameHint("A", "Left", view("A", { name: "Left" }), "Left", "Right")).toBe("Tip: name this side - it names the output files");
});

test("a folder deleted after it was picked falls back to Any path with a sentence", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/sources/folders") return json([]);
    if (url.endsWith("/schema")) return json({ label: "", kind: "csv", columns: [], error: "" });
    return json(body());
  }));
  setForm("A", { how: "path", folder: "DATA", file: "hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.type(await screen.findByLabelText("Path to CSV or JSON"), "D:/x/hr.csv");
  expect(screen.getByText(/The folder DATA is gone/)).toBeInTheDocument();
  expect(getForm("A")).toMatchObject({ folder: "", file: "", path: "D:/x/hr.csv" });
});
