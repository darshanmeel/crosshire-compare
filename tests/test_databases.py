# tests/test_databases.py
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from tablecmp import databases as db
from tablecmp.connections import Connection


@pytest.mark.parametrize("sql", ["SELECT 1", "  with x as (select 1) select * from x",
                                 "SELECT * FROM t -- trailing comment", "SELECT 1;",
                                 'SELECT "into" FROM t', "SELECT 'go into' FROM t",
                                 "SELECT [into] FROM t", "SELECT `into` FROM t",
                                 "SELECT 'a;b' FROM t", "SELECT 'x -- not a comment' FROM t",
                                 "SELECT deleted_at, updates FROM t"])
def test_guard_accepts(sql):
    assert db.check_read_only(sql)


@pytest.mark.parametrize("sql,word", [
    ("SELECT 1; DELETE FROM t", "two statements"),
    ("SELECT * INTO backup FROM t", "INTO"),
    ("/* SELECT */ UPDATE t SET a=1", "UPDATE"),
    ("CALL refresh()", "CALL"),
    ("", "empty"),
    ("-- only a comment", "empty"),
    ("WITH x AS (SELECT 1) DELETE FROM t", "DELETE"),
    ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", "INSERT"),
])
def test_guard_refuses(sql, word):
    with pytest.raises(db.NotReadOnly) as e:
        db.check_read_only(sql)
    assert word.lower() in str(e.value).lower()


def test_guard_strips_comments_but_keeps_literals():
    assert db.check_read_only("SELECT 1 -- note\nFROM t /* more */") == "SELECT 1  \nFROM t"
    assert db.check_read_only("SELECT 'a--b' AS x FROM t;") == "SELECT 'a--b' AS x FROM t"
    assert db.check_read_only("SELECT '/* kept */' FROM t") == "SELECT '/* kept */' FROM t"


def test_limit_sql_per_dialect():
    assert db.limit_sql("snowflake", "SELECT * FROM t", 10) == "SELECT * FROM (SELECT * FROM t) q LIMIT 10"
    assert db.limit_sql("oracle", "SELECT * FROM t", 10) == "SELECT * FROM (SELECT * FROM t) q FETCH FIRST 10 ROWS ONLY"
    assert db.limit_sql("mssql", "SELECT * FROM t", 10) == "SELECT TOP (10) * FROM (SELECT * FROM t) q"
    assert db.limit_sql("mssql", "SELECT * FROM t ORDER BY a", 10) == "SELECT * FROM t ORDER BY a"
    assert db.limit_sql("mssql", "WITH x AS (SELECT 1 a) SELECT * FROM x", 10).startswith("WITH")
    assert db.limit_sql("mssql", "SELECT 'order by' FROM t", 10).startswith("SELECT TOP (10)")
    assert db.limit_sql("postgresql", "SELECT 1", 0) == "SELECT 1"
    assert db.limit_sql("duckdb", "SELECT 1", 3) == "SELECT * FROM (SELECT 1) q LIMIT 3"


def test_has_order_by_ignores_quotes_and_comments():
    assert db.has_order_by("SELECT * FROM t ORDER   BY a")
    assert db.has_order_by("select * from t order by a")
    assert not db.has_order_by("SELECT 'order by' FROM t")
    assert not db.has_order_by("SELECT * FROM t -- order by a")
    assert not db.has_order_by('SELECT "order by" FROM t')


def test_probe_sql():
    assert db.probe_sql("postgresql", "SELECT * FROM t") == "SELECT * FROM (SELECT * FROM t) q WHERE 1=0"
    assert db.probe_sql("mssql", "SELECT * FROM t") == "SELECT * FROM (SELECT * FROM t) q WHERE 1=0"
    assert db.probe_sql("mssql", "WITH x AS (SELECT 1 a) SELECT * FROM x") == "WITH x AS (SELECT 1 a) SELECT * FROM x"
    assert db.probe_sql("mssql", "SELECT * FROM t ORDER BY a") == "SELECT * FROM t ORDER BY a"


