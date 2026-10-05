import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import App from "../App";
import { marks } from "../ui/marks";

const META = { app_name: "CrossHire Compare", tagline: "Tables, side by side", theme: "aurora", kinds: {}, form: {}, filepick: false };
const LOG = { entries: [{ id: "1", at: "10:00:00", kind: "Compare", label: "Compared in 1.2s", state: "done", seconds: 1.2, lines: ["Reading A…"], page: "Compare" }], last: {} };

const side = (tag: string) => ({ tag, loaded: false, name: "", label: "", origin: "", kind: "", rows: null, columns: [], cut: "", is_database: false,
  conn: "", fetched_at: "", snapshot: true, caption: "", notes: [], staged: "", fetched: null });
const SOURCES = { sides: { A: side("A"), B: side("B"), P: side("P") }, defaults: {}, quick_ops: [], name_help: { side: "", table: "" }, upload_types: [], config: null };
const COMPARE = { gate: "load", names: ["Left", "Right"], strip: null, settings: { display_rows: 1000, auto_rerun: false, out_fmt: "csv", auto_profile: false },
  filter_error: "", sig: "", stale: false, busy: false, said: [], run: null };

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
  expect(screen.getByRole("button", { name: /Connections/ })).toBeInTheDocument();
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

test("Light or dark flips the page's mode and keeps it", async () => {
  vi.stubGlobal("fetch", mockFetch());
  document.documentElement.setAttribute("data-fs-mode", "light");
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Light or dark" }));
  expect(document.documentElement.getAttribute("data-fs-mode")).toBe("dark");
  expect(localStorage.getItem("fs-mode")).toBe("dark");
});

test("marks turns the Streamlit markup into spans", () => {
  render(<p>{marks(":green[**ok**] and `x` and :red[bad]")}</p>);
  expect(screen.getByText("ok").closest(".pos")).not.toBeNull();
  expect(screen.getByText("x").tagName).toBe("CODE");
  expect(screen.getByText("bad")).toHaveClass("neg");
});
