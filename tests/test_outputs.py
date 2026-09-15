# tests/test_outputs.py
import csv
import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from tablecmp import outputs as out
from tablecmp.compare import Outcome, run_comparison
from tablecmp.sources import Side
from tablecmp.values import ColSpec, ReadOptions

HERE = Path(__file__).resolve().parent.parent / "examples"


def test_pair_name_defaults_and_slugs():
    """The side names name the pair - not the file stems - slugged, with Left / Right as fallbacks."""
    assert out.pair_name("Left", "Right") == "Left_compare_Right"
    assert out.pair_name("", "") == "Left_compare_Right"
    assert out.pair_name("HR", "Directory") == "HR_compare_Directory"
    assert out.pair_name("prod", "payroll employees") == "prod_compare_payroll_employees"
    assert out.pair_name("  HR / Sept 2026 ", "***") == "HR_Sept_2026_compare_Right"


@pytest.mark.parametrize("diff,only,matched,word", [(0, 0, 100, "Identical"), (3, 0, 100, "Small differences"),
                                                    (10, 0, 100, "Differences"), (0, 200, 100, "Differences")])
def test_verdict(diff, only, matched, word):
    res = Outcome(diff_rows=diff, only_left=only, matched_rows=matched)
    assert out.verdict_of(res, "key").word == word
    assert out.verdict_of(Outcome(error="x"), "key").status == "error"


def test_table_formats(monkeypatch):
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    assert out.table_formats() == {"csv"}
    assert out.table_formats("parquet") == {"parquet"}
    assert out.table_formats("both") == {"csv", "parquet"}
    monkeypatch.setenv("COMPARE_TABLE_FORMATS", "csv, parquet")
    assert out.table_formats() == {"csv", "parquet"}


def _run(tmp_path, monkeypatch, fmt="csv", mode="key"):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    A = Side(name="hr", label="hr_employees.csv", csv_path=str(HERE / "hr_employees.csv"))
    B = Side(name="payroll", label="payroll_employees.csv", csv_path=str(HERE / "payroll_employees.csv"))
    from tablecmp.sources import file_stamp, source_schema
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
        s.source_columns = list(s.schema)
    specs = [ColSpec(canon="emp_id", a_src="emp_id", b_src="EmployeeId", kind="text"),
             ColSpec(canon="department", a_src="department", b_src="Dept", kind="text"),
             ColSpec(canon="active", a_src="active", b_src="IsActive", kind="boolean")]
    # the app passes pair_name(NA, NB) (Left_compare_Right unless the sides are named); a short name keeps
    # the assertions readable - the engine and the writers take whatever cfg["name"] says
    cfg = {"name": "hr_compare_payroll", "mode": mode, "keys": ["emp_id"] if mode == "key" else [],
           "specs": [s.__dict__ for s in specs],
           "compare_columns": ["department", "active"], "only_a": ["salary"], "only_b": ["CostCenter"],
           "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0, "column_rules": {},
           "filters": {}, "left_filters": {}, "right_filters": {}, "display_rows": 100,
           "null_tokens": ["NULL"], "table_formats": [fmt] if fmt != "both" else ["csv", "parquet"],
           "matched_by": {"emp_id": "name", "department": "similar name", "active": "you"}}
    opts = ReadOptions(tokens=("NULL", ""), trim=True)
    return run_comparison(A, B, cfg, opts, "sig"), A, B


