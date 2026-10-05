# tests/test_runconfig.py
"""A run saved as a config and run again: on the same files, on other files, on many pairs,
from the command line - and what a config never holds."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from tablecmp.columns import apply_mapping_json
from tablecmp.compare import run_comparison, signature
from tablecmp.run import main
from tablecmp.runconfig import (ConfigError, build_cfg, make_config, open_side, options_of, read_config,
                                run_pair, side_block)
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
COLUMNS = {"columns": [
    {"a": "emp_id", "b": "EmployeeId", "name": "emp_id", "type": "text", "key": True, "compare": True},
    {"a": "department", "b": "Dept", "name": "department", "type": "text", "key": False, "compare": True,
     "case": "ignore", "a_steps": [{"op": "trim", "params": {}}], "b_steps": []},
    {"a": "active", "b": "IsActive", "name": "active", "type": "boolean", "key": False, "compare": True}]}


def _side(path, name):
    s = Side(name=name, label=Path(path).name, csv_path=str(path))
    s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    s.rows = 1
    return s


def _config(tmp_path, monkeypatch, filters=None):
    """The config the page saves after a run on the example pair."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    A, B = _side(EX / "hr_employees.csv", "hr"), _side(EX / "payroll_employees.csv", "payroll")
    cmap = apply_mapping_json(json.dumps(COLUMNS), A, B)
    cfg = {"mode": "key", "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0,
           "null_tokens": "NULL, N/A", "display_rows": 200, "table_formats": ["csv"]}
    return make_config(cfg, A, B, "hr", "payroll", cmap, filters), A, B


def test_a_config_holds_the_whole_setup_and_reads_back(tmp_path, monkeypatch):
    conf, A, B = _config(tmp_path, monkeypatch)
    again = read_config(json.dumps(conf))
    assert again["sides"]["A"]["path"] == str(EX / "hr_employees.csv") and again["sides"]["B"]["name"] == "payroll"
    assert again["sides"]["A"]["uploaded"] is False             # a path on disk, not an upload's copy
    assert [c["name"] for c in again["columns"]] == ["emp_id", "department", "active"]
    assert again["columns"][1]["a_steps"] == [{"op": "trim", "params": {}}] and again["columns"][1]["case"] == "ignore"
    assert again["settings"]["null_tokens"] == "NULL, N/A" and again["pairs"] == []
    assert options_of(again) == ReadOptions(("NULL", "N/A", ""), True)
    cfg = build_cfg(again, A, B, "hr", "payroll")
    assert cfg["keys"] == ["emp_id"] and cfg["compare_columns"] == ["department", "active"]
    assert cfg["only_a"] and cfg["only_b"]                       # what no pair uses, from these files
    assert cfg["column_rules"]["department"]["ignore_case"] is True
    assert cfg["name"] == "hr_compare_payroll"


@pytest.mark.parametrize("bad, said", [("{", "not JSON"), ('{"kind": "x"}', "not a config"),
                                       ('{"kind": "crosshire-compare config", "version": 9}', "newer"),
                                       ('{"kind": "crosshire-compare config", "version": "x"}', "not a number")])
def test_what_is_not_a_config_is_refused(bad, said):
    with pytest.raises(ConfigError, match=said):
        read_config(bad)


def test_a_rerun_gives_what_the_page_got(tmp_path, monkeypatch):
    """The config run and a run of the same cfg straight through run_comparison agree."""
    conf, A, B = _config(tmp_path, monkeypatch)
    o = run_pair(conf, say=lambda _m: None)
    assert not o.error, o.error
    cfg = build_cfg(conf, A, B, "hr", "payroll")
    res = run_comparison(A, B, cfg, options_of(conf), signature(A, B, cfg))["result"]
    assert o.counts == {"matched": res.matched_rows, "differ": res.diff_rows, "cells": res.cell_diffs,
                        "only_left": res.only_left, "only_right": res.only_right}
    names = {p.name for p in Path(o.folder).iterdir()}
    assert {"hr_compare_payroll__report.html", "hr_compare_payroll__summary.json"} <= names


