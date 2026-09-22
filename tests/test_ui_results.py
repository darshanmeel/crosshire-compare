# tests/test_ui_results.py
"""The results page: the verdict from the run, the Summary tab's Key block, the report reused rather
than rebuilt, the Downloads tab - zip, Parquet on the switch, saves in a per-run folder under
COMPARE_OUT_DIR."""
from pathlib import Path


from tablecmp import theme, ui_results
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


def _view(at, name: str):
    """The results show one view at a time - pick it and let the page draw it."""
    at.radio(key="res_view").set_value(name)
    at.run()
    assert not at.exception, at.exception
    return at


def test_summary_tab_opens_with_the_key(monkeypatch, tmp_path):
    """The Summary tab starts with a Key block - the key columns as green chips and the line that
    says what the rows were matched on - before the row counts; the ledger under Columns carries
    the column table's colours, a key row green and a one-sided row red."""
    at = _boot(monkeypatch, tmp_path)
    assert at.radio(key="res_view").value == "Summary"      # the view the results open on
    texts = [m.value for m in at.markdown]
    assert texts.index("#### Key") < texts.index("#### Row counts") < texts.index("#### Columns")
    assert texts[texts.index("#### Key") + 1] == '<div class="chips"><span class="chip key">emp_id</span></div>'
    matched = at.session_state["result"]["result"].matched_rows
    assert texts[texts.index("#### Key") + 2] == f"Rows are matched on **emp_id** - **{matched:,}** rows matched"
    ledger = next(d for d in at.dataframe if "Role" in list(d.value.columns))
    roles = ledger.value["Role"].tolist()
    assert roles[0] == "key" and roles[-1].startswith("only in ")
    # the Styler's rules, one per coloured row: "#T_x_row0_col0, ... { background-color: ...; color: ... }"
    rules = ledger.proto.arrow_data.styler.styles.splitlines()
    assert any("_row0_col0," in r and r.endswith(f"{{ {theme.row_tint('pos')} }}") for r in rules)
    assert any(f"_row{len(roles) - 1}_col0," in r and r.endswith(f"{{ {theme.row_tint('neg')} }}") for r in rules)
    plain = roles.index("compared")
    assert not any(f"_row{plain}_col0," in r for r in rules)     # a compared row is left alone


