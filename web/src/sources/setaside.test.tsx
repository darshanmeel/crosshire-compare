import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { SideCard } from "./SideCard";
import { setForm } from "./formStore";
import { body, json, META, mount, view, type Call } from "./testkit";

const INFO = { rows: 12, kept: 12, fields: 50, said: "12 rows set aside - 7 with 49 fields, 5 with 51 (the header has 50)",
               by: [{ fields: 49, rows: 7 }, { fields: 51, rows: 5 }] };
const LINES = Array.from({ length: 25 }, (_, i) => ({ line: i + 3, fields: i % 2 ? 51 : 49, raw: `row ${i + 3},a,b` }));

function stub(loadedSide = view("A", { loaded: true, name: "HR", label: "hr.csv", rows: 3000, columns: ["id", "a"],
                                       bad_rows: "set_aside", set_aside: INFO })) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources/A/schema") return json({ label: "hr.csv", kind: "csv", columns: [{ name: "id", type: "VARCHAR" }, { name: "a", type: "VARCHAR" }], error: "" });
    if (url.startsWith("/api/sources/A/set-aside?")) return json({ ...INFO, page: 1, size: 25, lines: LINES.slice(0, 2) });
    if (url === "/api/sources/folders") return json([]);
    if (url.startsWith("/api/sources/A/first-fields?")) return json({ fields: 50, width: 50, columns: ["id", "a"], sampled: 12, by: INFO.by, guessed: 3, unplaced: 0,
      rows: [{ line: 2, fields: 51, values: ["7", "kept value"], left_out: "33" }] });
    if (url === "/api/sources/A/load") return json({ side: loadedSide, warnings: [] });
    return json(body({ sides: { A: loadedSide, B: view("B"), P: view("P") } }));
  }));
  return calls;
}

test("split numbers can be joined instead: the preview shows the rows joined and what was a choice, Load sends it", async () => {
  const calls = stub();
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Join the split numbers instead" }));
  await within(await screen.findByRole("table", { name: "Rows as they will read" })).findByText("kept value");
  expect(screen.queryByRole("columnheader", { name: "Left out" })).not.toBeInTheDocument();
  expect(screen.getByText(/3 of these rows had more than one such pair/)).toBeInTheDocument();
  expect(calls.some(([u]) => u === "/api/sources/A/first-fields?n=0&join=true")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: /^Load A/ }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/load")).toBe(true));
  expect(JSON.parse(calls.find(([u]) => u === "/api/sources/A/load")![1]!.body as string)).toMatchObject({ bad_rows: "join_numbers" });
});

test("rows set aside can be read as their first fields instead: the preview shows them cut, Load sends it", async () => {
  const calls = stub();
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Use the first 50 fields of each row instead" }));
  expect(await screen.findByLabelText("Fields to use from each row")).toHaveValue(50);
  const t = await screen.findByRole("table", { name: "Rows as they will read" });
  expect(within(t).getByText("kept value")).toBeInTheDocument();
  expect(within(t).getByRole("columnheader", { name: "Left out" })).toBeInTheDocument();
  expect(within(t).getByText("33")).toBeInTheDocument();
  expect(calls.some(([u]) => u === "/api/sources/A/first-fields?n=50")).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: /^Load A/ }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/load")).toBe(true));
  expect(JSON.parse(calls.find(([u]) => u === "/api/sources/A/load")![1]!.body as string)).toMatchObject({ bad_rows: "first:50" });
});

test("a CSV's quote and its rows of the wrong width are chosen under Advanced and sent with Load", async () => {
  const calls = stub(view("A"));
  setForm("A", { how: "path", path: "D:/x/hr.csv" });
  mount(<SideCard tag="A" meta={META} />);
  await userEvent.click(await screen.findByRole("button", { name: "Advanced" }));
  expect(screen.getByLabelText("Rows with too few or too many fields")).toHaveValue("set_aside");   // by default
  await userEvent.selectOptions(screen.getByLabelText("Rows with too few or too many fields"), "set_aside");
  await userEvent.selectOptions(screen.getByLabelText("Quote character"), "'");
  await userEvent.click(await screen.findByRole("button", { name: "Load A" }));
  await waitFor(() => expect(calls.some(([u]) => u === "/api/sources/A/load")).toBe(true));
  const sent = JSON.parse(calls.find(([u]) => u === "/api/sources/A/load")![1]!.body as string);
  expect(sent).toMatchObject({ quote: "'", bad_rows: "set_aside" });
});

test("the rows set aside: the line under the file, and the rows a page at a time with a download", async () => {
  const calls = stub();
  mount(<SideCard tag="A" meta={META} />);
  expect(await screen.findByText("12 rows set aside - 7 with 49 fields, 5 with 51 (the header has 50)")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download them (CSV)" })).toHaveAttribute("href", "/api/sources/A/set-aside.csv");
  await userEvent.click(screen.getByRole("button", { name: "Show the rows set aside" }));
  const table = await screen.findByRole("table", { name: "Rows set aside" });
  expect(await screen.findByText("row 3,a,b")).toBeInTheDocument();
  expect(table.querySelectorAll("tbody tr")).toHaveLength(2);
  expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
  expect(calls.some(([u]) => u === "/api/sources/A/set-aside?page=1&size=25")).toBe(true);
});
