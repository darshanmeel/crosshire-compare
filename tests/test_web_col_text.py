"""GET /api/profiling/similar - a text column's values and the values that are probably the
same thing spelled twice, four ways; and the plain functions behind it."""
from pathlib import Path

from tablecmp.sql import scratch
from tablecmp.web import routes_col_text as tx
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture

PAYROLL = Path(HR).parent / "payroll_employees.csv"


def test_similar_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/similar", params={"column": "Dept"}).status_code == 409


def test_payroll_dept_renamed_spellings(c):
    load_p(c, PAYROLL, "Payroll")
    profile(c, "Payroll")
    r = c.get("/api/profiling/similar", params={"column": "Dept"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["distinct"] == 11 and g["filled"] == 2985 and g["more"] == 0 and not g["capped"]
    assert g["values"][0] == {"value": "Support", "n": 406}
    assert len(g["values"]) == 11
    assert g["shortest"] == "Eng" and g["longest"] == "Finance & Control"
    # no case or spacing variants: the fingerprint finds nothing, so the page opens on "same"
    assert g["counts"]["fingerprint"] == 0
    assert g["method"] == "same" and g["by"] == "CostCenter"
    got = {x["keep"]: ([m["value"] for m in x["members"]], x["rows"], x["why"]) for x in g["groups"]}
    assert got == {"Engineering": (["Engineering", "Eng"], 368, "both only in CostCenter CC-220"),
                   "Finance": (["Finance", "Finance & Control"], 364, "both only in CostCenter CC-110"),
                   "Sales": (["Sales", "Sales EMEA"], 363, "both only in CostCenter CC-310")}
    assert [x["rows"] for x in g["groups"]] == [368, 364, 363]
    assert g["groups"][0]["on"] == {"column": "CostCenter", "value": "CC-220"}
    pre = c.get("/api/profiling/similar", params={"column": "Dept", "method": "prefix"}).json()
    assert pre["method"] == "prefix"
    assert sorted(x["keep"] for x in pre["groups"]) == ["Engineering", "Finance", "Sales"]
    assert c.get("/api/profiling/similar", params={"column": "Dept", "method": "nope"}).status_code == 400
    assert c.get("/api/profiling/similar", params={"column": "nope"}).status_code == 404


def test_hr_department_is_clean(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    g = c.get("/api/profiling/similar", params={"column": "department"}).json()
    assert g["distinct"] == 8 and sum(v["n"] for v in g["values"]) == 3000
    assert g["counts"] == {"fingerprint": 0, "ngram": 0, "prefix": 0, "same": 0}
    assert g["groups"] == []


def test_ngram_groups_do_not_chain():
    vs = [{"value": v, "n": n} for v, n in (("abcdef", 5), ("abcdeg", 3), ("abcdhg", 2), ("zzzz", 1))]
    ng = tx.by_ngram(vs, 0.5)
    assert [[m["value"] for m in g["members"]] for g in ng] == [["abcdef", "abcdeg"]]
    assert tx.first_method({"fingerprint": {"groups": []}, "same": {"groups": []}, "ngram": {"groups": [1]},
                            "prefix": {"groups": [1]}}) == "fingerprint"


def _rel(rows):
    con = scratch()
    con.execute("CREATE TABLE t (OrderType VARCHAR, Region VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    return con


def test_the_functions_on_any_relation():
    rows = ([("New Order", "x")] * 5 + [("new order", "x")] * 2 + [(" New Order", "x")]
            + [("Order New", "y")] + [("Cancel", "z")] * 4 + [("Cancelled", "z")] * 3 + [("Replace", "w")] * 6
            + [(None, "w")])
    con = _rel(rows)
    try:
        v = tx.text_values(con, "t", "OrderType")
        assert v["distinct"] == 7 and v["filled"] == 22 and v["values"][0] == {"value": "Replace", "n": 6}
        fp = tx.by_fingerprint(v["values"])
        assert len(fp) == 1 and fp[0]["keep"] == "New Order" and fp[0]["rows"] == 9
        assert {m["value"] for m in fp[0]["members"]} == {"New Order", "new order", " New Order", "Order New"}
        assert fp[0]["why"] == "the same words in another order"
        assert tx._fp_why(["New Order", "new order"]) == "differ only in case"
        assert tx._fp_why(["Sales-EMEA", "Sales EMEA"]) == "differ only in punctuation, case or spacing"
        pre = tx.by_prefix(v["values"])
        assert [(g["keep"], [m["value"] for m in g["members"]]) for g in pre] == [("Cancel", ["Cancel", "Cancelled"])]
        ng = tx.by_ngram(v["values"], 0.5)
        assert any({m["value"] for m in g["members"]} == {"Cancel", "Cancelled"} for g in ng)
        by, same = tx.by_other(con, "t", "OrderType", ["Region"], v["values"])
        assert by == "Region"                    # z holds Cancel and Cancelled alone, x the three New Orders
        assert [(g["keep"], g["rows"], g["why"]) for g in same] == [
            ("New Order", 8, "all 3 only in Region x"), ("Cancel", 7, "both only in Region z")]
        res = tx.similar(con, "t", "OrderType", ["Region"])
        assert res["scanned"] == 7 and set(res["methods"]) == set(tx.METHODS)
        assert tx.first_method(res["methods"]) == "fingerprint"
    finally:
        con.close()


def test_same_needs_the_other_column_mostly_one_to_one():
    # every city in one country: a hierarchy, not renamed spellings - no group
    con = scratch()
    try:
        con.execute("CREATE TABLE t (City VARCHAR, Country VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?, ?)", [("Lyon", "FR"), ("Paris", "FR"), ("Rome", "IT"), ("Milan", "IT")])
        v = tx.text_values(con, "t", "City")
        assert tx.by_other(con, "t", "City", ["Country"], v["values"]) == ("", [])
    finally:
        con.close()


def test_ngram_leaves_free_text_out_and_other_needs_one_value_each():
    long_ = [{"value": "order note " + "x" * 80, "n": 2}, {"value": "order note " + "x" * 79, "n": 1}]
    assert tx.by_ngram(long_) == []                     # past NGRAM_LEN: free text, not compared
    assert len(tx.by_ngram([{"value": "Warehouse", "n": 3}, {"value": "Warehous", "n": 1}])) == 1
    con = scratch()
    try:
        con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('North', 'R1'), ('Nord', 'R1'), ('South', 'R2'), "
                    "('East', 'R3'), ('West', 'R4'), ('West', NULL), (NULL, 'R5')) v(region, rep)")
        vals = tx.text_values(con, "t", "region")["values"]
        by, groups = tx.by_other(con, "t", "region", ["rep"], vals)
        assert by == "rep" and [m["value"] for m in groups[0]["members"]] == ["Nord", "North"]
        con.execute("INSERT INTO t VALUES ('South', 'R4')")   # South now goes with two reps: rep no longer decided
        assert tx.by_other(con, "t", "region", ["rep"], tx.text_values(con, "t", "region")["values"]) == ("", [])
    finally:
        con.close()
