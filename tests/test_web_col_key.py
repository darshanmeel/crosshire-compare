"""GET /api/profiling/keycheck - one column checked as a key: unique, nulls, blanks, case and
space variants, width, shapes, prefix, the number part and its gaps, file order, the next id."""
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


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
