# tests/test_web_bucket_values.py
"""Profile by bucket over HTTP: each bucket's values counted on that bucket's rows alone (the
counts add up to the bucket's rows), the columns ticked by default per bucket, and the paged
table of key values under By key value."""
import pytest

from tests.webkit import COUNTS, W, auto_run, c, compare, load_pair, seed_table, state  # noqa: F401


@pytest.fixture
def run(c):
    """The sample pair on emp_id with department compared - so all five buckets are there."""
    load_pair(c)
    seed_table(c)
    assert compare(c)["state"] == "done"
    rid = state(c)["run"]["id"]
    s = c.get(f"/api/results/{rid}/summary").json()
    return {"id": rid, "buckets": s["buckets"], "counts": {m["label"]: m["value"] for m in s["counts"]}}


def get(c, url, **params):
    r = c.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_bucket_counts_its_own_rows(c, run):
    n = run["counts"]
    matched, diff = n["Matched on key"], n["Rows that differ"]
    rows = {"matched": matched, "same": matched - diff, "differ": diff,
            "left": n["Only in Left"], "right": n["Only in Right"]}
    assert [b["id"] for b in run["buckets"]] == list(rows) and diff == 337
    for b in run["buckets"]:
        assert f"({rows[b['id']]:,})" in b["label"]
        body = get(c, f"/api/results/{run['id']}/buckets/{b['id']}")
        for col in body["columns"]:
            side = "both" if col["sides"] == ["a", "b"] else col["sides"][0]
            d = get(c, f"/api/results/{run['id']}/values", column=col["column"], subset=body["subset"], side=side,
                    size=500)
            assert [s["rows"] for s in d["sides"]] == [rows[b["id"]]] * len(col["sides"]), (b, col)
            if d["values"] <= 500:                                        # every value on one page: they add up
                assert [sum(r["n"][i] for r in d["rows"]) for i in range(len(col["sides"]))] == [rows[b["id"]]] * len(col["sides"])


def test_the_defaults_tick_the_key_and_on_differing_buckets_the_worst_three(c, run):
    base = f"/api/results/{run['id']}/buckets"
    want = {"matched": ["emp_id", "department"], "differ": ["emp_id", "department"],
            "same": ["emp_id"], "left": ["emp_id"], "right": ["emp_id"]}
    for b, cols in want.items():
        d = get(c, base + "/" + b)
        assert d["shown"] == [x["column"] for x in d["columns"]] == cols, b
        assert d["groups"][0] == {"title": "Key columns", "items": [{"name": "emp_id", "label": "emp_id"}]}
    left = get(c, base + "/left")
    assert left["subset"] == "only_a" and {tuple(x["sides"]) for x in left["columns"]} == {("a",)}
    assert get(c, base + "/right")["columns"][0]["sides"] == ["b"]
    assert get(c, base + "/differ", add=["department"], exact=True)["columns"][0]["column"] == "department"
    assert get(c, base + "/differ", exact=True)["empty"]                # everything unticked


def test_the_worst_three_mismatched_columns_on_the_auto_run(c):
    rid = auto_run(c)["run"]["id"]
    d = get(c, f"/api/results/{rid}/buckets/differ")
    mism = next(g for g in d["groups"] if g["title"] == "Mismatched columns")["items"]
    assert d["shown"] == [COUNTS["key"]] + [o["name"] for o in mism[:3]] and len(mism) > 3
    assert d["by_key"]["tables"][0]["column"] == COUNTS["key"]
    one = get(c, f"/api/results/{rid}/buckets/left")
    assert one["shown"] == [COUNTS["key"]]


def test_the_key_values_table_pages_every_value(c, run):
    url = f"/api/results/{run['id']}/key-values"
    first = get(c, url, column="emp_id")
    assert first["values"] == 337 and len(first["rows"]) == 25 and first["size"] == 25
    r = first["rows"][0]
    assert set(r) == {"value", "matched", "differ", "pct", "cells", "columns"}
    assert r["matched"] == 1 and r["differ"] == 1 and r["pct"] == 100.0 and r["columns"] == "department"
    seen, page = [], 1
    while True:
        d = get(c, url, column="emp_id", page=page)
        if not d["rows"]:
            break
        seen += [x["value"] for x in d["rows"]]
        page += 1
    assert len(seen) == len(set(seen)) == 337 and page == 15
    hit = get(c, url, column="emp_id", search=seen[0])
    assert hit["values"] >= 1 and seen[0] in [x["value"] for x in hit["rows"]]
    assert c.get(url, params={"column": "department"}).status_code == 404       # not a key column


def test_what_the_bucket_values_refuse(c, run):
    url = f"/api/results/{run['id']}/values"
    code = lambda **p: c.get(url, params=p).status_code                         # noqa: E731
    assert code(column="department", subset="same", side="pair") == 400
    assert code(column="department", subset="matched", differs="department") == 400
    assert code(column="department", subset="same", side="both") == 200


def test_a_filtered_run_counts_only_the_rows_it_compared(c):
    """The paired buckets and the key values count the rows the engine paired after the run's
    filters - not every row the two sides hold."""
    load_pair(c)
    seed_table(c)
    row = {"Apply to": "Both", "Column": "department", "Operator": "=", "Value": "Engineering", "Type": "auto"}
    assert c.put("/api/setup/filters", json={"rows": [row]}, headers=W).json()["error"] == ""
    assert compare(c)["state"] == "done"
    rid = state(c)["run"]["id"]
    n = {m["label"]: m["value"] for m in c.get(f"/api/results/{rid}/summary").json()["counts"]}
    matched, diff = n["Matched on key"], n["Rows that differ"]
    assert 0 < matched < 2960
    url = f"/api/results/{rid}/values"
    for subset, want in (("matched", matched), ("same", matched - diff), ("differ", diff)):
        d = get(c, url, column="emp_id", subset=subset, side="both")
        assert [s["rows"] for s in d["sides"]] == [want, want], subset
    kv = get(c, f"/api/results/{rid}/key-values", column="emp_id", size=500)
    assert all(r["matched"] == 1 for r in kv["rows"])
