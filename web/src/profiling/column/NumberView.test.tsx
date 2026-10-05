// web/src/profiling/column/NumberView.test.tsx - the number column's page on made-up quantities.
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { json, mount } from "../../sources/testkit";
import { statsOf } from "../frame";
import { profile, T } from "../testkit";
import { NumberView, numberFormText, type NumForm } from "./NumberView";

const OUT = ["Column", "Type", "P1", "P5", "P25", "Median", "P75", "P95", "P99", "Std dev", "Low fence", "High fence",
  "Lowest", "Highest", "Outliers", "Outlier %", "Zeros", "Negatives"];
const STATS = ["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled", "Distinct % of rows",
  "Top value", "Top %", "Min", "Max", "Mean"];

function prof(mean: number) {
  return profile({
    stats: T(STATS, [["qty", "number", 1000, 0, 0, 120, 12, 12, "2000", 5.5, 1, 900000, mean]]),
    outliers: T(OUT, [["qty", "number", 1, 3, 38, 250, 2800, 18000, 20000, 11000.5, -4100, 7000, 1, 900000, 160, 16, 0, 0]]),
  });
}

const FORM: NumForm = {
  column: "qty", filled: 1000, zeros: 0, negatives: 0,
  log_bins: [{ label: "1 - 9", lo: 1, hi: 10, n: 300 }, { label: "10 - 99", lo: 10, hi: 100, n: 400 },
    { label: "100,000 - 900,000", lo: 100000, hi: 900000, n: 300 }],
  before: [{ label: "1-3", n: 700 }, { label: "4-6", n: 300 }], places: { min: 0, max: 0 }, fits: "DECIMAL(6, 0)",
  round_lots: [2000, 5000], lot_step: 1000, top: [{ value: 2000, n: 55 }, { value: 5000, n: 40 }, { value: 7, n: 30 }], once: [11, 13],
};

function stub(skewHist: boolean) {
  const urls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    urls.push(url);
    if (url.startsWith("/api/profiling/numform?column=qty")) return json(FORM);
    if (url.startsWith("/api/profiling/hist?")) return json({ column: "qty", kind: "number", bins: skewHist
      ? [{ lo: 1, hi: 90000, n: 950 }, ...Array.from({ length: 9 }, (_, i) => ({ lo: 90000 * (i + 1), hi: 90000 * (i + 2), n: i < 5 ? 10 : 0 }))]
      : Array.from({ length: 10 }, (_, i) => ({ lo: i * 10, hi: i * 10 + 10, n: 100 })) });
    if (url === "/api/profiling/casts") return json({ columns: [] });
    if (url.startsWith("/api/profiling/parts?column=qty")) return json({ column: "qty", kind: "number", groups: [
      { title: "Digits before the point", total: 1000, rows: [{ label: "1-3", n: 700 }, { label: "4-6", n: 300 }] },
      { title: "Places after the point", total: 1000, rows: [{ label: "0", n: 1000 }] },
      { title: "Before · after", total: 1000, rows: [{ label: "1-3 · 0", n: 700 }, { label: "4-6 · 0", n: 300 }] }] });
    if (url.startsWith("/api/profiling/freq?")) return json({ column: "qty", title: "",
      top: T(["Value", "Count", "%"], [[2000, 55, 5.5]]), bottom: T(["Value", "Count", "%"], [[11, 1, 0.1], [13, 1, 0.1]]) });
    return json({});
  }));
  return urls;
}

afterEach(() => vi.unstubAllGlobals());

function show(mean: number) {
  const p = prof(mean);
  mount(<NumberView p={p} column="qty" made="m1" st={statsOf(p, "qty")!} as="number" />);
}