def test_downloads_tab_and_saves(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    run = at.session_state["result"]
    pair, rid = run["pair"], run["run_id"]
    folder = Path(run["folder"])
    assert pair == "Left_compare_Right"            # the side names, left at their defaults
    # the report was built when the run finished; the results page reuses it
    html = run["_report"]
    assert html and (folder / f"{pair}__report.html").exists()
    assert f"{pair}__report.html" in run["files"]
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["result"]["_report"] is html
    assert any(f"<b>{run['verdict'].word}</b>" in m.value for m in at.markdown)   # the banner, above the views
    # one view at a time: the value pairs are on Columns & values, and nothing is swallowed
    _view(at, "Columns & values")
    assert not any("Could not" in e.value for e in at.error), [e.value for e in at.error]
    assert any("Where they differ" in m.value for m in at.markdown)
    # the paired rows are written when they are asked for, and then they are a file like any other
    import zipfile
    _view(at, "Downloads")
    assert not (folder / f"{pair}__paired.csv").exists()
    assert not any(p.startswith("Paired rows") for p in at.selectbox(key=f"dl_pick_{rid}").options)
    at.button(key="write_paired_btn").click(); at.run()
    assert not at.exception, at.exception
    assert (folder / f"{pair}__paired.csv").exists()
    assert any(p.startswith("Paired rows") for p in at.selectbox(key=f"dl_pick_{rid}").options)
    assert not any(b.key == "write_paired_btn" for b in at.button)      # written once, then kept
    # a file that went away - the sweep, or a hand - is offered again, and the zip writes it itself
    (folder / f"{pair}__paired.csv").unlink()
    at.run()
    assert any(b.key == "write_paired_btn" for b in at.button)
    # the zip is built when it is asked for, and holds every file
    assert not run.get("zip")
    at.button(key="zip_run_btn").click(); at.run()
    assert not at.exception, at.exception
    assert (folder / f"{pair}__paired.csv").exists()                    # the zip wrote it first
    assert not any(b.key == "write_paired_btn" for b in at.button)
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
    _view(at, "Report")
    assert at.text_input(key="save_report_dir").value == str(saved)
    (saved / f"{pair}__report.html").unlink()
    at.button(key="save_report").click(); at.run()
    assert not at.exception, at.exception
    assert (saved / f"{pair}__report.html").read_text(encoding="utf-8") == html
    assert any("Saved 1 file to" in s.value for s in at.success)
    # Parquet on the switch: the copies land in the run folder and the zip follows
    _view(at, "Downloads")
    assert not any(p.suffix == ".parquet" for p in run["files"].values())
    at.radio(key="out_fmt").set_value("parquet"); at.run()
    assert not at.exception, at.exception
    assert at.session_state["result"] is run                       # the format is not a setting: not stale
    at.button(key="write_pq").click(); at.run()
    assert not at.exception, at.exception
    assert f"{pair}__paired.parquet" in run["files"] and f"{pair}__cell_diffs.parquet" in run["files"]
    assert not any(b.key == "write_pq" for b in at.button)
    at.button(key="zip_run_btn").click(); at.run()            # the copies dropped the old zip
    with zipfile.ZipFile(run["zip"]) as zf:
        assert f"{pair}__paired.parquet" in zf.namelist()
    # the rerun behind Write Parquet copies stops before the save box is drawn. Streamlit 1.56
    # dropped the box's state on that run and the app seeds it again; 1.64 keeps it. Either way
    # the box holds the run's own folder, not empty, and Save works at once
    assert at.text_input(key="save_all_dir").value == str(saved)
    at.button(key="save_all").click(); at.run()
    assert not any("Type a folder" in e.value for e in at.error)
    assert (saved / f"{pair}__paired.parquet").exists()
    # a folder outside COMPARE_OUT_DIR is refused with a sentence
    at.text_input(key="save_all_dir").set_value(str(tmp_path / "elsewhere")); at.run()
    at.button(key="save_all").click(); at.run()
    assert not at.exception, at.exception
    assert any("Saves must stay under" in e.value for e in at.error)
    assert not (tmp_path / "elsewhere").exists()
    # Rows to display is display-only: the tables follow it, the run is not stale
    at.text_input(key="save_all_dir").set_value(str(tmp_path / "out" / "typed")); at.run()
    at.number_input(key="disp_rows").set_value(500); at.run()
    assert not at.exception, at.exception
    assert at.session_state["result"] is run and not any("Settings have changed" in w.value for w in at.warning)
    assert run["_report_key"] == ("report", run["at"], 500)
    _view(at, "Columns & values")
    assert any(e.label.startswith("Rows that differ") and "first 500 of" in e.label for e in at.expander)
    # a second run gets its own default folder, even though the box held a typed value
    _view(at, "Downloads")
    assert at.text_input(key="save_all_dir").value == str(tmp_path / "out" / "typed")
    at.button(key="go").click(); at.run()
    assert not at.exception, at.exception
    run2 = at.session_state["result"]
    assert run2["run_id"] != rid and run2["_report_key"] == ("report", run2["at"], 500)
    assert at.text_input(key="save_all_dir").value == str(tmp_path / "out" / f"{pair}__{run2['run_id']}")
    _view(at, "Report")
    assert at.text_input(key="save_report_dir").value == str(tmp_path / "out" / f"{pair}__{run2['run_id']}")
    assert not Path(run["folder"]).exists() and not z.exists()      # the old run and its zip are gone


def test_rows_filters_on_the_page(monkeypatch, tmp_path):
    """A bad filter is one error on the page, before and after Compare; a boolean filter typed
    True finds the rows the column holds as true; a date that is not one is refused in a sentence."""
    import pandas as pd
    import streamlit
    typed = {"rows": None}
    real = streamlit.data_editor

    def filters_editor(data, *args, **kwargs):          # AppTest cannot edit a data_editor
        if kwargs.get("key") == "filters" and typed["rows"] is not None:
            return pd.DataFrame(typed["rows"], columns=["Apply to", "Column", "Operator", "Value", "Type"])
        return real(data, *args, **kwargs)
    monkeypatch.setattr(streamlit, "data_editor", filters_editor)

    def row(col, op, val, where="Both", kind="auto"):
        return {"Apply to": where, "Column": col, "Operator": op, "Value": val, "Type": kind}
    at = _boot(monkeypatch, tmp_path)
    run = at.session_state["result"]
    typed["rows"] = [row("salary", "between", "3000", kind="number")]
    at.run()
    assert not at.exception, at.exception
    assert len([e for e in at.error if "between" in e.value]) == 1
    at.button(key="go").click(); at.run()
    assert not at.exception, at.exception
    assert len([e for e in at.error if "between" in e.value]) == 1
    assert at.session_state["result"] is run                       # nothing ran
    typed["rows"] = [row("active", "=", "True", where="Left")]
    at.run(); at.button(key="go").click(); at.run()
    assert not at.exception, at.exception
    new = at.session_state["result"]
    assert new is not run and new["cfg"]["left_filters"] == {"active": {"eq": "true"}}
    res = new["result"]
    assert res.rows_left == 2548 and res.rows_right == res.rows_right_read == 2985
    typed["rows"] = [row("hire_date", ">=", "not-a-date", kind="date")]
    at.run(); at.button(key="go").click(); at.run()
    assert not at.exception, at.exception
    assert [e.value for e in at.error if "not a date" in e.value] == ["filter on 'hire_date': 'not-a-date' is not a date"]
    assert at.session_state["result"] is new
    assert any("Ignore case switch does not apply to filters" in c.value for c in at.caption)
