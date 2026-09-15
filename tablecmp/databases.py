"""Reading a table or a query out of a database into a Parquet file, read-only.

Every kind has a dialect: how to quote a name, cap a query, probe its columns, test the
connection. The drivers are imported only when used, so the app runs without them and says
which package a database needs. Nothing but SELECT / WITH is ever sent, and no connection
ever commits.

How read-only is kept, per kind: DuckDB opens the file with read_only=True; Postgres sets
default_transaction_read_only=on for the session; Oracle runs SET TRANSACTION READ ONLY before
the statement; SQL Server connects with read_only application intent, autocommit off and a
rollback on close; Snowflake and Databricks rely on the role of the user in the connection.
On top of that check_read_only refuses anything that is not a single SELECT or WITH statement
before a connection is even opened.
"""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .connections import Connection, KINDS, redact

BATCH = 50_000
MIN_FREE_BYTES = 1 << 30
DRIVERS = {"snowflake": ("snowflake.connector", "snowflake-connector-python"),
           "databricks": ("databricks.sql", "databricks-sql-connector"),
           "mssql": ("pymssql", "pymssql"), "oracle": ("oracledb", "oracledb"),
           "postgresql": ("psycopg", "psycopg[binary]"), "duckdb": ("duckdb", "duckdb")}
QUOTES = {"mssql": ("[", "]"), "databricks": ("`", "`")}
TEST_SQL = {"oracle": "SELECT 1 FROM dual"}
IDENTITY_SQL = {
    "snowflake": "SELECT current_user(), current_role(), current_warehouse(), current_database()",
    "databricks": "SELECT current_user(), current_catalog(), current_schema()",
    "mssql": "SELECT SUSER_SNAME(), DB_NAME()",
    "oracle": "SELECT user, sys_context('USERENV', 'DB_NAME') FROM dual",
    "postgresql": "SELECT current_user, current_database()",
}
# Words that change a database. A SELECT or WITH statement has no business containing them
# outside a string or a quoted name (Postgres allows WITH x AS (DELETE ...) SELECT, SQL Server
# allows WITH x AS (...) DELETE FROM x).
WRITE_WORDS = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "ALTER", "TRUNCATE",
               "GRANT", "REVOKE", "EXEC", "EXECUTE", "CALL")


class NotReadOnly(Exception):
    pass


class DriverMissing(Exception):
    pass


@dataclass
class TestResult:
    ok: bool
    message: str
    identity: str = ""
    seconds: float = 0.0


@dataclass
class FetchResult:
    rows: int
    bytes: int
    capped: bool
    seconds: float
    columns: list[str] = field(default_factory=list)


