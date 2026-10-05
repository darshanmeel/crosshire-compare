import { afterEach, expect, test, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { json, mount } from "../../sources/testkit";
import { profile, T } from "../testkit";
import { rowsOf } from "../frame";
import { spanText, WhenView, ymd, type WhenBody } from "./WhenView";

afterEach(() => vi.unstubAllGlobals());

const COLS = ["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled", "Distinct % of rows", "Top value", "Top %", "Min", "Max", "Mean"];
const P = profile({ stats: T(COLS, [
  ["emp_id", "text", 3000, 0, 0, 3000, 100, 100, "E10001", 0.03, "", "", ""],
  ["joined", "date", 3000, 0, 0, 1877, 62.57, 62.57, "2026-09-26", 0.2, "2018-01-01", "2026-09-28", ""],
  ["Stamp", "text", 1000, 4, 0.4, 990, 99.4, 99, "20261001 07:17:59.375000Z", 0.3, "", "", ""],
]) });
const st = (c: string) => rowsOf(P.stats).find((r) => r.Column === c)!;
const counts = (xs: [string, number][]) => xs.map(([label, n]) => ({ label, n }));

const base = { form: "", today: "2026-10-05", before_1900: 0, placeholders: [], future: 0, first_of_month: 0, date_only: 0 };
const DATE: WhenBody = { ...base, column: "joined", kind: "date", filled: 3000, distinct: 1877, first: "2018-01-01", last: "2026-09-28",
  span_seconds: 3191 * 86400, days: 1877, weekend: 852, first_of_month: 92, fraction_digits: 0, whole_ms: null, shared: 1123,
  repeated: [{ value: "2026-09-26", n: 6, weekday: "Sat" }, { value: "2024-10-21", n: 5, weekday: "Mon" }], bin: "year",
  bins: counts([["2018", 321], ["2019", 338], ["2020", 350], ["2021", 339], ["2022", 316], ["2023", 326], ["2024", 329], ["2025", 338], ["2026", 343]]),
  weekday: counts([["Mon", 425], ["Tue", 423], ["Wed", 442], ["Thu", 451], ["Fri", 407], ["Sat", 424], ["Sun", 428]]),
  months: [], quarters: counts([["Jan - Mar", 773], ["Apr - Jun", 800], ["Jul - Sep", 794], ["Oct - Dec", 633]]) };
const MONTHLY: WhenBody = { ...DATE, bin: "month", bins: Array.from({ length: 30 }, (_, i) => ({ label: `m${i}`, n: 100 })) };
const STAMP: WhenBody = { ...base, column: "Stamp", kind: "timestamp", form: "%Y%m%d %H:%M:%S.%f", filled: 996, distinct: 990,
  first: "2026-10-01 05:30:00.128158", last: "2026-10-01 17:30:41.059000", span_seconds: 43240.93, days: 1, weekend: 0,
  fraction_digits: 6, whole_ms: 93, shared: 6, repeated: [{ value: "2026-10-01 07:17:59.375000", n: 3, weekday: "Thu" }],
  bin: "hour", bins: Array.from({ length: 13 }, (_, i) => ({ label: `${String(5 + i).padStart(2, "0")}:00`, n: i === 3 ? 0 : 80 })),
  weekday: [], months: [], quarters: [] };

function stub(calls: string[], answer: (url: string) => unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { calls.push(url); return json(answer(url)); }));
}

test("spans read as years, months and days for dates and as hours for one day of stamps", () => {
  expect(ymd("2018-01-01", "2026-09-28")).toBe("8 y 8 m 27 d");
  expect(ymd("2024-01-31", "2024-03-01")).toBe("0 y 1 m 1 d");
  expect(spanText({ kind: "timestamp", span_seconds: 43241.9, first: "", last: "" })).toBe("12 h 00 m 41 s");
  expect(spanText({ kind: "timestamp", span_seconds: 3 * 86400 + 3600 * 4 + 600, first: "", last: "" })).toBe("3 d 04 h 10 m");
});

