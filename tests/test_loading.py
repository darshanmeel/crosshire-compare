"""Loading a side with no page attached - what the Streamlit sidebar and the React server both call."""
from pathlib import Path

import pytest

from tablecmp import connections as cx
from tablecmp import loading as ld
from tablecmp.sources import Side, file_stamp, source_schema

EX = Path(__file__).resolve().parent.parent / "examples"
HR = EX / "hr_employees.csv"


@pytest.fixture(autouse=True)
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    return tmp_path


def test_names_default_and_the_box_wins():
    assert ld.side_name("A", "", Side()) == "Left"
    assert ld.side_name("A", "Left", Side(name="SAMPLE")) == "SAMPLE"
    assert ld.side_name("B", " HR ", Side(name="SAMPLE")) == "HR"
    assert ld.load_name("A", "Left", conn="SAMPLE") == "SAMPLE"
    assert ld.load_name("A", "", conn="") == "A" and ld.load_name("P", "Mine", conn="SAMPLE") == "Mine"


def test_the_name_hint():
    db = Side(name="SAMPLE", conn="SAMPLE")
    assert ld.name_hint("A", "", db, "SAMPLE", "SAMPLE").startswith(":orange[Both sides are called SAMPLE]")
    assert ld.name_hint("A", "Left", Side(name="Left"), "Left", "Right") == \
        "Tip: name this side - it names the output files"
    assert ld.name_hint("A", "HR", Side(name="HR"), "HR", "Right") == ""


def test_an_upload_keeps_its_bare_name_in_the_work_folder(work):
    p = ld.upload_path("A", "..\\..\\secret/hr.csv")
    assert p.parent == work / "work" and p.name.startswith("cmp_A_") and p.name.endswith("_hr.csv")
    assert ld.upload_ok("x.PARQUET") and ld.upload_ok("x.ndjson") and not ld.upload_ok("x.exe")


def test_a_path_is_checked_in_a_sentence(work, monkeypatch):
    assert ld.path_problem(str(work / "nope.csv")) == "File not found."
    assert ld.path_problem(str(HR)) == ""
    monkeypatch.setenv("COMPARE_DATA_DIR", str(work))
    assert ld.path_problem(str(HR)) == "Not under an allowed folder (COMPARE_DATA_DIR)."


def test_a_browsed_file_is_named_in_its_folder(work):
    (work / "sub").mkdir()
    f = work / "sub" / "a.csv"
    f.write_text("x\n1\n", encoding="utf-8")
    assert ld.picked_in(str(work), str(f)) == "sub/a.csv"
    assert ld.picked_in(str(work / "sub"), str(HR)) == "" and ld.picked_in("", str(f)) == ""


def test_what_a_folder_list_says(work):
    assert ld.folder_note(str(work / "gone"), [])[0] == "error"
    assert ld.folder_note(str(work), []) == ("caption", "No CSV, JSON or Parquet file in it yet - type a name")
    assert "first 2,000" in ld.folder_note(str(work), ["x"] * 2000)[1]
    assert ld.folder_note(str(work), ["a.csv"]) is None


def test_build_side_reads_cuts_and_snapshots():
    schema = source_schema(str(HR), "csv", ",", True, file_stamp(str(HR)))
    ask = ld.ReadAsked(name="HR", label="hr_employees.csv", path=str(HR), where="department = 'Finance'")
    side = ld.build_side("A", ask, schema)
    assert side.rows == 370 and side.cache_path.endswith(".parquet") and Path(side.cache_path).exists()
    assert ld.loaded_caption(side).startswith(":green[**✓ HR**] · hr_employees.csv · 370 rows × 7 columns")
    assert "WHERE department = 'Finance'" in ld.loaded_caption(side)
    plain = ld.build_side("A", ld.ReadAsked(path=str(HR), label="hr.csv", snapshot=False), schema)
    assert plain.name == "A" and plain.rows == 3000 and plain.cache_path == ""


def test_column_names_over_the_header():
    schema = {"a": "VARCHAR", "b": "VARCHAR"}
    assert ld.names_warning("x, y, z", schema).startswith("You gave 3 names but the file has 2 columns")
    assert ld.names_warning("", schema) == "" and ld.names_warning("x,y", schema) == ""


def test_what_is_said_under_a_loaded_side():
    assert ld.loaded_notes(Side(schema={"a": "V"}, rows=0, where="a = '1'")) == [("warning", "The filter left no rows.")]
    assert ld.loaded_notes(Side(schema={"a": "V"}, rows=0, conn="X"))[0][1] == "The fetch returned no rows."
    headerless = Side(schema={"1": "V", "2026-01-01": "V", "3.5": "V"}, rows=4)
    assert any("look like a data row" in t for _, t in ld.loaded_notes(headerless))
    short = Side(schema={"a": "V", "column1": "V"}, rows=3)
    assert any("names only **1** columns" in t for _, t in ld.loaded_notes(short))


