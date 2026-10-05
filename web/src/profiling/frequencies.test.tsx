// web/src/profiling/frequencies.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import { resetView } from "../shell/view";
import { json, mount, type Call } from "../sources/testkit";
import { resetPicks } from "./picks";
import { ProfileView } from "./ProfileView";
import { resetKept } from "./SaveRow";
import { defaults, profile, profiling, T } from "./testkit";

beforeEach(() => { resetPicks(); resetKept(); resetView(); });

const freq = (column: string) => ({ column, title: "",
  top: T(["Value", "Count", "%"], [[`${column}-top`, 2, 66.67], [`${column}-2nd`, 1, 33.33]]),
  bottom: T(["Value", "Count", "%"], [[`${column}-low`, 1, 33.33]]) });

function stub(calls: Call[], save?: (b: { folder: string }) => Response) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    if (url.startsWith("/api/profiling/freq?column=")) return json(freq(decodeURIComponent(url.split("=")[1])));
    if (url.startsWith("/api/profiling/defaults?")) return json(defaults());
    if (url === "/api/profiling/save") return save!(JSON.parse(init!.body as string));
    return json({});
  }));
}

test("Value frequencies starts on a column with a handful of values; the picker asks for another by name", async () => {
  const calls: Call[] = [];
  stub(calls);
  mount(<ProfileView view={profiling()} name="HR" />);
  const picker = screen.getByLabelText("Value frequencies of");
  expect(picker).toHaveValue("department");                         // 8 distinct: the telling one, not the key
  expect(await screen.findByText("department-top")).toBeInTheDocument();
  expect(screen.getByText("8 distinct · all 3,000 rows")).toBeInTheDocument();
  await userEvent.selectOptions(picker, "a/b %");
  expect(await screen.findByText("a/b %-top")).toBeInTheDocument();
  expect(calls.map(([u]) => u)).toContain("/api/profiling/freq?column=a%2Fb%20%25");
  expect(screen.getByRole("button", { name: "Most and least frequent of a/b %" })).toBeInTheDocument();
});

test("the pick survives the page going away, and a column the new profile lacks drops out", async () => {
  stub([]);
  mount(<ProfileView view={profiling()} name="HR" />);
  await userEvent.selectOptions(screen.getByLabelText("Value frequencies of"), "emp_id");
  expect(await screen.findByText("emp_id-top")).toBeInTheDocument();
  cleanup();
  mount(<ProfileView view={profiling()} name="HR" />);
  expect(await screen.findByText("emp_id-top")).toBeInTheDocument();
  cleanup();
  const narrow = profile({ freq: { columns: ["department"], picked: [], titles: { department: "**department** - text" } } });
  mount(<ProfileView view={profiling({ profile: narrow, made: "20261004-130000" })} name="HR" />);
  expect(await screen.findByText("department-top")).toBeInTheDocument();
  expect(screen.queryByText("emp_id-top")).toBeNull();
});

test("Download profile.csv is a link; Save to folder writes the six files or says why not", async () => {
  const calls: Call[] = [];
  let n = 0;
  stub(calls, (b) => (n++ === 0
    ? json({ detail: "Saves must stay under D:\\out" }, 400)
    : json({ text: `Saved 6 files to \`${b.folder}\`: HR__profile.csv, HR__keys.csv`, folder: b.folder })));
  mount(<ProfileView view={profiling()} name="HR" />);
  const link = await screen.findByRole("link", { name: "Download profile.csv" });
  expect(link).toHaveAttribute("href", "/api/profiling/profile.csv?name=HR");
  await waitFor(() => expect(link).toHaveAttribute("download", "HR__profile.csv"));
  const box = await screen.findByLabelText("Save to folder");
  expect(box).toHaveValue("D:/out/HR__20261004-120000");
  await userEvent.click(screen.getByRole("button", { name: "Save to folder" }));
  expect(await screen.findByText("Saves must stay under D:\\out")).toHaveClass("note", "error");
  expect(box).toHaveValue("D:/out/HR__20261004-120000");                     // what was typed stays
  await userEvent.clear(box);
  await userEvent.type(box, "D:/out/mine");
  await userEvent.click(screen.getByRole("button", { name: "Save to folder" }));
  expect(await screen.findByText(/Saved 6 files to/)).toHaveClass("note", "success");
  const sent = calls.filter(([u]) => u === "/api/profiling/save").map(([, i]) => JSON.parse(i!.body as string));
  expect(sent).toEqual([{ name: "HR", folder: "D:/out/HR__20261004-120000" }, { name: "HR", folder: "D:/out/mine" }]);
});

test("a Name edit moves the folder box with it, unless the user typed in the box; the profile stays drawn", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.startsWith("/api/profiling/defaults?")) {
      const n = decodeURIComponent(url.split("=")[1]);
      return json(defaults({ csv_name: `${n}__profile.csv`, save_folder: `D:/out/${n}__20261004-120000` }));
    }
    if (url.startsWith("/api/profiling/freq?column=")) return json(freq("emp_id"));
    return json({});
  }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const draw = (name: string) => <QueryClientProvider client={qc}><ProfileView view={profiling()} name={name} /></QueryClientProvider>;
  const r = render(draw("HR"));
  expect(await screen.findByLabelText("Save to folder")).toHaveValue("D:/out/HR__20261004-120000");
  r.rerender(draw("Staff"));
  expect(screen.getByRole("link", { name: "Download profile.csv" })).toBeInTheDocument();   // not blanked while asking
  await waitFor(() => expect(screen.getByLabelText("Save to folder")).toHaveValue("D:/out/Staff__20261004-120000"));
  await userEvent.clear(screen.getByLabelText("Save to folder"));
  await userEvent.type(screen.getByLabelText("Save to folder"), "D:/mine");
  r.rerender(draw("Team"));
  await waitFor(() => expect(qc.getQueryData(["profiling-defaults", "Team", "20261004-120000"])).toBeTruthy());
  expect(screen.getByLabelText("Save to folder")).toHaveValue("D:/mine");
});
