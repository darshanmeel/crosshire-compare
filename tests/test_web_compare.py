# tests/test_web_compare.py
"""Compare and Auto over HTTP: where the comparison stands, the settings it keeps, a run as a job,
stale or not, what a new side does to it, and a config that loads and compares."""
import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi import HTTPException

from tablecmp import comparing, results
from tablecmp.web import runs
from tests.webkit import (COLS, COUNTS, EX, FAKE_PW, W, auto_run, c, compare, load_pair,  # noqa: F401
                          newest, seed_table, state, wait, ws_of)


def test_before_anything_is_loaded(c):
    s = state(c)
    assert s["gate"] == "load" and s["run"] is None and s["busy"] is False
    assert s["strip"] == {"cells": {"Files": "0 of 2 loaded", "Columns": "-", "Key": "-", "Compare": "-",
                                    "Result": "-"}, "tones": {"Files": "warn"}}
    assert s["settings"] == {"display_rows": 1000, "auto_rerun": False, "out_fmt": "csv", "auto_profile": False}
    r = c.post("/api/compare", headers=W)
    assert r.status_code == 409 and r.json()["detail"] == "Load A and B in the sidebar first."
    assert c.post("/api/auto", headers=W).status_code == 409


def test_the_settings_are_kept_and_checked(c):
    r = c.put("/api/compare/settings", json={"display_rows": 500, "auto_rerun": True, "out_fmt": "parquet"}, headers=W)
    assert r.json() == {"display_rows": 500, "auto_rerun": True, "out_fmt": "parquet", "auto_profile": False}
    assert state(c)["settings"]["display_rows"] == 500
    assert ws_of(c).data["settings"]["display_rows"] == 500          # beside phase 3's switches
    assert c.put("/api/compare/settings", json={"display_rows": 50}, headers=W).status_code == 422
    assert c.put("/api/compare/settings", json={"out_fmt": "xlsx"}, headers=W).status_code == 422


def test_the_gates_before_a_run(c):
    load_pair(c)
    s = state(c)
    assert s["gate"] == "pair" and s["strip"]["tones"]["Columns"] == "warn"
    seed_table(c, [COLS[0], {**COLS[1], "compare": False}])
    s = state(c)
    assert s["gate"] == "tick" and s["strip"]["cells"]["Compare"] == "none"
    r = c.post("/api/compare", headers=W)
    assert r.status_code == 409 and r.json()["detail"] == comparing.TICK_COMPARE
    seed_table(c)
    s = state(c)
    assert s["gate"] == "" and s["run"] is None and s["strip"]["cells"]["Result"] == "press Compare"
    assert s["names"] == ["Left", "Right"] and s["sig"]
    ws_of(c).data["names"] = {"A": "HR", "B": "Right"}                # the boxes, as the page PUTs them
    assert state(c)["names"] == ["HR", "Right"]


def test_auto_works_it_out_and_compares(c):
    s = auto_run(c)
    run = s["run"]
    ws = ws_of(c)
    r = ws.data["result"]["result"]
    assert (r.matched_rows, r.only_left, r.only_right, r.diff_rows, r.cell_diffs) == tuple(
        int(COUNTS[k]) for k in ("matched", "only_left", "only_right", "diff_rows", "cells"))
    assert run["keys"] == [COUNTS["key"]] and run["pair"] == "Left_compare_Right" and run["stale"] is False
    assert s["strip"]["cells"]["Key"] == COUNTS["key"] and s["said"] == [] and s["busy"] is False
    words = "".join(x["text"] for x in run["verdict"]["segments"])
    assert f"rows matched on {COUNTS['key']}" in words and run["verdict"]["word"]
    log = c.get("/api/log").json()["entries"][::-1]                         # oldest first
    kinds = [e["kind"] for e in log]
    assert kinds.index("Auto") < kinds.index("Auto decisions") < kinds.index("Compare")
    auto = log[kinds.index("Auto")]
    assert auto["label"].startswith("Worked out in ") and auto["label"].endswith(f"key: {COUNTS['key']} - comparing now")
    assert log[kinds.index("Compare")]["label"].startswith("Compared in ")
    assert ws.data["cmap_rev"] >= 1 and ws.data["auto_notes"]               # put_table: a new version of the table
    folder, pair = Path(ws.data["result"]["folder"]), run["pair"]
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "report.html", "diff.html", "config.json"):
        assert (folder / f"{pair}__{suffix}").exists(), suffix
    assert not (folder / f"{pair}__paired.csv").exists()     # written when asked for, not as the run goes
    conf = json.loads((folder / f"{pair}__config.json").read_text(encoding="utf-8"))
    assert conf["sides"]["A"]["name"] == "Left"
    blob = json.dumps([s, c.get("/api/log").json(), c.get("/api/sources").json()])
    blob += "".join(p.read_text(encoding="utf-8", errors="ignore") for p in folder.iterdir()
                    if p.suffix in (".csv", ".json", ".html"))
    assert FAKE_PW not in blob


