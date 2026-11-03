# tests/test_web_value_counts.py
"""The value counts the results views draw - a column's values counted on side A or B, both, or
as A -> B pairs, over all rows, the differing rows or one side's one-sided rows: ranked most
frequent first, a page at a time, searched, with bins and a median for a number."""
import pytest

from tests.webkit import COUNTS, W, auto_run, c, compare, seed_table, state, ws_of  # noqa: F401


@pytest.fixture
def run(c):
    r = auto_run(c)["run"]
    s = c.get(f"/api/results/{r['id']}/summary").json()
    led = [dict(zip(s["ledger"]["columns"], row)) for row in s["ledger"]["rows"]]
    return {"url": f"/api/results/{r['id']}/values", "counts": {m["label"]: m["value"] for m in s["counts"]},
            "ledger": led}


def get(c, url, **params):
    r = c.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def every_row(c, url, **params):
    """Every ranked value, page by page, and the last page's body."""
    rows, page = [], 1
    while True:
        d = get(c, url, page=page, size=200, **params)
        rows += d["rows"]
        if not d["rows"]:
            return rows, d
        page += 1


def test_all_rows_of_a_side_count_every_row_most_frequent_first(c, run):
    rows, d = every_row(c, run["url"], column="department")
    total = run["counts"]["Rows Left"]
    assert d["sides"] == [{**d["sides"][0], "side": "a", "rows": total}]
    assert sum(r["n"][0] for r in rows) == total == 3000
    ns = [r["n"][0] for r in rows]
    assert ns == sorted(ns, reverse=True) and ns[0] == d["sides"][0]["top"]
    assert rows[-1]["cum"] == [total] and [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert d["values"] == len(rows) == d["sides"][0]["distinct"] + (1 if d["sides"][0]["nulls"] else 0)
    b = get(c, run["url"], column="department", side="b")
    assert b["sides"][0]["rows"] == run["counts"]["Rows Right"] == 2985


def small_pair(c, tmp_path):
    """A small pair with nulls - the sample has none."""
    (tmp_path / "a.csv").write_text("emp_id,department\n1,Eng\n2,Eng\n3,\n4,Ops\n5,\n6,Eng\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("EmployeeId,Dept\n1,Eng\n2,Ops\n3,\n4,\n6,Eng\n7,Ops\n", encoding="utf-8")
    for tag, f in (("A", "a.csv"), ("B", "b.csv")):
        r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(tmp_path / f), "name": tag}, headers=W)
        assert r.status_code == 200, r.text
    seed_table(c)


def test_non_null_leaves_the_null_out(c, tmp_path):
    small_pair(c, tmp_path)
    assert compare(c)["state"] == "done"
    url = f"/api/results/{state(c)['run']['id']}/values"
    d = get(c, url, column="department")
    assert d["sides"] == [{"side": "a", "rows": 6, "nulls": 2, "distinct": 2, "top": 3}]
    assert [(r["value"], r["n"], r["cum"]) for r in d["rows"]] == [("Eng", [3], [3]), (None, [2], [5]),
                                                                   ("Ops", [1], [6])]
    nn = get(c, url, column="department", basis="nonnull")
    assert [(r["rank"], r["value"], r["cum"]) for r in nn["rows"]] == [(1, "Eng", [3]), (2, "Ops", [4])]
    assert nn["values"] == 2 and nn["sides"][0]["top"] == 3
    both = get(c, url, column="department", side="both")
    assert [(r["value"], r["n"]) for r in both["rows"]] == [("Eng", [3, 2]), (None, [2, 2]), ("Ops", [1, 2])]
    assert [x["nulls"] for x in both["sides"]] == [2, 2]
    pair = get(c, url, column="department", subset="differ", side="pair")      # 2 Eng -> Ops, 4 Ops -> null
    assert sorted((r["value"], r["b"], r["n"][0]) for r in pair["rows"]) == [("Eng", "Ops", 1), ("Ops", None, 1)]
    assert get(c, url, column="department", subset="only_a")["rows"] == [{"rank": 1, "value": None, "n": [1], "cum": [1]}]
    nn = get(c, url, column="department", side="both", basis="nonnull")      # cumulative per side, null left out
    assert [(r["value"], r["cum"]) for r in nn["rows"]] == [("Eng", [3, 2]), ("Ops", [4, 4])]
    nn = get(c, url, column="department", subset="differ", side="pair", basis="nonnull")   # Ops -> null stays
    assert nn["values"] == 2 and nn["sides"][0]["nulls"] == 0
    assert get(c, url, column="department", subset="differ", side="pair", search="ops")["values"] == 2  # on A or B
    hit = get(c, url, column="department", search="NUL")                      # null reads "null" on the page
    assert [(r["value"], r["rank"]) for r in hit["rows"]] == [(None, 2)]
    assert get(c, url, column="department", subset="differ", side="pair", search="null")["rows"][0]["b"] is None


