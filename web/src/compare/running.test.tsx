// web/src/compare/running.test.tsx - the running panel (SPEC §07), the Compare bar and Re-run on every change.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import type { LogEntry } from "../api/client";
import { setup } from "../setup/testkit";
import { resetForms } from "../sources/formStore";
import { body, json, mount, type Call } from "../sources/testkit";
import { AutoRerun } from "./AutoRerun";
import { CompareBar, NOTHING_PAIRED } from "./CompareBar";
import { RunningPanel } from "./RunningPanel";
import type { CompareState, RunView } from "./types";

beforeEach(() => resetForms());

const RUN: RunView = {
  id: "r1", at: "10:00:00", pair: "HR_compare_PR", mode: "key", names: ["HR", "PR"], keys: ["emp_id"],
  columns: ["salary"], matched: 2960, diff_rows: 12, stale: false,
  verdict: { tone: "warn", word: "Small differences", when: "1.2s at 10:00:00", segments: [] },
};

function state(over: Partial<CompareState> = {}): CompareState {
  return {
    gate: "", names: ["HR", "PR"], filter_error: "", sig: "s1", stale: false, busy: false, said: [], run: null,
    strip: { cells: { Files: "", Columns: "", Key: "", Compare: "", Result: "" }, tones: {} },
    settings: { display_rows: 1000, auto_rerun: false, out_fmt: "csv", auto_profile: false }, ...over,
  };
}

const entry = (over: Partial<LogEntry> = {}): LogEntry => ({
  id: "e1", at: "10:00:00", kind: "Auto", label: "Auto - figuring it all out…", state: "running", seconds: null,
  lines: [], page: "Compare", ...over,
});

type Handler = (url: string, init?: RequestInit) => unknown;
type Reply = { status: number; body: unknown };

function mock(routes: Record<string, Handler>, calls: Call[] = []) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    const hit = Object.keys(routes).find((k) => url === k || url.startsWith(k + "?"));
    if (hit) {
      const r = routes[hit](url, init);
      if (r && typeof r === "object" && "status" in (r as Reply)) return json((r as Reply).body, (r as Reply).status);
      return json(r);
    }
    if (url === "/api/sources") return json(body());
    if (url === "/api/log") return json({ entries: [], last: {} });
    if (url === "/api/setup") return json(setup());
    return json({ detail: "not here" }, 404);
  });
}

const posts = (calls: Call[], url: string) => calls.filter(([u, i]) => u === url && i?.method === "POST");

// ---- RunningPanel

test("while Auto runs, the panel lists each reported line as done and the newest as running", async () => {
  const lines = ["Pairing columns by name…", "Pairing 2 × 2 leftover columns by their values…"];
  vi.stubGlobal("fetch", mock({
    "/api/compare": () => state({ busy: true }),
    "/api/log": () => ({ entries: [entry({ lines })], last: {} }),
  }));
  mount(<RunningPanel />);
  const panel = await screen.findByRole("region", { name: "Progress" });
  expect(within(panel).getByRole("heading", { name: "Working it out…" })).toBeInTheDocument();
  expect(within(panel).getByRole("status")).toHaveTextContent(lines[1]);
  expect(within(panel).getByText(/step 2 ·/)).toBeInTheDocument();
  expect(within(panel).queryByText(/ of /)).toBeNull();                  // the job does not say how many steps
  const items = within(panel).getAllByRole("listitem");
  expect(items).toHaveLength(2);                                          // no invented todo steps
  expect(items[0]).toHaveClass("done");
  expect(items[0]).toHaveTextContent("Done: Pairing columns by name…");
  expect(items[1]).toHaveClass("run");
  expect(items[1]).toHaveTextContent("running");
  expect(panel.querySelector(".progress.indeterminate")).not.toBeNull();
  expect(within(panel).queryByRole("button")).toBeNull();                 // the API has no cancel
});

test("the elapsed time counts up on the page", async () => {
  vi.stubGlobal("fetch", mock({
    "/api/compare": () => state({ busy: true }),
    "/api/log": () => ({ entries: [entry({ id: "tick", kind: "Compare", lines: ["Reading HR…"] })], last: {} }),
  }));
  mount(<RunningPanel />);
  const secs = await screen.findByText(/^\d+\.\ds$/);
  const first = parseFloat(secs.textContent!);
  await waitFor(() => expect(parseFloat(screen.getByText(/^\d+\.\ds$/).textContent!)).toBeGreaterThan(first), { timeout: 1500 });
});

test("before the job says anything, its label stands in for the current line", async () => {
  vi.stubGlobal("fetch", mock({
    "/api/compare": () => state({ busy: true }),
    "/api/log": () => ({ entries: [entry({ kind: "Config", label: "Running config.json…" })], last: {} }),
  }));
  mount(<RunningPanel />);
  const panel = await screen.findByRole("region", { name: "Progress" });
  expect(within(panel).getByRole("status")).toHaveTextContent("Running config.json…");
  expect(within(panel).queryByRole("list")).toBeNull();
  expect(within(panel).queryByText(/step/)).toBeNull();
});

test("the panel is not shown when nothing runs, or only a Key search or Profile runs", async () => {
  vi.stubGlobal("fetch", mock({
    "/api/compare": () => state({ busy: true }),
    "/api/log": () => ({ entries: [entry({ kind: "Key", lines: ["Finding the key…"] })], last: {} }),
  }));
  mount(<RunningPanel />);
  await new Promise((r) => setTimeout(r, 100));
  expect(screen.queryByRole("region", { name: "Progress" })).toBeNull();
});

