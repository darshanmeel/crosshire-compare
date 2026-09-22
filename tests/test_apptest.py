# tests/test_apptest.py
"""The whole app, headless: files in, Auto, compare, save - and the same through a DuckDB
database; the Profiling page with one table from a file or a database."""
import json
import os
from pathlib import Path
from streamlit.testing.v1 import AppTest

from tablecmp.columns import specs_from
from tablecmp.compare import column_ledger

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
COUNTS = dict(line.split("=") for line in (ROOT / "docs/superpowers/plans/COUNTS.md").read_text().split()
              if "=" in line)      # matched=... only_left=... only_right=... diff_rows=... cells=...
FAKE_PW = "example-not-a-real-password"


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
    # the profile is the slow part, so the tick starts off: this flow asks for it
    at.sidebar.checkbox(key="auto_profile").set_value(True)
    _ok(at.run())
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
    # Auto's profile fills the Profile section under Rows with its button never pressed,
    # and the label and the tick's help say where the profile goes - no report sheet holds it
    box = next(e for e in at.expander if e.label.startswith("Profile - "))
    assert "Auto fills it in" in box.label and "only when pressed" not in box.label, box.label
    assert box.dataframe, "Auto's profile is not shown"
    tick = at.checkbox(key="auto_profile").help
    assert "Profile section" in tick and "profile.csv" in tick and "report" not in tick, tick
    _ok(at.radio(key="res_view").set_value("Downloads").run())    # one results view at a time
    _ok(at.button(key="save_all").click().run())
    saved = list((Path(os.environ["COMPARE_OUT_DIR"])).glob(f"{pair}__*"))
    assert saved and (saved[0] / f"{pair}__summary.json").exists()
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in folder.iterdir() if p.suffix in (".csv", ".json", ".html"))
    assert FAKE_PW not in blob and "example-not" not in blob
    return res


def _name_hints(at) -> list[str]:
    return [c.value for c in at.sidebar.caption if "Name this side" in c.value]


def _files_line(at) -> str:
    """The page's Files caption: one line, both sides."""
    return next(c.value for c in at.main.caption if " rows × " in c.value)