def test_both_sides_from_a_held_count_and_a_view(c, tmp_path, monkeypatch):
    from tablecmp.web import routes_results
    small_pair(c, tmp_path)
    assert compare(c)["state"] == "done"
    url = f"/api/results/{state(c)['run']['id']}/values"
    get(c, url, column="department")
    monkeypatch.setattr(routes_results, "HELD_VALUES", 0)
    get(c, url, column="department", side="b")
    names = ws_of(c).data["result"]["_values"]
    assert [names[("all", s, "department", "")][:3] for s in "ab"] == ["vc_", "vv_"]
    both = get(c, url, column="department", side="both")
    assert [(r["value"], r["n"]) for r in both["rows"]] == [("Eng", [3, 2]), (None, [2, 2]), ("Ops", [1, 2])]


@pytest.mark.parametrize("op", ["!=", "not in"])
def test_a_not_equal_filter_keeps_the_null_rows_as_the_engine_does(c, tmp_path, op):
    small_pair(c, tmp_path)
    row = {"Apply to": "Both", "Column": "department", "Operator": op, "Value": "Eng", "Type": "auto"}
    assert c.put("/api/setup/filters", json={"rows": [row]}, headers=W).json()["error"] == ""
    assert compare(c)["state"] == "done"
    res = ws_of(c).data["result"]["result"]
    assert (res.rows_left, res.rows_right) == (3, 4)                        # Ops + 2 nulls, Ops x2 + 2 nulls
    d = get(c, f"/api/results/{state(c)['run']['id']}/values", column="department", side="both")
    assert [(x["rows"], x["nulls"]) for x in d["sides"]] == [(3, 2), (4, 2)]


def test_a_search_keeps_the_ranks(c, run):
    every, _ = every_row(c, run["url"], column="department")
    rank = {r["value"]: r["rank"] for r in every}
    d = get(c, run["url"], column="department", search="ENG", size=500)
    assert d["rows"] and d["values"] == len(d["rows"])
    assert all("eng" in r["value"].lower() for r in d["rows"])
    assert all(rank[r["value"]] == r["rank"] for r in d["rows"])
    assert d["sides"] == get(c, run["url"], column="department")["sides"]     # sides count the whole set


def test_both_sides_count_a_side_each(c, run):
    rows, d = every_row(c, run["url"], column="department", side="both")
    assert [s["side"] for s in d["sides"]] == ["a", "b"]
    assert sum(r["n"][0] for r in rows) == d["sides"][0]["rows"] == 3000
    assert sum(r["n"][1] for r in rows) == d["sides"][1]["rows"] == 2985
    assert [sum(r["n"]) for r in rows] == sorted((sum(r["n"]) for r in rows), reverse=True)
    assert rows[-1]["cum"] == [3000, 2985]
    one = get(c, run["url"], column="first_name", side="both")                  # only A has it
    assert one["sides"][1]["rows"] == 0 and one["sides"][0]["rows"] == 3000


def test_the_differing_rows_and_one_column_s_mismatches(c, run):
    diff = int(COUNTS["diff_rows"])
    d = get(c, run["url"], column="department", subset="differ")
    assert d["sides"][0]["rows"] == diff == 2960
    led = {r["Column"]: r for r in run["ledger"]}
    for col in ("last_name", "department"):                                    # the worst, and one of 337
        n = int(led[col]["Mismatched"])
        assert get(c, run["url"], column=col, subset="differ", differs=col)["sides"][0]["rows"] == n
        rows, p = every_row(c, run["url"], column=col, subset="differ", side="pair", differs=col)
        assert p["sides"][0]["side"] == "pair" and p["sides"][0]["rows"] == n
        assert sum(r["n"][0] for r in rows) == n and all(r["value"] != r["b"] for r in rows)
    assert int(led["department"]["Mismatched"]) == 337
    both = get(c, run["url"], column="department", subset="differ", side="both")
    assert [s["rows"] for s in both["sides"]] == [diff, diff]
    assert get(c, run["url"], column="first_name", subset="differ")["sides"][0]["rows"] == diff   # A's own
    assert c.get(run["url"], params={"column": "first_name", "subset": "differ", "side": "b"}).status_code == 404


def test_one_sided_rows_count_their_own_side(c, run):
    a = get(c, run["url"], column="department", subset="only_a")
    b = get(c, run["url"], column="department", subset="only_b", side="b")
    assert a["sides"][0]["rows"] == int(COUNTS["only_left"]) == 40
    assert b["sides"][0]["rows"] == int(COUNTS["only_right"]) == 25
    assert get(c, run["url"], column="CostCenter", subset="only_b", side="b")["sides"][0]["rows"] == 25
    assert c.get(run["url"], params={"column": "department", "subset": "only_a", "side": "b"}).status_code == 400


