# tests/test_comparing.py
"""A comparison with no page attached - what compare_app.py and the React server both call."""
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from tablecmp import comparing as cm
from tablecmp import runconfig
from tablecmp import setup as su
from tablecmp.compare import run_comparison as real_run, signature
from tablecmp.sources import Side, file_stamp, row_count, source_schema
from tablecmp.values import ColSpec
from tests.test_outputs import _run

EX = Path(__file__).resolve().parent.parent / "examples"
COLS = [{"a": "emp_id", "b": "EmployeeId", "name": "emp_id", "type": "text", "key": True, "compare": False},
        {"a": "department", "b": "Dept", "name": "department", "type": "text", "key": False, "compare": True}]


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    return tmp_path


def _side(name, fname):
    s = Side(name=name, label=fname, csv_path=str(EX / fname))
    s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    s.rows = row_count(s)
    return s


def _pair(cols=COLS):
    A, B = _side("hr", "hr_employees.csv"), _side("payroll", "payroll_employees.csv")
    return A, B, runconfig.column_table({"columns": cols}, A, B)


def _cfg(A, B, cmap, **over):
    s = cm.page_settings(su.settings_of(over))
    st = su.setup_of(cmap)
    filters, _ = cm.filters_of(None, "hr", "payroll", st.specs)
    cfg = cm.pending_cfg(st, "hr", "payroll", cm.mode_of(st.keys, s["nokey_mode"]), cm.values_of(s),
                         filters, ["a note"], s["out_fmt"], s["display_rows"])
    return cfg, su.read_options(s), st


def test_the_page_switches_fill_in_their_defaults(monkeypatch):
    s = cm.page_settings(su.settings_of({"tolerance": 0.5}))
    assert s["trim"] is True and s["nokey_mode"] == "hash" and s["tolerance"] == 0.5
    assert s["display_rows"] == 1000 and s["auto_rerun"] is False and s["out_fmt"] == "csv"
    assert cm.page_settings(su.settings_of({"display_rows": 500}))["display_rows"] == 500
    monkeypatch.setenv("COMPARE_TABLE_FORMATS", "csv,parquet")
    assert cm.page_settings(su.settings_of(None))["out_fmt"] == "both"
    assert cm.values_of(s) == {"trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.5,
                               "null_tokens": s["null_tokens"]}


def test_the_engine_cfg_from_the_column_table():
    A, B, cmap = _pair()
    cfg, _, st = _cfg(A, B, cmap)
    assert st.keys == ["emp_id"] and st.compare == ["department"] and "salary" in st.only_a
    assert cfg["name"] == "hr_compare_payroll" and cfg["mode"] == "key" and cfg["keys"] == ["emp_id"]
    assert cfg["compare_columns"] == ["department"] and cfg["notes"] == ["a note"]
    assert cfg["table_formats"] == ["csv"] and cfg["display_rows"] == 1000
    assert set(cfg["matched_by"]) == {"emp_id", "department"}
    # what is shown is not what is compared: the rows on screen leave the signature alone
    assert signature(A, B, cfg) == signature(A, B, _cfg(A, B, cmap, display_rows=500)[0])
    assert signature(A, B, cfg) != signature(A, B, _cfg(A, B, cmap, tolerance=0.5)[0])
    assert cm.mode_of([], "position") == "position" and cm.mode_of(["k"], "hash") == "key"


def test_a_bad_filter_is_a_sentence_not_a_crash():
    _, _, cmap = _pair()
    specs = su.setup_of(cmap).specs
    rows = pd.DataFrame([{"Apply to": "Both", "Column": "department", "Operator": "between", "Value": "3000",
                          "Type": "number"}])
    filters, err = cm.filters_of(rows, "hr", "payroll", specs)
    assert filters == ({}, {}, {}) and "between" in err
    assert cm.filters_of(None, "hr", "payroll", specs) == (({}, {}, {}), "")