def test_other_files_run_on_the_same_settings_and_are_named_after_their_stems(tmp_path, monkeypatch):
    conf, _, _ = _config(tmp_path, monkeypatch)
    jan = tmp_path / "jan"
    jan.mkdir()
    shutil.copy(EX / "hr_employees.csv", jan / "hr_jan.csv")
    shutil.copy(EX / "hr_employees.csv", jan / "hr_copy.csv")
    # B is the HR file again under B's names: the same rows, so nothing differs
    df = pd.read_csv(EX / "hr_employees.csv", dtype=str, keep_default_na=False)
    df.rename(columns={"emp_id": "EmployeeId", "department": "Dept", "active": "IsActive"}).to_csv(
        jan / "payroll_jan.csv", index=False, lineterminator="\n")
    o = run_pair(conf, str(jan / "hr_jan.csv"), str(jan / "payroll_jan.csv"), out=str(tmp_path / "res"),
                 say=lambda _m: None)
    assert not o.error, o.error
    assert o.status == "Identical" and o.counts["differ"] == 0
    assert Path(o.folder).parent == tmp_path / "res" and Path(o.folder).name.startswith("hr_jan_compare_payroll_jan__")


def test_a_column_gone_fails_that_pair_and_says_which(tmp_path, monkeypatch):
    conf, _, _ = _config(tmp_path, monkeypatch)
    thin = tmp_path / "thin.csv"
    pd.read_csv(EX / "payroll_employees.csv", dtype=str).drop(columns=["Dept"]).to_csv(thin, index=False)
    o = run_pair(conf, None, str(thin), say=lambda _m: None)
    assert o.status == "Error" and "Dept (not in thin)" in o.error


def test_the_command_line_runs_every_pair_and_goes_on_past_a_bad_one(tmp_path, monkeypatch, capsys):
    conf, _, _ = _config(tmp_path, monkeypatch)
    conf["pairs"] = [{"left": str(EX / "hr_employees.csv"), "right": str(EX / "payroll_employees.csv"),
                      "name_left": "hr", "name_right": "payroll"},
                     {"left": str(tmp_path / "nowhere.csv"), "right": str(EX / "payroll_employees.csv")}]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    code = main([str(path), "--out", str(tmp_path / "res"), "-q"])
    out = capsys.readouterr().out
    assert code == 2                                             # an error in the batch
    assert "[1/2]" in out and "[2/2]" in out and "file not found" in out
    assert "Differences" in out and len(list((tmp_path / "res").iterdir())) == 1
    # one pair given on the line: differences, no error
    assert main([str(path), "--left", str(EX / "hr_employees.csv"),
                 "--right", str(EX / "payroll_employees.csv"), "-q"]) == 1