def test_retire_removes_what_nothing_reads(work):
    snap, fetch = work / "s.parquet", work / "f.parquet"
    snap.write_bytes(b"x")
    fetch.write_bytes(b"x")
    old = Side(cache_path=str(snap), csv_path=str(fetch), conn="X")
    ld.retire(old, Side(), held_fetch=str(fetch))
    assert not snap.exists() and fetch.exists()          # the panel still holds the fetch
    ld.retire(old, Side())
    assert not fetch.exists()


def test_the_sql_a_database_side_fetches():
    assert ld.db_sql("snowflake", "table", " hr.employees ", "") == ('SELECT * FROM "HR"."EMPLOYEES"', "hr.employees")
    assert ld.db_sql("duckdb", "sql", "", " SELECT 1 ") == ("SELECT 1", "query")
    assert ld.db_sql("duckdb", "table", "", "") == ("", "")
    assert ld.fetch_key("S", "SELECT  *\nFROM t", 5) == ("S", "SELECT * FROM t", 5)
    c = cx.Connection(name="S", kind="duckdb", host="x.duckdb")
    s = ld.fetched_side(c, 'SELECT * FROM "hr"."employees"', "hr.employees", 0, "10:00:00", False)
    assert (s.conn, s.database, s.origin, s.fetched_at) == ("S", "duckdb", "DuckDB file · hr.employees", "10:00:00")
    assert ld.fetched_side(c, "SELECT 1", "query", 0, "", False).origin == "DuckDB file · SELECT 1"


def test_config_boxes():
    conf = {"settings": {"trim": False, "tolerance": 0.5, "table_formats": ["csv", "parquet"], "mode": "position"},
            "sides": {"A": {"name": "HR", "path": "D:/x/hr.csv", "folder": "DATA", "file": "hr.csv",
                            "column_names": ["a", "b"]},
                      "B": {"connection": "SAMPLE", "query": "SELECT 1", "cap": 10}}}
    boxes = ld.config_boxes(conf, {"DATA"})
    assert boxes["settings"] == {"trim": False, "empty_as_null": True, "ignore_case": False, "tolerance": 0.5,
                                 "out_fmt": "both", "nokey_mode": "position"}
    assert boxes["A"]["how"] == "path" and boxes["A"]["folder"] == "DATA" and boxes["A"]["column_names"] == "a, b"
    assert ld.config_boxes(conf, set())["A"]["folder"] == ""                 # the folder is gone: its path then
    assert boxes["B"] == {**boxes["B"], "how": "database", "name": "Right", "db_mode": "sql", "sql": "SELECT 1",
                          "cap": 10}


def test_a_config_opens_both_sides_and_builds_the_table():
    conf = {"sides": {"A": {"name": "HR", "path": str(HR)}, "B": {"name": "PR", "path": str(EX / "payroll_employees.csv")}},
            "columns": [{"a": "emp_id", "b": "EmployeeId", "name": "emp_id", "type": "text", "key": True, "compare": False}],
            "filters": []}
    sides, said = ld.open_config_sides(conf, {})
    assert said == [] and sides["A"].rows == 3000 and sides["B"].name == "PR"
    cmap, rows, done = ld.config_columns(conf, sides["A"], sides["B"], comparing=False)
    assert done == [("success", "Loaded - HR against PR, 1 pairs")] and list(rows.columns) == ld.FILTER_COLS
    assert ld.config_columns(conf, sides["A"], sides["B"])[2][0][1].endswith("; comparing")
    bad = dict(conf, columns=[{"a": "nope", "b": "EmployeeId", "name": "x"}])
    assert ld.config_columns(bad, sides["A"], sides["B"])[0] is None
    gone = dict(conf, sides={**conf["sides"], "A": {"name": "HR", "path": "D:/nowhere/x.csv", "uploaded": True}})
    _, said = ld.open_config_sides(gone, {})
    assert said[0][0] == "error" and "it was an upload" in said[0][1]


def test_a_connection_key_leaves_out_tokens_and_passphrases():
    stored = cx.Connection(name="SF", kind="snowflake", host="acct", user="me", extra={"warehouse": "W"})
    typed = cx.Connection(name="SF", kind="snowflake", host="acct", user="me",
                          extra={"warehouse": "W", "private_key_pwd": "s3cret", "token": "t0k"})
    assert ld.conn_key(stored) == ld.conn_key(typed)
    assert ld.conn_key(stored) != ld.conn_key(cx.Connection(name="SF", kind="snowflake", host="acct", user="me",
                                                            extra={"warehouse": "X"}))
