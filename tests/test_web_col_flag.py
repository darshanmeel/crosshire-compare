"""GET /api/profiling/flag - a boolean column's true / false split, its spellings and its true
rate per group of a category column."""
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


def test_flag_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/flag", params={"column": "active"}).status_code == 409


def test_hr_active_by_department(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    r = c.get("/api/profiling/flag", params={"column": "active"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["true"], g["false"], g["nulls"]) == (2548, 452, 0)
    assert [(s["value"], s["n"], s["reads"]) for s in g["spellings"]] == [("True", 2548, True), ("False", 452, False)]
    assert ["True", "False"] in g["accepts"] and ["Y", "N"] in g["accepts"] and ["1", "0"] in g["accepts"]
    assert ["On", "Off"] not in g["accepts"]           # the engine does not read on / off as a boolean
    assert g["by"] == "department" and "department" in g["groups"]
    assert "emp_id" not in g["groups"] and "salary" not in g["groups"]
    assert len(g["rates"]) == 8 and sum(x["n"] for x in g["rates"]) == 3000
    assert sum(x["true"] for x in g["rates"]) == 2548
    rates = [x["rate"] for x in g["rates"]]
    assert rates == sorted(rates, reverse=True)
    top = g["rates"][0]
    assert top["rate"] == round(100 * top["true"] / top["n"], 2)


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
    assert g["groups"] == ["team", "region"] and g["by"] == "team"
    assert g["rates"] == [{"group": "a", "n": 3, "true": 2, "rate": 66.67},
                          {"group": "b", "n": 3, "true": 1, "rate": 50.0}]
    by = c.get("/api/profiling/flag", params={"column": "flag", "by": "region"}).json()
    assert by["by"] == "region"
    assert {x["group"]: (x["n"], x["true"]) for x in by["rates"]} == {"x": (3, 1), "y": (3, 2)}
    assert c.get("/api/profiling/flag", params={"column": "flag", "by": "id"}).status_code == 400
    assert c.get("/api/profiling/flag", params={"column": "nope"}).status_code == 404
