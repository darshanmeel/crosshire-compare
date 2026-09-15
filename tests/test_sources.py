# tests/test_sources.py
from pathlib import Path

from tablecmp import sources as src
from tablecmp.sql import scratch
from tablecmp.values import STEPS, step_sql


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
    (tmp_path / "in.csv").write_text("a" + chr(10) + "1" + chr(10))
    monkeypatch.setenv("COMPARE_DATA_DIR", str(tmp_path))
    assert src.path_allowed(str(tmp_path / "in.csv"))
    assert not src.path_allowed(str(Path.home() / "x.csv"))
    assert not src.path_allowed(str(tmp_path / "missing.csv"))


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


def test_blob_reads_as_hex(tmp_path):
    pq = tmp_path / "b.parquet"
    scratch().execute(
        f"COPY (SELECT 1 AS id, 'ab'::BLOB AS raw) TO '{pq.as_posix()}' (FORMAT PARQUET)")
    expr = src.read_expr(str(pq), "parquet")
    assert 'hex("raw")' in expr
    rows = scratch().execute(f"SELECT * FROM {expr}").fetchall()
    assert rows == [("1", "6162")]
