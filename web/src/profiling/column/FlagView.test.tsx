import { afterEach, expect, test, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../../sources/testkit";
import type { Row } from "../frame";
import { profile } from "../testkit";
import { FlagView, type FlagBody } from "./FlagView";

afterEach(() => { vi.unstubAllGlobals(); });

const ACCEPTS: [string, string][] = [["True", "False"], ["true", "false"], ["Yes", "No"], ["Y", "N"], ["1", "0"]];

const CLEAN: FlagBody = {
  column: "enabled", true: 2548, false: 452, nulls: 0,
  spellings: [{ value: "True", n: 2548, reads: true }, { value: "False", n: 452, reads: false }],
  accepts: ACCEPTS, groups: ["team", "region"], by: "team",
  rates: [{ group: "North", n: 370, true: 326, rate: 88.11 }, { group: "South", n: 377, true: 312, rate: 82.76 }],
};

const MIXED: FlagBody = {
  column: "enabled", true: 30, false: 15, nulls: 5,
  spellings: [{ value: "Y", n: 20, reads: true }, { value: "N", n: 10, reads: false },
              { value: "true", n: 10, reads: true }, { value: "false", n: 5, reads: false }],
  accepts: ACCEPTS, groups: [], by: "", rates: [],
};

const st = (nulls: number): Row => ({ Column: "enabled", Type: "boolean", Rows: 3000, Nulls: nulls, "Null %": (100 * nulls) / 3000, Distinct: 2 });

function stub(f: (url: string) => FlagBody, calls: string[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.startsWith("/api/profiling/flag?")) return json(f(url));
    return json({});
  }));
}

const show = (nulls = 0) => mount(<FlagView p={profile()} column="enabled" made="20261004-120000" st={st(nulls)} as="boolean" />);

test("a clean flag: cards, the green banner, the values, the accepted spellings, the rate by group", async () => {
  const calls: string[] = [];
  stub((url) => (url.includes("by=region")
    ? { ...CLEAN, by: "region", rates: [{ group: "East", n: 1500, true: 1300, rate: 86.67 }, { group: "West", n: 1500, true: 1248, rate: 83.2 }] }
    : CLEAN), calls);
  show();
  expect(await screen.findByText("5.6 : 1")).toBeInTheDocument();
  expect(screen.getByText("True · False - one pair")).toBeInTheDocument();
  expect(screen.getByText("84.93%")).toBeInTheDocument();
  expect(screen.getByText(/A clean flag\./).parentElement).toHaveTextContent(/Exactly two spellings.*One in 7 rows is false - those 452 are the ones to look at\./);
  const values = screen.getByRole("list", { name: "Values of enabled" });
  expect(within(values).getByText("True")).toBeInTheDocument();
  expect(within(values).getByText("2,548")).toBeInTheDocument();
  const acc = screen.getByRole("list", { name: "Spellings this column accepts as boolean" });
  expect(within(acc).getAllByRole("listitem")).toHaveLength(5);
  expect(within(acc).getByText("- seen in this column", { exact: false }).parentElement).toHaveTextContent("True / False");
  const rates = screen.getByRole("list", { name: "True rate of enabled by team" });
  expect(within(rates).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    expect.stringContaining("North"), expect.stringContaining("South")]);
  expect(screen.getByText(/82\.76% – 88\.11% across all 2 - flat/)).toBeInTheDocument();
  // the bars show the rate itself, not the rate against the highest one
  expect(within(rates).getAllByRole("listitem")[0].querySelector(".bar i")).toHaveStyle({ width: "88.11%" });
  expect(screen.getByRole("list", { name: "Not shown for this column" })).toHaveTextContent("False, 452 times");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "True rate by" }), "region");
  expect(await screen.findByRole("list", { name: "True rate of enabled by region" })).toHaveTextContent("East");
  expect(calls.some((u) => u.includes("by=region"))).toBe(true);
});

test("mixed spellings and blanks: a warn banner that names each spelling with its count", async () => {
  stub(() => MIXED);
  show(5);
  expect(await screen.findByText("Mixed spellings.")).toBeInTheDocument();
  const banner = screen.getByText("Mixed spellings.").parentElement!;
  expect(banner).toHaveTextContent("4 spellings in 2 pairs - Y (20), N (10), true (10), false (5).");
  expect(banner).toHaveTextContent("5 blanks");
  expect(screen.getByText("2 pairs mixed")).toBeInTheDocument();
  expect(screen.getByText("2.0 : 1")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Values of enabled" })).toHaveTextContent("blank");
  expect(screen.getByText("No text column with 2 to 30 values to group by.")).toBeInTheDocument();
  const acc = screen.getByRole("list", { name: "Spellings this column accepts as boolean" });
  expect(within(acc).getAllByText("- seen in this column", { exact: false })).toHaveLength(2);
});
