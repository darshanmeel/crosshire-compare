import { screen, waitFor } from "@testing-library/react";
import { beforeEach, vi } from "vitest";
import { ColumnsSection } from "../columns/ColumnsSection";
import { resetForms, setForm } from "../sources/formStore";
import { body, view } from "../sources/testkit";
import { SetupSync } from "./SetupPage";
import { IDLE, json, mount, setup, type Call } from "./testkit";

beforeEach(() => resetForms());

function stub(s: unknown, loaded = true) {
  const calls: Call[] = [];
  const sides = body({ sides: { A: view("A", { loaded }), B: view("B", { loaded }), P: view("P") } });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url === "/api/sources") return json(sides);
    if (url === "/api/setup" || url === "/api/setup/names") return json(s);
    if (url === "/api/compare") return json(IDLE.compare);
    if (url === "/api/log") return json(IDLE.log);
    return json({ columns: [], rows: [], error: "" });
  }));
  return calls;
}

test("nothing to pair until both sides are loaded", async () => {
  stub({ ready: false, names: ["Left", "Right"] }, false);
  mount(<><SetupSync /><ColumnsSection /></>);
  expect(await screen.findByText("appears once both sides are loaded")).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Column table" })).toBeNull();
});

test("the Name boxes are sent to the server, and the board is headed by them", async () => {
  setForm("A", { name: "HR" });
  setForm("B", { name: "Payroll" });
  const calls = stub(setup({ names: ["HR", "Payroll"] }));
  mount(<><SetupSync /><ColumnsSection /></>);
  await waitFor(() => expect(calls.some(([u, i]) => u === "/api/setup/names" && i?.method === "PUT")).toBe(true));
  expect(JSON.parse(calls.find(([u]) => u === "/api/setup/names")![1]!.body as string)).toEqual({ A: "HR", B: "Payroll" });
  expect(await screen.findByRole("columnheader", { name: "Payroll column" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "Columns" })).toBeInTheDocument();
});

test("with nothing paired the section says to pick a counterpart", async () => {
  stub(setup({ specs: [], pairs: 0, compare: [] }));
  mount(<><SetupSync /><ColumnsSection /></>);
  expect(await screen.findByText("Nothing is paired yet - pick a counterpart for at least one column in the table.")).toBeInTheDocument();
  expect(screen.getByText("0 pairs · 1 only in HR · 1 only in PR")).toBeInTheDocument();
});
