import { afterEach, expect, test, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { json, mount } from "../../sources/testkit";
import { profile, T } from "../testkit";
import { rowsOf } from "../frame";
import { batchOf, formText, spanText, WhenView, ymd, type WhenBody } from "./WhenView";

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
  years: counts([["2018", 321], ["2026", 343]]),
  months: counts([["Jan", 300], ["Feb", 200], ["Mar", 273], ["Apr", 250], ["May", 250], ["Jun", 300], ["Jul", 270], ["Aug", 270], ["Sep", 254], ["Oct", 211], ["Nov", 211], ["Dec", 211]]),
  quarters: counts([["Jan - Mar", 773], ["Apr - Jun", 800], ["Jul - Sep", 794], ["Oct - Dec", 633]]) };
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

test("a date column: findings, cards, rows per year with its table, calendar checks, parts, repeats", async () => {
  const calls: string[] = [];
  stub(calls, (u) => (u.includes("bin=month") ? MONTHLY : DATE));
  mount(<WhenView p={P} column="joined" made="m1" st={st("joined")} as="date" />);
  expect(await screen.findByText("8 y 8 m 27 d")).toBeInTheDocument();
  expect(calls[0]).toBe("/api/profiling/when?column=joined&as=date");
  expect(screen.getByText("3,191 days")).toBeInTheDocument();
  const found = screen.getByRole("list", { name: "Findings" });
  expect(within(found).getByText("Weekend 28.40%")).toBeInTheDocument();
  expect(within(found).getByText("852 dates")).toBeInTheDocument();
  expect(within(found).getByText("No future dates · no placeholders · no nulls")).toBeInTheDocument();
  expect(within(found).queryByText("Batch date")).toBeNull();                 // 6 against 5 is no batch
  expect(screen.getByText("×6 · a Saturday")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /^Rows per year: 2018 321, 2019 338/ })).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Rows per year" });
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  expect(within(table).getByText("11.67%")).toBeInTheDocument();
  expect(within(table).getByText("2026 to Sep")).toBeInTheDocument();         // the last year stops in September
  expect(screen.getByText("Flat: 316 - 350 rows a year.")).toBeInTheDocument();
  const checks = screen.getByRole("list", { name: "Calendar checks" });
  expect(within(checks).getByText("after today, 2026-10-05")).toBeInTheDocument();
  expect(within(checks).getByText("a date column")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Parts · weekday, month and quarter" })).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Quarter" })).getByText("Q4 · Oct - Dec")).toBeInTheDocument();
  expect(screen.getByText("2026 stops in Sep, so the months after it hold one year fewer.")).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Not shown for this column" })).getByText("Parts · hour")).toBeInTheDocument();
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
  expect(within(reps).getByText("996 filled - 990 distinct; the busiest stamps below")).toBeInTheDocument();
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

const WRITTEN: WhenBody = { ...STAMP, form: "%Y%m%d %H:%M:%S.%n", whole_ms: 93,
  hours: Array.from({ length: 24 }, (_, h) => ({ label: String(h).padStart(2, "0"), n: h >= 5 && h <= 17 ? 76 : 0 })),
  years: counts([["2026", 996]]), months: counts([["Sep", 0], ["Oct", 996]]),
  weekday: counts([["Mon", 0], ["Tue", 0], ["Wed", 0], ["Thu", 996], ["Fri", 0], ["Sat", 0], ["Sun", 0]]),
  session: { from: "00:00", to: "24:00", before: 0, after: 0 },
  written: { shapes: [{ shape: "99999999 99:99:99.999999A", n: 996, example: "20261001 05:30:00.128158Z",
    spelled: "8 digits · space · hh:mm:ss · point · 6 digits · Z" }], shape_count: 1,
    fractions: [{ digits: 6, n: 996 }], first_over_12: 0, second_over_12: 0, text_last: null } };

test("the form beside read as: %n said as %f up to 6 digits, the Z put back, ISO said in full", () => {
  expect(formText(WRITTEN)).toBe("%Y%m%d %H:%M:%S.%fZ");
  expect(formText({ ...WRITTEN, written: { ...WRITTEN.written!, fractions: [{ digits: 7, n: 1 }] } })).toBe("%Y%m%d %H:%M:%S.%nZ");
  expect(formText({ form: "ISO", written: null })).toBe("ISO 8601");
  expect(formText({ form: "", written: null })).toBe("");
  expect(batchOf({ repeated: [{ value: "2026-09-01", n: 26, weekday: "Tue" }, { value: "2026-09-26", n: 6, weekday: "Sat" }] }))
    .toMatchObject({ value: "2026-09-01", n: 26, background: 6 });
  expect(batchOf({ repeated: [{ value: "2026-09-01", n: 9, weekday: "Tue" }] })).toBeNull();
});

