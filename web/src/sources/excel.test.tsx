// web/src/sources/excel.test.tsx - where the data starts: an Excel file's sheet, range, header and
// first empty row; a CSV's lines to skip at the top; a database side shows neither.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { getForm, setForm } from "./formStore";
import { SideCard } from "./SideCard";
import { ConfigSync } from "./ConfigPanel";
import { ProfileSource } from "./SourcesSection";
import { body, json, META, mount, view, type Call } from "./testkit";

const COLS = [{ name: "emp_id", type: "VARCHAR" }, { name: "first_name", type: "VARCHAR" }];
const XL = { label: "hr.xlsx", kind: "excel", columns: COLS, error: "", sheets: ["Cover", "Staff", "Notes"], sheet: "Cover" };
const CSV = { label: "hr.csv", kind: "csv", columns: COLS, error: "", sheets: [], sheet: "" };
const sent = (calls: Call[], url: string) => calls.filter(([u]) => u === url).map(([, i]) => JSON.parse(i!.body as string));

test("an Excel file shows Sheet, Table starts at, the header and Stop at the first empty row; what is picked goes to /schema and /load", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/A/schema") return json(XL);
    if (url === "/api/sources/A/load")
      return json({ side: view("A", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", rows: 3000, columns: ["emp_id", "first_name"],
                                      sheet: "Staff", cell_range: "B4", read_from: "sheet Staff · B4" }), warnings: [] });
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("A", { how: "path", path: "D:/x/hr.xlsx" });
  mount(<SideCard tag="A" meta={META} />);
  const A = screen.getByRole("region", { name: "File A" });
  const sheet = await within(A).findByRole("combobox", { name: "Sheet" });
  await waitFor(() => expect(sheet).toHaveValue("Cover"));                            // the first sheet when none is picked
  expect(within(sheet).getAllByRole("option").map((o) => o.textContent)).toEqual(["Cover", "Staff", "Notes"]);
  expect(within(A).queryByLabelText("Delimiter")).toBeNull();
  expect(within(A).queryByLabelText("Skip lines at top")).toBeNull();
  const range = within(A).getByLabelText("Table starts at");
  expect(range).toHaveAttribute("placeholder", "A1 or B4:H500");
  expect(within(A).getByLabelText("First row is a header")).toBeChecked();
  const stop = within(A).getByRole("checkbox", { name: "Stop at the first empty row" });
  expect(stop).not.toBeChecked();

  await userEvent.selectOptions(sheet, "Staff");
  await userEvent.type(range, "B4");
  await userEvent.click(stop);
  expect(getForm("A")).toMatchObject({ sheet: "Staff", cell_range: "B4", stop_at_blank: true });
  await waitFor(() => expect(sent(calls, "/api/sources/A/schema").some((b) => b.sheet === "Staff" && b.cell_range === "B4")).toBe(true));
  await userEvent.click(within(A).getByRole("button", { name: "Load A" }));
  await waitFor(() => expect(sent(calls, "/api/sources/A/load")).toHaveLength(1));
  expect(sent(calls, "/api/sources/A/load")[0]).toMatchObject({ how: "path", path: "D:/x/hr.xlsx", sheet: "Staff", cell_range: "B4",
                                                               stop_at_blank: true, header: true });
});

test("a loaded Excel side says its sheet and range in the loaded line, and the first sheet by name when none was picked", async () => {
  const XV = view("A", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", rows: 3000, columns: ["emp_id", "first_name"],
                         sheet: "", cell_range: "B4:H500", read_from: "B4:H500" });
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/sources/A/schema" ? json(XL) : url === "/api/sources/folders" ? json([])
      : json(body({ sides: { A: XV, B: view("B"), P: view("P") } }))));
  setForm("A", { how: "path", path: "D:/x/hr.xlsx", cell_range: "B4:H500", name: "HR" });
  mount(<SideCard tag="A" meta={META} />);
  expect(await screen.findByText("· 3,000 rows × 2 columns · sheet Cover · B4:H500")).toBeInTheDocument();
});