test("a date column: cards, the weekend banner, rows per year with its table, calendar checks, weekdays, repeats", async () => {
  const calls: string[] = [];
  stub(calls, (u) => (u.includes("bin=month") ? MONTHLY : DATE));
  mount(<WhenView p={P} column="joined" made="m1" st={st("joined")} as="date" />);
  expect(await screen.findByText("8 y 8 m 27 d")).toBeInTheDocument();
  expect(calls[0]).toBe("/api/profiling/when?column=joined&as=date");
  expect(screen.getByText("3,191 days")).toBeInTheDocument();
  expect(screen.getByText(/28\.40% of joined values fall on a Saturday or Sunday/)).toBeInTheDocument();
  expect(screen.getByText(/Monday to Friday hold 407 - 451 each/)).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /^Rows per year: 2018 321, 2019 338/ })).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Rows per year" });
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  expect(within(table).getByText("11.67%")).toBeInTheDocument();
  expect(screen.getByText("Flat: 316 - 350 rows a year.")).toBeInTheDocument();
  const checks = screen.getByRole("list", { name: "Calendar checks" });
  expect(within(checks).getByText("after today, 2026-10-05")).toBeInTheDocument();
  expect(within(checks).getByText("a date column")).toBeInTheDocument();
  const week = screen.getByRole("list", { name: "Weekday" });
  expect(within(week).getByText("Sat")).toHaveClass("when-we");
  expect(within(week).getByText("Mon")).not.toHaveClass("when-we");
  expect(screen.getByText("1,877 distinct · 1,123 rows share a date")).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Most repeated dates" })).getByText("Sat")).toBeInTheDocument();
  // the bin picker: a real group of toggles; Month asks again, and a long list has no table
  const seg = screen.getByRole("group", { name: "Bin by" });
  expect(within(seg).getByRole("button", { name: "Year" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(seg).getByRole("button", { name: "Month" }));
  expect(await screen.findByRole("img", { name: /^Rows per month/ })).toBeInTheDocument();
  expect(calls).toContain("/api/profiling/when?column=joined&as=date&bin=month");
  expect(screen.queryByRole("table", { name: "Rows per month" })).toBeNull();
});

test("text read as a timestamp: precision, one calendar day, the session, repeats, the finer bins kept to the span", async () => {
  const calls: string[] = [];
  stub(calls, () => STAMP);
  mount(<WhenView p={P} column="Stamp" made="m1" st={st("Stamp")} as="timestamp" />);
  expect(await screen.findByText("µs")).toBeInTheDocument();
  expect(calls[0]).toBe("/api/profiling/when?column=Stamp&as=timestamp");
  expect(screen.getByText("6 fractional digits")).toBeInTheDocument();
  expect(screen.getByText("one calendar day")).toBeInTheDocument();
  expect(screen.getByText("07:17:59.375000")).toBeInTheDocument();
  expect(screen.getByText("×3")).toBeInTheDocument();
  expect(screen.getByText("Read as a timestamp.")).toBeInTheDocument();
  expect(screen.getByText("%Y%m%d %H:%M:%S.%f")).toBeInTheDocument();
  expect(screen.getByText(/Every stamp falls on 2026-10-01 between 05:30 and 17:30/)).toBeInTheDocument();
  const outl = screen.getByRole("list", { name: "Outlier findings" });
  expect(within(outl).getByText("2026-10-01 is a Thursday")).toBeInTheDocument();
  expect(within(outl).getByText("no midnight values - every row carries a time")).toBeInTheDocument();
  const reps = screen.getByRole("list", { name: "Precision and repeats" });
  expect(within(reps).getByText("996 filled - 990 distinct")).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Most repeated stamps" })).getByText("2026-10-01 07:17:59.375000")).toBeInTheDocument();
  expect(screen.getByText(/all 1 end in/)).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Session" })).toHaveTextContent("05:30:00.128158 → 17:30:41.059000 · 12 h 00 m 40 s");
  const seg = screen.getByRole("group", { name: "Bin by" });
  expect(within(seg).getByRole("button", { name: "Hour" })).toHaveAttribute("aria-pressed", "true");
  expect(within(seg).getByRole("button", { name: "Minute" })).toBeEnabled();     // 720 minutes fit
  expect(screen.getByRole("img", { name: /^Rows per hour: 05:00 80, 06:00 80, 07:00 80, 08:00 0/ })).toBeInTheDocument();
});

test("a long span turns the finer bins off and adds Month", async () => {
  stub([], () => ({ ...STAMP, span_seconds: 400 * 86400, days: 300, bin: "month", first: "2025-01-01 00:00:00", last: "2026-02-05 00:00:00" }));
  mount(<WhenView p={P} column="Stamp" made="m1" st={st("Stamp")} as="timestamp" />);
  const seg = await screen.findByRole("group", { name: "Bin by" });
  expect(within(seg).getByRole("button", { name: "Minute" })).toBeDisabled();
  expect(within(seg).getByRole("button", { name: "Hour" })).toBeDisabled();
  expect(within(seg).getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByText("1 y 1 m 4 d").length).toBeGreaterThan(0);
  expect(screen.getByText("300 calendar days")).toBeInTheDocument();
  expect(screen.getByText(/The stamps run from 2025-01-01 00:00:00 to 2026-02-05 00:00:00/)).toBeInTheDocument();
});

test("a failed read says why", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Read the column as a date or a timestamp." }, 400)));
  mount(<WhenView p={P} column="Stamp" made="m1" st={st("Stamp")} as="timestamp" />);
  expect(await screen.findByText(/Read the column as a date or a timestamp/)).toBeInTheDocument();
});
