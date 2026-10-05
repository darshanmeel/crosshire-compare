# tests/test_column_facts.py
"""The extended column profile: column_facts over any relation, and the bucket's facts over HTTP."""
import duckdb

from tablecmp.column_facts import column_facts
from tests.webkit import COUNTS, auto_run, c  # noqa: F401


def _con():
    con = duckdb.connect()
    con.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        ('Finance', '10', '2024-01-02', 'AB-1001-UK'), ('finance ', '12', '2024-03-04', 'AB-1002-UK'),
        ('Sales', '14.5', NULL, 'CD-1003-US'), (NULL, NULL, '2024-02-01', 'AB-1004-UK'),
        ('', '9', '2023-12-31', 'EF-1005-DE')) v(dept, amount, day, ref)""")
    for i in range(30):                                   # ref past a category: starts and ends are read
        con.execute(f"INSERT INTO t VALUES ('Sales', '1', '2024-01-01', 'ZZ-{2000 + i}-UK')")
    return con


def test_facts_read_each_column_as_what_its_values_are():
    f = column_facts(_con(), "t", ["dept", "amount", "day", "ref"])
    d = f["dept"]
    assert d["rows"] == 35 and d["nulls"] == 2 and d["null_pct"] == 5.71      # a blank counts as null
    assert d["top"] == {"value": "Sales", "n": 31, "pct": 88.57}
    assert d["length"] == {"min": 5, "max": 7} and d["number"] is None and d["date"] is None
    assert d["spellings"] == [{"members": ["Finance", "finance"], "rows": 2, "why": "differ only in case"}]
    assert d["prefixes"] == [] and d["suffixes"] == []                       # a category: no starts or ends
    assert f["amount"]["number"] == {"min": 1.0, "max": 14.5, "mean": 2.2206} and f["amount"]["shapes"] == []
    assert f["day"]["date"]["min"].startswith("2023-12-31") and f["day"]["length"] is None
    r = f["ref"]
    assert r["shapes"][0] == {"shape": "AA-9999-AA", "n": 35, "pct": 100.0}
    assert r["suffixes"][0] == {"value": "-UK", "n": 33, "pct": 94.29}
    assert r["prefixes"][0]["value"] == "ZZ-"


def test_no_columns_no_facts():
    assert column_facts(_con(), "t", []) == {}


def test_a_bucket_gives_its_facts_a_side_each(c):
    run = auto_run(c)["run"]
    base = f"/api/results/{run['id']}/buckets"
    plain = c.get(f"{base}/differ").json()
    d = c.get(f"{base}/differ/facts").json()
    assert d["bucket"] == "differ"
    assert [x["column"] for x in d["columns"]] == plain["shown"]               # the same columns as the simple view
    one = d["columns"][0]
    assert [s["side"] for s in one["sides"]] == ["A", "B"]
    assert all(s["rows"] == int(COUNTS["diff_rows"]) for s in one["sides"])
    assert {"nulls", "null_pct", "distinct", "top", "shapes", "spellings"} <= set(one["sides"][0])
    extra = plain["others"][0]["name"]
    more = c.get(f"{base}/differ/facts", params={"add": [extra]}).json()
    assert extra in [x["column"] for x in more["columns"]]
    only = c.get(f"{base}/differ/facts", params={"add": [extra], "exact": "true"}).json()
    assert [x["column"] for x in only["columns"]] == [extra]
    assert c.get(f"{base}/nope/facts").status_code == 404


def test_a_one_sided_bucket_gives_one_side(c):
    run = auto_run(c)["run"]
    base = f"/api/results/{run['id']}/buckets"
    d = c.get(f"{base}/left/facts").json()
    assert d["columns"] and all([s["side"] for s in x["sides"]] == ["A"] for x in d["columns"])
