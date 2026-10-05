# tests/test_web_detail.py
"""The read the Differing rows tab added: a page of the rows that paired but differ, A then B under a
Side column, the most differing cells first, narrowed to one column on request."""
from tests.webkit import COUNTS, auto_run, c  # noqa: F401


def test_differing_rows_come_a_page_at_a_time_worst_first(c):
    run = auto_run(c)["run"]
    base = f"/api/results/{run['id']}/diff-rows"
    d = c.get(base, params={"limit": 7}).json()
    assert d["total"] == int(COUNTS["diff_rows"]) and d["offset"] == 0
    assert d["keys"] == [COUNTS["key"]] and d["columns"]
    f = d["frame"]
    assert f["columns"][:2] == ["Side", COUNTS["key"]]
    assert f["columns"][2:2 + len(d["columns"])] == d["columns"]
    assert [r[0] for r in f["rows"]] == ["A", "B"] * 7
    assert len(d["marks"]) == len(d["cells"]) == 7
    assert d["cells"] == sorted(d["cells"], reverse=True)
    assert all(n == len(m) and n > 0 for n, m in zip(d["cells"], d["marks"]))
    for i, m in enumerate(d["marks"]):                       # a marked column differs, an unmarked one agrees
        a, b = f["rows"][2 * i], f["rows"][2 * i + 1]
        assert a[1] == b[1]
        assert all(set(m) <= set(d["columns"]) for m in d["marks"])
    assert d["file"].endswith("__cell_diffs.csv")
    by = {x["column"]: x["n"] for x in d["by_column"]}
    assert sum(by.values()) == int(COUNTS["cells"])
    assert [x["n"] for x in d["by_column"]] == sorted(by.values(), reverse=True)

    nxt = c.get(base, params={"offset": 7, "limit": 7}).json()
    keys = {r[1] for r in f["rows"]}
    assert not keys & {r[1] for r in nxt["frame"]["rows"]}


def test_differing_rows_narrow_to_one_column(c):
    run = auto_run(c)["run"]
    base = f"/api/results/{run['id']}/diff-rows"
    by = c.get(base, params={"limit": 1}).json()["by_column"]
    one = by[-1]
    d = c.get(base, params={"column": one["column"], "limit": 10_000}).json()
    assert d["total"] == one["n"] == len(d["marks"])
    assert all(one["column"] in m for m in d["marks"])
    assert c.get(base, params={"column": "nowhere"}).status_code == 404
    assert c.get(base, params={"limit": 0}).status_code == 422


def test_one_sided_columns_ride_along_on_their_own_side(c):
    run = auto_run(c)["run"]
    d = c.get(f"/api/results/{run['id']}/diff-rows", params={"limit": 3}).json()
    cols = d["frame"]["columns"]
    for name in d["only_a"]:
        i = cols.index(name)
        assert all(r[i] is None for r in d["frame"]["rows"] if r[0] == "B")
    for name in d["only_b"]:
        i = cols.index(name)
        assert all(r[i] is None for r in d["frame"]["rows"] if r[0] == "A")
    assert len(cols) == 1 + len(d["keys"]) + len(d["columns"]) + len(d["only_a"]) + len(d["only_b"])