# ---- SQL text ---------------------------------------------------------------
# One pass over the text that knows about string literals and quoted names, so a -- or /* inside
# a literal is left alone and only real comments go.
_QUOTED_SRC = r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]|`[^`]*`"
_COMMENT_SRC = r"--[^\n]*|/\*.*?\*/"
_QUOTED = re.compile(_QUOTED_SRC)
_TOKENS = re.compile(_QUOTED_SRC + "|" + _COMMENT_SRC, re.S)
_WRITE_WORD = re.compile(r"\b(" + "|".join(WRITE_WORDS) + r")\b", re.I)


def strip_comments(sql: str) -> str:
    """The SQL with -- and /* */ comments replaced by a space; literals and quoted names kept."""
    return _TOKENS.sub(lambda m: " " if m.group(0)[0] in "-/" else m.group(0), sql or "")


def _bare(sql: str) -> str:
    """Comments gone and every literal or quoted name blanked: what is left is the SQL's own words."""
    return _QUOTED.sub(" ", strip_comments(sql))


def check_read_only(sql: str) -> str:
    """The statement with comments and one trailing ; stripped, or NotReadOnly naming the word."""
    clean = strip_comments(sql).strip()
    if clean.endswith(";"):
        clean = clean[:-1].rstrip()
    if not clean:
        raise NotReadOnly("The statement is empty")
    bare = _QUOTED.sub(" ", clean)
    if ";" in bare:
        raise NotReadOnly("Only one statement is allowed - two statements were given")
    first = re.match(r"\s*([A-Za-z]+)", bare)
    word = first.group(1).upper() if first else ""
    if word not in ("SELECT", "WITH"):
        raise NotReadOnly(f"Only SELECT or WITH statements are sent - this one starts with {word or 'something else'}")
    hit = _WRITE_WORD.search(bare)
    if hit:
        raise NotReadOnly(f"{hit.group(1).upper()} is not allowed in a read-only statement - "
                          "quote it if it is a column name")
    if re.search(r"\bINTO\b", bare, re.I):
        raise NotReadOnly("SELECT ... INTO writes a table - INTO is not allowed")
    return clean


def quote(kind: str, name: str) -> str:
    o, c = QUOTES.get(kind, ('"', '"'))
    return o + name.replace(c, c + c) + c


# What a database does with a name nobody quoted: Snowflake and Oracle fold it to upper case,
# Postgres to lower; DuckDB, SQL Server and Databricks compare names case-insensitively.
FOLD = {"snowflake": str.upper, "oracle": str.upper, "postgresql": str.lower}


def table_sql(kind: str, table: str) -> str:
    """SELECT * FROM schema.table with every part quoted the way this kind wants it. A part the
    user quoted ("My Table", [My Table], `my table`) is kept exactly; a bare part is folded the
    way the database would fold it, so hr.employees on Snowflake finds HR.EMPLOYEES."""
    parts = []
    for raw in (table or "").strip().split("."):
        p = raw.strip()
        if not p:
            continue
        if len(p) >= 2 and ((p[0] == p[-1] and p[0] in "\"`") or (p[0] == "[" and p[-1] == "]")):
            parts.append(p[1:-1].replace(p[-1] * 2, p[-1]))     # "My""Table" is My"Table
        else:
            parts.append(FOLD.get(kind, lambda s: s)(p))
    if not parts:
        raise ValueError("Give the table as schema.table")
    return "SELECT * FROM " + ".".join(quote(kind, p) for p in parts)


def has_order_by(sql: str) -> bool:
    return bool(re.search(r"\bORDER\s+BY\b", _bare(sql), re.I))


def _leading_with(sql: str) -> bool:
    return bool(re.match(r"\s*WITH\b", _bare(sql), re.I))


def limit_sql(kind: str, sql: str, n: int) -> str:
    """The statement capped at n rows where the dialect can do it in SQL. SQL Server cannot wrap a
    statement that starts with WITH or carries an ORDER BY, so those come back unchanged and the
    batch loop in fetch_parquet stops at n instead (it does that on every kind anyway)."""
    if not n:
        return sql
    if kind == "oracle":
        return f"SELECT * FROM ({sql}) q FETCH FIRST {int(n)} ROWS ONLY"
    if kind == "mssql":
        if _leading_with(sql) or has_order_by(sql):
            return sql
        return f"SELECT TOP ({int(n)}) * FROM ({sql}) q"
    return f"SELECT * FROM ({sql}) q LIMIT {int(n)}"


def probe_sql(kind: str, sql: str) -> str:
    """A statement that returns the columns and no rows. SQL Server has the same wrapping limits
    as limit_sql; there the statement comes back as it is and the caller reads cursor.description."""
    if kind == "mssql" and (_leading_with(sql) or has_order_by(sql)):
        return sql
    return f"SELECT * FROM ({sql}) q WHERE 1=0"


def origin_of(c: Connection, what: str) -> str:
    """'<Kind> · <schema.table or query>' for the report; never a credential."""
    return f"{KINDS.get(c.kind, c.kind)} · {' '.join((what or '').split())[:80]}"


# ---- connecting -------------------------------------------------------------
def _import(kind: str):
    mod, pkg = DRIVERS[kind]
    try:
        return __import__(mod, fromlist=["_"])
    except ImportError as exc:
        raise DriverMissing(f"{KINDS[kind]} needs the {pkg} package: pip install {pkg}") from exc


