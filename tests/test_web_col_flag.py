"""GET /api/profiling/flag - a boolean column's true / false split, its spellings and its true
rate per group of another column; GET /api/profiling/flags - text columns that read as a boolean;
and the plain functions behind them, run on a relation of their own."""
import duckdb

from tablecmp.web.routes_col_flag import flag_counts, flag_reads, group_options, true_rates
from tests.test_web_profiling import HR, EX, c, load_p, profile  # noqa: F401 - c is the client fixture

PAY = EX / "payroll_employees.csv"


def test_flag_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/flag", params={"column": "active"}).status_code == 409
    assert c.get("/api/profiling/flags").status_code == 409


def test_hr_active_by_department(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    r = c.get("/api/profiling/flag", params={"column": "active"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["true"], g["false"], g["nulls"], g["blanks"], g["odd"]) == (2548, 452, 0, 0, 0)
    assert [(s["value"], s["n"], s["reads"]) for s in g["spellings"]] == [("True", 2548, True), ("False", 452, False)]
    assert ["True", "False"] in g["accepts"] and ["Y", "N"] in g["accepts"] and ["1", "0"] in g["accepts"]
    assert ["On", "Off"] not in g["accepts"]           # the engine does not read on / off as a boolean
    assert (g["by"], g["how"]) == ("department", "value")
    opts = {(x["column"], x["how"]) for x in g["groups"]}
    assert ("department", "value") in opts
    assert ("hire_date", "year") in opts and ("salary", "band") in opts
    assert not any(x["column"] in ("emp_id", "active") for x in g["groups"])
    assert len(g["rates"]) == 8 and sum(x["n"] for x in g["rates"]) == 3000
    assert sum(x["true"] for x in g["rates"]) == 2548
    rates = [x["rate"] for x in g["rates"]]
    assert rates == sorted(rates, reverse=True)
    top = g["rates"][0]
    assert top["rate"] == round(100 * top["true"] / top["n"], 2)

    y = c.get("/api/profiling/flag", params={"column": "active", "by": "hire_date", "how": "year"}).json()
    assert y["how"] == "year" and sum(x["n"] for x in y["rates"]) == 3000
    years = [x["group"] for x in y["rates"]]
    assert years == sorted(years) and all(len(v) == 4 for v in years)
    b = c.get("/api/profiling/flag", params={"column": "active", "by": "salary", "how": "band"}).json()
    assert len(b["rates"]) == 5 and sum(x["n"] for x in b["rates"]) == 3000
    assert all(x["lo"] <= x["hi"] for x in b["rates"])
    assert [x["lo"] for x in b["rates"]] == sorted(x["lo"] for x in b["rates"])


def test_payroll_isactive_y_n_by_cost_center_and_hire_year(c):
    load_p(c, PAY, "Payroll")
    profile(c, "Payroll")
    g = c.get("/api/profiling/flag", params={"column": "IsActive", "by": "CostCenter"}).json()
    assert {s["value"] for s in g["spellings"]} == {"Y", "N"}
    assert g["true"] + g["false"] + g["nulls"] == 2985
    assert len(g["rates"]) == 8 and sum(x["n"] for x in g["rates"]) == 2985
    assert ("HireDate", "year") in {(x["column"], x["how"]) for x in g["groups"]}
    assert "EmployeeId" not in {x["column"] for x in g["groups"]}
    y = c.get("/api/profiling/flag", params={"column": "IsActive", "by": "HireDate", "how": "year"}).json()
    assert sum(x["n"] for x in y["rates"]) == 2985 and all(x["group"] is None or len(x["group"]) == 4 for x in y["rates"])
    assert c.get("/api/profiling/flags").json()["columns"] == []      # IsActive is a boolean already


def test_mixed_spellings_and_another_group(c, tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("id,flag,team,region\n1,Y,a,x\n2,N,a,x\n3,true,b,y\n4,false,b,y\n5,,b,x\n6,Y,a,y\n",
                 encoding="utf-8")
    load_p(c, f)
    profile(c)
    g = c.get("/api/profiling/flag", params={"column": "flag"}).json()
    assert (g["true"], g["false"], g["nulls"]) == (3, 2, 1)
    assert g["spellings"][0] == {"value": "Y", "n": 2, "reads": True}
    assert sorted(s["value"] for s in g["spellings"]) == ["N", "Y", "false", "true"]
    assert [x["column"] for x in g["groups"]] == ["team", "region"] and g["by"] == "team"
    assert g["rates"] == [{"group": "a", "n": 3, "true": 2, "rate": 66.67},
                          {"group": "b", "n": 3, "true": 1, "rate": 50.0}]
    by = c.get("/api/profiling/flag", params={"column": "flag", "by": "region"}).json()
    assert by["by"] == "region"
    assert {x["group"]: (x["n"], x["true"]) for x in by["rates"]} == {"x": (3, 1), "y": (3, 2)}
    assert c.get("/api/profiling/flag", params={"column": "flag", "by": "id"}).status_code == 400
    assert c.get("/api/profiling/flag", params={"column": "flag", "by": "team", "how": "band"}).status_code == 400
    assert c.get("/api/profiling/flag", params={"column": "nope"}).status_code == 404
    assert c.get("/api/profiling/flags").json()["columns"] == []        # flag is a boolean already


def test_a_number_of_ones_and_zeros_reads_as_a_boolean(c, tmp_path):
    f = tmp_path / "n.csv"
    f.write_text("order_id,shipped,OrderQty\n" + "".join(f"{i},{1 if i % 4 else 0},{i % 3}\n" for i in range(40)),
                 encoding="utf-8")
    load_p(c, f)
    profile(c)
    assert c.get("/api/profiling/flags").json()["columns"] == [
        {"column": "shipped", "filled": 40, "true": 30, "false": 10}]
    g = c.get("/api/profiling/flag", params={"column": "shipped"}).json()
    assert (g["true"], g["false"]) == (30, 10) and {s["value"] for s in g["spellings"]} == {"1", "0"}
    assert g["by"] == "OrderQty" and len(g["rates"]) == 3


def test_the_functions_run_on_any_relation():
    con = duckdb.connect()
    con.execute("CREATE TABLE r AS SELECT * FROM (VALUES ('Y', 'a', 10.0, 'x'), ('N', 'a', 20.0, 'x'), "
                "('Y', 'b', 30.0, 'maybe'), (' ', 'b', 40.0, NULL), (NULL, 'b', 50.0, 'x')) t(f, g, amt, other)")
    k = flag_counts(con, "r", "f")
    assert (k["true"], k["false"], k["nulls"], k["blanks"], k["odd"]) == (2, 1, 1, 1, 0)
    assert true_rates(con, "r", "f", '"g"') == [{"group": "a", "n": 2, "true": 1, "rate": 50.0},
                                                {"group": "b", "n": 3, "true": 1, "rate": 100.0}][::-1]
    bands = true_rates(con, "r", "f", '"amt"', "band")
    assert sum(x["n"] for x in bands) == 5 and bands[0]["lo"] == 10.0
    assert [x["column"] for x in flag_reads(con, "r", ["f", "g", "other"])] == ["f"]
    con.execute("CREATE TABLE n AS SELECT * FROM (VALUES (1.0, 2), (0.0, 1), (1.0, 0)) t(x, y)")
    assert flag_reads(con, "n", ["x", "y"], ("x", "y")) == [{"column": "x", "filled": 3, "true": 2, "false": 1}]
    stats = [{"Column": "f", "Type": "text", "Distinct": 2}, {"Column": "g", "Type": "text", "Distinct": 2},
             {"Column": "amt", "Type": "number", "Distinct": 500}, {"Column": "d", "Type": "date", "Distinct": 900},
             {"Column": "one", "Type": "text", "Distinct": 1}]
    assert group_options(stats, "f") == [{"column": "g", "how": "value", "distinct": 2},
                                         {"column": "d", "how": "year", "distinct": 900},
                                         {"column": "amt", "how": "band", "distinct": 500}]