test("the panel goes once the compare state is no longer busy", async () => {
  vi.stubGlobal("fetch", mock({
    "/api/compare": () => state({ busy: false }),
    "/api/log": () => ({ entries: [entry({ lines: ["x"] })], last: {} }),
  }));
  mount(<RunningPanel />);
  await new Promise((r) => setTimeout(r, 100));
  expect(screen.queryByRole("region", { name: "Progress" })).toBeNull();
});

// ---- CompareBar

test("the Compare bar names both sides, says what it compares, and starts a run", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", mock({
    "/api/compare": (_u, init) => (init?.method === "POST" ? { id: "j1", state: "running" } : state({ run: RUN })),
    "/api/setup": () => setup({ keys: ["emp_id"] }),
  }, calls));
  mount(<CompareBar />);
  const go = await screen.findByRole("button", { name: "Compare HR against PR" });
  expect(await screen.findByText("2 columns on 2,960 paired rows · key emp_id · runs in DuckDB")).toBeInTheDocument();
  await userEvent.click(go);
  await waitFor(() => expect(posts(calls, "/api/compare")).toHaveLength(1));
  const [, init] = posts(calls, "/api/compare")[0];
  expect(init!.body).toBeUndefined();
  expect((init!.headers as Record<string, string>)["X-Compare"]).toBe("1");
});

test("a stale run's row count is not quoted, and with no key it says how rows pair", async () => {
  vi.stubGlobal("fetch", mock({ "/api/compare": () => state({ stale: true, run: { ...RUN, stale: true } }) }));
  mount(<CompareBar />);
  expect(await screen.findByText("2 columns · no key - rows paired by hash · runs in DuckDB")).toBeInTheDocument();
});

test("nothing paired: the button is disabled and says why", async () => {
  vi.stubGlobal("fetch", mock({ "/api/compare": () => state({ gate: "pair" }) }));
  mount(<CompareBar />);
  const go = await screen.findByRole("button", { name: "Compare HR against PR" });
  expect(go).toBeDisabled();
  expect(go).toHaveAccessibleDescription(NOTHING_PAIRED);
});

test("no column ticked: the button is disabled and says to tick Compare", async () => {
  vi.stubGlobal("fetch", mock({ "/api/compare": () => state({ gate: "tick" }) }));
  mount(<CompareBar />);
  const go = await screen.findByRole("button", { name: "Compare HR against PR" });
  expect(go).toBeDisabled();
  expect(go).toHaveAccessibleDescription(/on at least one column in the table/);
});

test("nothing loaded: no bar; while a run is busy the button waits", async () => {
  vi.stubGlobal("fetch", mock({ "/api/compare": () => state({ gate: "load" }) }));
  mount(<CompareBar />);
  await new Promise((r) => setTimeout(r, 100));
  expect(screen.queryByRole("button")).toBeNull();
});

test("busy: the button says Comparing and is disabled", async () => {
  vi.stubGlobal("fetch", mock({ "/api/compare": () => state({ busy: true }) }));
  mount(<CompareBar />);
  expect(await screen.findByRole("button", { name: "Comparing…" })).toBeDisabled();
});

test("a refused press, a filter the engine refused and the engine's notes are shown under the button", async () => {
  vi.stubGlobal("fetch", mock({
    "/api/compare": (_u, init) => (init?.method === "POST" ? { status: 409, body: { detail: "That is running already - wait for it to finish." } }
      : state({ filter_error: "The filter on salary is not a number", said: [{ tone: "warning", text: "Read **2** columns as text" }] })),
  }));
  mount(<CompareBar />);
  expect(await screen.findByText("The filter on salary is not a number")).toHaveClass("note", "error");
  expect(screen.getByText("2")).toBeInTheDocument();                       // the note's markup, as spans
  await userEvent.click(screen.getByRole("button", { name: "Compare HR against PR" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("That is running already - wait for it to finish.");
});

// ---- AutoRerun

test("with Re-run on every change, a stale run is compared again once per change", async () => {
  const calls: Call[] = [];
  let sig = "s1";
  vi.stubGlobal("fetch", mock({
    "/api/compare": (_u, init) => {
      if (init?.method === "POST") {
        if (posts(calls, "/api/compare").length === 1) sig = "s2";     // the table changed after the first run
        return { id: "j", state: "running" };
      }
      return state({ sig, stale: true, run: { ...RUN, stale: true }, settings: { ...state().settings, auto_rerun: true } });
    },
  }, calls));
  mount(<AutoRerun />);
  await waitFor(() => expect(posts(calls, "/api/compare")).toHaveLength(2));
  await new Promise((r) => setTimeout(r, 300));
  expect(posts(calls, "/api/compare")).toHaveLength(2);    // still stale (it keeps failing), but not run again
});

test("Re-run on every change waits while off, busy, gated or the filter is refused", async () => {
  for (const over of [{ settings: { ...state().settings, auto_rerun: false } }, { busy: true }, { gate: "tick" as const },
                      { filter_error: "bad filter" }]) {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", mock({
      "/api/compare": () => state({ stale: true, run: { ...RUN, stale: true }, settings: { ...state().settings, auto_rerun: true }, ...over }),
    }, calls));
    mount(<AutoRerun />);
    await waitFor(() => expect(calls.some(([u]) => u === "/api/compare")).toBe(true));
    await new Promise((r) => setTimeout(r, 100));
    expect(posts(calls, "/api/compare")).toHaveLength(0);
  }
});