def test_the_strip_says_where_the_page_stops():
    A, B, cmap = _pair()
    d = cm.strip_cells(A, Side(), "hr", "payroll")
    assert d == {"cells": {"Files": "1 of 2 loaded", "Columns": "-", "Key": "-", "Compare": "-", "Result": "-"},
                 "tones": {"Files": "warn"}}
    d = cm.strip_cells(A, B, "hr", "payroll", su.setup_of(cmap.iloc[0:0]))
    assert d["cells"]["Columns"] == "0 paired · 0 one-sided" and d["tones"]["Columns"] == "warn"
    assert d["cells"]["Result"] == "not run"
    st = su.setup_of(cmap)
    d = cm.strip_cells(A, B, "hr", "payroll", st, "key")
    assert d["cells"]["Files"] == "hr 3,000 · payroll 2,985 rows" and d["cells"]["Key"] == "emp_id"
    assert d["cells"]["Compare"] == "1 columns" and d["cells"]["Result"] == "press Compare"
    assert d["tones"] == {"Result": "warn", "Key": ""}
    untick = su.Setup(st.cmap, st.specs, st.keys, [], st.only_a, st.only_b)
    assert cm.strip_cells(A, B, "hr", "payroll", untick, "key")["cells"]["Compare"] == "none"
    nokey = su.Setup(st.cmap, st.specs, [], st.compare, st.only_a, st.only_b)
    d = cm.strip_cells(A, B, "hr", "payroll", nokey, "hash")
    assert d["cells"]["Key"] == "none - hash" and d["tones"]["Key"] == "warn"