def connect(c: Connection):
    """A DB-API connection, read-only wherever the driver has a switch; never commits."""
    login = min(c.timeout, 10)
    kind = c.kind
    if kind not in DRIVERS:
        raise ValueError(f"Unknown connection kind {kind!r}")
    m = _import(kind)
    if kind == "duckdb":
        # read-only, and no reading of other files on the server through the SQL box
        return m.connect(c.host, read_only=True, config={"enable_external_access": "false"})
    if kind == "snowflake":
        return m.connect(user=c.user, password=c.password, account=c.host, database=c.database or None,
                         schema=c.schema or None, warehouse=c.extra.get("warehouse") or None,
                         role=c.extra.get("role") or None, authenticator=c.extra.get("authenticator") or "snowflake",
                         login_timeout=login, network_timeout=c.timeout,
                         session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": c.timeout})
    if kind == "databricks":
        return m.connect(server_hostname=c.host, http_path=c.extra.get("http_path", ""),
                         access_token=c.extra.get("token") or c.password, catalog=c.extra.get("catalog") or None,
                         schema=c.schema or None, _socket_timeout=c.timeout)
    if kind == "mssql":
        return m.connect(server=c.host, port=c.port or 1433, user=c.user, password=c.password,
                         database=c.database or "", login_timeout=login, timeout=c.timeout,
                         autocommit=False, appname="crosshire-compare", read_only=True)
    if kind == "oracle":
        dsn = f"{c.host}:{c.port or 1521}/{c.extra.get('service_name') or c.database}"
        con = m.connect(user=c.user, password=c.password, dsn=dsn, tcp_connect_timeout=login)
        con.call_timeout = c.timeout * 1000
        return con
    if kind == "postgresql":
        return m.connect(host=c.host, port=c.port or 5432, dbname=c.database or None, user=c.user,
                         password=c.password, connect_timeout=login,
                         options=f"-c default_transaction_read_only=on -c statement_timeout={c.timeout * 1000}",
                         autocommit=False)
    raise ValueError(f"Unknown connection kind {kind!r}")


def _close(con) -> None:
    """Roll back whatever the driver opened and close; never commit."""
    try:
        if hasattr(con, "rollback"):
            con.rollback()
    except Exception:
        pass
    try:
        con.close()
    except Exception:
        pass


def _cursor(con, kind: str):
    cur = con.cursor()
    if kind == "oracle":
        cur.execute("SET TRANSACTION READ ONLY")
    return cur


def test(c: Connection) -> TestResult:
    """Connect, run the smallest query, say who the database thinks we are."""
    t0 = time.perf_counter()
    try:
        con = connect(c)
    except DriverMissing as exc:
        return TestResult(False, str(exc))
    except Exception as exc:
        return TestResult(False, "Could not connect - " + redact(exc))
    try:
        cur = _cursor(con, c.kind)
        cur.execute(TEST_SQL.get(c.kind, "SELECT 1"))
        cur.fetchall()
        if c.kind == "duckdb":
            cur.execute("SELECT count(*) FROM information_schema.tables")
            n = cur.fetchone()[0]
            identity = f"{n} table{'s' if n != 1 else ''}"
        else:
            cur.execute(IDENTITY_SQL[c.kind])
            identity = " · ".join(str(v) for v in (cur.fetchone() or ()) if v is not None)
        secs = time.perf_counter() - t0
        return TestResult(True, f"OK - {identity} - {secs:.1f} s", identity, secs)
    except Exception as exc:
        return TestResult(False, "Connected, but the test query failed - " + redact(exc))
    finally:
        _close(con)


# ---- fetching ---------------------------------------------------------------
_PLAIN = (bool, int, float, str, bytes, _dt.date, _dt.datetime, _dt.time)


def _clean(v):
    """A value Arrow maps on its own, else its text. Decimal, UUID, LOB handles, intervals:
    text is the honest form."""
    if v is None or isinstance(v, _PLAIN):
        return v
    if isinstance(v, (memoryview, bytearray)):
        return bytes(v)
    return str(v)


def _column(values: list, typ: pa.DataType | None) -> pa.Array:
    if typ is None:
        try:
            arr = pa.array(values)
        except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError):
            arr = pa.array([None if v is None else str(v) for v in values], type=pa.string())
        return arr.cast(pa.string()) if pa.types.is_null(arr.type) else arr
    if pa.types.is_string(typ) or pa.types.is_large_string(typ):
        values = [v if v is None or isinstance(v, str) else str(v) for v in values]
    return pa.array(values, type=typ)