test("a skewed column: the findings, mean in warn with its ratio, the banner, log bins by default, the form", async () => {
  const urls = stub(true);
  show(22000);
  const found = within(screen.getByRole("list", { name: "Findings for qty" }));
  expect(found.getByText("mean 88× the median")).toBeTruthy();
  expect(found.getByText("16.00% past the IQR fence, all high")).toBeTruthy();
  expect(found.getByText("900,000 · 45× the P99")).toBeTruthy();
  expect(await found.findByText("2 of the top 3 end in 000")).toBeTruthy();
  expect(found.getByText("fits DECIMAL(6,0)")).toBeTruthy();
  expect(found.getByText("No nulls · no zeros · no negatives")).toBeTruthy();
  expect(screen.getByText("88× the median")).toBeTruthy();
  expect(await screen.findByText("Heavily skewed.")).toBeTruthy();
  expect(screen.getByText(/the top 1% runs from 20,000 to 900,000/)).toBeTruthy();
  const bins = within(screen.getByRole("group", { name: "Bins" }));
  expect(bins.getByRole("button", { name: "Log" }).getAttribute("aria-pressed")).toBe("true");
  const table = await screen.findByRole("table", { name: "Bins of qty" });
  expect(within(table).getByText("100,000 - 900,000")).toBeTruthy();
  expect(within(table).getByText("40.00%")).toBeTruthy();
  expect(screen.getByText(/Equal width was tried first/)).toBeTruthy();
  expect(screen.getByText("100,000 +")).toBeTruthy();                   // the last log bin on the axis
  // the form taken apart: digits banded from /parts, whole numbers and the DECIMAL, the combinations, round lots
  expect(screen.getByText("Form · parts")).toBeTruthy();
  expect(within(await screen.findByRole("list", { name: "Digits before the point" })).getByText("1 - 3")).toBeTruthy();
  expect(screen.getByText("0 · every value")).toBeTruthy();
  expect(screen.getByText("DECIMAL(6, 0)")).toBeTruthy();
  expect(within(await screen.findByRole("list", { name: "Before · after" })).getByText("4 - 6 · 0")).toBeTruthy();
  expect(screen.getByText("2,000 · 5,000")).toBeTruthy();
  expect(screen.getByText("2 of the 3 most frequent values end in 000")).toBeTruthy();
  // least frequent, each seen once: one inline list, no bars
  expect(await screen.findByText("Least frequent · each once")).toBeTruthy();
  expect(screen.getByLabelText("Least frequent values of qty").textContent).toBe("11 · 13");
  expect(screen.getAllByText("none").length).toBeGreaterThan(0);       // zero · negative
  expect(urls.some((u) => u.includes("numform?column=qty"))).toBe(true);
  // percentile: the strip as bins
  fireEvent.click(bins.getByRole("button", { name: "Percentile" }));
  expect(within(screen.getByRole("table", { name: "Bins of qty" })).getByText("P25 - Median · 38 - 250")).toBeTruthy();
  fireEvent.click(bins.getByRole("button", { name: "Equal width" }));
  expect(await screen.findByText(/95.00% of rows fall in one of 10 bins/)).toBeTruthy();
});

test("an even column: no skew, equal width by default, a spread-evenly line", async () => {
  stub(false);
  show(260);
  expect(await screen.findByText("Spread evenly.")).toBeTruthy();
  expect(screen.queryByText("Heavily skewed.")).toBeNull();
  const bins = within(screen.getByRole("group", { name: "Bins" }));
  expect(bins.getByRole("button", { name: "Equal width" }).getAttribute("aria-pressed")).toBe("true");
  expect(within(await screen.findByRole("table", { name: "Bins of qty" })).getByText("0 - 10")).toBeTruthy();
  const found = within(screen.getByRole("list", { name: "Findings for qty" }));
  expect(found.queryByText("Skewed")).toBeNull();
});

test("the header's form text", () => {
  expect(numberFormText({ filled: 10, places: { min: 0, max: 0 }, fits: "DECIMAL(8, 0)" })).toBe("whole · fits DECIMAL(8,0)");
  expect(numberFormText({ filled: 10, places: { min: 2, max: 2 }, fits: "DECIMAL(10, 2)" })).toBe("2 places · fits DECIMAL(10,2)");
  expect(numberFormText({ filled: 10, places: { min: 0, max: 4 }, fits: "DECIMAL(9, 4)" })).toBe("0 to 4 places · fits DECIMAL(9,4)");
  expect(numberFormText({ filled: 0, places: { min: 0, max: 0 }, fits: "" })).toBe("");
  expect(numberFormText(undefined)).toBe("");
});
