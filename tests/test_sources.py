# tests/test_sources.py
from pathlib import Path

from tablecmp import sources as src
from tablecmp.sql import lit, scratch
from tablecmp.values import STEPS, blank_param, describe_step, step_sql, substitute_x


def test_stem_and_slug():
    assert src.slug("prod / HR.EMPLOYEES") == "prod_HR_EMPLOYEES"
    assert src.Side(label="hr_employees.csv").stem == "hr_employees"
    assert src.Side(label="fetch.parquet", conn="prod", database="snowflake", kind="parquet").stem == "prod"
    assert src.Side().stem == ""


def test_is_database():
    assert not src.Side(label="a.csv").is_database
    assert src.Side(conn="prod", kind="parquet").is_database


def test_read_key_changes_on_refetch():
    a = src.Side(csv_path="x.parquet", kind="parquet", conn="prod", query="SELECT 1", fetched_at="10:12")
    b = src.Side(csv_path="x.parquet", kind="parquet", conn="prod", query="SELECT 1", fetched_at="10:15")
    assert a.read_key != b.read_key


def test_work_and_out_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "w"))
    assert src.work_dir() == tmp_path / "w" and (tmp_path / "w").is_dir()
    monkeypatch.delenv("COMPARE_OUT_DIR", raising=False)
    assert src.out_dir() is None
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "o"))
    assert src.out_dir() == tmp_path / "o"


def test_work_dir_default_is_under_temp(monkeypatch):
    monkeypatch.delenv("COMPARE_WORK_DIR", raising=False)
    p = src.work_dir()
    assert p.name == "crosshire-compare" and p.is_dir()


def test_data_roots(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    assert src.data_roots() == [] and src.path_allowed(str(tmp_path / "any.csv"))
    root, other = tmp_path / "root", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    (root / "in.csv").write_text("a" + chr(10) + "1" + chr(10))
    (other / "x.csv").write_text("a" + chr(10) + "1" + chr(10))
    monkeypatch.setenv("COMPARE_DATA_DIR", str(root))
    assert src.path_allowed(str(root / "in.csv"))
    # a real file outside the root is refused, also when reached by walking up out of the root
    assert not src.path_allowed(str(other / "x.csv"))
    assert not src.path_allowed(str(root / ".." / "other" / "x.csv"))
    # so is a file that does not exist
    assert not src.path_allowed(str(root / "missing.csv"))


def test_scratch_is_utc():
    assert scratch().execute("SELECT current_setting('TimeZone')").fetchone()[0] == "UTC"


def test_scratch_temp_directory_under_work_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "w"))
    got = scratch().execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert Path(got) == tmp_path / "w" / "duckdb"


def test_scratch_memory_limit(monkeypatch):
    monkeypatch.setenv("COMPARE_DUCKDB_MEMORY", "1GB")
    got = scratch().execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert got.upper().replace(" ", "").startswith(("1.0GIB", "953", "1GB", "1.0GB"))


def test_length_step():
    assert "length" in STEPS and step_sql({"op": "length"}) == "length(x)"


def test_text_step_parameters_keep_spaces():
    # a separator, find text or pad character of one space is a real value, not blank
    split = {"op": "part N split by S", "params": {"s": " ", "n": "1"}}
    assert step_sql(split) == "split_part(x, ' ', 1)"
    assert describe_step(split) == "part N split by S (separator=' ', N=1)"
    got = scratch().execute(f"SELECT {substitute_x(step_sql(split), lit('Elena Costa'))}").fetchone()[0]
    assert got == "Elena"
    assert step_sql({"op": "replace text", "params": {"a": " - ", "b": "_"}}) == "replace(x, ' - ', '_')"
    assert step_sql({"op": "pad left to N with C", "params": {"n": " 8 ", "c": " "}}) == "lpad(x, 8, ' ')"
    # unchanged: a plain separator stays unquoted, a blank format means auto
    assert describe_step({"op": "part N split by S", "params": {"s": "-", "n": "1"}}) == \
        "part N split by S (separator=-, N=1)"
    assert describe_step({"op": "to date", "params": {"fmt": " "}}) == "to date"


def test_blank_text_parameter_is_named():
    # nothing at all is blank and named for the screen to refuse; one space is a value
    assert blank_param({"op": "part N split by S", "params": {"s": "", "n": "1"}}) == "separator"
    assert blank_param({"op": "part N split by S", "params": {"s": " ", "n": "1"}}) is None
    assert blank_param({"op": "replace text", "params": {"a": "", "b": "_"}}) == "find"
    assert blank_param({"op": "replace text", "params": {"a": "-", "b": ""}}) is None   # deletes
    assert blank_param({"op": "pad left to N with C", "params": {"n": "8", "c": ""}}) == "pad character"
    assert blank_param({"op": "to date", "params": {"fmt": ""}}) is None
    assert blank_param({"op": "trim"}) is None


def test_blob_reads_as_hex(tmp_path):
    pq = tmp_path / "b.parquet"
    scratch().execute(
        f"COPY (SELECT 1 AS id, 'ab'::BLOB AS raw) TO '{pq.as_posix()}' (FORMAT PARQUET)")
    expr = src.read_expr(str(pq), "parquet")
    assert 'hex("raw")' in expr
    rows = scratch().execute(f"SELECT * FROM {expr}").fetchall()
    assert rows == [("1", "6162")]


def test_mixed_json_column_reads_bare_text(tmp_path):
    """A field mixing numbers and strings is typed JSON by DuckDB; its strings must come
    back without the JSON quotes, so "hello" equals the CSV field hello and n/a can fold to null."""
    js = tmp_path / "mixed.json"
    js.write_text('[{"id": "E1", "note": 10}, {"id": "E2", "note": "n/a"}, {"id": "E3", "note": null},'
                  ' {"id": "E4", "note": "hello"}, {"id": "E5", "note": {"a": [1, "x"]}}]', encoding="utf-8")
    assert src.source_schema(str(js), "json", ",", True, src.file_stamp(str(js)))["note"] == "JSON"
    expr = src.read_expr(str(js), "json")
    assert 'json_extract_string("note"' in expr and '"id"::VARCHAR' in expr
    rows = scratch(ordered=True).execute(f"SELECT * FROM {expr}").fetchall()
    assert rows == [("E1", "10"), ("E2", "n/a"), ("E3", None), ("E4", "hello"), ("E5", '{"a":[1,"x"]}')]