def test_a_pairs_csv_names_the_pairs(tmp_path, monkeypatch, capsys):
    conf, _, _ = _config(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    pairs = tmp_path / "pairs.csv"
    pairs.write_text(f"left,right,name_left,name_right\n{EX / 'hr_employees.csv'},{EX / 'payroll_employees.csv'},HR,PAY\n",
                     encoding="utf-8")
    assert main([str(path), "--pairs", str(pairs), "--out", str(tmp_path / "res"), "-q"]) == 1
    assert [p.name.split("__")[0] for p in (tmp_path / "res").iterdir()] == ["HR_compare_PAY"]


def test_a_database_side_is_its_connection_and_sql_never_a_secret():
    side = Side(name="SAMPLE", conn="SAMPLE", database="snowflake", query="SELECT 1", cap=10,
                csv_path="/tmp/fetch.parquet", kind="parquet")
    block = side_block(side, "SAMPLE")
    assert block["connection"] == "SAMPLE" and block["query"] == "SELECT 1" and "path" not in block
    assert not any(k in json.dumps(block).lower() for k in ("password", "private_key", "token"))


def test_names_typed_over_the_header_are_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    f = tmp_path / "raw.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    side = open_side({"name": "raw", "path": str(f), "column_names": ["id", "amount"]}, "A", say=lambda _m: None)
    assert side.columns == ["id", "amount"] and side.source_columns == ["a", "b"] and side.rows == 1
    assert side_block(side, "raw")["column_names"] == ["id", "amount"]


def _folder_conf(tmp_path, monkeypatch, root):
    """The example pair picked from a folder connection, saved as a config."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    from tablecmp import connections as cx
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(root)))
    A, B = _side(root / "hr.csv", "hr"), _side(root / "payroll.csv", "payroll")
    A.folder = B.folder = "DATA"
    cmap = apply_mapping_json(json.dumps(COLUMNS), A, B)
    cfg = {"mode": "key", "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0,
           "null_tokens": "NULL", "display_rows": 200, "table_formats": ["csv"]}
    return make_config(cfg, A, B, "hr", "payroll", cmap)


def test_a_side_from_a_folder_is_kept_by_its_name_there_and_reruns_on_a_bare_name(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    (root / "feb").mkdir(parents=True)
    shutil.copy(EX / "hr_employees.csv", root / "hr.csv")
    shutil.copy(EX / "payroll_employees.csv", root / "payroll.csv")
    shutil.copy(EX / "hr_employees.csv", root / "feb" / "hr_feb.csv")
    conf = _folder_conf(tmp_path, monkeypatch, root)
    assert conf["sides"]["A"]["folder"] == "DATA" and conf["sides"]["A"]["file"] == "hr.csv"
    o = run_pair(conf, "feb/hr_feb.csv", None, say=lambda _m: None)      # a bare name: in the folder
    assert not o.error, o.error
    assert Path(o.folder).name.startswith("hr_feb_compare_payroll__")
    # the folder moved: the connection points at the new place, and the config still runs
    moved = tmp_path / "moved"
    shutil.copytree(root, moved)
    shutil.rmtree(root)
    from tablecmp import connections as cx
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(moved)))
    o = run_pair(conf, say=lambda _m: None)
    assert not o.error, o.error
    # a full path given is that file, folder or not
    o = run_pair(conf, str(EX / "hr_employees.csv"), None, say=lambda _m: None)
    assert not o.error and Path(o.folder).name.startswith("hr_employees_compare_payroll__")


def test_a_folder_the_machine_does_not_know_falls_back_to_the_path(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    root.mkdir()
    shutil.copy(EX / "hr_employees.csv", root / "hr.csv")
    shutil.copy(EX / "payroll_employees.csv", root / "payroll.csv")
    conf = _folder_conf(tmp_path, monkeypatch, root)
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "none.json"))   # no DATA here
    o = run_pair(conf, say=lambda _m: None)
    assert not o.error, o.error
    o = run_pair(conf, "nowhere.csv", None, say=lambda _m: None)
    assert o.status == "Error" and "file not found: nowhere.csv" in o.error


def test_the_command_line_takes_a_connections_file(tmp_path, monkeypatch, capsys):
    root = tmp_path / "exports"
    root.mkdir()
    shutil.copy(EX / "hr_employees.csv", root / "hr.csv")
    shutil.copy(EX / "payroll_employees.csv", root / "payroll.csv")
    conf = _folder_conf(tmp_path, monkeypatch, root)
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "none.json"))
    monkeypatch.delenv("COMPARE_CONNECTION_FILES", raising=False)
    import os
    path = tmp_path / "config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(root, elsewhere)
    team = tmp_path / "team.yml"
    team.write_text(f"DATA:\n  kind: folder\n  path: {elsewhere.as_posix()}\n", encoding="utf-8")
    (elsewhere / "hr.csv").write_text((EX / "payroll_employees.csv").read_text(encoding="utf-8"), encoding="utf-8")
    # A now reads elsewhere/hr.csv - payroll's columns, so the config's A columns are gone
    assert main([str(path), "--connections", str(team), "-q"]) == 2
    assert "not in hr" in capsys.readouterr().out
    bad = tmp_path / "bad.yml"
    bad.write_text("X: {kind: mysql}\n", encoding="utf-8")
    assert main([str(path), "--connections", str(bad), "-q"]) == 2
    assert "not one of" in capsys.readouterr().err
    assert "COMPARE_CONNECTION_FILES" not in os.environ          # main left the environment as it was