def test_a_number_has_bins_and_a_median(c, run):
    col = next(r["Column"] for r in run["ledger"] if str(r["Read as"]).startswith("number"))
    d = get(c, run["url"], column=col, bins=10, size=3, basis="nonnull")
    assert d["kind"] == "number" and len(d["rows"]) == 3
    (h,) = d["hist"]
    s = d["sides"][0]
    assert h["side"] == "a" and len(h["bins"]) == 10
    assert sum(b["n"] for b in h["bins"]) <= s["rows"] - s["nulls"]
    assert h["bins"][0]["lo"] <= h["median"] <= h["bins"][-1]["hi"]
    both = get(c, run["url"], column=col, side="both", bins=5)
    assert [x["side"] for x in both["hist"]] == ["a", "b"] and all(len(x["bins"]) == 5 for x in both["hist"])
    when = get(c, run["url"], column="hire_date", bins=4, subset="only_a")       # text read from the file
    assert when["kind"] == "date" and len(when["hist"][0]["bins"]) == 4
    assert len(when["hist"][0]["median"]) == 10                               # a date, no time
    assert get(c, run["url"], column="department", bins=10)["hist"] == []
    assert get(c, run["url"], column=col, subset="differ", side="pair", differs=col, bins=10)["hist"] == []


def test_what_it_refuses(c, run):
    url = run["url"]
    code = lambda **p: c.get(url, params=p).status_code                                 # noqa: E731
    assert code(column="nowhere") == 404
    assert code(column="department", subset="some") == 422 and code(column="department", side="c") == 422
    assert code(column="department", side="pair") == 400                                # pairs: differing rows only
    assert code(column="department", subset="only_b", side="both") == 400
    assert code(column="department", differs="department") == 400
    assert code(column="department", subset="differ", differs="nowhere") == 404
    assert code(column="CostCenter") == 404                                             # only B has it
    assert get(c, url, column="department", page=999)["rows"] == []
    assert c.get(url.replace("/results/", "/results/old"), params={"column": "department"}).status_code == 404


def test_a_count_is_made_once(c, run):
    held = ws_of(c).data["result"]
    get(c, run["url"], column="department", side="both")
    n = len(held["_values"])
    assert n == 3                                                                       # a, b and both
    get(c, run["url"], column="department", side="both", page=2, search="a", basis="nonnull")
    get(c, run["url"], column="department")
    assert len(held["_values"]) == n
    col = next(r["Column"] for r in run["ledger"] if str(r["Read as"]).startswith("number"))
    assert get(c, run["url"], column=col, side="both", bins=5)["hist"]
    k = len(held["_values_hist"])
    get(c, run["url"], column=col, side="both", bins=5, page=2)
    assert len(held["_values_hist"]) == k


def test_only_the_counts_used_last_are_held(c, run, monkeypatch):
    from tablecmp.web import routes_results
    monkeypatch.setattr(routes_results, "HELD_TABLES", 3)
    held = ws_of(c).data["result"]
    tables = lambda: {r[0] for r in held["con"].execute("SELECT table_name FROM duckdb_tables()").fetchall()}  # noqa: E731
    get(c, run["url"], column="department", side="both")                   # a, b, and both on them
    first = held["_values"][("all", "a", "department", "")]
    assert first in tables()
    get(c, run["url"], column="last_name")                                  # the oldest goes, and both with it
    assert list(held["_values"]) == [("all", "b", "department", ""), ("all", "a", "last_name", "")]
    assert first not in tables()
    d = get(c, run["url"], column="department", side="both")
    assert [s["rows"] for s in d["sides"]] == [3000, 2985] and len(held["_values"]) == 3


def test_a_column_of_many_values_is_counted_per_call_not_held(c, run, monkeypatch):
    from tablecmp.web import routes_results
    monkeypatch.setattr(routes_results, "HELD_VALUES", 100)
    d = get(c, run["url"], column="emp_id", side="both", size=3)
    names = ws_of(c).data["result"]["_values"]
    assert sorted(names.values()) == ["vv_0", "vv_1", "vv_2"]                 # views: no copy held
    monkeypatch.setattr(routes_results, "HELD_VALUES", 50_000)
    monkeypatch.setattr(routes_results, "HOLD_SHARE", 0)                      # nor one too big for memory
    get(c, run["url"], column="last_name")
    assert names[("all", "a", "last_name", "")].startswith("vv_")
    monkeypatch.setattr(routes_results, "HOLD_SHARE", 0.25)
    assert [s["rows"] for s in d["sides"]] == [3000, 2985] and d["sides"][0]["top"] == 1
    assert get(c, run["url"], column="department")["sides"][0]["rows"] == 3000
    assert names[("all", "a", "department", "")].startswith("vc_")            # few values: held


def test_a_page_past_any_set_is_refused(c, run):
    assert c.get(run["url"], params={"column": "department", "page": 4611686018427387904}).status_code == 422
