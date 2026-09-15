# tests/test_ui_results.py
"""The results page: the verdict from the run, the report reused rather than rebuilt, the Downloads
tab - zip, Parquet on the switch, saves in a per-run folder under COMPARE_OUT_DIR."""
import os
from pathlib import Path

import pytest

from tablecmp import ui_results
from tests.test_outputs import _run          # the sample run helper

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def test_verdict_reads_the_run(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    tone, html = ui_results.verdict(run, "hr", "payroll", stale=False)
    v = run["verdict"]
    assert tone == v.tone
    assert html.startswith(f'<div class="verdict {v.tone}">')
    assert f"<b>{v.word}</b> · " in html
    assert "rows matched on <b>emp_id</b>" in html and "only in hr" in html and "only in payroll" in html
    assert "stale" not in html
    _, html = ui_results.verdict(run, "hr", "payroll", stale=True)
    assert "stale - settings changed since" in html


def test_ensure_report_reuses_then_rebuilds(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    path = Path(run["folder"]) / f"{run['pair']}__report.html"
    assert "_report" not in run and not path.exists()
    html = ui_results.ensure_report(run, A, B, "hr", "payroll", 100)          # nothing yet: build
    assert html.startswith("<!DOCTYPE html>") or html.lstrip().startswith("<!")
    assert run["_report"] is html and run["_report_key"] == ("report", run["at"], 100)
    assert path.exists() and run["files"][path.name] == path
    assert bytes([13, 10]) not in path.read_bytes()                            # LF file

    run["_report"] = "<html>sentinel</html>"                                   # same limit: reused
    assert ui_results.ensure_report(run, A, B, "hr", "payroll", 100) == "<html>sentinel</html>"
    assert run["_report"] == "<html>sentinel</html>"
    path.unlink()                                                              # file gone: written back
    assert ui_results.ensure_report(run, A, B, "hr", "payroll", 100) == "<html>sentinel</html>"
    assert path.read_text(encoding="utf-8") == "<html>sentinel</html>"

    html2 = ui_results.ensure_report(run, A, B, "hr", "payroll", 50)           # other limit: rebuilt
    assert html2 != "<html>sentinel</html>" and run["_report_key"] == ("report", run["at"], 50)
    assert path.read_text(encoding="utf-8") == html2


def _boot(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    at = AppTest.from_file(str(ROOT / "compare_app.py"), default_timeout=600)
    at.run()
    assert not at.exception, at.exception
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        at.sidebar.radio(key=f"how_{tag}").set_value("Path on disk"); at.run()
        at.sidebar.text_input(key=f"pt_{tag}").set_value(str(EX / f)); at.run()
        at.sidebar.button(key=f"load_{tag}").click(); at.run()
        assert not at.exception, at.exception
    at.sidebar.button(key="auto_btn").click(); at.run()
    assert not at.exception, at.exception
    return at


def test_downloads_tab_and_saves(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    run = at.session_state["result"]
    pair, rid = run["pair"], run["run_id"]
    folder = Path(run["folder"])
    assert pair == "hr_employees_compare_payroll_employees"
    # the report was built when the run finished; the results page reuses it
    html = run["_report"]
    assert html and (folder / f"{pair}__report.html").exists()
    assert f"{pair}__report.html" in run["files"]
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["result"]["_report"] is html
    # every tab rendered: no swallowed failure, the value pairs are on the Columns tab
    assert not any("Could not" in e.value for e in at.error), [e.value for e in at.error]
    assert any("Where they differ" in m.value for m in at.markdown)
    assert any(f"<b>{run['verdict'].word}</b>" in m.value for m in at.markdown)
    # the zip is built on the first visit and holds every file
    import zipfile
    z = run["zip"]
    assert z.name == f"{pair}__{rid}.zip" and z.parent == folder.parent
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "report.html", "diff.html"):
        assert f"{pair}__{suffix}" in names, suffix
    # save everything lands in <out>/<pair>__<run_id>
    at.button(key="save_all").click(); at.run()
    assert not at.exception, at.exception
    saved = tmp_path / "out" / f"{pair}__{rid}"
    assert saved.is_dir()
    on_disk = {p.name for p in saved.iterdir()}
    expect = {p.name for p in run["files"].values() if p.exists()}
    assert on_disk == expect and f"{pair}__report.html" in on_disk and f"{pair}__summary.json" in on_disk
    assert any(f"Saved {len(expect)} files to" in s.value for s in at.success)
    # the report button saves the report alone into the same per-run folder
    assert at.text_input(key="save_report_dir").value == str(saved)
    (saved / f"{pair}__report.html").unlink()
    at.button(key="save_report").click(); at.run()
    assert not at.exception, at.exception
    assert (saved / f"{pair}__report.html").read_text(encoding="utf-8") == html
    assert any("Saved 1 file to" in s.value for s in at.success)
    # a folder outside COMPARE_OUT_DIR is refused with a sentence
    at.text_input(key="save_all_dir").set_value(str(tmp_path / "elsewhere")); at.run()
    at.button(key="save_all").click(); at.run()
    assert not at.exception, at.exception
    assert any("Saves must stay under" in e.value for e in at.error)
    assert not (tmp_path / "elsewhere").exists()
    # Parquet on the switch: the copies land in the run folder and the zip follows
    assert not any(p.suffix == ".parquet" for p in run["files"].values())
    at.radio(key="out_fmt").set_value("parquet"); at.run()
    assert not at.exception, at.exception
    assert at.session_state["result"] is run                       # the format is not a setting: not stale
    at.button(key="write_pq").click(); at.run()
    assert not at.exception, at.exception
    assert f"{pair}__paired.parquet" in run["files"] and f"{pair}__cell_diffs.parquet" in run["files"]
    assert not any(b.key == "write_pq" for b in at.button)
    with zipfile.ZipFile(run["zip"]) as zf:
        assert f"{pair}__paired.parquet" in zf.namelist()
    at.text_input(key="save_all_dir").set_value(str(saved)); at.run()
    at.button(key="save_all").click(); at.run()
    assert (saved / f"{pair}__paired.parquet").exists()
    # a second run gets its own default folder, even though the box held a typed value
    at.number_input(key="disp_rows").set_value(500); at.run()
    at.button(key="go").click(); at.run()
    assert not at.exception, at.exception
    run2 = at.session_state["result"]
    assert run2["run_id"] != rid and run2["_report_key"] == ("report", run2["at"], 500)
    assert at.text_input(key="save_all_dir").value == str(tmp_path / "out" / f"{pair}__{run2['run_id']}")
    assert at.text_input(key="save_report_dir").value == str(tmp_path / "out" / f"{pair}__{run2['run_id']}")
    assert not Path(run["folder"]).exists() and not z.exists()      # the old run and its zip are gone
