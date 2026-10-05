"""GET /api/profiling/findings - what stands out across the whole table, one pill each, with the
facts per column and the strongest dependency pairs; and the plain functions behind it."""
from datetime import date
from pathlib import Path

import pandas as pd

from tablecmp.sql import scratch
from tablecmp.values import ColSpec
from tablecmp.web import routes_overview as ov
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture

PAYROLL = Path(HR).parent / "payroll_employees.csv"


def test_findings_ask_for_a_profile_first(c):
    assert c.get("/api/profiling/findings").status_code == 409


def test_payroll_findings(c):
    load_p(c, PAYROLL, "Payroll")
    profile(c, "Payroll")
    r = c.get("/api/profiling/findings")
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["rows"] == 2985 and f["nulls"] == 0 and f["duplicates"] == 0
    got = {i["label"]: i for i in f["items"]}
    assert got["Sequence gap"]["detail"] == "EmployeeId · 40 ids missing · E12961 - E13000"
    assert got["One value on every id past the gap ×25"]["detail"].startswith("FullName New Starter")
    assert got["3 near-duplicate groups"]["columns"] == ["Dept"]
    assert got["Weekend dates 28.17%"]["detail"] == "HireDate"
    assert got["CostCenter decides Dept"]["detail"] == "70.00% beyond chance"
    assert f["items"][-1] == {"tone": "pos", "label": "No nulls · no duplicate rows · no whitespace or case variants",
                              "detail": "", "columns": []}
    assert f["gaps"] == {"column": "EmployeeId", "count": 1, "ids": 40, "largest": {"from": "E12961", "to": "E13000", "n": 40}}
    # the key is left out of the pairs: it decides every column by being unique
    assert f["pairs"][0] == {"x": "Dept", "y": "CostCenter", "v": 100.0}
    assert all("EmployeeId" not in (p["x"], p["y"]) for p in f["pairs"])
    cols = f["columns"]
    assert "1 gap · 40 ids missing (E12961 - E13000)" in cols["EmployeeId"]
    assert cols["Dept"][0].startswith("3 near-duplicate groups: Engineering / Eng · Finance / Finance & Control")
    assert cols["Dept"][0].endswith("each only with one CostCenter")
    assert "weekend 28.17%" in cols["HireDate"]
    # the Profile job works the casts out before it says done; held per profile, not measured again
    assert f["casts"] is True
    assert c.get("/api/profiling/findings").json() == f


def test_hr_is_clean_and_has_no_gap(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    f = c.get("/api/profiling/findings").json()
    labels = [i["label"] for i in f["items"]]
    assert f["gaps"] is None and not any("gap" in x.lower() for x in labels)
    assert not any("near-duplicate" in x for x in labels)


def _rel(sql: str):
    con = scratch(ordered=True)
    con.execute(f"CREATE TABLE mismatched AS {sql}")
    return con


def test_looks_like_reads_casts_and_flags():
    casts = [{"column": "OrderTime", "kind": "text", "filled": 10,
              "date": {"any": 10, "form": "%d/%m/%Y", "n": 10}},
             {"column": "OrderQty", "kind": "text", "filled": 10, "number": {"any": 9, "form": "plain", "n": 9}},
             {"column": "Price", "kind": "text", "filled": 10, "number": {"any": 5, "form": "plain", "n": 5}}]
    flags = [{"column": "Paid", "filled": 4, "true": 3, "false": 1}]
    got = {x["column"]: (x["as"], x["form"]) for x in ov.looks_like(casts, flags)}
    assert got == {"OrderTime": ("date", "%d/%m/%Y"), "OrderQty": ("number", "plain"), "Paid": ("boolean", "")}


def test_with_looks_adds_a_pill_first_and_a_fact():
    base = {"items": [{"tone": "pos", "label": "No nulls", "detail": "", "columns": []}], "columns": {"Price": ["x"]}}
    looks = [{"column": "OrderTime", "kind": "text", "as": "date", "form": "%d/%m/%Y", "n": 9, "filled": 10},
             {"column": "Price", "kind": "number", "as": "date", "form": "ISO", "n": 10, "filled": 10}]
    got = ov.with_looks(base, looks)
    assert got["items"][0]["label"] == "1 text column looks like date"
    assert got["items"][0]["detail"] == "OrderTime → date"
    assert got["columns"]["OrderTime"] == ["reads as date · %d/%m/%Y - 9 of 10"]
    assert got["columns"]["Price"] == ["reads as date - 10 of 10", "x"]
    assert base["columns"] == {"Price": ["x"]} and len(base["items"]) == 1      # left as it was


def test_placeholders_and_spellings_on_a_plain_relation():
    con = _rel("SELECT * FROM (VALUES ('o1', 'N/A', 'North'), ('o2', 'n/a', 'north'), ('o3', 'Ann', 'South'), "
               "('o4', 'Bo', 'South')) t(order_id, buyer, region)")
    try:
        assert ov.placeholder_values(con, "mismatched", ["buyer", "region"]) == [{"column": "buyer", "value": "N/A", "n": 2}]
        sp = ov.spellings(con, "mismatched", "region", [])
        assert sp["method"] == "fingerprint" and sp["groups"][0]["why"] == "differ only in case"
    finally:
        con.close()


def test_strongest_pairs_leave_the_key_out():
    m = pd.DataFrame([{"Column": "region", "order_id": 0.0, "region": None, "rep": 100.0},
                      {"Column": "rep", "order_id": 0.0, "region": 55.5, "rep": None}])
    assert ov.strongest_pairs(m, ["order_id"]) == [{"x": "region", "y": "rep", "v": 100.0},
                                                   {"x": "rep", "y": "region", "v": 55.5}]
    assert ov.strongest_pairs(pd.DataFrame(), []) == []


def test_overview_on_a_plain_relation():
    con = _rel("SELECT 'O' || lpad(CAST(i AS VARCHAR), 3, '0') AS order_id, "
               "DATE '2026-01-05' + CAST(i % 7 AS INT) AS OrderDay, i % 3 AS OrderQty "
               "FROM range(1, 21) t(i) WHERE i NOT IN (8, 9)")
    specs = [ColSpec("order_id", "order_id", "order_id"), ColSpec("OrderDay", "OrderDay", "OrderDay", kind="date"),
             ColSpec("OrderQty", "OrderQty", "OrderQty", kind="number")]
    stats = [{"Column": "order_id", "Type": "text", "Rows": 18, "Nulls": 0, "Distinct": 18},
             {"Column": "OrderDay", "Type": "date", "Rows": 18, "Nulls": 0, "Distinct": 7},
             {"Column": "OrderQty", "Type": "number", "Rows": 18, "Nulls": 0, "Distinct": 3}]
    try:
        f = ov.overview(con, "mismatched", specs, stats, key=["order_id"], notes=[], duplicates=0,
                        matrix=pd.DataFrame(), today=date(2026, 10, 1))
    finally:
        con.close()
    assert f["gaps"]["ids"] == 2 and f["gaps"]["largest"] == {"from": "O008", "to": "O009", "n": 2}
    labels = [i["label"] for i in f["items"]]
    assert "Sequence gap" in labels and any(x.startswith("Weekend dates ") for x in labels)
    assert labels[-1] == "No nulls · no duplicate rows · no whitespace or case variants"