def test_table_sql_quotes_per_dialect():
    assert db.table_sql("snowflake", "HR.EMPLOYEES") == 'SELECT * FROM "HR"."EMPLOYEES"'
    assert db.table_sql("mssql", "dbo.Employees") == "SELECT * FROM [dbo].[Employees]"
    assert db.table_sql("databricks", "main.hr.employees") == "SELECT * FROM `main`.`hr`.`employees`"
    assert db.table_sql("postgresql", ' public . "Odd" ') == 'SELECT * FROM "public"."Odd"'
    assert db.table_sql("postgresql", "Public.Odd") == 'SELECT * FROM "public"."odd"'
    assert db.table_sql("snowflake", "hr.employees") == 'SELECT * FROM "HR"."EMPLOYEES"'
    assert db.table_sql("snowflake", 'hr."Mixed Case"') == 'SELECT * FROM "HR"."Mixed Case"'
    assert db.table_sql("oracle", "hr.employees") == 'SELECT * FROM "HR"."EMPLOYEES"'
    assert db.table_sql("mssql", "[dbo].[My Table]") == "SELECT * FROM [dbo].[My Table]"
    assert db.table_sql("duckdb", "hr.Employees") == 'SELECT * FROM "hr"."Employees"'
    assert db.table_sql("duckdb", 'hr."My""Table"') == 'SELECT * FROM "hr"."My""Table"'
    with pytest.raises(ValueError):
        db.table_sql("duckdb", " . ")


def _hide_driver(monkeypatch, prefix):
    """Make any import of the named driver fail, whether or not it is installed here."""
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith(prefix):
            raise ImportError("no")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)


def test_driver_missing_names_the_package(monkeypatch):
    _hide_driver(monkeypatch, "pymssql")
    with pytest.raises(db.DriverMissing) as e:
        db.connect(Connection(name="p", kind="mssql", host="h", database="d", user="u", password="p"))
    assert "pip install pymssql" in str(e.value)
    assert "SQL Server" in str(e.value)


def test_test_reports_a_missing_driver_without_raising(monkeypatch):
    _hide_driver(monkeypatch, "snowflake")
    r = db.test(Connection(name="p", kind="snowflake", host="h", user="u", password="p"))
    assert not r.ok and "snowflake-connector-python" in r.message and r.identity == ""


class FakeCursor:
    description = [("id", None), ("name", None)]

    def __init__(self, rows, fail_after=None):
        self.rows, self.fail_after, self.calls, self.executed = rows, fail_after, 0, []

    def execute(self, sql):
        self.sql = sql
        self.executed.append(sql)

    def fetchmany(self, n):
        self.calls += 1
        if self.fail_after and self.calls > self.fail_after:
            raise RuntimeError("boom")
        out, self.rows = self.rows[:n], self.rows[n:]
        return out

    def fetchall(self):
        out, self.rows = self.rows, []
        return out

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self.cur, self.closed, self.rolled_back = cur, False, False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        raise AssertionError("commit must never be called")


def _stub_driver(monkeypatch, module, calls):
    """A driver module whose connect records its keyword arguments and hands back a FakeConn."""
    import sys
    import types
    m = types.ModuleType(module)
    m.connect = lambda **kw: calls.append(kw) or FakeConn(FakeCursor([]))
    monkeypatch.setitem(sys.modules, module, m)


def test_connect_passes_the_read_only_switches(monkeypatch):
    calls = []
    for module in ("pymssql", "psycopg", "oracledb"):
        _stub_driver(monkeypatch, module, calls)
    for kind in ("mssql", "postgresql", "oracle"):
        con = db.connect(Connection(name="p", kind=kind, host="h", database="d", user="u", password="p", timeout=30))
    mssql, pg, ora = calls
    assert mssql["read_only"] is True and mssql["autocommit"] is False
    assert "-c default_transaction_read_only=on" in pg["options"] and pg["autocommit"] is False
    assert ora["dsn"] == "h:1521/d" and con.call_timeout == 30_000