def test_file_flow(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    assert not _name_hints(at)                     # nothing loaded, nothing to name yet
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        at.radio(key=f"how_{tag}").set_value("Path on disk").run()
        at.text_input(key=f"pt_{tag}").input(str(EX / f)).run()
        _ok(at.button(key=f"load_{tag}").click().run())
        assert at.session_state[tag].loaded, tag
    assert len(_name_hints(at)) == 2               # both file sides still called Left / Right
    assert _files_line(at) == ("**Left** hr_employees.csv - 3,000 rows × 7 columns &nbsp;|&nbsp; "
                               "**Right** payroll_employees.csv - 2,985 rows × 7 columns")
    res = _finish(at)
    assert res["pair"] == "Left_compare_Right"     # the defaults, not the file stems


def test_side_names_name_the_files(monkeypatch, tmp_path):
    """The Name boxes decide the pair: HR and Directory give HR_compare_Directory, every file follows."""
    at = _boot(monkeypatch, tmp_path)
    at.text_input(key="nick_A").input("HR").run()
    at.text_input(key="nick_B").input("Directory").run()
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        _load_path(at, tag, EX / f)
        assert at.session_state[tag].loaded, tag
    assert not _name_hints(at)                     # named sides get no reminder
    res = _finish(at)
    assert res["pair"] == "HR_compare_Directory"
    names = {p.name for p in Path(res["folder"]).iterdir()}
    assert names and all(n.startswith("HR_compare_Directory__") for n in names), names
    js = json.loads((Path(res["folder"]) / "HR_compare_Directory__summary.json").read_text(encoding="utf-8"))
    assert js["pair"] == "HR_compare_Directory"
    assert js["sources"]["A"]["name"] == "HR" and js["sources"]["B"]["name"] == "Directory"


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
    assert not _name_hints(at)                     # a database side is called after its connection
    # ... so both are SAMPLE here, and each panel says so (A's from the run after B loaded);
    # the names still name the run
    at = _ok(at.run())
    assert [c.value for c in at.sidebar.caption if c.value.startswith("Both sides are called SAMPLE")] == [
        "Both sides are called SAMPLE, so the page shows them as A · SAMPLE and B · SAMPLE - name "
        "this one to tell them apart in the tables and on every output file "
        "(left_compare_right)."] * 2
    # the page's Files line names the tables, like the sidebar and the report - not a made-up
    # file - with the tag in front, since one name for both sides names neither
    assert _files_line(at) == (
        "**A · SAMPLE** DuckDB file · hr.employees - 3,000 rows × 7 columns &nbsp;|&nbsp; "
        "**B · SAMPLE** DuckDB file · payroll.employees - 2,985 rows × 7 columns")
    res = _finish(at)
    assert res["pair"] == "A_SAMPLE_compare_B_SAMPLE"
    # the two sides are two columns in the tables the run writes, not one name twice
    sheet = (Path(res["folder"]) / f"{res['pair']}__columns.csv").read_text(encoding="utf-8")
    assert sheet.splitlines()[0].split(",")[:3] == ["column", "name_a", "name_b"]
    ledger = column_ledger(res, "A · SAMPLE", "B · SAMPLE")
    assert "A · SAMPLE" in ledger.columns and "B · SAMPLE" in ledger.columns
    js = json.loads((Path(res["folder"]) / f"{res['pair']}__summary.json").read_text(encoding="utf-8"))
    assert js["sources"]["A"]["connection"] == "SAMPLE" and js["sources"]["A"]["sql"].startswith("SELECT")
    # where a side is picked the tag keeps the two SAMPLEs apart: a step added to B lands on B
    side_pick = at.radio(key="tx_side")
    assert side_pick.options == ["A · SAMPLE", "B · SAMPLE"]
    side_pick.set_value("B").run()
    at.selectbox(key="tx_op").select("trim").run()
    at = _ok(at.button(key="tx_add").click().run())
    canon = at.selectbox(key="tx_col").value
    spec = next(s for s in specs_from(at.session_state["cmap"]) if s.canon == canon)
    assert spec.a_steps == [] and spec.b_steps == [{"op": "trim", "params": {}}], canon
    assert [b.label for b in at.main.button if b.label.startswith("Copy to")] == ["Copy to A · SAMPLE"]
    assert at.radio(key="bucket_pick").options[-2:] == [
        f"Only in A · SAMPLE ({int(COUNTS['only_left']):,})", f"Only in B · SAMPLE ({int(COUNTS['only_right']):,})"]


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


def test_profiling_page(monkeypatch, tmp_path):
    """The Profiling page: one source panel and the Connections manager in the sidebar, no
    Auto; the table loads with tag P, Profile fills the statistics table and logs the run,
    and the profile survives a trip back to the Compare page."""
    at = _boot(monkeypatch, tmp_path)
    at.radio(key="page").set_value("Profiling").run()
    assert not [b for b in at.button if b.key == "auto_btn"] and not [b for b in at.button if b.key == "load_B"]
    assert [m.value for m in at.sidebar.markdown if m.value.startswith("#### ")] == ["#### File"]
    assert at.button(key="load_P").label == "Load"
    assert [i.value for i in at.main.info] == ["Load a table in the sidebar - a CSV or JSON file, or a database table."]
    _load_path(at, "P", EX / "hr_employees.csv")
    P = at.session_state["P"]
    assert P.loaded and P.rows == 3000
    assert not _name_hints(at)                     # the one table needs no naming reminder
    assert _files_line(at) == "**Table** hr_employees.csv - 3,000 rows × 7 columns"
    assert [h.value for h in at.main.subheader] == ["File"]      # nothing measured yet
    at = _ok(at.button(key="do_profile_P").click().run())
    key, prof, made = at.session_state["profile_P"]
    assert len(prof["stats"]) == 7 and "Null %" in prof["stats"].columns
    assert set(prof["freq"]) == set(P.columns)
    # the run, then its notes as their own entry - the way Auto's decisions are logged
    entry, noted = at.session_state["log"][-2], at.session_state["log"][-1]
    assert entry["kind"] == "Profile" and entry["state"] == "done"
    assert entry["lines"][0] == "Looking at the values…" and "Looking for keys…" in entry["lines"]
    assert entry["label"].startswith("Profile ready - key: emp_id in ")
    assert noted["kind"] == "Profile notes" and noted["lines"] == prof["notes"]
    assert noted["label"] == f"{len(prof['notes'])} things stand out" and len(prof["notes"]) > 1
    assert [h.value for h in at.main.subheader] == ["File", "Profile"]
    assert 'class="runbox done"' in "".join(m.value for m in at.main.markdown)
    # top to bottom: the headline, the key line and table, what stands out, the statistics,
    # the three folds, then the frequencies
    captions = [c.value for c in at.main.caption]
    assert prof["headline"].startswith("3,000 rows × 7 columns · key: emp_id") and prof["headline"] in captions
    assert [s.value for s in at.main.success] == [f"Key: **emp_id** - unique on every row. {prof['keys'][2]}."]
    frames = [d.value for d in at.main.dataframe]
    keys_df = next(f for f in frames if "Key columns" in f.columns)
    assert keys_df.iloc[0]["Key columns"] == "emp_id" and keys_df.iloc[0]["Unique"] == "yes"
    notes_md = next(m.value for m in at.main.markdown if "- key: emp_id - unique on every row" in m.value)
    assert notes_md.splitlines() == [f"- {n}" for n in prof["notes"]]
    labels = [e.label for e in at.main.expander]
    assert [lb for lb in labels if lb in ("Outliers", "Patterns", "Dependencies")] == ["Outliers", "Patterns", "Dependencies"]
    assert labels.index("Dependencies") < labels.index("**emp_id** - text · 3,000 distinct · 0.0% null")
    assert [d.proto.label for d in at.main.get("download_button")] == ["Download profile.csv"]
    assert [e.label for e in at.main.expander if e.label.startswith("**emp_id**")] == [
        "**emp_id** - text · 3,000 distinct · 0.0% null"]
    assert "profile is from earlier settings" not in "".join(c.value for c in at.main.caption)
    # Save to folder: the six files land in a folder named after the table, under COMPARE_OUT_DIR
    _ok(at.button(key="save_profile_P").click().run())
    folder = Path(os.environ["COMPARE_OUT_DIR"]) / f"Table__{made}"
    assert sorted(p.name for p in folder.iterdir()) == [
        "Table__dependencies.csv", "Table__keys.csv", "Table__notes.txt", "Table__outliers.csv",
        "Table__patterns.csv", "Table__profile.csv"]
    assert (folder / "Table__profile.csv").read_text(encoding="utf-8").startswith("Column,Type,Rows,Nulls,Null %,")
    assert (folder / "Table__keys.csv").read_text(encoding="utf-8").startswith("Key columns,Distinct,Unique,")
    assert (folder / "Table__outliers.csv").read_text(encoding="utf-8").startswith("Column,Type,P1,P5,")
    assert (folder / "Table__patterns.csv").read_text(encoding="utf-8").startswith("Column,Pattern,Collapsed,")
    assert (folder / "Table__dependencies.csv").read_text(encoding="utf-8").startswith("Column A,Column B,Kind,")
    assert (folder / "Table__notes.txt").read_text(encoding="utf-8") == (
        prof["headline"] + "\n\n" + "\n".join(prof["notes"]) + "\n")
    # back to Compare: its own sidebar, and the profile is still held
    at.radio(key="page").set_value("Compare").run()
    _ok(at)
    assert at.button(key="load_A") is not None and not [b for b in at.button if b.key == "load_P"]
    assert at.session_state["profile_P"][1] is prof


def test_profiling_page_with_no_key_and_nothing_to_measure(monkeypatch, tmp_path):
    """A table with no unique column and no number or date columns: the Keys warning says
    the search depth (keys.MAX_KEY_COLS), every candidate reads Unique = no, the Outliers
    fold says there is nothing to measure, and Save to folder still writes the six files,
    the outliers one header-only. A clean table - a unique id and one text column - notes
    the key and nothing else, so only a table with no rows has nothing standing out. A
    measure that raises shows 'Profile failed', not a traceback."""
    from tablecmp import ui_profile
    from tablecmp.keys import MAX_KEY_COLS
    from tablecmp.observe import OUTLIER_COLS
    rows = ["dept,grade,flag"] + [f"{'Sales' if i % 3 else 'Ops'},G{i % 4},{'Y' if i % 2 else 'N'}" for i in range(24)]
    (tmp_path / "nokey.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "clean.csv").write_text("id,name\n" + "".join(f"{i},n{i}\n" for i in range(1, 6)), encoding="utf-8")
    (tmp_path / "empty.csv").write_text("id,name\n", encoding="utf-8")
    at = _boot(monkeypatch, tmp_path)
    at.radio(key="page").set_value("Profiling").run()
    _load_path(at, "P", tmp_path / "nokey.csv")
    at = _ok(at.button(key="do_profile_P").click().run())
    key, prof, made = at.session_state["profile_P"]
    assert MAX_KEY_COLS == 4                       # the depth the warning and the headline say
    assert [w.value for w in at.main.warning] == [
        f"Nothing up to 4 columns is unique - the closest are below. {prof['keys'][2]}."]
    assert not at.main.success
    keys_df = next(d.value for d in at.main.dataframe if "Key columns" in d.value.columns)
    assert len(keys_df) and set(keys_df["Unique"]) == {"no"}
    assert prof["headline"].startswith("24 rows × 3 columns · no key up to 4 columns · ")
    assert at.session_state["log"][-2]["label"].startswith("Profile ready - no key in ")
    captions = [c.value for c in at.main.caption]
    assert not len(prof["outliers"]) and "No number, date or timestamp columns - nothing to measure." in captions
    assert not any(c.startswith("Nothing stands out") for c in captions)     # the no-key line is a note
    _ok(at.button(key="save_profile_P").click().run())
    folder = Path(os.environ["COMPARE_OUT_DIR"]) / f"Table__{made}"
    assert sorted(p.name for p in folder.iterdir()) == [
        "Table__dependencies.csv", "Table__keys.csv", "Table__notes.txt", "Table__outliers.csv",
        "Table__patterns.csv", "Table__profile.csv"]
    assert (folder / "Table__outliers.csv").read_text(encoding="utf-8") == ",".join(OUTLIER_COLS) + "\n"
    assert (folder / "Table__keys.csv").read_text(encoding="utf-8").count("\n") == len(keys_df) + 1
    assert (folder / "Table__notes.txt").read_text(encoding="utf-8").startswith(prof["headline"] + "\n\n")
    # a clean table: the key is the one note, so the caption for no notes does not show
    _load_path(at, "P", tmp_path / "clean.csv")
    at = _ok(at.button(key="do_profile_P").click().run())
    prof = at.session_state["profile_P"][1]
    assert prof["notes"] == ["key: id - unique on every row"]
    assert [s.value for s in at.main.success] == [f"Key: **id** - unique on every row. {prof['keys'][2]}."]
    assert not at.main.warning and "- key: id - unique on every row" in [m.value for m in at.main.markdown]
    assert not any(c.value.startswith("Nothing stands out") for c in at.main.caption)
    # no rows at all: nothing to note, and the page says so
    _load_path(at, "P", tmp_path / "empty.csv")
    at = _ok(at.button(key="do_profile_P").click().run())
    prof = at.session_state["profile_P"][1]
    assert prof["notes"] == [] and prof["headline"] == "0 rows × 2 columns · 0 duplicate rows"
    assert "Nothing stands out - no nulls, no duplicates, no constant columns, no outliers." in [
        c.value for c in at.main.caption]
    # a measure that raises - a date past Python's range, say - is an error line, not a traceback
    def boom(*_args, **_kwargs):
        raise OverflowError("date value out of range")
    monkeypatch.setattr(ui_profile, "profile_single", boom)
    at = _ok(at.button(key="do_profile_P").click().run())
    assert [e.value for e in at.main.error] == ["Profile failed: date value out of range"]
    assert at.session_state["log"][-1]["kind"] == "Profile" and at.session_state["log"][-1]["state"] == "error"


def _discs(at) -> list[str]:
    return [m.value for m in at.main.markdown if 'class="runbox' in m.value]


def test_compare_settings_survive_the_profiling_page(monkeypatch, tmp_path):
    """Streamlit forgets a widget a run does not draw: the Compare page's settings, its filters
    and both sidebar panels are written back every run, so a trip to Profiling and back changes
    nothing - a stale result stays stale - and each page shows its own last run's disc."""
    import pandas as pd
    import streamlit
    typed = {"rows": None}
    real = streamlit.data_editor

    def filters_editor(data, *args, **kwargs):          # AppTest cannot edit a data_editor
        if kwargs.get("key") == "filters" and typed["rows"] is not None:
            return pd.DataFrame(typed["rows"], columns=["Apply to", "Column", "Operator", "Value", "Type"])
        return real(data, *args, **kwargs)
    monkeypatch.setattr(streamlit, "data_editor", filters_editor)
    at = _boot(monkeypatch, tmp_path)
    at.text_input(key="nick_A").input("HR").run()
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        _load_path(at, tag, EX / f)
    _ok(at.button(key="auto_btn").click().run())
    at = _ok(at.run())
    run = at.session_state["result"]
    at.checkbox(key="opt_case").check().run()
    at.text_input(key="null_tokens").input("NULL, NA, -").run()
    at.number_input(key="disp_rows").set_value(500).run()
    typed["rows"] = [{"Apply to": "Both", "Column": "department", "Operator": "=", "Value": "Sales", "Type": "auto"}]
    at = _ok(at.run())
    typed["rows"] = None                           # from here on the real editor, fed the kept rows
    at = _ok(at.run())
    assert at.session_state["filter_rows"][1]["Column"].tolist() == ["department"]

    def settings():
        return (at.checkbox(key="opt_case").value, at.text_input(key="null_tokens").value,
                at.number_input(key="disp_rows").value, at.radio(key="how_A").value,
                at.text_input(key="nick_A").value, at.text_input(key="pt_A").value,
                any("Settings have changed" in w.value for w in at.warning))
    before = settings()
    assert before[0] and before[1] == "NULL, NA, -" and before[2] == 500 and before[6], before
    assert 'class="runbox done"' in _discs(at)[0] and "Compared in" in _discs(at)[0]
    at.radio(key="page").set_value("Profiling").run()
    _ok(at)
    assert not _discs(at)                          # nothing has run on this page
    assert any("One table" in m.value for m in at.main.markdown)
    at.radio(key="page").set_value("Compare").run()
    _ok(at)
    assert settings() == before
    assert at.session_state["result"] is run and at.session_state["filter_rows"][1]["Column"].tolist() == ["department"]
    assert "Compared in" in _discs(at)[0] and any("Two tables" in m.value for m in at.main.markdown)


def test_load_with_nothing_picked_is_refused(monkeypatch, tmp_path):
    """A Load click that arrives with no file behind it is refused in a sentence - it must
    never read an empty path, which DuckDB would take as a glob of the working folder."""
    at = _boot(monkeypatch, tmp_path)
    _ok(at.button(key="load_A").click().run())
    assert [e.value for e in at.sidebar.error] == ["Nothing to load - pick a file, or fetch a table, first."]
    assert not at.session_state["A"].loaded


def test_profiling_page_from_a_database(monkeypatch, tmp_path):
    """The P panel's Database branch: a plain Fetch button (no Same SQL as A), the fetched
    table loads under its connection's name, and the profile types the text columns by
    what their values look like."""
    at = _boot(monkeypatch, tmp_path)
    at.radio(key="page").set_value("Profiling").run()
    at.radio(key="how_P").set_value("Database").run()
    at.selectbox(key="conn_P").select("SAMPLE").run()
    at.radio(key="dbmode_P").set_value("Table").run()
    at.text_input(key="tbl_P").input("payroll.employees").run()
    assert at.button(key="fetch_P").label == "Fetch" and not [b for b in at.button if b.key == "same_as_A"]
    _ok(at.button(key="fetch_P").click().run())
    at = _ok(at.run())                             # the rerun after the fetch shows fetched_P
    assert at.session_state["fetched_P"][0][0] == "SAMPLE"
    _ok(at.button(key="load_P").click().run())
    P = at.session_state["P"]
    assert P.loaded and P.is_database and P.rows == 2985
    assert not [c.value for c in at.sidebar.caption if c.value.startswith("Both sides are called")]
    assert _files_line(at) == "**SAMPLE** DuckDB file · payroll.employees - 2,985 rows × 7 columns"
    at = _ok(at.button(key="do_profile_P").click().run())
    stats = at.session_state["profile_P"][1]["stats"].set_index("Column")
    # every column is VARCHAR in the database: the values decide - a number with thousands
    # separators, a date, Y/N - and the rest stays text
    assert stats["Type"].to_dict() == {"EmployeeId": "text", "FullName": "text", "Dept": "text",
                                       "Salary": "number", "HireDate": "date", "IsActive": "boolean",
                                       "CostCenter": "text"}
    assert stats.at["Salary", "Mean"] != "" and stats.at["IsActive", "Distinct"] == 2
    assert [d.proto.label for d in at.main.get("download_button")] == ["Download profile.csv"]
    assert at.text_input(key="save_profile_P_dir").value.startswith(os.environ["COMPARE_OUT_DIR"])
    assert [e["kind"] for e in at.session_state["log"][-3:]] == ["Fetch", "Profile", "Profile notes"]
    assert at.session_state["log"][-2]["label"].startswith("Profile ready - key: EmployeeId in ")
