# tests/test_web_results.py
"""The results views over HTTP: Summary with Profile by bucket, Columns & values, near-match -
read from the run on the page, and said in a sentence when that run is gone."""
import shutil

from tablecmp import results
from tests.webkit import COUNTS, W, auto_run, c, compare, state, ws_of  # noqa: F401


def test_the_summary_opens_with_the_key(c):
    run = auto_run(c)["run"]
    s = c.get(f"/api/results/{run['id']}/summary").json()
    key, matched, diff = COUNTS["key"], int(COUNTS["matched"]), int(COUNTS["diff_rows"])
    assert s["mode"] == "key" and s["keys"] == [key]
    assert s["key_line"] == f"Rows are matched on **{key}** - **{matched:,}** rows matched"
    assert [m["label"] for m in s["counts"]] == ["Rows Left", "Rows Right", "Matched on key", "Only in Left",
                                                 "Only in Right", "Rows that differ"]
    assert s["counts"][2]["value"] == matched and s["counts"][5]["value"] == diff
    assert s["counts"][5]["help"] == "Matched rows where at least one compared column differs"
    assert [m["label"] for m in s["column_counts"]] == ["Key", "Compared", "Not compared", "Only in Left",
                                                        "Only in Right"]
    assert [m["label"] for m in s["overall"]] == ["Overall match %", "Fully matched rows", "Rows with differences"]
    roles = [r[s["ledger"]["columns"].index("Role")] for r in s["ledger"]["rows"]]
    assert roles[0] == "key" and s["tones"][0] == "pos" and len(s["tones"]) == len(roles)
    assert [b["id"] for b in s["buckets"]][:2] == ["matched", "differ"] and s["default_bucket"] == "differ"
    assert s["buckets"][1]["label"] == f"Matched but different ({diff:,})"


def test_a_bucket_counts_its_rows_and_adds_what_is_asked_for(c):
    run = auto_run(c)["run"]
    base, key = f"/api/results/{run['id']}/buckets", COUNTS["key"]
    d = c.get(f"{base}/differ").json()
    assert d["by_key"]["title"].startswith("**By key value** - where the :red[") and d["by_key"]["tables"]
    assert key not in [p["column"] for p in d["profiles"]] + [o["name"] for o in d["others"]]   # in By key value
    extra = d["others"][0]["name"]
    assert d["others_title"] == f"Other columns - {len(d['others'])} to add"
    more = c.get(f"{base}/differ", params={"add": [extra]}).json()
    assert extra in [p["column"] for p in more["profiles"]] and extra not in [p["column"] for p in d["profiles"]]
    assert [g["title"] for g in d["groups"]][0] == "Mismatched columns"          # the key has its own tables
    assert d["shown"] == [p["column"] for p in d["profiles"]] == [o["name"] for o in d["groups"][0]["items"]]   # every mismatched column
    one = c.get(f"{base}/differ", params={"add": [extra], "exact": True}).json()
    assert [p["column"] for p in one["profiles"]] == [extra]                       # a default can be unticked
    assert c.get(f"{base}/differ", params={"exact": True}).json()["empty"]
    left = c.get(f"{base}/left").json()
    assert left["groups"][0] == {"title": "Key columns", "items": [{"name": key, "label": key}]}
    assert left["by_key"] is None and left["profiles"] and left["empty"] == ""
    assert left["profiles"][0]["column"] == key and left["profiles"][0]["title"] == f"**{key}** · key"
    assert c.get(f"{base}/nowhere").status_code == 404


def test_columns_and_values_open_the_worst_first(c, monkeypatch):
    run = auto_run(c)["run"]
    monkeypatch.setattr(results, "COLUMN_CARDS", 1)          # so some columns wait under Other columns
    url, diff = f"/api/results/{run['id']}/columns", int(COUNTS["diff_rows"])
    d = c.get(url).json()
    assert d["hash_caption"] == "" and d["differ_error"].startswith("**")
    assert d["rows"]["title"] == (f"Rows that differ - Left above Right, differing cells marked · "
                                  f"first {min(1000, diff):,} of {diff:,}")
    t = d["rows"]["table"]
    assert t["columns"][0] == "Side" and [r[0] for r in t["rows"][:2]] == ["A", "B"] and d["rows"]["marks"]["0"]
    assert len(d["cards"]) == 1 and d["cards"][0]["head"].startswith(":red[**")
    assert d["cards"][0]["pairs"]["columns"][2:] == ["Count", "%"] and d["near_match"] is True
    assert d["rest"] and d["rest_title"] == f"Other columns - {len(d['rest'])} not open"
    more = c.get(url, params={"open": [d["rest"][0]]}).json()
    assert [x["column"] for x in more["cards"]] == [d["cards"][0]["column"], d["rest"][0]]
    c.put("/api/compare/settings", json={"display_rows": 500}, headers=W)
    assert f"first {min(500, diff):,} of" in c.get(url).json()["rows"]["title"]
    nm = c.get(f"/api/results/{run['id']}/near-match").json()
    assert nm["columns"] == ["Column", "Mismatches", "Avg edit distance", "Similarity %"] and nm["rows"]


def test_without_a_key_there_are_no_differing_rows_to_show(c):
    auto_run(c)
    ws = ws_of(c)
    cmap = ws.data["cmap"].copy()
    cmap["Key"] = False
    ws.data["cmap"] = cmap
    ws.data.setdefault("settings", {})["nokey_mode"] = "hash"
    assert compare(c)["state"] == "done"
    run = state(c)["run"]
    s = c.get(f"/api/results/{run['id']}/summary").json()
    assert s["mode"] == "hash" and s["key_line"].startswith("No key - rows were matched by hashing the ")
    assert s["overall"] is None and s["hash_caption"].startswith("Distinct values present on one side only")
    assert "differ" not in [b["id"] for b in s["buckets"]]
    d = c.get(f"/api/results/{run['id']}/columns").json()
    assert d == {"hash_caption": "With hashing there are no matched-but-different rows: a row is either "
                                 "identical on the other side or one-sided. The one-sided rows are below."}


def test_an_old_or_swept_run_is_said_in_a_sentence(c):
    run = auto_run(c)["run"]
    r = c.get("/api/results/19990101-000000/summary")
    assert r.status_code == 404 and r.json()["detail"].startswith("This run is not the one on the page")
    shutil.rmtree(ws_of(c).data["result"]["folder"])
    r = c.get(f"/api/results/{run['id']}/near-match")
    assert r.status_code == 410 and r.json()["detail"].startswith("The files of this run are gone")
