"""The Key section and Profile both files over HTTP: Suggest keys and the profile as jobs, Use as
key, Check key, a key written differently fixed or offered, the profile and its frequencies."""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.values import steps_from_json
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

W = {"X-Compare": "1"}
EX = Path(__file__).resolve().parent.parent / "examples"
HR, PR = EX / "hr_employees.csv", EX / "payroll_employees.csv"


def client(tmp_path, monkeypatch, a, b):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    c = TestClient(create_app())
    c.get("/api/workspace")
    for tag, path, name in (("A", a, "HR"), ("B", b, "PR")):
        r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
        assert r.status_code == 200, r.text
    return c


@pytest.fixture
def c(tmp_path, monkeypatch):
    return client(tmp_path, monkeypatch, HR, PR)


@pytest.fixture
def codes(tmp_path, monkeypatch):
    """emp_code written 'AB 7' on A and 'AB7' on B; ref carries a prefix on A only."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("emp_code,ref,salary\n" + "".join(f"AB {i},R-{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    b.write_text("emp_code,ref,salary\n" + "".join(f"AB{i},{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    return client(tmp_path, monkeypatch, a, b)


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


def wait(c, entry, seconds=120):
    t0 = time.time()
    while True:
        e = c.get(f"/api/jobs/{entry['id']}").json()
        if e["state"] != "running" or time.time() - t0 > seconds:
            return e
        time.sleep(0.05)


def steps_of(c, canon, which):
    spec = next(s for s in c.get("/api/setup").json()["specs"] if s["canon"] == canon)
    return spec[f"{which.lower()}_steps"]


def test_no_key_yet_and_the_pairing_without_one(c):
    k = c.get("/api/setup/keys").json()
    assert k["keys"] == [] and k["mode"] == "hash" and k["suggestions"] is None and k["report"] is None
    assert set(k["nokey_modes"]) == {"hash", "position"} and k["formats"] == []
    c.put("/api/setup/settings", json={"nokey_mode": "position"}, headers=W)
    assert c.get("/api/setup/keys").json()["mode"] == "position"
    assert c.post("/api/setup/keys/check", headers=W).status_code == 409


def test_suggest_keys_is_a_job_and_use_as_key_ticks_it(c):
    e = wait(c, c.post("/api/setup/keys/suggest", headers=W).json())
    assert e["state"] == "done" and e["kind"] == "Key search" and e["label"].startswith("Best key: emp_id in ")
    k = c.get("/api/setup/keys").json()
    s = k["suggestions"]
    assert s["said"]["tone"] == "success" and s["labels"][0] == "emp_id" and s["columns"][0] == "Key columns"
    assert c.post("/api/setup/keys/use", json={"picks": []}, headers=W).status_code == 400
    k = c.post("/api/setup/keys/use", json={"picks": [0]}, headers=W).json()
    assert k["keys"] == ["emp_id"] and k["mode"] == "key" and k["suggestions"] is None and k["error"] == ""
    assert c.get("/api/setup").json()["rows"][0]["Role"] == "key"
    assert k["formats"] == [{"tone": "caption", "text": "Key formats checked (emp_id): the two sides write them alike.",
                             "apply": None}]


def test_check_key_counts_on_both_sides(c):
    v = c.get("/api/setup").json()
    c.post("/api/setup/cell", json={"rev": v["rev"], "row": 0, "column": "Key", "value": True}, headers=W)
    k = c.post("/api/setup/keys/check", headers=W).json()
    assert k["report"]["said"] == {"tone": "success", "text": "**emp_id** identifies a single row on both sides."}
    assert k["report"]["columns"] == ["Side", "Rows", "Distinct keys", "Duplicate rows", "Null keys", "Unique"]
    assert [r[:2] for r in k["report"]["rows"]] == [["HR", 3000], ["PR", 2985]]
    v = c.get("/api/setup").json()
    c.post("/api/setup/cell", json={"rev": v["rev"], "row": 2, "column": "Key", "value": True}, headers=W)
    assert c.get("/api/setup/keys").json()["report"] is None          # another key: that count is not its


def test_a_key_written_differently_is_fixed_or_offered(codes):
    v = codes.get("/api/setup").json()
    codes.post("/api/setup/cell", json={"rev": v["rev"], "row": 0, "column": "Key", "value": True}, headers=W)
    v = codes.get("/api/setup").json()
    codes.post("/api/setup/cell", json={"rev": v["rev"], "row": 1, "column": "Key", "value": True}, headers=W)
    k = codes.post("/api/setup/keys/check", headers=W).json()
    assert steps_of(codes, "emp_code", "A") == [{"op": "remove spaces", "params": {}}]
    applied, offered = k["formats"]
    assert applied["tone"] == "success" and applied["apply"] is None and "emp_code: " in applied["text"]
    assert offered["tone"] == "warning" and offered["apply"] == 1 and "ref: " in offered["text"]
    k = codes.post("/api/setup/keys/formats/1/apply", headers=W).json()
    assert k["formats"][1]["tone"] == "success"
    assert steps_from_json(ws_of(codes).data["cmap"].set_index("Common name").at["ref", "A steps"])[0]["op"] == \
        "regex replace"
    assert codes.delete("/api/setup/keys/formats", headers=W).json()["formats"] == []
    assert codes.post("/api/setup/keys/formats/0/apply", headers=W).status_code == 404


def test_profile_both_files_checks_the_key_like_columns_first(codes):
    e = wait(codes, codes.post("/api/setup/profile", headers=W).json())
    assert e["state"] == "done" and e["label"].startswith("Profile ready in ")
    assert "Checking whether emp_code, ref is written differently on the two sides…" in e["lines"]
    assert steps_of(codes, "emp_code", "A") == [{"op": "remove spaces", "params": {}}]
    p = codes.get("/api/setup/profile").json()
    assert p["stale"] is False and p["names"] == ["HR", "PR"]       # current for the fixed table
    assert p["both"]["columns"][:3] == ["Column", "Type", "Null % HR"] and p["A"]["columns"][0] == "Column"
    assert p["freq_columns"] == ["emp_code", "ref", "salary"] and p["freq_default"] == []
    f = codes.get("/api/setup/profile/freq", params={"col": "salary"}).json()
    assert f["title"] == "**salary** - number · HR: 40 distinct · PR: 40 distinct"
    assert f["A"]["top"]["columns"] == ["Value", "Count", "%"] and len(f["B"]["bottom"]["rows"]) == 10
    assert codes.get("/api/setup/profile/freq", params={"col": "nope"}).status_code == 404
    codes.put("/api/setup/settings", json={"trim": False}, headers=W)
    assert codes.get("/api/setup/profile").json()["stale"] is True   # other settings: run it again


def test_no_profile_until_one_is_made_and_a_reshaped_table_drops_it(c):
    assert c.get("/api/setup/profile").json() is None
    wait(c, c.post("/api/setup/profile", headers=W).json())
    assert c.get("/api/setup/profile").json() is not None
    v = c.get("/api/setup").json()
    c.post("/api/setup/cell", json={"rev": v["rev"], "row": 1, "column": "B column", "value": ""}, headers=W)
    assert c.get("/api/setup/profile").json() is None


def test_a_job_that_fails_says_so_in_the_log(c, monkeypatch):
    import duckdb
    import tablecmp.web.routes_setup as rs

    def boom(*a, **k):
        raise duckdb.IOException("disk gone for postgresql://me:hunter2@db/x")
    monkeypatch.setattr(rs, "profile_tables", boom)
    e = wait(c, c.post("/api/setup/profile", headers=W).json())
    assert e["state"] == "error" and e["lines"][-1].startswith("Profile failed:")
    assert "hunter2" not in c.get("/api/log").text


def test_no_answer_holds_a_typed_password(c):
    ws_of(c).passwords["SAMPLE"] = "typed-secret-77"
    wait(c, c.post("/api/setup/keys/suggest", headers=W).json())
    wait(c, c.post("/api/setup/profile", headers=W).json())
    for path in ("/api/setup", "/api/setup/keys", "/api/setup/profile", "/api/setup/filters",
                 "/api/setup/settings", "/api/log"):
        assert "typed-secret-77" not in c.get(path).text