test("text stamps: the findings row, shape to format, the session fence and the parts by weekday and hour", async () => {
  stub([], () => WRITTEN);
  mount(<WhenView p={P} column="Stamp" made="m1" st={st("Stamp")} as="timestamp" />);
  const found = await screen.findByRole("list", { name: "Findings" });
  expect(within(found).getByText("Format inferred from the shape")).toBeInTheDocument();
  expect(within(found).getByText(/8 digits · space · hh:mm:ss · point · 6 digits · Z → %Y%m%d %H:%M:%S.%fZ/)).toBeInTheDocument();
  expect(within(found).getByText("Missing 0.40%")).toBeInTheDocument();
  expect(within(found).getByText("4 rows")).toBeInTheDocument();
  expect(within(found).getByText("Mixed precision")).toBeInTheDocument();
  expect(within(found).getByText("9.34% whole milliseconds")).toBeInTheDocument();
  expect(within(found).getByText("Near-unique")).toBeInTheDocument();
  expect(within(found).getByText("2026-10-01 · 05:30 - 17:30")).toBeInTheDocument();
  expect(within(found).getByText("No out-of-session stamps")).toBeInTheDocument();
  const reps = screen.getByRole("list", { name: "Precision and repeats" });
  expect(within(reps).getByText("99999999 99:99:99.999999A")).toBeInTheDocument();
  expect(within(reps).getByText("6 · every value")).toBeInTheDocument();
  expect(within(reps).getByText(/one shape covers all 996 filled rows/)).toBeInTheDocument();
  expect(within(screen.getByRole("list", { name: "Outlier findings" })).getByText("0 · 0")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Parts · week and day" })).toBeInTheDocument();
  const hours = screen.getByRole("list", { name: "Hour of day" });
  expect(within(hours).getAllByRole("listitem")).toHaveLength(13);              // 05:00 to 17:00, the empty night left out
  expect(within(hours).getByText("05:00")).toBeInTheDocument();
  expect(screen.getByText("Year and month: all on 2026-10-01")).toBeInTheDocument();
  expect(screen.getByText("20261001 05:30:00.128158Z")).toBeInTheDocument();
});

test("a batch date is named, marked in the chart and said against the next most repeated", async () => {
  const B: WhenBody = { ...DATE, repeated: [{ value: "2026-09-01", n: 26, weekday: "Tue" }, { value: "2026-09-26", n: 6, weekday: "Sat" }],
    future: 2, form: "%d/%m/%Y",
    written: { shapes: [{ shape: "99/99/9999", n: 3000, example: "04/03/2023", spelled: "2 digits · / · 2 digits · / · 4 digits" }],
      shape_count: 1, fractions: [], first_over_12: 1708, second_over_12: 0, text_last: { text: "28/12/2024", read: "2024-12-28" } } };
  stub([], () => B);
  mount(<WhenView p={P} column="joined" made="m1" st={st("joined")} as="date" />);
  const found = await screen.findByRole("list", { name: "Findings" });
  expect(within(found).getByText("Batch date")).toBeInTheDocument();
  expect(within(found).getByText("2026-09-01 ×26 · the next most repeated ×6")).toBeInTheDocument();
  expect(within(found).getByText(/99\/99\/9999 → %d\/%m\/%Y · day first: 1,708 values carry a day above 12 in the first slot/)).toBeInTheDocument();
  expect(within(found).getByText("latest read 28/12/2024 · really 2026-09-28")).toBeInTheDocument();
  expect(within(found).getByText("No placeholders · no nulls")).toBeInTheDocument();
  expect(within(found).getByText("In the future")).toBeInTheDocument();
  expect(screen.getByText(/2026 to Sep holds the 26-row batch on 2026-09-01/)).toBeInTheDocument();
  expect(screen.getByText("26 on 2026-09-01 against 6 on the next most repeated date")).toBeInTheDocument();
  expect(document.querySelector(".when-hist i.when-mark")).not.toBeNull();
});
