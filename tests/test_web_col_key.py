"""GET /api/profiling/keycheck - one column checked as a key: unique, nulls, blanks, case and
space variants, width, shapes, prefix, the number part and its gaps, file order, the next id."""
from tests.test_web_profiling import HR, W, c, load_p, profile, wait  # noqa: F401 - c is the client fixture


def test_keycheck_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/keycheck", params={"column": "emp_id"}).status_code == 409


def test_the_sample_key_is_clean_and_contiguous(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    k = c.get("/api/profiling/keycheck", params={"column": "emp_id"}).json()
    assert k["column"] == "emp_id"
    assert (k["rows"], k["filled"], k["nulls"], k["blanks"]) == (3000, 3000, 0, 0)
    assert (k["distinct"], k["duplicates"], k["case_variants"], k["spaces"]) == (3000, 0, 0, 0)
    assert k["width"] == {"min": 6, "max": 6}
    assert k["shapes"] == [{"shape": "A99999", "n": 3000, "example": "E10001"}]
    assert k["prefix"] == {"text": "E", "n": 3000}
    assert k["number"] == {"min": 10001, "max": 13000, "distinct": 3000, "gaps": 0, "leading_zeros": 0}
    assert k["order"] == "ascending"
    assert k["next_id"] == "E13001"
    assert c.get("/api/profiling/keycheck", params={"column": "nope"}).status_code == 404


def test_gaps_a_duplicate_mixed_case_and_spaces(c, tmp_path):
    f = tmp_path / "k.csv"
    f.write_text("code,qty\n"
                 "AB0007,1\n"
                 "AB0003,2\n"
                 "ab0003,3\n"
                 "AB0010,4\n"
                 "AB0010,5\n"
                 ",6\n"
                 "X0012,7\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    k = c.get("/api/profiling/keycheck", params={"column": "code"}).json()
    assert k["rows"] == 7 and k["nulls"] + k["blanks"] == 1 and k["filled"] == 6
    assert k["distinct"] == 5 and k["duplicates"] == 1
    assert k["case_variants"] == 1                  # AB0003 and ab0003
    assert k["width"] == {"min": 5, "max": 6}
    assert k["shapes"][0] == {"shape": "AA9999", "n": 5, "example": "AB0003"}
    assert k["shapes"][1]["shape"] == "A9999"
    assert k["prefix"] == {"text": "AB", "n": 4}
    # 3, 7, 10, 12 between 3 and 12: 6 gaps; every number part starts with 0
    assert k["number"] == {"min": 3, "max": 12, "distinct": 4, "gaps": 6, "leading_zeros": 6}
    assert k["order"] == "neither"
    assert k["next_id"] == "X0013"


def test_plain_numbers_count_down_and_free_text_has_no_number_part(c, tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("id,name\n5,ann lee\n3,bob\n1,cy\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    k = c.get("/api/profiling/keycheck", params={"column": "id"}).json()
    assert k["number"] == {"min": 1, "max": 5, "distinct": 3, "gaps": 2, "leading_zeros": 0}
    assert k["order"] == "descending" and k["next_id"] == "6" and k["prefix"] is None
    t = c.get("/api/profiling/keycheck", params={"column": "name"}).json()
    assert t["number"] is None and t["next_id"] == "" and t["spaces"] == 1
    assert t["prefix"] == {"text": "ann", "n": 1}


PAYROLL = HR.parent / "payroll_employees.csv"


def test_a_contiguous_key_is_one_run(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    k = c.get("/api/profiling/keycheck", params={"column": "emp_id"}).json()
    assert k["runs"] == [{"from": 10001, "to": 13000, "kind": "run", "n": 3000, "holes": 0,
                          "id_from": "E10001", "id_to": "E13000"}]
    assert k["gaps"] == {"count": 0, "ids": 0, "shown": 0} and k["beyond"] is None


def test_the_payroll_key_has_one_hole_and_a_run_past_it(c):
    load_p(c, PAYROLL, "Payroll")
    profile(c, "Payroll")
    k = c.get("/api/profiling/keycheck", params={"column": "EmployeeId"}).json()
    assert [(r["kind"], r["id_from"], r["id_to"], r["n"]) for r in k["runs"]] == [
        ("run", "E10001", "E12960", 2960), ("gap", "E12961", "E13000", 40), ("run", "E13001", "E13025", 25)]
    assert k["gaps"] == {"count": 1, "ids": 40, "shown": 1}
    b = k["beyond"]
    assert (b["id_from"], b["id_to"], b["n"], b["rows"]) == ("E13001", "E13025", 25, 25)
    assert {"column": "FullName", "value": "New Starter"} in b["shared"]


def test_only_the_largest_gaps_are_drawn_and_runs_keep_their_holes(c, tmp_path, monkeypatch):
    from tablecmp.web import routes_col_key
    monkeypatch.setattr(routes_col_key, "GAPS", 2)
    f = tmp_path / "g.csv"
    ids = [1, 2, 3, 5, 6, 20, 21, 22, 30, 32]           # gaps 4 (1), 7-19 (13), 23-29 (7), 31 (1)
    f.write_text("order_id,qty\n" + "".join(f"{i},1\n" for i in ids), encoding="utf-8")
    load_p(c, f)
    profile(c)
    k = c.get("/api/profiling/keycheck", params={"column": "order_id"}).json()
    assert k["gaps"] == {"count": 4, "ids": 22, "shown": 2}
    assert [(r["kind"], r["from"], r["to"], r["n"], r["holes"]) for r in k["runs"]] == [
        ("run", 1, 6, 5, 1), ("gap", 7, 19, 13, 0), ("run", 20, 22, 3, 0), ("gap", 23, 29, 7, 0), ("run", 30, 32, 2, 1)]
    assert k["runs"][0]["id_from"] == "1"                # plain numbers, no prefix: written as numbers
    assert k["beyond"]["n"] == 5 and k["beyond"]["shared"] == [] and k["beyond"]["rows"] == 5


def test_keycompare_before_a_run_and_after_one(c):
    load_p(c, PAYROLL, "Payroll")
    profile(c, "Payroll")
    assert c.get("/api/profiling/keycompare", params={"column": "EmployeeId"}).json() == {"run": None, "key": None}
    for tag, path, name in (("A", HR, "HR"), ("B", PAYROLL, "Payroll")):
        r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
        assert r.status_code == 200, r.text

    e = wait(c, c.post("/api/auto", headers=W).json())
    assert e["state"] == "done", e
    log = c.get("/api/log").json()["entries"]
    done = wait(c, next(x for x in log if x["kind"] == "Compare"))
    assert done["state"] == "done", done
    k = c.get("/api/profiling/keycompare", params={"column": "EmployeeId"}).json()
    assert k["names"] == ["HR", "Payroll"] and k["stale"] is False
    key = k["key"]
    assert key["canon"] == "emp_id" and key["columns"] == ["emp_id", "EmployeeId"] and key["side"] == "B"
    assert key["matched"] == 2960 and key["rows"] == [3000, 2985]
    assert [(o["side"], o["n"], o["min"], o["max"]) for o in key["only"]] == [
        ("A", 40, "E12961", "E13000"), ("B", 25, "E13001", "E13025")]
    assert c.get("/api/profiling/keycompare", params={"column": "FullName"}).json()["key"] is None
