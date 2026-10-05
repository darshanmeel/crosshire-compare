# tests/test_web_setup.py
"""The column table over HTTP: built for the loaded pair, changed a cell at a time, Match by
data, Reset, Save and Load mapping, the names and the card."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

W = {"X-Compare": "1"}
EX = Path(__file__).resolve().parent.parent / "examples"
HR, PR = EX / "hr_employees.csv", EX / "payroll_employees.csv"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


def load(c, tag, path, name):
    r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
    assert r.status_code == 200, r.text


@pytest.fixture
def both(c):
    load(c, "A", HR, "HR")
    load(c, "B", PR, "PR")
    return c


def cell(c, view, row, column, value):
    return c.post("/api/setup/cell", json={"rev": view["rev"], "row": row, "column": column, "value": value},
                  headers=W)


def test_nothing_until_both_sides_are_loaded(c):
    assert c.get("/api/setup").json() == {"ready": False, "names": ["Left", "Right"]}
    load(c, "A", HR, "HR")
    assert c.get("/api/setup").json()["ready"] is False
    r = c.post("/api/setup/cell", json={"rev": "x", "row": 0, "column": "Key", "value": True}, headers=W)
    assert r.status_code == 409 and r.json()["detail"] == "Load A and B first."


def test_the_table_is_built_for_the_pair(both):
    v = both.get("/api/setup").json()
    assert v["ready"] and v["names"] == ["HR", "PR"] and v["pairs"] == 5
    assert [r["A column"] for r in v["rows"]][:5] == ["emp_id", "last_name", "salary", "hire_date", "active"]
    assert v["rows"][5] == {**v["rows"][5], "Role": "only in HR", "tone": "neg", "B column": ""}
    assert v["rows"][4]["B looks like"] == "boolean · Y/N"
    assert v["columns"]["B"][0] == "EmployeeId" and "timestamp" in v["types"] and v["cases"] == ["", "ignore", "exact"]
    assert {"text": "Dept · only in PR", "cls": "off"} in v["chips"]
    assert [x["label"] for x in v["card"]] == ["Paired", "Key", "Compare", "Read as", "Only in HR", "Only in PR"]
    assert v["specs"][2] == {**v["specs"][2], "canon": "salary", "kind": "number", "a_steps": [], "describe": "number"}
    assert v["can_match"] and v["data_match"] is None and v["settings"]["nokey_mode"] == "hash"
    assert both.get("/api/setup").json()["rev"] == v["rev"]          # a read changes nothing


def test_a_cell_changes_and_the_table_comes_back_whole(both):
    v = both.get("/api/setup").json()
    r = cell(both, v, 0, "Key", True)
    assert r.status_code == 200
    v2 = r.json()
    assert v2["keys"] == ["emp_id"] and v2["rows"][0]["Role"] == "key" and v2["rev"] != v["rev"]
    v3 = cell(both, v2, 1, "B column", "").json()                    # last_name gives FullName back
    assert len(v3["rows"]) == len(v2["rows"]) + 1 and v3["pairs"] == 4
    assert any(r["B column"] == "FullName" and r["Role"] == "only in PR" for r in v3["rows"])


def test_an_edit_on_a_table_that_changed_since_is_refused(both):
    from tablecmp.web import setupws as sw
    v = both.get("/api/setup").json()
    cell(both, v, 0, "Key", True)
    r = cell(both, v, 1, "Compare", False)                           # sent with the old rev
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    ws = ws_of(both)
    now = both.get("/api/setup").json()
    sw.put_table(ws, ws.data["cmap"].copy())                         # swapped in whole by another route
    assert cell(both, now, 1, "Compare", False).status_code == 409


def test_a_cell_that_cannot_change_is_a_sentence(both):
    v = both.get("/api/setup").json()
    r = cell(both, v, 0, "Matched by", "you")
    assert r.status_code == 400 and "worked out" in r.json()["detail"]
    assert cell(both, v, 99, "Key", True).status_code == 400


def test_match_by_data_then_apply_or_dismiss(both):
    v = both.post("/api/setup/match", headers=W).json()
    assert v["data_match"]["pairs"] == 1 and v["data_match"]["columns"][:2] == ["HR column", "PR column"]
    assert v["data_match"]["rows"][0][:2] == ["department", "Dept"]
    assert both.delete("/api/setup/match", headers=W).json()["data_match"] is None
    both.post("/api/setup/match", headers=W)
    v = both.post("/api/setup/match/apply", headers=W).json()
    assert v["data_match"] is None and v["pairs"] == 6
    row = next(r for r in v["rows"] if r["A column"] == "department")
    assert row["B column"] == "Dept" and row["Matched by"] == "data"
    assert both.post("/api/setup/match/apply", headers=W).status_code == 409


def test_reset_and_the_mapping_round_trip(both):
    v = both.get("/api/setup").json()
    v = cell(both, v, 0, "Key", True).json()
    saved = both.get("/api/setup/mapping")
    assert saved.headers["content-disposition"] == 'attachment; filename="mapping.json"'
    assert json.loads(saved.text)["columns"][0] == {**json.loads(saved.text)["columns"][0], "a": "emp_id", "key": True}
    assert both.post("/api/setup/reset", headers=W).json()["keys"] == []
    back = both.post("/api/setup/mapping", json={"text": saved.text}, headers=W).json()
    assert back["keys"] == ["emp_id"] and back["rows"][0]["Matched by"] == "file"
    bad = both.post("/api/setup/mapping", json={"text": "{nope"}, headers=W)
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Could not read the mapping file:")


def test_the_names_the_page_sends(both):
    v = both.put("/api/setup/names", json={"A": "Left", "B": "Payroll"}, headers=W).json()
    assert v["names"] == ["HR", "Payroll"]                           # a box at its default: the side's own name
    assert v["card"][-1]["label"] == "Only in Payroll"
    v = both.put("/api/setup/names", json={"A": "X", "B": "X"}, headers=W).json()
    assert v["names"] == ["A · X", "B · X"]


def test_a_new_side_builds_a_new_table(both):
    v = cell(both, both.get("/api/setup").json(), 0, "Key", True).json()
    assert v["keys"] == ["emp_id"]
    load(both, "B", PR, "PR")                                        # loaded again: the table starts afresh
    assert both.get("/api/setup").json()["keys"] == []


# ---- C1: a filter value never reaches SQL as text ----------------------------------------------
STACKED = "1; COPY (SELECT 42) TO '{out}'; SELECT 1 WHERE 1=1"


def _bad_filters(out):
    return [{"Apply to": "Both", "Column": "emp_id", "Operator": "=", "Value": STACKED.format(out=out),
             "Type": "string"},
            {"Apply to": "Both", "Column": "emp_id", "Operator": ">", "Value": "5", "Type": "number"}]


def test_filters_that_mix_text_and_number_on_one_column_are_said(both, tmp_path):
    out = tmp_path / "pwned.csv"
    r = both.put("/api/setup/filters", json={"rows": _bad_filters(out)}, headers=W)
    assert r.status_code == 200 and "emp_id" in r.json()["error"] and "number" in r.json()["error"]
    g = both.post("/api/compare", json={}, headers=W)
    assert g.status_code == 400 and "emp_id" in g.json()["detail"]
    assert not out.exists()


def test_a_config_with_those_filters_never_writes_a_file(c, tmp_path):
    from tests.test_web_sources import _conf, wait
    out = tmp_path / "pwned.csv"
    conf, path = _conf(tmp_path)
    conf["settings"] = {"mode": "hash"}
    conf["columns"][0].update(key=False, compare=True)
    conf["filters"] = _bad_filters(out)
    path.write_text(json.dumps(conf), encoding="utf-8")
    wait(c, c.post("/api/sources/config", json={"path": str(path)}, headers=W).json())
    for e in c.get("/api/log").json()["entries"]:
        if e["kind"] == "Compare":
            wait(c, e)
    assert not out.exists()


# ---- races: the version, the freshness check, the job's reads, the filters -----------------------
def _job(c, kind):
    from tests.test_web_sources import wait
    return wait(c, next(e for e in c.get("/api/log").json()["entries"] if e["kind"] == kind))


def test_the_rev_is_a_counter_and_a_config_bumps_it(c, tmp_path):
    from tests.test_web_sources import _conf, wait
    load(c, "A", HR, "HR")
    load(c, "B", PR, "PR")
    before = c.get("/api/setup").json()["rev"]
    assert "." not in before                                           # no id() in it
    _, path = _conf(tmp_path)
    wait(c, c.post("/api/sources/config", json={"path": str(path)}, headers=W).json())
    assert ws_of(c).data["cmap_rev"] > int(before)
    assert cell(c, {"rev": before}, 0, "Key", True).status_code == 409


def test_a_table_put_in_while_a_get_waited_for_the_lock_is_kept(both):
    import threading
    import time
    from tablecmp.web import setupws as sw
    ws = ws_of(both)
    both.get("/api/setup")
    ws.data.pop("cmap")
    seen = {}
    ready = threading.Event()

    def holder():
        with ws.lock:
            ready.set()
            time.sleep(0.4)
            sw.table(ws)                                                # the job's table is in ...
            ws.data["cmap"] = ws.data["cmap"].assign(Compare=False)     # ... changed the way a config would
            ws.data["marker"] = True

    t = threading.Thread(target=holder)
    t.start()
    ready.wait()
    seen["t"] = sw.table(ws)                                            # decided "fresh" before the holder is done
    t.join()
    assert not seen["t"]["Compare"].any()


def test_suggest_keys_reads_the_pair_inside_the_job(both):
    ws = ws_of(both)
    both.get("/api/setup")
    with ws.lock:
        r = both.post("/api/setup/keys/suggest", headers=W)
        assert r.status_code == 200
        ws.data.pop("cmap")                                             # a side was loaded meanwhile
    e = _job(both, "Key search")
    assert e["state"] == "done", e["lines"]


def test_profile_reads_the_pair_inside_the_job(both):
    ws = ws_of(both)
    both.get("/api/setup")
    with ws.lock:
        assert both.post("/api/setup/profile", headers=W).status_code == 200
        ws.data.pop("cmap")
    e = _job(both, "Profile")
    assert e["state"] == "done", e["lines"]


def test_a_job_that_fails_for_another_reason_says_a_sentence(both, monkeypatch):
    from tablecmp.web import routes_setup as rs

    def boom(*a, **k):
        raise KeyError("cmap")
    monkeypatch.setattr(rs, "suggest_keys", boom)
    both.get("/api/setup")
    both.post("/api/setup/keys/suggest", headers=W)
    e = _job(both, "Key search")
    assert e["state"] == "error" and "'cmap'" not in " ".join(e["lines"])
    assert any(l.startswith("Could not measure the columns") for l in e["lines"])


def test_filters_carry_a_version_and_a_stale_put_is_refused(both):
    f = both.get("/api/setup/filters").json()
    row = {"Apply to": "Both", "Column": "department", "Operator": "=", "Value": "Finance", "Type": "auto"}
    one = both.put("/api/setup/filters", json={"rows": [row], "rev": f["rev"]}, headers=W)
    assert one.status_code == 200 and one.json()["rev"] != f["rev"]
    two = both.put("/api/setup/filters", json={"rows": [{**row, "Value": "x"}], "rev": f["rev"]}, headers=W)
    assert two.status_code == 409 and two.json()["detail"] == "The filters changed since - they are shown again as they are now."
    assert both.get("/api/setup/filters").json()["rows"][0]["Value"] == "Finance"


def test_apply_on_a_column_no_longer_paired_says_so(both):
    from tablecmp import keying as kg
    ws = ws_of(both)
    both.get("/api/setup")
    fx = kg.Fix("gone", [], [], False, "leading zeros", 0.5, 1.0)
    ws.data["key_formats"] = (("gone",), [(fx, False)])
    r = both.post("/api/setup/keys/formats/0/apply", headers=W)
    assert r.status_code == 200 and "no longer paired" in r.json()["error"]


def test_a_config_drops_the_old_pairs_looks_like_sample(c, tmp_path):
    from tests.test_web_sources import _conf, wait
    load(c, "A", HR, "HR")
    load(c, "B", PR, "PR")
    c.get("/api/setup")
    ws = ws_of(c)
    ws.data["looks_like"] = {"A": {"stale": "x"}, "B": {}}
    _, path = _conf(tmp_path)
    wait(c, c.post("/api/sources/config", json={"path": str(path)}, headers=W).json())
    assert "stale" not in (ws.data.get("looks_like") or {}).get("A", {})
