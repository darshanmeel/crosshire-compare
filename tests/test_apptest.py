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


def _load_path(at, tag, path):
    at.radio(key=f"how_{tag}").set_value("Path on disk").run()
    at.text_input(key=f"pt_{tag}").input(str(path)).run()
    return _ok(at.button(key=f"load_{tag}").click().run())


def test_empty_file_loads_with_no_rows_and_no_filter_blame(monkeypatch, tmp_path):
    """An empty file loads with 0 rows: the sidebar says the file has none, not that a
    filter cut them, and does not ask for column names DuckDB's fallback column never had."""
    files = {"empty.json": "", "empty_array.json": "[]", "empty.csv": "", "header_only.csv": "emp_id,first_name\n"}
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
        at = _load_path(_boot(monkeypatch, tmp_path), "A", tmp_path / name)
        side = at.session_state["A"]
        assert side.loaded and side.rows == 0 and side.cut == "", name
        warnings = [w.value for w in at.sidebar.warning]
        assert warnings == ["The file has no rows."], (name, warnings)
        assert not [e.value for e in at.sidebar.error], name


def test_filter_leaving_no_rows_still_blames_the_filter(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    at.radio(key="how_A").set_value("Path on disk").run()
    at.text_input(key="pt_A").input(str(EX / "hr_employees.csv")).run()
    at.text_area(key="cw_A_0").input("department = 'Nowhere'").run()
    _ok(at.button(key="load_A").click().run())
    side = at.session_state["A"]
    assert side.rows == 0 and side.cut == "WHERE department = 'Nowhere'"
    assert [w.value for w in at.sidebar.warning] == ["The filter left no rows."]
