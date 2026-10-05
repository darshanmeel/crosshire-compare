// web/src/results/downloads.test.tsx - the Report (SPEC §11) and Downloads (SPEC §12) tabs.
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import type { RunView } from "../compare/types";
import { getView, resetView } from "../shell/view";
import { json, mount, type Call } from "../sources/testkit";
import type { FilesView } from "./detailApi";
import { DownloadsTab } from "./DownloadsTab";
import { resetPicks } from "./pickStore";
import { ReportTab } from "./ReportTab";

beforeEach(() => { resetPicks(); resetView(); });
afterEach(() => vi.restoreAllMocks());

const RUN: RunView = {
  id: "r1", at: "10:00:00", pair: "X", mode: "key", names: ["HR", "Payroll"], keys: ["emp_id"], columns: ["department"],
  matched: 2960, diff_rows: 12, stale: false, verdict: { tone: "warn", word: "Small differences", when: "1.2s at 10:00:00", segments: [] },
};
const FILES: FilesView = {
  config: { name: "X__config.json", bytes: 2048 }, engine: { name: "X__diff.html", bytes: 4096 }, engine_gone: false,
  report: "X__report.html",
  files: [{ name: "X__cell_diffs.csv", label: "Cell differences", bytes: 1_500_000 },
          { name: "X__left_only.csv", label: "Rows only in HR", bytes: 2_000 },
          { name: "X__summary.json", label: "Settings and result", bytes: 6_800 },
          { name: "X__report.html", label: "Report", bytes: 500_000 },
          { name: "X__diff.html", label: "Engine report", bytes: 4096 }],
  paired: false, zip: null, parquet: false, out_fmt: "csv", save_folder: "D:\\out\\X__r1",
};

function serve(calls: Call[], files: () => FilesView, extra: Record<string, (init?: RequestInit) => unknown> = {}) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url in extra) return json(extra[url](init));
    if (url === "/api/results/r1/files" || url === "/api/results/r2/files") return json(files());
    return json({ detail: "not here" }, 404);
  });
}

