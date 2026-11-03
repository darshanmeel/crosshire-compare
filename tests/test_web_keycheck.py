"""GET /api/profiling/keycombo: any combination of the profiled columns checked as a key."""
from tests.test_web_profiling import HR, load_p, profile

URL = "/api/profiling/keycombo"


def check(c, *cols):
    return c.get(URL, params={"columns": list(cols)})


def test_a_unique_key(c):
    load_p(c, HR, "HR")
    assert profile(c, "HR")["state"] == "done"
    r = check(c, "emp_id")
    assert r.status_code == 200, r.text
    assert r.json() == {"columns": ["emp_id"], "rows": 3000, "distinct": 3000, "duplicate_rows": 0,
                        "null_keys": 0, "nulls_same": False, "unique": True, "top": [], "nulls_by_column": {}}


def test_a_combination_with_duplicates_lists_the_most_repeated(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    b = check(c, "department", "active").json()
    assert b["columns"] == ["department", "active"]
    assert (b["rows"], b["distinct"], b["duplicate_rows"], b["null_keys"]) == (3000, 16, 2984, 0)
    assert b["unique"] is False
    assert b["top"][0] == {"values": ["Support", "true"], "n": 349}
    assert b["top"][1] == {"values": ["Marketing", "true"], "n": 330}
    assert len(b["top"]) == 10 and all(t["n"] > 1 for t in b["top"])
    assert [t["n"] for t in b["top"]] == sorted((t["n"] for t in b["top"]), reverse=True)


def test_a_null_key_is_a_key_of_its_own(c, tmp_path):
    p = tmp_path / "nulls.csv"
    p.write_text("id,grp\n1,a\n2,a\n3,\n4,b\n5,\n", encoding="utf-8")
    load_p(c, p)
    profile(c)
    b = check(c, "grp").json()
    assert (b["rows"], b["distinct"], b["duplicate_rows"], b["null_keys"], b["unique"]) == (5, 4, 1, 2, False)
    assert b["top"] == [{"values": ["a"], "n": 2}]
    assert b["nulls_by_column"] == {"grp": 2}
    b = check(c, "id", "grp").json()
    assert (b["distinct"], b["duplicate_rows"], b["null_keys"], b["unique"]) == (5, 0, 2, True)
    assert b["top"] == []


def test_an_unknown_column_or_too_many_is_400(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    r = check(c, "emp_id", "nope")
    assert r.status_code == 400 and r.json()["detail"] == "No column called nope in this profile."
    r = check(c, *[f"c{i}" for i in range(11)])
    assert r.status_code == 400 and r.json()["detail"] == "Pick 1 to 10 columns."
    assert c.get(URL).status_code == 422


def test_nothing_profiled_is_409(c):
    r = check(c, "emp_id")
    assert r.status_code == 409 and r.json()["detail"] == "Profile the table first."
    load_p(c, HR, "HR")
    assert check(c, "emp_id").status_code == 409


def test_null_equals_null_when_asked(c, tmp_path):
    p = tmp_path / "nulls.csv"
    p.write_text("id,grp\n1,a\n2,a\n3,\n4,b\n5,\n", encoding="utf-8")
    load_p(c, p)
    profile(c)
    b = c.get("/api/profiling/keycombo", params={"columns": ["grp"], "nulls": "same"}).json()
    assert (b["rows"], b["distinct"], b["duplicate_rows"], b["null_keys"], b["unique"]) == (5, 3, 2, 2, False)
    assert b["top"] == [{"values": ["a"], "n": 2}, {"values": [None], "n": 2}]
    b = c.get("/api/profiling/keycombo", params={"columns": ["grp"], "nulls": "apart"}).json()   # held apart
    assert (b["distinct"], b["duplicate_rows"], b["nulls_same"]) == (4, 1, False)
    b = c.get("/api/profiling/keycombo", params={"columns": ["id", "grp"], "nulls": "same"}).json()
    assert (b["distinct"], b["duplicate_rows"], b["unique"]) == (5, 0, True)
    assert c.get("/api/profiling/keycombo", params={"columns": ["grp"], "nulls": "x"}).status_code == 422