def test_a_change_makes_the_run_stale_and_compare_brings_it_up_to_date(c):
    auto_run(c)
    ws = ws_of(c)
    first = ws.data["result"]
    c.put("/api/compare/settings", json={"display_rows": 500, "out_fmt": "both"}, headers=W)
    assert state(c)["stale"] is False                                    # what is shown is not a setting
    ws.data.setdefault("settings", {})["tolerance"] = 0.5                # How values are read - phase 3's box
    s = state(c)
    assert s["stale"] is True and s["run"]["stale"] is True and s["strip"]["cells"]["Result"].endswith(" · stale")
    assert s["strip"]["tones"]["Result"] == "warn"
    e = compare(c)
    assert e["state"] == "done" and e["label"].startswith("Compared in ")
    s = state(c)
    assert s["stale"] is False and s["run"]["id"] != first["run_id"]
    assert not Path(first["folder"]).exists()
    with pytest.raises(duckdb.Error):                                    # closed, not left to the GC
        first["con"].execute("SELECT 1")


def test_a_bad_filter_refuses_the_run_in_a_sentence(c):
    load_pair(c)
    seed_table(c)
    ws_of(c).data["filter_rows"] = pd.DataFrame([{"Apply to": "Both", "Column": "department",
                                                  "Operator": "between", "Value": "3000", "Type": "number"}])
    s = state(c)
    assert "between" in s["filter_error"]
    r = c.post("/api/compare", headers=W)
    assert r.status_code == 400 and r.json()["detail"] == s["filter_error"]
    assert ws_of(c).data.get("result") is None


def test_compare_twice_runs_once(c):
    load_pair(c)
    seed_table(c)
    ws = ws_of(c)
    with ws.lock:                        # holds the job back, as a long Profile would
        first = c.post("/api/compare", headers=W)
        again = c.post("/api/compare", headers=W)
        auto = c.post("/api/auto", headers=W)
    assert first.status_code == 200
    assert again.status_code == 409 and again.json()["detail"] == runs.BUSY and auto.status_code == 409
    assert wait(c, first.json())["state"] == "done"
    assert [e["kind"] for e in c.get("/api/log").json()["entries"]].count("Compare") == 1


def test_a_failed_run_keeps_the_last_one_and_says_why(c, monkeypatch):
    first = auto_run(c)["run"]["id"]

    def boom(*_a, **_k):
        raise RuntimeError("no such column x")
    monkeypatch.setattr(comparing, "run_comparison", boom)
    ws_of(c).data.setdefault("settings", {})["tolerance"] = 0.5
    e = compare(c)
    msg = "The comparison failed: no such column x - the previous result is still shown below."
    assert e["state"] == "error" and "could not finish" in e["label"] and e["lines"][-1] == msg
    s = state(c)
    assert s["run"]["id"] == first and s["said"] == [{"tone": "error", "text": msg}] and s["stale"] is True


def test_a_new_side_drops_the_run_and_closes_its_connection(c):
    auto_run(c)
    run = ws_of(c).data["result"]
    r = c.post("/api/sources/B/load", json={"how": "path", "path": str(EX / "payroll_employees.csv"),
                                            "name": "Right"}, headers=W)
    assert r.status_code == 200
    assert "result" not in ws_of(c).data and state(c)["run"] is None
    with pytest.raises(duckdb.Error):
        run["con"].execute("SELECT 1")


def test_a_replaced_or_swept_run_is_said_not_crashed(c, tmp_path):
    auto_run(c)
    ws = ws_of(c)
    run = ws.data["result"]
    with pytest.raises(HTTPException) as e:
        runs.run_of(ws, "19990101-000000")
    assert e.value.status_code == 404 and e.value.detail == runs.REPLACED
    assert runs.run_of(ws, run["run_id"]) is run
    with pytest.raises(HTTPException) as e:
        with runs.guard({"folder": str(tmp_path)}, "Summary"):
            raise ValueError("bad")
    assert e.value.status_code == 400 and e.value.detail == "Could not build the Summary view: bad"
    shutil.rmtree(run["folder"])
    with pytest.raises(HTTPException) as e:
        with runs.guard(run, "Summary"):
            raise OSError("gone")
    assert e.value.status_code == 410 and e.value.detail == results.GONE


def test_a_config_loads_both_sides_and_compares(c):
    conf = {"kind": "crosshire-compare config", "version": 1,
            "sides": {"A": {"name": "HR", "path": str(EX / "hr_employees.csv")},
                      "B": {"name": "PR", "path": str(EX / "payroll_employees.csv")}},
            "columns": COLS, "settings": {"trim": True}, "filters": []}
    e = wait(c, c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W).json())
    assert e["state"] == "done"
    said = c.get("/api/sources").json()["config"]["said"]
    assert said == [{"tone": "success", "text": "Loaded - HR against PR, 2 pairs; comparing"}]
    assert wait(c, newest(c, "Compare"))["state"] == "done"
    s = state(c)
    assert s["names"] == ["HR", "PR"] and s["run"]["pair"] == "HR_compare_PR" and s["stale"] is False