def _to_arrow(cur, rows: list, schema: pa.Schema | None) -> pa.Table:
    """A batch of DB-API rows as an Arrow table. The first batch (schema None) sets the types; a
    column that is all null there becomes text so later batches always fit. Later batches are
    built straight into the fixed types."""
    names = [d[0] for d in cur.description]
    cols = [list(map(_clean, col)) for col in zip(*rows)] if rows else [[] for _ in names]
    if schema is None:
        arrays = [_column(col, None) for col in cols]
    else:
        arrays = [_column(col, schema.field(i).type) for i, col in enumerate(cols)]
    return pa.Table.from_arrays(arrays, names=names)


def _batches(cur, kind: str):
    """Yield pyarrow tables, driver by driver. The Arrow-native kinds yield an empty table when
    there are no rows, so the file still gets the real column types."""
    if kind == "duckdb":
        reader = (getattr(cur, "to_arrow_reader", None) or cur.fetch_record_batch)(BATCH)
        seen = False
        for b in reader:
            if b.num_rows:
                seen = True
                yield pa.Table.from_batches([b])
        if not seen:
            yield reader.schema.empty_table()
        return
    if kind == "snowflake":
        for b in cur.fetch_arrow_batches():
            yield b if isinstance(b, pa.Table) else pa.Table.from_batches([b])
        return
    if kind == "databricks":
        first = True
        while True:
            t = cur.fetchmany_arrow(BATCH)
            if t.num_rows == 0:
                if first:
                    yield t
                break
            first = False
            yield t
        return
    schema = None
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        t = _to_arrow(cur, rows, schema)
        schema = schema or t.schema
        yield t


def fetch_parquet(c: Connection, sql: str, path: str, cap: int = 0, progress=None) -> FetchResult:
    """Run the statement and stream the rows into a Parquet file. Read-only, batch by batch.

    The statement goes through check_read_only before a connection is opened; the cap is put
    into the SQL where the dialect allows and enforced by the loop everywhere. On any error the
    half-written file is removed and the connection closed. Stops with a plain message when the
    folder has under 1 GB free."""
    say = progress or (lambda _m: None)
    clean = check_read_only(sql)
    stmt = limit_sql(c.kind, clean, cap)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    con = connect(c)
    writer = None
    rows = 0
    columns: list[str] = []
    try:
        cur = _cursor(con, c.kind)
        cur.execute(stmt)
        for table in _batches(cur, c.kind):
            if cap and rows + table.num_rows > cap:
                table = table.slice(0, cap - rows)
            if writer is None:
                columns = list(table.column_names)
                writer = pq.ParquetWriter(str(out), table.schema, compression="zstd")
            elif table.schema != writer.schema:
                table = table.cast(writer.schema)
            if table.num_rows:
                writer.write_table(table)
            rows += table.num_rows
            size = out.stat().st_size if out.exists() else 0
            say(f"{rows:,} rows · {size / 1e6:,.0f} MB · {time.perf_counter() - t0:.0f} s")
            if shutil.disk_usage(out.parent).free < MIN_FREE_BYTES:
                raise RuntimeError("Stopped: under 1 GB free in the work folder")
            if cap and rows >= cap:
                break
        if writer is None:                        # no rows and no schema: a header-only file
            columns = [d[0] for d in cur.description] if cur.description else []
            writer = pq.ParquetWriter(str(out), pa.schema([(n, pa.string()) for n in columns]))
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        out.unlink(missing_ok=True)
        raise
    finally:
        if writer is not None:
            writer.close()
        _close(con)
    return FetchResult(rows=rows, bytes=out.stat().st_size, capped=bool(cap and rows >= cap),
                       seconds=time.perf_counter() - t0, columns=columns)