def test_run_folder_has_every_file(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    out.write_summary(run, A, B, "hr", "payroll", notes=["key: emp_id"])
    folder = Path(run["folder"])
    assert folder.name.startswith("hr_compare_payroll__") and folder.parent == tmp_path / "work"
    names = {p.name for p in folder.iterdir()}
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "diff.html"):
        assert f"hr_compare_payroll__{suffix}" in names, suffix
    assert not [p for p in folder.iterdir() if p.is_dir()]          # flat: no <pair>/ sub-folder left
    js = json.loads((folder / "hr_compare_payroll__summary.json").read_text(encoding="utf-8"))
    assert js["schema_version"] == 1 and js["pair"] == "hr_compare_payroll" and js["run_id"] == run["run_id"]
    assert js["started_at"] == run["started_at"] and "T" in js["started_at"]
    assert js["sources"]["A"]["name"] == "hr" and js["sources"]["B"]["label"] == "payroll_employees.csv"
    assert js["sources"]["A"]["rows"] == run["result"].rows_left_read
    assert js["verdict"]["word"] and js["notes"] == ["key: emp_id"]
    assert js["settings"]["keys"] == ["emp_id"] and "display_rows" not in js["settings"]
    assert {f["name"] for f in js["files"]} >= {"hr_compare_payroll__cell_diffs.csv"}
    assert "password" not in json.dumps(js).lower()
    with open(folder / "hr_compare_payroll__summary.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == out.SUMMARY_COLUMNS and len(rows) == 2
    with open(folder / "hr_compare_payroll__columns.csv", newline="") as fh:
        cols = list(csv.DictReader(fh))
    assert list(cols[0]) == out.COLUMNS_HEADER
    assert {c["column"] for c in cols} >= {"emp_id", "department", "active", "salary", "CostCenter"}
    assert next(c for c in cols if c["column"] == "department")["role"] == "compared"
    # matched_by: how each pair was made, from the column table; blank on a one-sided column
    by = {c["column"]: c["matched_by"] for c in cols}
    assert by["emp_id"] == "name" and by["department"] == "similar name" and by["active"] == "you"
    assert by["salary"] == "" and by["CostCenter"] == ""
    assert "matched_by" not in js["settings"]                      # not a setting: display-only
    assert run["verdict"].status == "differences" and run["pair"] == "hr_compare_payroll"
    run["cfg"].pop("matched_by")                                   # an older cfg without it: blanks
    assert out.columns_frame(run)["matched_by"].isna().all()


def test_paired_file_and_value_pairs(tmp_path, monkeypatch):
    from tablecmp.compare import value_pairs
    run, A, B = _run(tmp_path, monkeypatch)
    res = run["result"]
    paired = Path(run["files"]["hr_compare_payroll__paired.csv"])
    with open(paired, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["emp_id", "a_department", "a_active", "b_department", "b_active"]
    assert len(rows) - 1 == res.matched_rows
    pairs = value_pairs(run, 3)
    assert set(pairs) <= {"department", "active"} and pairs
    for col, df in pairs.items():
        assert list(df.columns) == ["a", "b", "n", "pct"] and len(df) <= 3
        assert df["n"].is_monotonic_decreasing


def test_hash_mode_writes_whole_rows(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch, mode="hash")
    folder = Path(run["folder"])
    with open(folder / "hr_compare_payroll__left_only.csv", newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == ["emp_id", "department", "active"]     # every column, no __h / __k helpers
    with open(folder / "hr_compare_payroll__paired.csv", newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == ["department", "active"]
    out.write_summary(run, A, B, "hr", "payroll")
    assert (folder / "hr_compare_payroll__summary.json").exists()


def test_parquet_copies_and_zip(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch, fmt="both")
    out.write_summary(run, A, B, "hr", "payroll")
    written = out.write_parquet_copies(run)
    names = {p.name for p in written}
    assert {"hr_compare_payroll__cell_diffs.parquet", "hr_compare_payroll__left_only.parquet",
            "hr_compare_payroll__paired.parquet", "hr_compare_payroll__columns.parquet"} <= names
    assert "hr_compare_payroll__cell_diffs.parquet" in run["files"]
    z = out.zip_run(run)
    assert z.name.startswith("hr_compare_payroll__") and z.suffix == ".zip"
    with zipfile.ZipFile(z) as zf:
        assert "hr_compare_payroll__summary.json" in zf.namelist()
        assert "hr_compare_payroll__paired.parquet" in zf.namelist()


def test_discard_run_keeps_the_work_dir(tmp_path, monkeypatch):
    from tablecmp.compare import discard_run
    run, A, B = _run(tmp_path, monkeypatch)
    z = out.zip_run(run)
    keep = tmp_path / "work" / "fetch_A_1.parquet"
    keep.write_bytes(b"x")
    discard_run(run)
    assert not Path(run["folder"]).exists() and not z.exists()
    assert keep.exists() and (tmp_path / "work").is_dir()


def test_save_target_is_fenced(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPARE_OUT_DIR", raising=False)
    run = {"pair": "a_compare_b", "run_id": "20260915-101233"}
    assert out.default_save_folder(run, tmp_path) == tmp_path / "a_compare_b__20260915-101233"
    assert out.save_target(str(tmp_path / "x"), run) == (tmp_path / "x").resolve()
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    assert out.default_save_folder(run, tmp_path) == tmp_path / "out" / "a_compare_b__20260915-101233"
    assert out.save_target("sub", run) == (tmp_path / "out" / "sub").resolve()
    assert out.save_target(str(tmp_path / "out"), run) == (tmp_path / "out").resolve()
    with pytest.raises(ValueError):
        out.save_target(str(tmp_path / "elsewhere"), run)
    with pytest.raises(ValueError):
        out.save_target("../elsewhere", run)


def test_sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path))
    stale = time.time() - 90000
    old = tmp_path / "a_compare_b__20260101-000000"
    old.mkdir()
    (old / "x").write_text("1")
    os.utime(old, (stale, stale))
    old_zip = tmp_path / "a_compare_b__20260101-000000.zip"
    old_zip.write_bytes(b"z")
    os.utime(old_zip, (stale, stale))
    old_upload = tmp_path / "cmp_A_1_x.csv"
    old_upload.write_text("a")
    os.utime(old_upload, (stale, stale))
    keep_dir = tmp_path / "duckdb"
    keep_dir.mkdir()
    os.utime(keep_dir, (stale, stale))
    new = tmp_path / "a_compare_b__20260915-000000"
    new.mkdir()
    assert out.sweep_work_dir(24) == 3
    assert not old.exists() and not old_zip.exists() and not old_upload.exists()
    assert new.exists() and keep_dir.exists()
