import { afterEach, expect, test, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mount } from "../../sources/testkit";
import type { Row } from "../frame";
import { profile } from "../testkit";
import { FlagView, flagForm, useFlagForm, useReadsAsFlag, type FlagBody } from "./FlagView";

afterEach(() => { vi.unstubAllGlobals(); });

const ACCEPTS: [string, string][] = [["True", "False"], ["true", "false"], ["Yes", "No"], ["Y", "N"], ["1", "0"]];
const GROUPS: FlagBody["groups"] = [
  { column: "CostCenter", how: "value", distinct: 8 }, { column: "Dept", how: "value", distinct: 11 },
  { column: "HireDate", how: "year", distinct: 1860 }, { column: "Salary", how: "band", distinct: 2958 }];

const CLEAN: FlagBody = {
  column: "IsActive", true: 2518, false: 467, nulls: 0, blanks: 0, odd: 0,
  spellings: [{ value: "Y", n: 2518, reads: true }, { value: "N", n: 467, reads: false }],
  accepts: ACCEPTS, groups: GROUPS, by: "CostCenter", how: "value",
  rates: [{ group: "CC-110", n: 364, true: 317, rate: 87.09 }, { group: "CC-510", n: 368, true: 303, rate: 82.34 }],
};

const MIXED: FlagBody = {
  column: "IsActive", true: 30, false: 15, nulls: 5, blanks: 0, odd: 0,
  spellings: [{ value: "Y", n: 20, reads: true }, { value: "N", n: 10, reads: false },
              { value: "true", n: 10, reads: true }, { value: "false", n: 5, reads: false }],
  accepts: ACCEPTS, groups: [], by: "", how: "", rates: [],
};

const st = (nulls: number, rows = 2985): Row => ({ Column: "IsActive", Type: "boolean", Rows: rows, Nulls: nulls, "Null %": (100 * nulls) / rows, Distinct: 2 });

function stub(f: (url: string) => unknown, calls: string[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.startsWith("/api/profiling/flag?")) return json(f(url));
    if (url.startsWith("/api/profiling/flags")) return json({ columns: [{ column: "IsActive", filled: 2985, true: 2518, false: 467 }] });
    return json({});
  }));
}

const show = (nulls = 0, rows = 2985) => mount(<FlagView p={profile()} column="IsActive" made="20261004-120000" st={st(nulls, rows)} as="boolean" />);

test("a clean Y / N flag: findings first, the cards, the values and the pairs, the rate by group", async () => {
  const calls: string[] = [];
  stub((url) => (url.includes("by=HireDate")
    ? { ...CLEAN, by: "HireDate", how: "year", rates: [{ group: "2019", n: 1500, true: 1300, rate: 86.67 }, { group: "2020", n: 1485, true: 1218, rate: 82.02 }] }
    : url.includes("by=Salary")
    ? { ...CLEAN, by: "Salary", how: "band", rates: [{ group: "1000 - 5000", lo: 1000, hi: 5000, n: 597, true: 500, rate: 83.75 }] }
    : CLEAN), calls);
  show();
  const findings = await screen.findByRole("list", { name: "Findings" });
  const pills = within(findings).getAllByRole("listitem").map((li) => li.textContent);
  expect(pills[0]).toBe("Read as boolean fromY / N - one spelling pair, every row");
  expect(pills).toContain("Imbalanced 84 / 16one in 6 values is false");
  expect(pills).toContain("No nulls · no blanks");
  expect(findings.compareDocumentPosition(screen.getByText("Balance"))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  expect(screen.getByText("True · Y")).toBeInTheDocument();
  expect(screen.getByText("False · N")).toBeInTheDocument();
  expect(screen.getByText("Y · N")).toBeInTheDocument();
  expect(screen.getByText("one pair")).toBeInTheDocument();
  expect(screen.getByText("5.4 : 1")).toBeInTheDocument();
  const values = screen.getByRole("list", { name: "Values of IsActive" });
  expect(within(values).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    "Y → true2,518 · 84.36%", "N → false467 · 15.64%"]);
  const acc = screen.getByRole("list", { name: "Spelling pairs the reader accepts" });
  expect(within(acc).getAllByRole("listitem")).toHaveLength(5);
  expect(within(acc).getAllByText("- seen in this column", { exact: false })).toHaveLength(1);
  expect(within(acc).getByText("- seen in this column", { exact: false }).parentElement).toHaveTextContent("Y / N");
  const rates = screen.getByRole("list", { name: "True rate of IsActive by CostCenter" });
  expect(within(rates).getAllByRole("listitem")[0]).toHaveTextContent("CC-110");
  expect(within(rates).getAllByRole("listitem")[0].querySelector(".bar i")).toHaveStyle({ width: "87.09%" });
  expect(screen.getByText(/82\.34% - 87\.09% across all 2 groups - flat/)).toBeInTheDocument();
  const notShown = screen.getByRole("list", { name: "Not shown for this column" });
  expect(notShown).toHaveTextContent("N, 467 times");
  expect(notShown).toHaveTextContent("one letter or word per value");

  const pick = screen.getByRole("combobox", { name: "True rate by" });
  expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["CostCenter", "Dept", "HireDate · year", "Salary · bands"]);
  await userEvent.selectOptions(pick, "HireDate|year");
  expect(await screen.findByRole("list", { name: "True rate of IsActive by HireDate · year" })).toHaveTextContent("2019");
  expect(screen.getByText(/across all 2 years/)).toBeInTheDocument();
  expect(calls.some((u) => u.includes("by=HireDate&how=year"))).toBe(true);
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "True rate by" }), "Salary|band");
  expect(await screen.findByRole("list", { name: "True rate of IsActive by Salary · bands" })).toHaveTextContent("1,000 - 5,000");
});

test("mixed spellings and nulls: a finding names each pair with its rows", async () => {
  stub(() => MIXED);
  show(5, 50);
  const findings = await screen.findByRole("list", { name: "Findings" });
  const pills = within(findings).getAllByRole("listitem").map((li) => li.textContent);
  expect(pills).toContain("Mixed spellingsY / N 30 · true / false 15");
  expect(pills).toContain("5 nulls10.00% of rows");
  expect(pills.some((x) => x?.startsWith("Read as boolean"))).toBe(false);
  expect(screen.getByText("2 pairs mixed")).toBeInTheDocument();
  expect(screen.getByText("2.0 : 1")).toBeInTheDocument();
  expect(screen.getByText("True · Y / true")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Values of IsActive" })).toHaveTextContent("null");
  expect(screen.getByText("No other column with 2 to 50 values, dates or numbers to group by.")).toBeInTheDocument();
  const acc = screen.getByRole("list", { name: "Spelling pairs the reader accepts" });
  expect(within(acc).getAllByText("- seen in this column", { exact: false })).toHaveLength(2);
});

test("flagForm gives the header its pair; the hooks tell the header what to offer", async () => {
  expect(flagForm(CLEAN)).toBe("Y / N");
  expect(flagForm(MIXED)).toBe("Y / N · true / false");
  expect(flagForm({ accepts: ACCEPTS, spellings: [{ value: "true", n: 3, reads: true }] })).toBe("true / false");
  stub(() => CLEAN);
  function Head({ kind }: { kind: string }) {
    const form = useFlagForm("IsActive", "20261004-120000", true);
    const offer = useReadsAsFlag("IsActive", "20261004-120000", kind);
    return <p>{form}|{offer ? "offer" : "no"}</p>;
  }
  mount(<Head kind="text" />);
  expect(await screen.findByText("Y / N|offer")).toBeInTheDocument();
});