def test_oracle_sets_the_transaction_read_only_first(tmp_path, monkeypatch):
    fc = FakeConn(FakeCursor([]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    db.fetch_parquet(Connection(name="p", kind="oracle", host="h", user="u", password="p"),
                     "SELECT * FROM t", str(tmp_path / "x.parquet"), cap=0)
    assert fc.cur.executed == ["SET TRANSACTION READ ONLY", "SELECT * FROM t"] and fc.rolled_back


class ArrowCursor(FakeCursor):
    """A cursor of the Arrow-native kinds: fetch_arrow_batches (Snowflake) yields what it was
    given, fetchmany_arrow (Databricks) hands out one table per call and an empty one at the end."""
    empty = pa.table({"id": pa.array([], pa.int64()), "name": pa.array([], pa.string())})

    def fetch_arrow_batches(self):
        yield from self.rows

    def fetchmany_arrow(self, n):
        return self.rows.pop(0) if self.rows else self.empty


def test_fetch_parquet_snowflake_arrow_batches(tmp_path, monkeypatch):
    t = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    fc = FakeConn(ArrowCursor([t.slice(0, 2), t.slice(2).to_batches()[0]]))   # a Table, then a RecordBatch
    monkeypatch.setattr(db, "connect", lambda c: fc)
    out = tmp_path / "x.parquet"
    r = db.fetch_parquet(Connection(name="p", kind="snowflake", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    got = pq.read_table(out)
    assert r.rows == 3 and r.columns == ["id", "name"] and got.column("id").to_pylist() == [1, 2, 3]
    assert fc.cur.executed == ["SELECT * FROM t"] and fc.closed


def test_fetch_parquet_databricks_arrow_tables(tmp_path, monkeypatch):
    t = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    fc = FakeConn(ArrowCursor([t.slice(0, 2), t.slice(2)]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    c = Connection(name="p", kind="databricks", host="h", user="u", password="p")
    r = db.fetch_parquet(c, "SELECT * FROM t", str(tmp_path / "x.parquet"), cap=2)
    assert r.rows == 2 and r.capped and pq.read_table(tmp_path / "x.parquet").column("name").to_pylist() == ["a", "b"]
    fc = FakeConn(ArrowCursor([]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    r = db.fetch_parquet(c, "SELECT * FROM t", str(tmp_path / "z.parquet"), cap=0)
    z = pq.read_table(tmp_path / "z.parquet")
    assert r.rows == 0 and z.num_rows == 0 and z.column_names == ["id", "name"]
    assert str(z.schema.field("id").type) == "int64"           # the empty table keeps the real types


def test_fetch_parquet_streams_and_caps(tmp_path, monkeypatch):
    rows = [(i, f"n{i}") for i in range(10)]
    fc = FakeConn(FakeCursor(rows))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    monkeypatch.setattr(db, "BATCH", 4)
    out = tmp_path / "x.parquet"
    seen = []
    r = db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=7, progress=seen.append)
    t = pq.read_table(out)
    assert t.num_rows == 7 and t.column_names == ["id", "name"] and r.rows == 7 and r.capped
    assert r.columns == ["id", "name"] and r.bytes == out.stat().st_size and r.seconds >= 0
    assert fc.closed and fc.rolled_back and seen and "rows" in seen[0]
    assert fc.cur.sql == "SELECT * FROM (SELECT * FROM t) q LIMIT 7"
    assert t.column("id").to_pylist() == list(range(7))


def test_fetch_parquet_odd_values_and_late_nulls(tmp_path, monkeypatch):
    import datetime
    import decimal
    import uuid
    u = uuid.uuid4()
    rows = [(1, decimal.Decimal("1.50"), u, memoryview(b"\x01"), datetime.date(2024, 1, 2), None),
            (2, None, None, None, None, None),
            (3, decimal.Decimal("2"), u, b"\x02", datetime.date(2024, 1, 3), "late")]
    cur = FakeCursor(rows)
    cur.description = [("n", None), ("d", None), ("u", None), ("b", None), ("dt", None), ("s", None)]
    fc = FakeConn(cur)
    monkeypatch.setattr(db, "connect", lambda c: fc)
    monkeypatch.setattr(db, "BATCH", 2)
    out = tmp_path / "x.parquet"
    r = db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    t = pq.read_table(out)
    assert r.rows == 3 and not r.capped and t.num_rows == 3
    assert t.column("d").to_pylist() == ["1.50", None, "2"]
    assert t.column("u").to_pylist() == [str(u), None, str(u)]
    assert t.column("b").to_pylist() == [b"\x01", None, b"\x02"]
    assert t.column("dt").to_pylist()[0] == datetime.date(2024, 1, 2)
    assert t.column("s").to_pylist() == [None, None, "late"]


def test_fetch_parquet_no_rows_keeps_the_columns(tmp_path, monkeypatch):
    fc = FakeConn(FakeCursor([]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    out = tmp_path / "x.parquet"
    r = db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    t = pq.read_table(out)
    assert r.rows == 0 and r.columns == ["id", "name"] and t.num_rows == 0 and t.column_names == ["id", "name"]
    assert fc.closed


def test_fetch_parquet_cleans_up_on_error(tmp_path, monkeypatch):
    fc = FakeConn(FakeCursor([(i, "x") for i in range(10)], fail_after=1))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    monkeypatch.setattr(db, "BATCH", 4)
    out = tmp_path / "x.parquet"
    with pytest.raises(RuntimeError):
        db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    assert not out.exists() and fc.closed


def test_fetch_parquet_refuses_writes_before_connecting(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(db, "connect", lambda c: called.append(c))
    with pytest.raises(db.NotReadOnly):
        db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "DROP TABLE t", str(tmp_path / "x.parquet"), cap=0)
    assert not called and not (tmp_path / "x.parquet").exists()


def test_fetch_parquet_stops_when_the_disk_is_nearly_full(tmp_path, monkeypatch):
    import collections
    fc = FakeConn(FakeCursor([(i, "x") for i in range(10)]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(db.shutil, "disk_usage", lambda p: usage(1, 1, 0))
    out = tmp_path / "x.parquet"
    with pytest.raises(RuntimeError) as e:
        db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    assert "free" in str(e.value) and not out.exists() and fc.closed


def test_test_redacts_driver_errors(monkeypatch):
    def bad(c):
        raise RuntimeError("login failed for postgresql://u:example-pw@h/db password=example-pw")
    monkeypatch.setattr(db, "connect", bad)
    r = db.test(Connection(name="p", kind="postgresql", host="h", user="u", password="example-pw"))
    assert not r.ok and "example-pw" not in r.message and "Could not connect" in r.message


class IdentityCursor(FakeCursor):
    def execute(self, sql):
        self.sql = sql
        self.rows = [(1,)] if sql == "SELECT 1" else [("reporter", "hr")]


def test_test_identity_from_fake_cursor(monkeypatch):
    fc = FakeConn(IdentityCursor([]))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    r = db.test(Connection(name="p", kind="postgresql", host="h", user="u", password="p"))
    assert r.ok and r.identity == "reporter · hr" and "OK" in r.message and r.seconds >= 0 and fc.closed


def test_duckdb_end_to_end(tmp_path):
    import duckdb
    f = tmp_path / "s.duckdb"
    con = duckdb.connect(str(f))
    con.execute("CREATE SCHEMA hr; CREATE TABLE hr.employees AS SELECT i AS emp_id, 'n' || i AS name FROM range(1, 21) t(i)")
    con.close()
    c = Connection(name="SAMPLE", kind="duckdb", host=str(f))
    t = db.test(c)
    assert t.ok and "1 table" in t.identity
    r = db.fetch_parquet(c, db.table_sql("duckdb", "hr.employees"), str(tmp_path / "e.parquet"), cap=0)
    assert r.rows == 20 and pq.read_table(tmp_path / "e.parquet").num_rows == 20
    assert r.columns == ["emp_id", "name"]
    r = db.fetch_parquet(c, "SELECT * FROM hr.employees", str(tmp_path / "c.parquet"), cap=5)
    assert r.rows == 5 and r.capped and pq.read_table(tmp_path / "c.parquet").num_rows == 5
    r = db.fetch_parquet(c, "SELECT * FROM hr.employees WHERE 1=0", str(tmp_path / "z.parquet"), cap=0)
    z = pq.read_table(tmp_path / "z.parquet")
    assert r.rows == 0 and z.num_rows == 0 and z.column_names == ["emp_id", "name"]
    assert str(z.schema.field("emp_id").type) == "int64"
    with pytest.raises(db.NotReadOnly):
        db.fetch_parquet(c, "DELETE FROM hr.employees", str(tmp_path / "d.parquet"), cap=0)
    assert db.origin_of(c, "hr.employees") == "DuckDB file · hr.employees"
    assert db.origin_of(c, "SELECT *\n  FROM   hr.employees") == "DuckDB file · SELECT * FROM hr.employees"


def test_duckdb_connection_is_read_only(tmp_path):
    import duckdb
    f = tmp_path / "s.duckdb"
    duckdb.connect(str(f)).close()
    con = db.connect(Connection(name="S", kind="duckdb", host=str(f)))
    try:
        with pytest.raises(Exception):
            con.execute("CREATE TABLE t AS SELECT 1")
    finally:
        con.close()


def test_duckdb_missing_file_is_a_failed_test(tmp_path):
    r = db.test(Connection(name="S", kind="duckdb", host=str(tmp_path / "nope.duckdb")))
    assert not r.ok and "Could not connect" in r.message


def test_duckdb_connection_cannot_read_other_files(tmp_path):
    """A DuckDB file source answers SELECTs on its own tables and nothing on the server's disk."""
    import duckdb
    path = tmp_path / "t.duckdb"
    duckdb.connect(str(path)).execute("CREATE TABLE t AS SELECT 1 AS x").close()
    other = tmp_path / "other.csv"
    other.write_text("a" + chr(10) + "1" + chr(10), encoding="utf-8")
    con = db.connect(Connection(name="F", kind="duckdb", host=str(path)))
    assert con.execute("SELECT * FROM t").fetchall() == [(1,)]
    with pytest.raises(Exception, match="(?i)permission|external"):
        con.execute(f"SELECT * FROM read_csv('{other.as_posix()}')").fetchall()
    con.close()