test("Downloads lists every file with what it is, the config among them, each a download", async () => {
  vi.stubGlobal("fetch", serve([], () => FILES));
  mount(<DownloadsTab run={RUN} limit={1000} />);
  const list = within(await screen.findByRole("region", { name: "Files in this run" }));
  expect(list.getByRole("link", { name: "X__cell_diffs.csv" })).toHaveAttribute("href", "/api/results/r1/file/X__cell_diffs.csv");
  expect(list.getByRole("link", { name: "X__config.json" })).toHaveAttribute("href", "/api/results/r1/file/X__config.json");
  expect(list.getByText("Every differing cell - key, column, HR value, Payroll value")).toBeInTheDocument();
  expect(list.getByText("Rows with no partner in Payroll, as read")).toBeInTheDocument();
  expect(list.getByText("1.5 MB")).toBeInTheDocument();
  expect(list.getByText("re-runnable · 2 KB")).toBeInTheDocument();
  const names = list.getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
  expect(names.indexOf("Select X__report.html")).toBe(0);                     // the report first
  expect(list.getByRole("checkbox", { name: "Select X__profile.csv" })).toBeDisabled();
  expect(list.getByText("not in this run")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download config" })).toHaveAttribute("href", "/api/results/r1/file/X__config.json");
  expect(screen.getByText(/python -m tablecmp\.run X__config\.json/)).toHaveTextContent("--left <new HR file> --right <new Payroll file> --out results");
});

test("Download selected takes the ticked files, and the count follows the ticks", async () => {
  vi.stubGlobal("fetch", serve([], () => FILES));
  const clicks: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicks.push(this.getAttribute("href")!); });
  mount(<DownloadsTab run={RUN} limit={1000} />);
  const btn = await screen.findByRole("button", { name: "Download selected · 4" });   // report, summary.json, cell diffs, config
  await userEvent.click(screen.getByRole("checkbox", { name: "Select X__summary.json" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Select X__left_only.csv" }));
  expect(btn).toHaveAccessibleName("Download selected · 4");
  await userEvent.click(btn);
  await waitFor(() => expect(clicks).toHaveLength(4));
  expect(clicks.sort()).toEqual(["/api/results/r1/file/X__cell_diffs.csv", "/api/results/r1/file/X__config.json",
                                 "/api/results/r1/file/X__left_only.csv", "/api/results/r1/file/X__report.html"]);
});

test("the paired rows on request, and Everything as one zip writes the zip and hands it over", async () => {
  const calls: Call[] = [];
  let now = FILES;
  vi.stubGlobal("fetch", serve(calls, () => now, {
    "/api/results/r1/paired": () => (now = { ...now, paired: true,
                                             files: [...now.files, { name: "X__paired.csv", label: "Paired rows", bytes: 2_000_000 }] }),
    "/api/results/r1/zip": () => (now = { ...now, zip: { name: "X__r1.zip", bytes: 3_000_000 } }),
  }));
  const clicks: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicks.push(this.getAttribute("href")!); });
  mount(<DownloadsTab run={RUN} limit={1000} />);
  expect(await screen.findByRole("checkbox", { name: "Select X__paired.csv" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Write the paired rows" }));
  expect(await screen.findByRole("link", { name: "X__paired.csv" })).toHaveAttribute("href", "/api/results/r1/file/X__paired.csv");
  expect(screen.queryByRole("button", { name: "Write the paired rows" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Everything as one zip" }));
  expect(await screen.findByRole("link", { name: "Download X__r1.zip · 3.0 MB" })).toHaveAttribute("href", "/api/results/r1/file/X__r1.zip");
  expect(calls.find(([u]) => u === "/api/results/r1/zip")![1]!.method).toBe("POST");
  expect(clicks).toEqual(["/api/results/r1/file/X__r1.zip"]);
});

test("Tables as Parquet is kept as a setting and offers the copies for this run", async () => {
  const calls: Call[] = [];
  let fmt: FilesView["out_fmt"] = "csv";
  vi.stubGlobal("fetch", serve(calls, () => ({ ...FILES, out_fmt: fmt }), {
    "/api/compare/settings": (init) => {
      fmt = JSON.parse(init!.body as string).out_fmt;
      return { display_rows: 1000, auto_rerun: false, out_fmt: fmt, auto_profile: false };
    },
    "/api/results/r1/parquet": () => ({ ...FILES, out_fmt: fmt, parquet: true,
                                        files: [...FILES.files, { name: "X__cell_diffs.parquet", label: "cell_diffs (Parquet)", bytes: 400_000 }] }),
  }));
  mount(<DownloadsTab run={RUN} limit={1000} />);
  const group = await screen.findByRole("radiogroup", { name: "Tables as" });
  await userEvent.click(within(group).getByRole("radio", { name: "Parquet" }));
  await userEvent.click(await screen.findByRole("button", { name: "Write Parquet copies for this run" }));
  expect(await screen.findByRole("link", { name: "X__cell_diffs.parquet" })).toBeInTheDocument();
  expect(screen.getByText("Same as cell_diffs.csv, for DuckDB, pandas or a warehouse")).toBeInTheDocument();
  expect(JSON.parse(calls.find(([u]) => u === "/api/compare/settings")![1]!.body as string)).toEqual({ out_fmt: "parquet" });
});

test("a save goes to the run's folder, keeps what was typed, and a new run starts at its own", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls, () => FILES, {
    "/api/results/r1/save": (init) => ({ tone: "success", files: FILES,
                                         text: `Saved 9 files to \`${JSON.parse(init!.body as string).folder}\`: a, b` }),
  }));
  mount(<DownloadsTab run={RUN} limit={1000} />);
  const box = await screen.findByLabelText("Run folder");
  expect(box).toHaveValue("D:\\out\\X__r1");
  await userEvent.click(screen.getByRole("button", { name: "Save everything to folder" }));
  expect(await screen.findByText("D:\\out\\X__r1", { selector: "code" })).toBeInTheDocument();
  expect(JSON.parse(calls.find(([u]) => u === "/api/results/r1/save")![1]!.body as string)).toEqual({ what: "all", folder: "D:\\out\\X__r1" });
  await userEvent.clear(box);
  await userEvent.type(box, "D:\\kept");
  cleanup();
  mount(<DownloadsTab run={RUN} limit={1000} />);
  expect(await screen.findByLabelText("Run folder")).toHaveValue("D:\\kept");
  await userEvent.click(screen.getByRole("button", { name: "Save config to folder" }));
  expect(JSON.parse(calls.filter(([u]) => u === "/api/results/r1/save").at(-1)![1]!.body as string)).toEqual({ what: "config", folder: "D:\\out\\X__r1" });
  cleanup();
  mount(<DownloadsTab run={{ ...RUN, id: "r2" }} limit={1000} />);
  expect(await screen.findByLabelText("Run folder")).toHaveValue("D:\\out\\X__r1");
});

test("Save mapping goes to the columns, Run from config to its view", async () => {
  vi.stubGlobal("fetch", serve([], () => FILES));
  mount(<DownloadsTab run={RUN} limit={1000} />);
  await userEvent.click(await screen.findByRole("button", { name: "Run from config" }));
  expect(getView().view).toBe("config");
  await userEvent.click(screen.getByRole("button", { name: "Save mapping" }));
  expect(getView()).toMatchObject({ view: "setup", anchor: "columns" });
});

test("the Report tab shows the report in a viewer, with its downloads, its save and its height", async () => {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", serve(calls, () => FILES, {
    "/api/results/r1/save": (init) => ({ tone: "success", files: FILES, text: `Saved the report to \`${JSON.parse(init!.body as string).folder}\`` }),
  }));
  mount(<ReportTab run={RUN} limit={500} />);
  const viewer = await screen.findByTitle("Report");
  expect(viewer).toHaveAttribute("src", "/api/results/r1/report?limit=500");
  expect(viewer).toHaveAttribute("sandbox", "");
  expect(screen.getByRole("link", { name: "Download report" })).toHaveAttribute("href", "/api/results/r1/report?limit=500&download=1");
  expect(await screen.findByRole("link", { name: "Download engine report" })).toHaveAttribute("href", "/api/results/r1/file/X__diff.html");
  expect(screen.getByRole("region", { name: "Report preview" })).toHaveTextContent("X__report.html");
  await userEvent.selectOptions(screen.getByLabelText("Viewer height"), "1200");
  expect(viewer).toHaveAttribute("height", "1200");
  await userEvent.selectOptions(screen.getByLabelText("Viewer height"), "fit");
  expect(viewer).not.toHaveAttribute("height");
  expect(screen.getByLabelText("Run folder")).toHaveValue("D:\\out\\X__r1");
  await userEvent.click(screen.getByRole("button", { name: "Save report to folder" }));
  expect(JSON.parse(calls.find(([u]) => u === "/api/results/r1/save")![1]!.body as string)).toEqual({ what: "report", folder: "D:\\out\\X__r1" });
});

test("the Report tab says when the engine's report is gone", async () => {
  vi.stubGlobal("fetch", serve([], () => ({ ...FILES, engine: null, engine_gone: true })));
  mount(<ReportTab run={RUN} limit={500} />);
  expect(await screen.findByText(/engine's report file is no longer on disk/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download engine report" })).toBeNull();
});

test("a small file says KB, not 0.0 MB", async () => {
  const { size } = await import("./detailApi");
  expect([size(1_500), size(120), size(1_500_000)]).toEqual(["2 KB", "1 KB", "1.5 MB"]);
});