test("the Profile page's compact card keeps the Excel boxes under Advanced", async () => {
  const P = view("P", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", rows: 3000, columns: ["emp_id", "first_name"],
                        sheet: "Staff", read_from: "sheet Staff" });
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/sources/P/schema" ? json(XL) : url === "/api/sources/folders" ? json([])
      : json(body({ sides: { A: view("A"), B: view("B"), P } }))));
  setForm("P", { how: "path", path: "D:/x/hr.xlsx", sheet: "Staff", name: "HR" });
  mount(<ProfileSource meta={META} />);
  await waitFor(() => expect(screen.getByRole("region", { name: "File" })).toHaveClass("compact"));
  const card = screen.getByRole("region", { name: "File" });
  expect(await within(card).findByText("· 3,000 rows × 2 columns · sheet Staff")).toBeInTheDocument();
  expect(within(card).getByText("first row is a header")).toBeInTheDocument();
  expect(within(card).queryByRole("combobox", { name: "Sheet" })).toBeNull();
  await userEvent.click(within(card).getByRole("button", { name: "Advanced" }));
  expect(within(card).getByRole("combobox", { name: "Sheet" })).toHaveValue("Staff");
  expect(within(card).getByLabelText("Table starts at")).toBeInTheDocument();
});

test("a CSV shows Skip lines at top beside the delimiter, and the number goes with Load", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/B/schema") return json(CSV);
    if (url === "/api/sources/B/load") return json({ side: view("B", { loaded: true, label: "hr.csv", rows: 3000, columns: ["emp_id", "first_name"] }), warnings: [] });
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("B", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="B" meta={META} />);
  const B = screen.getByRole("region", { name: "File B" });
  const skip = await within(B).findByLabelText("Skip lines at top");
  expect(skip).toHaveValue(0);
  expect(skip).toHaveAttribute("min", "0");
  expect(within(B).getByLabelText("Delimiter")).toBeInTheDocument();
  expect(within(B).queryByRole("combobox", { name: "Sheet" })).toBeNull();
  expect(within(B).queryByLabelText("Table starts at")).toBeNull();
  await userEvent.clear(skip);
  await userEvent.type(skip, "2");
  expect(getForm("B").skip_rows).toBe(2);
  await userEvent.click(await within(B).findByRole("button", { name: "Load B" }));
  await waitFor(() => expect(sent(calls, "/api/sources/B/load")).toHaveLength(1));
  expect(sent(calls, "/api/sources/B/load")[0]).toMatchObject({ path: "D:/x/hr.csv", skip_rows: 2, delimiter: "," });
});

test("a database side shows neither the CSV nor the Excel boxes", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/connections") return json([]);
    if (url === "/api/sources/A/db") return json({ sql: "", error: "", warning: "", held: null, password: "none" });
    if (url === "/api/sources/A/schema") return json({ label: "PG.parquet", kind: "parquet", columns: [], error: "" });
    return json(body());
  }));
  setForm("A", { how: "database" });
  mount(<SideCard tag="A" meta={META} />);
  const A = screen.getByRole("region", { name: "File A" });
  await userEvent.click(within(A).getByRole("button", { name: "Advanced" }));
  for (const name of ["Delimiter", "Skip lines at top", "Table starts at", "First row is a header"])
    expect(within(A).queryByLabelText(name)).toBeNull();
  expect(within(A).queryByRole("combobox", { name: "Sheet" })).toBeNull();
});

test("the upload accepts Excel files and says so", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(body({ upload_types: ["csv", "json", "parquet", "xlsx", "xlsm", "xls"] }))));
  mount(<SideCard tag="A" meta={META} />);
  const input = screen.getByLabelText("CSV, JSON, Parquet or Excel file");
  await waitFor(() => expect(input).toHaveAttribute("accept", ".csv,.json,.parquet,.xlsx,.xlsm,.xls"));
  expect(screen.getByText("Drop a CSV, JSON, Parquet or Excel file")).toBeInTheDocument();
});

