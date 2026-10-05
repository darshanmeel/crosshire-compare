# tests/test_web_pairs.py
"""The two reads the results head added: the value pairs behind one column's mismatches (Why they
differ, on the Summary) and a page of the one-sided rows (One-sided rows tab)."""
from tests.webkit import COUNTS, auto_run, c  # noqa: F401


def test_pairs_count_a_columns_mismatches_most_frequent_first(c):
    run = auto_run(c)["run"]
    summary = c.get(f"/api/results/{run['id']}/summary").json()
    led = summary["ledger"]
    cols = led["columns"]
    worst = max((r for r in led["rows"] if r[cols.index("Role")] == "compared"),
                key=lambda r: r[cols.index("Mismatched")] or 0)
    column, bad = worst[cols.index("Column")], int(worst[cols.index("Mismatched")])
    d = c.get(f"/api/results/{run['id']}/pairs/{column}", params={"limit": 3}).json()
    assert d["column"] == column and d["mismatches"] == bad and 0 < d["distinct"] <= bad
    assert 0 < len(d["pairs"]) <= 3
    ns = [p["n"] for p in d["pairs"]]
    assert ns == sorted(ns, reverse=True) and all(set(p) == {"a", "b", "n"} for p in d["pairs"])
    assert c.get(f"/api/results/{run['id']}/pairs/nowhere").status_code == 404
    assert c.get(f"/api/results/{run['id']}/pairs/{column}", params={"limit": 0}).status_code == 422


def test_one_sided_rows_come_a_page_at_a_time(c):
    run = auto_run(c)["run"]
    base = f"/api/results/{run['id']}/one-sided"
    a = c.get(f"{base}/A", params={"limit": 6}).json()
    assert a["total"] == int(COUNTS["only_left"]) and len(a["rows"]) == 6 and a["offset"] == 0
    assert a["file"].endswith("__left_only.csv") and a["columns"] and a["keys"]
    assert a["keys"][0] in a["columns"]
    assert a["groups"][0]["title"] == "Key columns" and a["groups"][0]["items"] == [k for k in a["columns"] if k in a["keys"]]
    assert sorted(c for g in a["groups"] for c in g["items"]) == sorted(a["columns"])
    assert a["shown"][:len(a["keys"])] == a["groups"][0]["items"] and len(a["shown"]) == len(a["keys"]) + 3
    mine = next((g["items"] for g in a["groups"] if g["title"] == "Not compared"), [])
    assert mine and not set(a["shown"]) & set(mine)                                # the side's own columns wait until ticked
    rest = c.get(f"{base}/A", params={"offset": 6, "limit": 1000}).json()
    assert len(rest["rows"]) == a["total"] - 6
    b = c.get(f"{base}/B").json()
    assert b["total"] == int(COUNTS["only_right"]) and b["file"].endswith("__right_only.csv")
    assert b["keys"] and b["keys"][0] in b["columns"]
    assert all(x["column"] not in b["keys"] for x in b["constant"])
    for x in b["constant"]:
        i = b["columns"].index(x["column"])
        assert {str(r[i]) for r in b["rows"]} == {x["value"]}
    assert c.get(f"{base}/C").status_code == 404
