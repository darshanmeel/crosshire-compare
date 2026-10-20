import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import App from "../App";
import { marks } from "../ui/marks";
import { Welcome } from "./Welcome";
import type { Meta } from "../api/client";
import { compareState } from "../setup/testkit";
import { body } from "../sources/testkit";

const META = { app_name: "CrossHire Compare", tagline: "Tables, side by side", theme: "aurora", kinds: {}, form: {}, filepick: false };
const LOG = { entries: [{ id: "1", at: "10:00:00", kind: "Compare", label: "Compared in 1.2s", state: "done", seconds: 1.2, lines: ["Reading A…"], page: "Compare" }], last: {} };

const SOURCES = body();
const COMPARE = compareState({ gate: "load", names: ["Left", "Right"], sig: "" });

function mockFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const body = url.endsWith("/api/meta") ? META : url.endsWith("/api/log") ? (init?.method === "DELETE" ? { entries: [], last: {} } : LOG)
      : url.endsWith("/api/connections") ? [] : url.endsWith("/api/sources") ? SOURCES : url.endsWith("/api/setup") ? { ready: false, names: ["Left", "Right"] }
      : url.endsWith("/api/compare") ? COMPARE : { id: "w" };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function mount() {
  render(<QueryClientProvider client={new QueryClient()}><App /></QueryClientProvider>);
}

test("the header shows the brand, the page switch, Connections and the Log count", async () => {
  vi.stubGlobal("fetch", mockFetch());
  mount();
  expect(await screen.findByText("Compare", { selector: "em" })).toBeInTheDocument();
  const pages = screen.getByRole("radiogroup", { name: "Page" });
  expect(within(pages).getByRole("radio", { name: "Compare" })).toBeChecked();
  expect(await screen.findByRole("button", { name: /^Log\s*1$/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Connections" })).toBeInTheDocument();   // none saved: no "0" badge
});

test("the rail's Auto keeps its old name and waits for both sides", async () => {
  vi.stubGlobal("fetch", mockFetch());
  mount();
  const auto = await screen.findByRole("button", { name: "Figure it all out and compare" });
  expect(auto).toBeDisabled();
  expect(screen.getByRole("navigation", { name: "Steps" })).toHaveTextContent("nothing loaded yet");
});

test("the switch moves to Profiling and the hash follows", async () => {
  vi.stubGlobal("fetch", mockFetch());
  mount();
  await userEvent.click(await screen.findByRole("radio", { name: "Profiling" }));
  expect(location.hash).toBe("#profiling");
  expect(await screen.findByRole("button", { name: "Profile" })).toBeDisabled();
});

test("the Dark toggle flips the page's mode and keeps it", async () => {
  vi.stubGlobal("fetch", mockFetch());
  document.documentElement.setAttribute("data-fs-mode", "light");
  mount();
  const dark = await screen.findByRole("button", { name: "Dark" });
  expect(dark).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(dark);
  expect(dark).toHaveAttribute("aria-pressed", "true");
  expect(document.documentElement.getAttribute("data-fs-mode")).toBe("dark");
  expect(localStorage.getItem("fs-mode")).toBe("dark");
});

test("marks turns the Streamlit markup into spans", () => {
  render(<p>{marks(":green[**ok**] and `x` and :red[bad]")}</p>);
  expect(screen.getByText("ok").closest(".pos")).not.toBeNull();
  expect(screen.getByText("x").tagName).toBe("CODE");
  expect(screen.getByText("bad")).toHaveClass("neg");
});

test("Try the HR vs Payroll example loads both sample files by path", async () => {
  const fetch = vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  const meta = { ...META, examples: { A: "/ex/hr_employees.csv", B: "/ex/payroll_employees.csv" } } as unknown as Meta;
  render(<QueryClientProvider client={new QueryClient()}><Welcome page="Compare" meta={meta} setPage={() => {}} /></QueryClientProvider>);
  await userEvent.click(screen.getByRole("button", { name: "Try the HR vs Payroll example" }));
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  const sent = fetch.mock.calls.map(([url, init]: unknown[]) => [url, JSON.parse((init as RequestInit).body as string)]);
  expect(sent).toEqual([
    ["/api/sources/A/load", expect.objectContaining({ how: "path", path: "/ex/hr_employees.csv", name: "HR" })],
    ["/api/sources/B/load", expect.objectContaining({ how: "path", path: "/ex/payroll_employees.csv", name: "Payroll" })],
  ]);
  expect(fetch.mock.calls.every(([, init]: unknown[]) => (init as RequestInit).method === "POST")).toBe(true);
});