test("picking another file clears the sheet, range and lines to skip, so the old file's read is not applied to it", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/A/schema") return json(XL);
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("A", { how: "path", path: "D:/x/a.xlsx", sheet: "Staff", cell_range: "B4", stop_at_blank: true, skip_rows: 2 });
  mount(<SideCard tag="A" meta={META} />);
  const A = screen.getByRole("region", { name: "File A" });
  expect(await within(A).findByLabelText("Table starts at")).toHaveValue("B4");
  const path = within(A).getByLabelText("Path to CSV or JSON");
  await userEvent.clear(path);
  await userEvent.type(path, "D:/x/b.xlsx");
  expect(getForm("A")).toMatchObject({ path: "D:/x/b.xlsx", sheet: "", cell_range: "", stop_at_blank: false, skip_rows: 0 });
  await waitFor(() => expect(sent(calls, "/api/sources/A/schema").at(-1)).toMatchObject({ path: "D:/x/b.xlsx", cell_range: "", sheet: "" }));
});

test("a hidden sheet is marked in the Sheet list", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/sources/A/schema" ? json({ ...XL, sheets: ["Lookup", "Data"], hidden: ["Lookup"], sheet: "Data" })
      : url === "/api/sources/folders" ? json([]) : json(body())));
  setForm("A", { how: "path", path: "D:/x/h.xlsx" });
  mount(<SideCard tag="A" meta={META} />);
  const sheet = await within(screen.getByRole("region", { name: "File A" })).findByRole("combobox", { name: "Sheet" });
  await waitFor(() => expect(within(sheet).getAllByRole("option").map((o) => o.textContent)).toEqual(["Lookup (hidden)", "Data"]));
  expect(sheet).toHaveValue("Data");
});

test("another sheet picked lists that sheet's columns", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/sources/A/schema") {
      const b = JSON.parse(init!.body as string);
      return json(b.sheet === "Staff" ? { ...XL, sheet: "Staff", columns: [{ name: "id", type: "VARCHAR" }, { name: "dept", type: "VARCHAR" }, { name: "pay", type: "VARCHAR" }] } : XL);
    }
    if (url === "/api/sources/folders") return json([]);
    return json(body());
  }));
  setForm("A", { how: "path", path: "D:/x/hr.xlsx" });
  mount(<SideCard tag="A" meta={META} />);
  const A = screen.getByRole("region", { name: "File A" });
  expect(await within(A).findByText("2 columns: emp_id, first_name")).toBeInTheDocument();
  await userEvent.selectOptions(await within(A).findByRole("combobox", { name: "Sheet" }), "Staff");
  expect(await within(A).findByText("3 columns: id, dept, pay")).toBeInTheDocument();
});

test("a Run from config fills the sheet, range, stop and lines to skip into the forms", async () => {
  const config = { n: 3, said: [], boxes: { settings: {},
    A: { name: "HR", how: "path", path: "D:/x/hr.xlsx", sheet: "Staff", cell_range: "B4", stop_at_blank: true, skip_rows: 0 },
    B: { name: "PR", how: "path", path: "D:/x/pr.csv", sheet: "", cell_range: "", stop_at_blank: false, skip_rows: 2 } } };
  vi.stubGlobal("fetch", vi.fn(async () => json(body({ config } as never))));
  mount(<ConfigSync />);
  await waitFor(() => expect(getForm("A")).toMatchObject({ sheet: "Staff", cell_range: "B4", stop_at_blank: true }));
  expect(getForm("B")).toMatchObject({ skip_rows: 2, sheet: "" });
});

test("a page reload seeds the form from the Excel side the server holds", async () => {
  const A = view("A", { loaded: true, name: "HR", label: "hr.xlsx", kind: "excel", rows: 3000, columns: ["emp_id"],
                        sheet: "Staff", cell_range: "B4", stop_at_blank: true, skip_rows: 0 });
  vi.stubGlobal("fetch", vi.fn(async () => json(body({ sides: { A, B: view("B"), P: view("P") } }))));
  mount(<ConfigSync />);
  await waitFor(() => expect(getForm("A")).toMatchObject({ name: "HR", how: "path", sheet: "Staff", cell_range: "B4", stop_at_blank: true }));
});
