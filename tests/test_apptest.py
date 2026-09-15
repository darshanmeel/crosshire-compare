# tests/test_apptest.py
"""The whole app, headless: files in, Auto, compare, save - and the same through a DuckDB database."""
import json, os
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
COUNTS = dict(line.split("=") for line in (ROOT / "docs/superpowers/plans/COUNTS.md").read_text().split()
              if "=" in line)      # matched=... only_left=... only_right=... diff_rows=... cells=...
FAKE_PW = "hunter2-not-a-real-password"


def _boot(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.setenv("COMPARE_CONN_SAMPLE", "duckdb:///" + (EX / "sample.duckdb").as_posix())
    monkeypatch.setenv("COMPARE_CONN_FAKE", f"postgresql://u:{FAKE_PW}@nowhere:5432/db")
    at = AppTest.from_file(str(ROOT / "compare_app.py"), default_timeout=600)
    return _ok(at.run())


def _ok(at):
    """A script error shows as the traceback, not as a missing widget or result later."""
    assert not at.exception, at.exception
    return at


def _finish(at):
    _ok(at.button(key="auto_btn").click().run())
    at = _ok(at.run())                             # the auto_go rerun
    res = at.session_state["result"]
    r = res["result"]
    assert (r.matched_rows, r.only_left, r.only_right, r.diff_rows, r.cell_diffs) == tuple(
        int(COUNTS[k]) for k in ("matched", "only_left", "only_right", "diff_rows", "cells"))
    folder = Path(res["folder"])
    pair = res["pair"]
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "report.html", "diff.html", "profile.csv"):
        assert (folder / f"{pair}__{suffix}").exists(), suffix
    _ok(at.button(key="save_all").click().run())
    saved = list((Path(os.environ["COMPARE_OUT_DIR"])).glob(f"{pair}__*"))
    assert saved and (saved[0] / f"{pair}__summary.json").exists()
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in folder.iterdir() if p.suffix in (".csv", ".json", ".html"))
    assert FAKE_PW not in blob and "hunter2" not in blob
    return res


def test_file_flow(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        at.radio(key=f"how_{tag}").set_value("Path on disk").run()
        at.text_input(key=f"pt_{tag}").input(str(EX / f)).run()
        _ok(at.button(key=f"load_{tag}").click().run())
        assert at.session_state[tag].loaded, tag
    res = _finish(at)
    assert res["pair"] == "hr_employees_compare_payroll_employees"


def test_database_flow(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    for tag, table in (("A", "hr.employees"), ("B", "payroll.employees")):
        at.radio(key=f"how_{tag}").set_value("Database").run()
        at.selectbox(key=f"conn_{tag}").select("SAMPLE").run()
        at.radio(key=f"dbmode_{tag}").set_value("Table").run()
        at.text_input(key=f"tbl_{tag}").input(table).run()
        _ok(at.button(key=f"fetch_{tag}").click().run())
        at = _ok(at.run())                         # the rerun after the fetch shows fetched_{tag}
        assert at.session_state[f"fetched_{tag}"][0][0] == "SAMPLE", tag
        _ok(at.button(key=f"load_{tag}").click().run())
        side = at.session_state[tag]
        assert side.loaded and side.is_database and side.kind == "parquet", tag
    res = _finish(at)
    assert res["pair"] == "SAMPLE_compare_SAMPLE"
    js = json.loads((Path(res["folder"]) / f"{res['pair']}__summary.json").read_text(encoding="utf-8"))
    assert js["sources"]["A"]["connection"] == "SAMPLE" and js["sources"]["A"]["sql"].startswith("SELECT")