def test_the_strip_carries_the_verdict_and_stale(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    A.rows, B.rows = 3000, 2985
    st = su.Setup(None, [ColSpec(**d) for d in run["cfg"]["specs"]], ["emp_id"], ["department", "active"],
                  ["salary"], ["CostCenter"])
    res = run["result"]
    want = ("identical" if run["verdict"].tone == "ok"
            else f"{res.diff_rows:,} differ · {res.only_left + res.only_right:,} one-sided")
    d = cm.strip_cells(A, B, "hr", "payroll", st, "key", run, stale=False)
    assert d["cells"]["Result"] == want and d["tones"]["Result"] == run["verdict"].tone
    d = cm.strip_cells(A, B, "hr", "payroll", st, "key", run, stale=True)
    assert d["cells"]["Result"] == want + " · stale" and d["tones"]["Result"] == "warn"


def test_one_run_replaces_the_last_and_leaves_its_files():
    A, B, cmap = _pair()
    cfg, opts, _ = _cfg(A, B, cmap)
    sig = signature(A, B, cfg)
    lines = []
    first, said = cm.compare_once(A, B, "hr", "payroll", cfg, opts, sig, None, None, {"kind": "x"}, lines.append)
    assert said == [] and lines and first["signature"] == sig and first["config"] == {"kind": "x"}
    folder = Path(first["folder"])
    for suffix in ("report.html", "config.json", "summary.json", "summary.csv", "columns.csv", "cell_diffs.csv"):
        assert (folder / f"hr_compare_payroll__{suffix}").exists(), suffix
    assert first["_report_key"] == ("report", first["at"], 1000)
    second, _ = cm.compare_once(A, B, "hr", "payroll", cfg, opts, sig, first, None, None, lines.append)
    assert not folder.exists() and Path(second["folder"]).exists()
    with pytest.raises(duckdb.Error):                    # the old run's connection is closed, not left to the GC
        first["con"].execute("SELECT 1")
    assert not (Path(second["folder"]) / "hr_compare_payroll__config.json").exists()   # no config this time


def test_a_failed_run_leaves_the_last_one_shown(work, monkeypatch):
    A, B, cmap = _pair()
    cfg, opts, _ = _cfg(A, B, cmap)
    sig = signature(A, B, cfg)
    first, _ = cm.compare_once(A, B, "hr", "payroll", cfg, opts, sig, None, None, None, lambda _m: None)

    def boom(*_a, **_k):
        raise RuntimeError("no such column x")
    monkeypatch.setattr(cm, "run_comparison", boom)
    with pytest.raises(cm.CompareFailed) as exc:
        cm.compare_once(A, B, "hr", "payroll", cfg, opts, sig, first, None, None, lambda _m: None)
    assert str(exc.value) == "The comparison failed: no such column x - the previous result is still shown below."
    assert Path(first["folder"]).exists() and first["con"].execute("SELECT 1").fetchone() == (1,)

    def engine_says(*a, **k):
        run = real_run(*a, **k)
        run["result"].error = "bad column"
        return run
    monkeypatch.setattr(cm, "run_comparison", engine_says)
    with pytest.raises(cm.CompareFailed) as exc:
        cm.compare_once(A, B, "hr", "payroll", cfg, opts, sig, None, None, None, lambda _m: None)
    assert str(exc.value) == "The engine reported: bad column"
    assert [p for p in (work / "work").iterdir() if p.is_dir()] == [Path(first["folder"])]   # the failed one went


def test_outputs_say_what_failed_and_the_command_line_still_raises(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)

    def broken(*_a, **_k):
        raise ValueError("no report today")
    monkeypatch.setattr(cm, "build_report", broken)
    said = cm.write_outputs(run, run["cfg"], A, B, "hr", "payroll")
    assert said == [("warning", "The report could not be written to the run folder: no report today")]
    assert (Path(run["folder"]) / "hr_compare_payroll__summary.json").exists()
    with pytest.raises(ValueError):
        runconfig.write_outputs(run, run["cfg"], A, B, "hr", "payroll")


def test_the_command_line_writes_through_the_same_function(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch, fmt="parquet")
    runconfig.write_outputs(run, run["cfg"], A, B, "hr", "payroll")
    names = {p.name for p in Path(run["folder"]).iterdir()}
    assert {"hr_compare_payroll__report.html", "hr_compare_payroll__summary.json",
            "hr_compare_payroll__cell_diffs.parquet"} <= names
    assert "hr_compare_payroll__config.json" not in names


def test_auto_settles_the_table_and_says_so():
    A, B, _ = _pair()
    lines = []
    done = cm.run_auto(A, B, "hr", "payroll", su.read_options(su.settings_of(None)), lines.append)
    assert done.chosen == ["emp_id"] and done.profile is None and lines
    assert su.setup_of(done.cmap).keys == ["emp_id"]
    assert done.label.startswith("Worked out in ") and done.label.endswith("s - key: emp_id - comparing now")
    assert cm.decisions_label(done.notes) == f"{len(done.notes)} decisions - every one a cell in the column table"
    assert done.key_formats is None or done.key_formats[0]
    assert cm.auto_stopped(RuntimeError("x")) == "Auto stopped: x" and cm.key_formats_of([]) is None


def test_a_run_that_raises_leaves_no_folder_and_any_error_in_the_outputs_is_a_warning(work, tmp_path, monkeypatch):
    from tablecmp import compare as cmp_
    A, B, cmap = _pair()
    cfg, opts, _ = _cfg(A, B, cmap)

    def boom(*_a, **_k):
        raise RuntimeError("engine fell over")
    monkeypatch.setattr(cmp_, "engine_compare", boom)
    with pytest.raises(RuntimeError):
        real_run(A, B, cfg, opts)
    assert [p for p in (work / "work").iterdir()] == []
    monkeypatch.undo()
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work2"))
    run, A, B = _run(tmp_path, monkeypatch)

    def odd(*_a, **_k):
        raise TypeError("an odd one")
    monkeypatch.setattr(cm, "build_report", odd)
    said = cm.write_outputs(run, run["cfg"], A, B, "hr", "payroll")
    assert said == [("warning", "The report could not be written to the run folder: an odd one")]
