# Database sources, named connections, defined outputs - implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Either side of a comparison can be a database table (Snowflake, Databricks, SQL Server, Oracle, Postgres, DuckDB file) through Airflow-style named connections; every run leaves one folder with a fixed, documented set of files; the report says where each side came from and why the key was chosen; a single `requirements.txt` and a Dockerfile run it anywhere; the sample domain is employees and departments.

**Architecture:** A database side is fetched once into a Parquet file in the work folder and becomes an ordinary `Side(kind="parquet")`, so nothing downstream of Load changes. Three new plain-Python modules (`connections.py`, `databases.py`, `outputs.py`) hold everything that can be unit-tested without Streamlit; one new UI module (`ui_database.py`) holds the sidebar panel and the connection manager. `csvdiff.py` is not modified.

**Tech Stack:** Python 3.12-3.14, Streamlit 1.49+, DuckDB 1.2+, pandas, pyarrow; drivers `snowflake-connector-python`, `databricks-sql-connector`, `pymssql`, `oracledb`, `psycopg[binary]` (all plain pip wheels); pytest; Streamlit AppTest; Playwright for screenshots.

**Spec:** `docs/superpowers/specs/2026-09-15-database-sources-outputs-design.md`

## Global Constraints

- `csvdiff.py` is never modified.
- `st.*` only in `tablecmp/ui_*.py`, `compare_app.py`, `tablecmp/state.py`.
- No `.streamlit/` folder, ever. Streamlit settings come from the bootstrap dict or `STREAMLIT_*` env vars.
- Plain human wording, no emojis. SQL identifiers through `tablecmp.sql.ident`, literals through `tablecmp.sql.lit`.
- Existing AppTest widget keys stay: `how_A/B`, `pt_A/B`, `load_A/B`, `auto_btn`, `go`, `disp_rows`, `auto_rerun`, `bucket_pick`, `save_report`, `save_all`, `nick_A/B`, `sugg_btn`, `check_btn`, `do_profile`. Re-fetch widgets after every `at.run()`.
- Only `SELECT` / `WITH` statements ever reach a database; never `commit()`.
- No credential in any output, report, log, on-screen error, or the repository.
- Nothing company-specific anywhere; the sample domain is employees / departments.
- Text files are LF (`.gitattributes`); when writing files from Python use `newline="\n"` or write bytes.
- Streamlit does not hot-reload `tablecmp/`: restart the server after editing it.
- The headless gate: `python <scratchpad>/apptest_auto.py <name>.html` from the repo folder must stay green; after Task 3 it uses the new sample pair and its counts.
- Commit after every task with the attribution line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|---|---|
| `tablecmp/connections.py` (new) | `Connection` dataclass, URI parse/format, the `~/.crosshire-compare/connections.json` store, env overrides, `redact` |
| `tablecmp/databases.py` (new) | dialects, read-only guard, `connect`, `test`, `fetch_parquet` |
| `tablecmp/outputs.py` (new) | pair name, verdict, `summary.json` / `summary.csv` / `columns.csv` / `profile.csv` writers, formats, zip, save target rules, work-folder sweep |
| `tablecmp/ui_database.py` (new) | the Database branch of the source panel and the Connections manager |
| `tablecmp/sources.py` | `Side` gains database fields and `stem`; `work_dir`, `out_dir`, `data_roots`; BLOB as hex |
| `tablecmp/sql.py` | `scratch()` sets UTC and the temp directory |
| `tablecmp/values.py` | `length` step |
| `tablecmp/keys.py`, `profile.py`, `auto.py` | reasons, overlap, one profile reused |
| `tablecmp/compare.py` | run folder and files, `write_empty`, whole rows in hash mode, `paired.csv` by DuckDB, `value_pairs` |
| `tablecmp/report.py` | sources / key / values / filters rows, verdict, value pairs, anchors, cell cap, print CSS |
| `tablecmp/ui_results.py` | verdict from the run, downloads tab (zip, formats, per-run save folder) |
| `tablecmp/ui_sidebar.py` | `Database` option, name hint, `auto_profile` |
| `compare_app.py` | pair name, notes, profile hand-off, sweep, `COMPARE_UPLOAD_MB` |
| `examples/make_sample.py` | employee sample: two CSVs and `sample.duckdb` |
| `tests/` (new) | pytest for every plain module and the two AppTest flows |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `requirements.txt`, `requirements.lock` | packaging |
| `README.md`, `README.html`, `docs/*.png` | documentation |

---

### Task 1: Connections store

**Files:**
- Create: `tablecmp/connections.py`
- Create: `tests/__init__.py` (empty), `tests/test_connections.py`

**Interfaces:**
- Produces: `Connection` dataclass; `KINDS: dict[str, str]` (kind -> label); `to_uri(c) -> str`; `from_uri(name, uri) -> Connection`; `store_path() -> Path`; `load_all() -> dict[str, Connection]` (file then env, env wins); `save(c) -> None`; `delete(name) -> None`; `resolve(name, passwords: dict[str, str]) -> Connection`; `class PasswordNeeded(Exception)` with `.name`; `redact(text) -> str`; `env_connections() -> dict[str, Connection]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connections.py
import json, os, stat
import pytest
from tablecmp import connections as cx


def test_uri_round_trip_snowflake():
    c = cx.Connection(name="prod", kind="snowflake", host="xy12345.eu-west-1", database="ANALYTICS",
                      schema="HR", user="DSINGH", password="p@ss/word",
                      extra={"warehouse": "WH_SMALL", "role": "ANALYST"})
    uri = cx.to_uri(c)
    assert uri.startswith("snowflake://DSINGH:p%40ss%2Fword@xy12345.eu-west-1/ANALYTICS/HR?")
    back = cx.from_uri("prod", uri)
    assert back == c


@pytest.mark.parametrize("uri", [
    "databricks://token:dapi123@adb-1.azuredatabricks.net/?http_path=/sql/1.0/warehouses/abc&catalog=main&schema=hr",
    "mssql://svc:pw@sql01.corp:1433/Payroll",
    "oracle://hr_ro:pw@ora01:1521/?service_name=HRPDB",
    "postgresql://reporter:pw@pg01:5432/hr",
    "duckdb:///C:/data/sample.duckdb",
])
def test_uri_round_trip_other_kinds(uri):
    c = cx.from_uri("x", uri)
    assert cx.to_uri(c) == uri


def test_duckdb_uri_is_a_path():
    c = cx.from_uri("s", "duckdb:///C:/data/sample.duckdb")
    assert c.kind == "duckdb" and c.host == "C:/data/sample.duckdb"


def test_save_load_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "c" / "connections.json"))
    monkeypatch.delenv("COMPARE_CONN_PROD", raising=False)
    cx.save(cx.Connection(name="prod", kind="postgresql", host="pg", port=5432, database="hr",
                          user="u", password="secret"))
    cx.save(cx.Connection(name="dev", kind="postgresql", host="pg", port=5432, database="hr",
                          user="u", password=None))
    raw = json.loads((tmp_path / "c" / "connections.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    by = {c["name"]: c for c in raw["connections"]}
    assert by["prod"]["password"] == "secret" and "password" not in by["dev"]
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "c" / "connections.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "c").stat().st_mode) == 0o700
    got = cx.load_all()
    assert got["prod"].password == "secret" and got["dev"].password is None
    assert got["prod"].source == "file"
    cx.delete("prod")
    assert "prod" not in cx.load_all()


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="prod", kind="postgresql", host="old", database="hr", user="u"))
    monkeypatch.setenv("COMPARE_CONN_prod", "postgresql://u:pw@new:5432/hr")
    got = cx.load_all()
    assert got["prod"].host == "new" and got["prod"].source == "env"


def test_resolve_asks_for_a_missing_password(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="dev", kind="postgresql", host="pg", database="hr", user="u"))
    with pytest.raises(cx.PasswordNeeded) as e:
        cx.resolve("dev", {})
    assert e.value.name == "dev"
    assert cx.resolve("dev", {"dev": "typed"}).password == "typed"


def test_redact():
    s = ("postgresql://u:secret@h/db password=secret pwd=secret token=abc "
         "Authorization: Bearer xyz")
    r = cx.redact(s)
    for word in ("secret", "abc", "xyz"):
        assert word not in r
    assert "postgresql://u:***@h/db" in r
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_connections.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tablecmp.connections'`

- [ ] **Step 3: Write the module**

```python
# tablecmp/connections.py
"""Named database connections, the way Airflow keeps them: a name, a kind, where it is.

Made in the sidebar, kept in connections.json in the user's home folder (never in the repo),
and overridable one by one with COMPARE_CONN_<NAME>=<uri>. The URI form is Airflow's:

    snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=R
    databricks://token:TOKEN@host/?http_path=/sql/1.0/warehouses/x&catalog=c&schema=s
    mssql://user:pass@server:1433/db
    oracle://user:pass@host:1521/?service_name=X
    postgresql://user:pass@host:5432/db
    duckdb:///C:/data/sample.duckdb
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

KINDS = {"snowflake": "Snowflake", "databricks": "Databricks", "mssql": "SQL Server",
         "oracle": "Oracle", "postgresql": "Postgres", "duckdb": "DuckDB file"}
DEFAULT_PORTS = {"mssql": 1433, "oracle": 1521, "postgresql": 5432}
ENV_PREFIX = "COMPARE_CONN_"
NAME_OK = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class Connection:
    name: str
    kind: str
    host: str = ""                  # account (Snowflake), host, server - or the file path (duckdb)
    port: int | None = None
    database: str = ""
    schema: str = ""
    user: str = ""
    password: str | None = None     # None: not saved - asked for in the session
    extra: dict[str, str] = field(default_factory=dict)
    timeout: int = 600              # query timeout in seconds
    source: str = "file"            # file | env

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def where(self) -> str:
        """One line for lists: host and database, never a credential."""
        if self.kind == "duckdb":
            return self.host
        bits = [self.host + (f":{self.port}" if self.port else "")]
        if self.database:
            bits.append(self.database + (f".{self.schema}" if self.schema else ""))
        for k in ("warehouse", "http_path", "service_name"):
            if self.extra.get(k):
                bits.append(self.extra[k])
        return " · ".join(bits)


class PasswordNeeded(Exception):
    def __init__(self, name: str):
        super().__init__(f"Connection {name} has no saved password")
        self.name = name


def to_uri(c: Connection) -> str:
    if c.kind == "duckdb":
        return "duckdb:///" + c.host
    auth = quote(c.user, safe="") if c.user else ""
    if c.password is not None:
        auth += ":" + quote(c.password, safe="")
    netloc = (auth + "@" if auth else "") + c.host + (f":{c.port}" if c.port else "")
    path = "/" + "/".join(quote(p, safe="") for p in (c.database, c.schema) if p)
    query = urlencode({k: v for k, v in c.extra.items() if v})
    if c.timeout != 600:
        query += ("&" if query else "") + f"timeout={c.timeout}"
    return f"{c.kind}://{netloc}{path}" + (f"?{query}" if query else "")


def from_uri(name: str, uri: str) -> Connection:
    u = urlsplit(uri)
    kind = u.scheme.lower()
    if kind not in KINDS:
        raise ValueError(f"Unknown connection kind {u.scheme!r} - one of {', '.join(KINDS)}")
    if kind == "duckdb":
        return Connection(name=name, kind=kind, host=uri[len("duckdb:///"):])
    parts = [unquote(p) for p in u.path.split("/") if p]
    extra = dict(parse_qsl(u.query, keep_blank_values=False))
    timeout = int(extra.pop("timeout", 600))
    return Connection(name=name, kind=kind, host=u.hostname or "", port=u.port,
                      database=parts[0] if parts else "", schema=parts[1] if len(parts) > 1 else "",
                      user=unquote(u.username) if u.username else "",
                      password=unquote(u.password) if u.password is not None else None,
                      extra=extra, timeout=timeout)


def store_path() -> Path:
    given = os.environ.get("COMPARE_CONNECTIONS", "").strip()
    return Path(given).expanduser() if given else Path.home() / ".crosshire-compare" / "connections.json"


def _read_file() -> dict[str, Connection]:
    path = store_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for rec in raw.get("connections", []):
        rec = dict(rec)
        rec.setdefault("password", None)
        out[rec["name"]] = Connection(**{k: v for k, v in rec.items() if k in Connection.__dataclass_fields__})
    return out


def _write_file(conns: dict[str, Connection]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    records = []
    for c in conns.values():
        if c.source == "env":
            continue
        rec = asdict(c)
        rec.pop("source", None)
        if rec.get("password") is None:
            rec.pop("password", None)
        records.append(rec)
    text = json.dumps({"version": 1, "connections": records}, indent=2)
    fd, tmp = tempfile.mkstemp(prefix=".connections-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def env_connections() -> dict[str, Connection]:
    out = {}
    for key, val in os.environ.items():
        if key.startswith(ENV_PREFIX) and val.strip():
            name = key[len(ENV_PREFIX):]
            try:
                c = from_uri(name, val.strip())
            except ValueError:
                continue
            c.source = "env"
            out[name] = c
    return out


def load_all() -> dict[str, Connection]:
    conns = _read_file()
    conns.update(env_connections())
    return conns


def save(c: Connection) -> None:
    if not NAME_OK.match(c.name):
        raise ValueError("A connection name is letters, digits, _ and - only")
    if c.kind not in KINDS:
        raise ValueError(f"Unknown connection kind {c.kind!r}")
    conns = _read_file()
    c.source = "file"
    conns[c.name] = c
    _write_file(conns)


def delete(name: str) -> None:
    conns = _read_file()
    conns.pop(name, None)
    _write_file(conns)


def resolve(name: str, passwords: dict[str, str] | None = None) -> Connection:
    """The connection with a password: saved, or typed this session, else PasswordNeeded."""
    conns = load_all()
    if name not in conns:
        raise KeyError(f"No connection called {name}")
    c = conns[name]
    if c.password is None and c.kind != "duckdb":
        typed = (passwords or {}).get(name)
        if not typed:
            raise PasswordNeeded(name)
        c = Connection(**{**asdict(c), "password": typed})
    return c


_SECRET_KV = re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api_key)\s*[=:]\s*\S+")
_SECRET_AUTH = re.compile(r"(?i)authorization:\s*\S+(\s+\S+)?")
_SECRET_URI = re.compile(r"(\w+://[^:/@\s]+:)[^@\s]+(@)")


def redact(text: str) -> str:
    """Driver messages with every password, token and user:pass@ blanked."""
    text = _SECRET_URI.sub(r"\1***\2", str(text))
    text = _SECRET_AUTH.sub("authorization: ***", text)
    return _SECRET_KV.sub(lambda m: m.group(1) + "=***", text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_connections.py -q`
Expected: 8 passed. If `test_uri_round_trip_other_kinds` fails on query order, `urlencode` keeps dict order - the `extra` dict is built from `parse_qsl` in the URI's order, so the round trip holds.

- [ ] **Step 5: Commit**

```bash
git add tablecmp/connections.py tests/__init__.py tests/test_connections.py
git commit -m "Add named database connections: URI form, home-folder store, env overrides, redact"
```

---

### Task 2: Database dialects, read-only guard and the Parquet fetch

**Files:**
- Create: `tablecmp/databases.py`
- Create: `tests/test_databases.py`

**Interfaces:**
- Consumes: `Connection` from Task 1.
- Produces: `check_read_only(sql) -> str` (raises `NotReadOnly`); `limit_sql(kind, sql, n) -> str`; `table_sql(kind, table) -> str`; `probe_sql(kind, sql) -> str`; `DriverMissing(Exception)`; `connect(c) -> connection`; `test(c) -> TestResult(ok, message, identity, seconds)`; `fetch_parquet(c, sql, path, cap, progress=None) -> FetchResult(rows, bytes, capped, seconds, columns)`; `origin_of(c, table_or_sql) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_databases.py
import pyarrow.parquet as pq
import pytest
from tablecmp import databases as db
from tablecmp.connections import Connection


@pytest.mark.parametrize("sql", ["SELECT 1", "  with x as (select 1) select * from x",
                                 "SELECT * FROM t -- trailing comment", "SELECT 1;",
                                 'SELECT "into" FROM t', "SELECT 'go into' FROM t"])
def test_guard_accepts(sql):
    assert db.check_read_only(sql)


@pytest.mark.parametrize("sql,word", [
    ("SELECT 1; DELETE FROM t", "two statements"),
    ("SELECT * INTO backup FROM t", "INTO"),
    ("/* SELECT */ UPDATE t SET a=1", "UPDATE"),
    ("CALL refresh()", "CALL"),
    ("", "empty"),
])
def test_guard_refuses(sql, word):
    with pytest.raises(db.NotReadOnly) as e:
        db.check_read_only(sql)
    assert word.lower() in str(e.value).lower()


def test_limit_sql_per_dialect():
    assert db.limit_sql("snowflake", "SELECT * FROM t", 10) == "SELECT * FROM (SELECT * FROM t) q LIMIT 10"
    assert db.limit_sql("oracle", "SELECT * FROM t", 10) == "SELECT * FROM (SELECT * FROM t) q FETCH FIRST 10 ROWS ONLY"
    assert db.limit_sql("mssql", "SELECT * FROM t", 10) == "SELECT TOP (10) * FROM (SELECT * FROM t) q"
    assert db.limit_sql("mssql", "SELECT * FROM t ORDER BY a", 10) == "SELECT * FROM t ORDER BY a"
    assert db.limit_sql("mssql", "WITH x AS (SELECT 1 a) SELECT * FROM x", 10).startswith("WITH")
    assert db.limit_sql("postgresql", "SELECT 1", 0) == "SELECT 1"


def test_table_sql_quotes_per_dialect():
    assert db.table_sql("snowflake", "HR.EMPLOYEES") == 'SELECT * FROM "HR"."EMPLOYEES"'
    assert db.table_sql("mssql", "dbo.Employees") == "SELECT * FROM [dbo].[Employees]"
    assert db.table_sql("databricks", "main.hr.employees") == "SELECT * FROM `main`.`hr`.`employees`"


def test_driver_missing_names_the_package(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("pymssql"):
            raise ImportError("no")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(db.DriverMissing) as e:
        db.connect(Connection(name="p", kind="mssql", host="h", database="d", user="u", password="p"))
    assert "pip install pymssql" in str(e.value)


class FakeCursor:
    description = [("id", None), ("name", None)]

    def __init__(self, rows, fail_after=None):
        self.rows, self.fail_after, self.calls = rows, fail_after, 0

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, n):
        self.calls += 1
        if self.fail_after and self.calls > self.fail_after:
            raise RuntimeError("boom")
        out, self.rows = self.rows[:n], self.rows[n:]
        return out

    def close(self):
        pass


class FakeConn:
    def __init__(self, cur):
        self.cur, self.closed = cur, False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True

    def rollback(self):
        pass


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
    assert fc.closed and seen and "rows" in seen[0]


def test_fetch_parquet_cleans_up_on_error(tmp_path, monkeypatch):
    fc = FakeConn(FakeCursor([(i, "x") for i in range(10)], fail_after=1))
    monkeypatch.setattr(db, "connect", lambda c: fc)
    monkeypatch.setattr(db, "BATCH", 4)
    out = tmp_path / "x.parquet"
    with pytest.raises(RuntimeError):
        db.fetch_parquet(Connection(name="p", kind="postgresql", host="h", user="u", password="p"),
                         "SELECT * FROM t", str(out), cap=0)
    assert not out.exists() and fc.closed


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
    with pytest.raises(db.NotReadOnly):
        db.fetch_parquet(c, "DELETE FROM hr.employees", str(tmp_path / "d.parquet"), cap=0)
    assert db.origin_of(c, "hr.employees") == "DuckDB file · hr.employees"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_databases.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tablecmp.databases'`

- [ ] **Step 3: Write the module**

```python
# tablecmp/databases.py
"""Reading a table or a query out of a database into a Parquet file, read-only.

Every kind has a dialect: how to quote a name, cap a query, probe its columns, test the
connection. The drivers are imported only when used, so the app runs without them and says
which package a database needs. Nothing but SELECT / WITH is ever sent, and no connection
ever commits.
"""
from __future__ import annotations

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
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]|`[^`]*`")


def check_read_only(sql: str) -> str:
    """The statement with comments stripped, or NotReadOnly with the offending word."""
    clean = _COMMENTS.sub(" ", sql or "").strip().rstrip(";").strip()
    if not clean:
        raise NotReadOnly("The statement is empty")
    bare = _QUOTED.sub(" ", clean)
    if ";" in bare:
        raise NotReadOnly("Only one statement is allowed - two statements were given")
    first = re.match(r"[A-Za-z]+", bare)
    word = first.group(0).upper() if first else ""
    if word not in ("SELECT", "WITH"):
        raise NotReadOnly(f"Only SELECT or WITH statements are sent - this one starts with {word or 'something else'}")
    if re.search(r"\bINTO\b", bare, re.I):
        raise NotReadOnly("SELECT ... INTO writes a table - INTO is not allowed")
    return clean


def quote(kind: str, name: str) -> str:
    o, c = QUOTES.get(kind, ('"', '"'))
    return o + name.replace(c, c + c) + c


def table_sql(kind: str, table: str) -> str:
    parts = [p.strip() for p in table.strip().split(".") if p.strip()]
    if not parts:
        raise ValueError("Give the table as schema.table")
    return "SELECT * FROM " + ".".join(quote(kind, p) for p in parts)


def limit_sql(kind: str, sql: str, n: int) -> str:
    if not n:
        return sql
    if kind == "oracle":
        return f"SELECT * FROM ({sql}) q FETCH FIRST {int(n)} ROWS ONLY"
    if kind == "mssql":
        if re.match(r"\s*WITH\b", sql, re.I) or re.search(r"\bORDER\s+BY\b", sql, re.I):
            return sql                     # the batch loop stops at n instead
        return f"SELECT TOP ({int(n)}) * FROM ({sql}) q"
    return f"SELECT * FROM ({sql}) q LIMIT {int(n)}"


def probe_sql(kind: str, sql: str) -> str:
    return f"SELECT * FROM ({sql}) q WHERE 1=0"


def has_order_by(sql: str) -> bool:
    return bool(re.search(r"\bORDER\s+BY\b", _QUOTED.sub(" ", _COMMENTS.sub(" ", sql)), re.I))


def origin_of(c: Connection, what: str) -> str:
    return f"{KINDS.get(c.kind, c.kind)} · {' '.join(what.split())[:80]}"


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
    m = _import(kind)
    if kind == "duckdb":
        return m.connect(c.host, read_only=True)
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
    raise ValueError(f"Unknown kind {kind}")


def _close(con) -> None:
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
    if kind == "duckdb":
        return con.cursor()
    cur = con.cursor()
    if kind == "oracle":
        cur.execute("SET TRANSACTION READ ONLY")
    return cur


def test(c: Connection) -> TestResult:
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
            n = con.execute("SELECT count(*) FROM information_schema.tables").fetchone()[0]
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
def _to_arrow(cur, rows: list, schema: pa.Schema | None) -> pa.Table:
    names = [d[0] for d in cur.description]
    cols = list(zip(*rows)) if rows else [[] for _ in names]
    def clean(v):
        if v is None or isinstance(v, (bool, int, float, str, bytes)):
            return v
        if isinstance(v, memoryview):
            return v.tobytes()
        return str(v)          # Decimal, UUID, LOB handles, intervals: text is the honest form
    arrays = [[clean(v) for v in col] for col in cols]
    if schema is None:
        return pa.table({n: pa.array(a) for n, a in zip(names, arrays)})
    return pa.table({n: pa.array(a, type=schema.field(n).type) for n, a in zip(names, arrays)})


def _batches(con, cur, kind: str):
    """Yield pyarrow tables, driver by driver."""
    if kind == "duckdb":
        while True:
            b = cur.fetch_record_batch(BATCH)
            t = pa.Table.from_batches([b]) if b.num_rows else None
            if t is None or t.num_rows == 0:
                break
            yield t
        return
    if kind == "snowflake":
        for b in cur.fetch_arrow_batches():
            yield b if isinstance(b, pa.Table) else pa.Table.from_batches([b])
        return
    if kind == "databricks":
        while True:
            t = cur.fetchmany_arrow(BATCH)
            if t.num_rows == 0:
                break
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
    """Run the statement and stream the rows into a Parquet file. Read-only, batch by batch."""
    say = progress or (lambda _m: None)
    clean = check_read_only(sql)
    stmt = limit_sql(c.kind, clean, cap)
    out = Path(path)
    t0 = time.perf_counter()
    con = connect(c)
    writer = None
    rows = 0
    columns: list[str] = []
    try:
        cur = _cursor(con, c.kind)
        cur.execute(stmt)
        for table in _batches(con, cur, c.kind):
            if cap and rows + table.num_rows > cap:
                table = table.slice(0, cap - rows)
            if writer is None:
                columns = list(table.column_names)
                writer = pq.ParquetWriter(str(out), table.schema, compression="zstd")
            elif table.schema != writer.schema:
                table = table.cast(writer.schema)
            writer.write_table(table)
            rows += table.num_rows
            size = out.stat().st_size if out.exists() else 0
            say(f"{rows:,} rows · {size / 1e6:,.0f} MB · {time.perf_counter() - t0:.0f} s")
            if shutil.disk_usage(out.parent).free < MIN_FREE_BYTES:
                raise RuntimeError("Stopped: under 1 GB free in the work folder")
            if cap and rows >= cap:
                break
        if writer is None:                        # no rows at all: a header-only file
            names = [d[0] for d in cur.description] if cur.description else []
            columns = names
            writer = pq.ParquetWriter(str(out), pa.schema([(n, pa.string()) for n in names]))
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
```

Notes for the implementer: `pymssql.connect` accepts `read_only=True` from pymssql 2.3; `oracledb` thin mode needs no client; `psycopg` (v3) `connect(..., options=...)`. Check each call against the driver's current documentation with the context7 tool before finalising, and keep the fake-cursor tests as the proof that can run here. The DuckDB `fetch_record_batch` returns a `pyarrow.RecordBatch` (possibly empty); the loop above handles both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_databases.py -q`
Expected: all passed. `test_guard_accepts` with `SELECT "into"`: the quoted identifier is stripped before the `INTO` check.

- [ ] **Step 5: Commit**

```bash
git add tablecmp/databases.py tests/test_databases.py
git commit -m "Add database dialects, the read-only guard and the streamed Parquet fetch"
```

---

### Task 3: Employee sample data and the wording scrub

**Files:**
- Modify: `examples/make_sample.py` (rewrite)
- Create: `examples/hr_employees.csv`, `examples/payroll_employees.csv`, `examples/sample.duckdb` (generated); delete `examples/left.csv`, `examples/right.csv`
- Modify: `tablecmp/ui_sidebar.py:47,76,82,92,105`, `tablecmp/sources.py:19`, `tablecmp/theme.py:14-15`, `.gitignore`
- Modify: the scratchpad gate `apptest_auto.py` to load the new pair (the executor copies it into `tests/` in Task 11)

**Interfaces:**
- Produces: the sample pair every later task, README and test uses; `sample.duckdb` with tables `hr.employees` and `payroll.employees`.

- [ ] **Step 1: Rewrite the generator**

```python
# examples/make_sample.py
"""Regenerates the sample pair: the same 3,000 employees exported by two systems.

hr_employees.csv       the HR system: emp_id, first_name, last_name, department, salary,
                       hire_date (ISO), active (true/false)
payroll_employees.csv  payroll: renames every column, joins the two names, spells four
                       departments differently, writes salaries with thousands separators,
                       dates as dd/mm/yyyy, active as Y/N, adds a column HR does not have
                       (CostCenter), drops the last 40 employees and adds 25 of its own, and
                       changes a few salaries and a few active flags
sample.duckdb          the same two tables as hr.employees and payroll.employees, so the
                       database path can be tried with no server

Deterministic (seed 7):    python examples/make_sample.py
"""
import csv
import random
from pathlib import Path

import duckdb

random.seed(7)
here = Path(__file__).resolve().parent
FIRST = ["Aarav", "Amara", "Chen", "Elena", "Fatima", "Hugo", "Ines", "Jonas", "Kofi", "Lena",
         "Mateo", "Nadia", "Omar", "Priya", "Rafael", "Sara", "Tomasz", "Uma", "Viktor", "Zofia"]
LAST = ["Nair", "Okafor", "Kowalski", "Schmidt", "Rossi", "Haddad", "Novak", "Silva", "Tanaka",
        "Mensah", "Petrov", "Larsen", "Costa", "Nakamura", "Ibrahim", "Dubois", "Moreau", "Sato"]
DEPTS = ["Finance", "Engineering", "Sales", "Support", "Marketing", "Operations", "Legal", "People"]
RENAMED = {"Finance": "Finance & Control", "Engineering": "Eng", "Sales": "Sales EMEA"}
COST = {"Finance": "CC-110", "Engineering": "CC-220", "Sales": "CC-310", "Support": "CC-320",
        "Marketing": "CC-410", "Operations": "CC-510", "Legal": "CC-120", "People": "CC-130"}

n = 3000
rows = []
for i in range(1, n + 1):
    y = random.randint(2018, 2026)
    m = random.randint(1, 9 if y == 2026 else 12)
    rows.append({"emp_id": f"E{10000 + i}", "first_name": random.choice(FIRST),
                 "last_name": random.choice(LAST), "department": random.choice(DEPTS),
                 "salary": round(random.uniform(2150, 14980), 2),
                 "hire_date": f"{y}-{m:02d}-{random.randint(1, 28):02d}",
                 "active": random.random() < 0.85})
with open(here / "hr_employees.csv", "w", newline="\n", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

payroll = []
for r in rows[:-40]:
    sal = r["salary"] + (random.choice([0] * 8 + [1]) * round(random.uniform(-150, 150), 2))
    dept = r["department"]
    if random.random() < 0.30:
        dept = RENAMED.get(dept, dept)
    active = r["active"] if random.random() > 0.01 else (not r["active"])
    y, m, d = r["hire_date"].split("-")
    payroll.append({"EmployeeId": r["emp_id"], "FullName": f"{r['first_name']} {r['last_name']}",
                    "Dept": dept, "Salary": f"{sal:,.2f}", "HireDate": f"{d}/{m}/{y}",
                    "IsActive": "Y" if active else "N", "CostCenter": COST[r["department"]]})
for i in range(n + 1, n + 26):
    payroll.append({"EmployeeId": f"E{10000 + i}", "FullName": "New Starter", "Dept": "People",
                    "Salary": "3,000.00", "HireDate": "01/09/2026", "IsActive": "Y", "CostCenter": "CC-130"})
with open(here / "payroll_employees.csv", "w", newline="\n", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(payroll[0]))
    w.writeheader()
    w.writerows(payroll)

db = here / "sample.duckdb"
db.unlink(missing_ok=True)
con = duckdb.connect(str(db))
con.execute("CREATE SCHEMA hr; CREATE SCHEMA payroll")
con.execute(f"CREATE TABLE hr.employees AS SELECT * FROM read_csv('{(here / 'hr_employees.csv').as_posix()}', all_varchar=true)")
con.execute(f"CREATE TABLE payroll.employees AS SELECT * FROM read_csv('{(here / 'payroll_employees.csv').as_posix()}', all_varchar=true)")
con.close()
print("hr", n, "payroll", len(payroll), "duckdb", db.name)
```

- [ ] **Step 2: Generate and record the counts**

Run: `python examples/make_sample.py && git rm -q examples/left.csv examples/right.csv`
Then, from the repo folder, edit the gate script's data paths to `examples/hr_employees.csv` and `examples/payroll_employees.csv` and run `python <scratchpad>/apptest_auto.py sample.html`. Record the printed counts (`matched`, `only_left`, `only_right`, `diff_rows`, `cells`) and the key Auto chose (`emp_id` expected). These numbers replace `2960 / 40 / 25 / 956 / 1046` everywhere below; write them into `docs/superpowers/plans/COUNTS.md` as one line so later tasks can read them.

- [ ] **Step 3: Scrub the placeholders and comments**

In `tablecmp/ui_sidebar.py`: line 47 placeholder `C:\data\exports\employees_2026-09.csv`; line 76 caption example `` `hire_date >= '2026-07-20'` ``; line 82 placeholder `2026-07-20 · Finance · 100`; line 92 placeholder `hire_date >= '2026-07-20'\nAND department = 'Finance'`; line 105 placeholder `emp_id, first_name, dept_name, ...`. In `tablecmp/sources.py:19` the comment becomes `("Snowflake · HR.EMPLOYEES")`. In `tablecmp/theme.py:14-15` replace `Acme Table Check` with `Employee Table Check` (both lines). Grep the whole tree for `order`, `trade`, `ccy`, `currency`, `ACME`, `Globex`, `Initech`, `Umbrella`, `Hooli`, `Acme`, `SALES`: `grep -rniE "order_id|trade_|ccy|currency|acme|globex|initech|umbrella|hooli|sales\.orders" --include=*.py --include=*.md --include=*.html --include=*.svg . | grep -v csvdiff.py` must return nothing except README.md / README.html (rewritten in Task 12).

- [ ] **Step 4: .gitignore**

Append after the outputs block:

```
*__columns.csv
*__profile.csv
*__row_count_diffs.csv
*_compare_*__*/
*.zip

# Connections and secrets live in the home folder, never here
connections*.json
.env
.env.*

# DuckDB files, except the small committed sample
*.duckdb
*.duckdb.wal
!examples/sample.duckdb
```

- [ ] **Step 5: Run the gate and commit**

Run: `python <scratchpad>/apptest_auto.py sample.html` (prints the counts from Step 2 again).

```bash
git add -A examples tablecmp/ui_sidebar.py tablecmp/sources.py tablecmp/theme.py .gitignore docs/superpowers/plans/COUNTS.md
git commit -m "Employee sample pair and DuckDB sample; scrub placeholders to the employee domain"
```

---

### Task 4: Side fields, work and output folders, UTC, the length step

**Files:**
- Modify: `tablecmp/sources.py:14-58` (Side), `:88-95` (read_expr), append `work_dir`, `out_dir`, `data_roots`, `slug`
- Modify: `tablecmp/sql.py:17-22` (scratch)
- Modify: `tablecmp/values.py:45-67` (STEPS)
- Modify: `tablecmp/ui_sidebar.py:27,126` and `tablecmp/keys.py:75` and `tablecmp/compare.py:161` (temp paths -> `work_dir()`)
- Create: `tests/test_sources.py`

**Interfaces:**
- Produces: `Side.conn, query, fetched_at, cap, capped, database`; `Side.stem: str`; `Side.is_database: bool`; `slug(text) -> str`; `work_dir() -> Path`; `out_dir() -> Path | None`; `data_roots() -> list[Path]`; `path_allowed(p: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
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


def test_data_roots(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    assert src.data_roots() == [] and src.path_allowed(str(tmp_path / "any.csv"))
    (tmp_path / "in.csv").write_text("a\n1\n")
    monkeypatch.setenv("COMPARE_DATA_DIR", str(tmp_path))
    assert src.path_allowed(str(tmp_path / "in.csv"))
    assert not src.path_allowed(str(Path.home() / "x.csv"))


def test_scratch_is_utc():
    assert scratch().execute("SELECT current_setting('TimeZone')").fetchone()[0] == "UTC"


def test_length_step():
    assert "length" in STEPS and step_sql({"op": "length"}) == "length(x)"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sources.py -q` - Expected: FAIL (`AttributeError: slug`, etc.)

- [ ] **Step 3: Implement**

In `tablecmp/sources.py`, add to `Side` after `rows`:

```python
    conn: str = ""          # connection name for a database side - never a URI or password
    database: str = ""      # its kind: snowflake | databricks | mssql | oracle | postgresql | duckdb
    query: str = ""         # the SQL that was fetched
    fetched_at: str = ""    # HH:MM:SS of the fetch
    cap: int = 0            # "fetch at most" that was applied (0 = all)
    capped: bool = False    # the fetch hit the cap

    @property
    def is_database(self) -> bool:
        return bool(self.conn)

    @property
    def stem(self) -> str:
        """What names this side in output files: the connection for a database, the file's stem."""
        return slug(self.conn if self.is_database else Path(self.label).stem if self.label else "")
```

Extend `read_key` to `[..., self.limit, self.conn, self.query, self.cap, self.fetched_at]`.

Add at module level (after `looks_headerless`):

```python
def slug(text: str) -> str:
    """Letters, digits and underscores; runs of anything else become one underscore."""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")


def work_dir() -> Path:
    """Where fetches, snapshots and run folders go: COMPARE_WORK_DIR or the temp folder."""
    given = os.environ.get("COMPARE_WORK_DIR", "").strip()
    p = Path(given).expanduser() if given else Path(tempfile.gettempdir()) / "crosshire-compare"
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir() -> Path | None:
    """The root every save must land under, when COMPARE_OUT_DIR is set."""
    given = os.environ.get("COMPARE_OUT_DIR", "").strip()
    return Path(given).expanduser() if given else None


def data_roots() -> list[Path]:
    given = os.environ.get("COMPARE_DATA_DIR", "").strip()
    return [Path(p).expanduser().resolve() for p in given.split(os.pathsep) if p.strip()] if given else []


def path_allowed(path: str) -> bool:
    """A 'Path on disk' is fine unless COMPARE_DATA_DIR is set and it lies outside every root."""
    roots = data_roots()
    if not roots:
        return True
    try:
        p = Path(path).resolve(strict=True)
    except OSError:
        return False
    return any(p == r or r in p.parents for r in roots)
```

with `import os, tempfile` at the top. In `read_expr` (line 93-94) build the select as:

```python
    sel = ", ".join((f"hex({ident(c)}) AS {ident(c)}" if "BLOB" in str(t).upper()
                     else f"{ident(c)}::VARCHAR AS {ident(c)}") for c, t in cols.items()) or "*"
```

(`cols` is the `source_schema` dict; iterate `.items()`.)

In `tablecmp/sql.py` `scratch()` add after the `preserve_insertion_order` line:

```python
    con.execute("SET TimeZone = 'UTC'")
    from .sources import work_dir       # local import: sources imports sql
    con.execute(f"SET temp_directory = {lit(str(work_dir() / 'duckdb'))}")
    mem = os.environ.get("COMPARE_DUCKDB_MEMORY", "").strip()
    if mem:
        con.execute(f"SET memory_limit = {lit(mem)}")
```

with `import os` at the top. In `tablecmp/values.py` STEPS add after `"right N characters"`: `"length": ("length(x)", ()),`.

Replace the temp-folder uses: `ui_sidebar.py:27` `Path(tempfile.gettempdir())` -> `work_dir()`; `ui_sidebar.py:126` likewise; `keys.py:75` likewise; `compare.py:161` `tempfile.mkdtemp(prefix="cmp_", dir=str(work_dir()))` (Task 5 replaces this line again). Import `work_dir` from `.sources` in each.

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests -q` and `python <scratchpad>/apptest_auto.py t4.html` - Expected: all pass; gate prints the Task 3 counts.

- [ ] **Step 5: Commit**

```bash
git add tablecmp/sources.py tablecmp/sql.py tablecmp/values.py tablecmp/ui_sidebar.py tablecmp/keys.py tablecmp/compare.py tests/test_sources.py
git commit -m "Side carries its database origin; work and output folders; UTC scratch; length step"
```

---

### Task 5: Outputs - the run folder, its files, the verdict, formats, zip

**Files:**
- Create: `tablecmp/outputs.py`
- Modify: `tablecmp/compare.py:154-192` (run_comparison), `:195-218` (engine options), `:221-246` (hash tables), `:483-500` (paired), add `value_pairs`
- Create: `tests/test_outputs.py`

**Interfaces:**
- Consumes: `Side.stem`, `work_dir`, `out_dir` (Task 4).
- Produces: `pair_name(A, B) -> str`; `Verdict(status, tone, word)`; `verdict_of(res, mode) -> Verdict`; `run_id(started: datetime) -> str`; `summary_payload(run, A, B, name_a, name_b, notes, profile_df) -> dict`; `write_summary(run, A, B, name_a, name_b, notes=None, profile_df=None) -> None` (json + csv + columns.csv + profile.csv); `SUMMARY_COLUMNS: list[str]`; `table_formats(choice: str | None) -> set[str]`; `write_parquet_copies(run) -> list[Path]`; `zip_run(run) -> Path`; `save_target(folder_text: str, run) -> Path` (raises `ValueError` outside `COMPARE_OUT_DIR`); `default_save_folder(run, base: Path) -> Path`; `sweep_work_dir(keep_hours=24) -> int`. In `compare.py`: `run["run_id"]`, `run["started_at"]`, `run["verdict"]`, `run["pair"]`; `value_pairs(run, n=5) -> dict[str, pd.DataFrame]`; `paired.csv` written at run time.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_outputs.py
import csv, json, os, time, zipfile
from pathlib import Path
import pytest
from tablecmp import outputs as out
from tablecmp.compare import Outcome, run_comparison
from tablecmp.sources import Side
from tablecmp.values import ColSpec, ReadOptions

HERE = Path(__file__).resolve().parent.parent / "examples"


def test_pair_name_defaults_and_slugs():
    assert out.pair_name(Side(), Side()) == "Left_compare_Right"
    assert out.pair_name(Side(name="prod", label="x.parquet", conn="prod"), Side(label="payroll employees.csv")) == "prod_compare_payroll_employees"


@pytest.mark.parametrize("diff,only,matched,word", [(0, 0, 100, "Identical"), (3, 0, 100, "Small differences"),
                                                    (10, 0, 100, "Differences"), (0, 200, 100, "Differences")])
def test_verdict(diff, only, matched, word):
    res = Outcome(diff_rows=diff, only_left=only, matched_rows=matched)
    assert out.verdict_of(res, "key").word == word
    assert out.verdict_of(Outcome(error="x"), "key").status == "error"


def _run(tmp_path, monkeypatch, fmt="csv"):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    A = Side(name="hr", label="hr_employees.csv", csv_path=str(HERE / "hr_employees.csv"))
    B = Side(name="payroll", label="payroll_employees.csv", csv_path=str(HERE / "payroll_employees.csv"))
    from tablecmp.sources import source_schema, file_stamp
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path)); s.source_columns = list(s.schema)
    specs = [ColSpec(canon="emp_id", a_src="emp_id", b_src="EmployeeId", kind="text"),
             ColSpec(canon="department", a_src="department", b_src="Dept", kind="text"),
             ColSpec(canon="active", a_src="active", b_src="IsActive", kind="boolean")]
    cfg = {"name": out.pair_name(A, B), "mode": "key", "keys": ["emp_id"], "specs": [s.__dict__ for s in specs],
           "compare_columns": ["department", "active"], "only_a": ["salary"], "only_b": ["CostCenter"],
           "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0, "column_rules": {},
           "filters": {}, "left_filters": {}, "right_filters": {}, "display_rows": 100,
           "null_tokens": ["NULL"], "table_formats": [fmt] if fmt != "both" else ["csv", "parquet"]}
    return run_comparison(A, B, cfg, ReadOptions(tokens=("NULL",), trim=True, empty_null=True), "sig"), A, B


def test_run_folder_has_every_file(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    out.write_summary(run, A, B, "hr", "payroll", notes=["key: emp_id"])
    folder = Path(run["folder"])
    assert folder.name.startswith("hr_compare_payroll__") and folder.parent == tmp_path / "work"
    names = {p.name for p in folder.iterdir()}
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "diff.html"):
        assert f"hr_compare_payroll__{suffix}" in names, suffix
    js = json.loads((folder / "hr_compare_payroll__summary.json").read_text(encoding="utf-8"))
    assert js["schema_version"] == 1 and js["pair"] == "hr_compare_payroll" and js["run_id"] == run["run_id"]
    assert js["sources"]["A"]["name"] == "hr" and js["sources"]["B"]["label"] == "payroll_employees.csv"
    assert js["verdict"]["word"] and js["notes"] == ["key: emp_id"]
    assert {f["name"] for f in js["files"]} >= {"hr_compare_payroll__cell_diffs.csv"}
    assert "password" not in json.dumps(js).lower()
    with open(folder / "hr_compare_payroll__summary.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == out.SUMMARY_COLUMNS and len(rows) == 2
    with open(folder / "hr_compare_payroll__columns.csv", newline="") as fh:
        cols = list(csv.DictReader(fh))
    assert {c["column"] for c in cols} >= {"emp_id", "department", "active", "salary", "CostCenter"}
    assert next(c for c in cols if c["column"] == "department")["role"] == "compared"


def test_parquet_copies_and_zip(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch, fmt="both")
    out.write_summary(run, A, B, "hr", "payroll")
    written = out.write_parquet_copies(run)
    names = {p.name for p in written}
    assert {"hr_compare_payroll__cell_diffs.parquet", "hr_compare_payroll__left_only.parquet",
            "hr_compare_payroll__paired.parquet", "hr_compare_payroll__columns.parquet"} <= names
    z = out.zip_run(run)
    assert z.name.startswith("hr_compare_payroll__") and z.suffix == ".zip"
    with zipfile.ZipFile(z) as zf:
        assert "hr_compare_payroll__summary.json" in zf.namelist()


def test_save_target_is_fenced(tmp_path, monkeypatch):
    monkeypatch.delenv("COMPARE_OUT_DIR", raising=False)
    run = {"pair": "a_compare_b", "run_id": "20260915-101233"}
    assert out.default_save_folder(run, tmp_path) == tmp_path / "a_compare_b__20260915-101233"
    assert out.save_target(str(tmp_path / "x"), run) == (tmp_path / "x").resolve()
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    assert out.default_save_folder(run, tmp_path) == tmp_path / "out" / "a_compare_b__20260915-101233"
    assert out.save_target("sub", run) == (tmp_path / "out" / "sub").resolve()
    with pytest.raises(ValueError):
        out.save_target(str(tmp_path / "elsewhere"), run)


def test_sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path))
    old = tmp_path / "a_compare_b__20260101-000000"; old.mkdir(); (old / "x").write_text("1")
    os.utime(old, (time.time() - 90000, time.time() - 90000))
    new = tmp_path / "a_compare_b__20260915-000000"; new.mkdir()
    assert out.sweep_work_dir(24) == 1 and not old.exists() and new.exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_outputs.py -q` - Expected: FAIL (`No module named 'tablecmp.outputs'`)

- [ ] **Step 3: Write `outputs.py`**

```python
# tablecmp/outputs.py
"""What a run leaves behind: one folder, a fixed set of files, one name.

<pair>__<run_id>/ with <pair>__summary.json (the whole run for a script), __summary.csv
(one row, fixed columns), __columns.csv, __profile.csv when a profile ran, the engine's
__cell_diffs / __left_only / __right_only / __diff.html, __paired.csv, __report.html, the same
tables as Parquet on a switch, and a zip of the lot. <pair> is <left>_compare_<right>.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from .sources import Side, out_dir, work_dir
from .sql import lit

SCHEMA_VERSION = 1
SUMMARY_COLUMNS = ["schema_version", "run_id", "started_at", "pair", "left", "right", "mode", "keys",
                   "rows_left_read", "rows_right_read", "rows_left", "rows_right", "matched_rows",
                   "only_left", "only_right", "diff_rows", "cell_diffs", "duplicate_keys_left",
                   "duplicate_keys_right", "status", "tone", "seconds", "error"]
SETTINGS_KEYS = ["mode", "keys", "compare_columns", "only_a", "only_b", "trim", "empty_as_null",
                 "ignore_case", "tolerance", "column_rules", "filters", "left_filters", "right_filters",
                 "null_tokens", "specs", "table_formats"]
TABLES = ["cell_diffs", "left_only", "right_only", "paired", "columns", "profile"]
COLUMNS_HEADER = ["column", "name_a", "name_b", "role", "read_as", "matched", "mismatched", "match_pct",
                  "values_only_a", "values_only_b"]
PROFILE_HEADER = ["column", "side", "rows", "nulls", "null_pct", "distinct", "distinct_pct", "min", "max",
                  "mean", "avg_length"]


@dataclass
class Verdict:
    status: str      # identical | differences | error
    tone: str        # ok | warn | bad
    word: str        # Identical | Small differences | Differences | Error
    rule: str = ("rows that differ under 5% of matched rows and one-sided rows no more than "
                 "matched rows count as small differences")


def verdict_of(res, mode: str = "key") -> Verdict:
    if getattr(res, "error", ""):
        return Verdict("error", "bad", "Error")
    orphans = res.only_left + res.only_right
    if not res.diff_rows and not orphans:
        return Verdict("identical", "ok", "Identical")
    pct = res.diff_rows / res.matched_rows * 100 if res.matched_rows else 100.0
    if pct < 5 and orphans <= res.matched_rows:
        return Verdict("differences", "warn", "Small differences")
    return Verdict("differences", "bad", "Differences")


def pair_name(A: Side, B: Side) -> str:
    return f"{A.stem or 'Left'}_compare_{B.stem or 'Right'}"


def run_id(started: datetime | None = None) -> str:
    return (started or datetime.now()).strftime("%Y%m%d-%H%M%S")


def table_formats(choice: str | None = None) -> set[str]:
    """csv always; parquet when asked for - by the Downloads radio or COMPARE_TABLE_FORMATS."""
    if choice:
        return {"csv", "parquet"} if choice == "both" else {choice}
    env = os.environ.get("COMPARE_TABLE_FORMATS", "csv")
    got = {p.strip().lower() for p in env.split(",") if p.strip()}
    return got or {"csv"}


def _source_block(s: Side, rows_read: int) -> dict:
    wd = str(work_dir())
    path = s.csv_path if s.csv_path and not s.csv_path.startswith(wd) and not s.is_database else ""
    return {"name": s.name, "kind": "database" if s.is_database else s.kind, "database": s.database,
            "connection": s.conn, "origin": s.origin, "label": s.label, "path": path, "sql": s.query,
            "fetched_at": s.fetched_at, "cap": s.cap, "capped": s.capped, "rows": rows_read,
            "cut": s.cut, "delimiter": s.delimiter, "header": s.header, "snapshot": bool(s.cache_path),
            "columns": list(s.schema)}


def columns_frame(run: dict) -> pd.DataFrame:
    """The column sheet with machine headers - the report and the UI rename for display."""
    from .compare import column_ledger
    df = column_ledger(run, "A", "B").rename(columns={
        "Column": "column", "A": "name_a", "B": "name_b", "Role": "role", "Read as": "read_as",
        "Matched": "matched", "Mismatched": "mismatched", "Match %": "match_pct",
        "Values only in A": "values_only_a", "Values only in B": "values_only_b"})
    for c in COLUMNS_HEADER:
        if c not in df.columns:
            df[c] = None
    return df[COLUMNS_HEADER]


def profile_frame(prof: dict, name_a: str, name_b: str) -> pd.DataFrame:
    rows = []
    for which, name in (("A", name_a), ("B", name_b)):
        for _, r in prof["stats"][which].iterrows():
            rows.append({"column": r["Column"], "side": name, "rows": r["Rows"], "nulls": r["Nulls"],
                         "null_pct": r["Null %"], "distinct": r["Distinct"], "distinct_pct": r["Distinct %"],
                         "min": r["Min"], "max": r["Max"], "mean": r["Mean"], "avg_length": r["Avg length"]})
    return pd.DataFrame(rows, columns=PROFILE_HEADER)


def summary_payload(run: dict, A: Side, B: Side, name_a: str, name_b: str,
                    notes: list[str] | None = None) -> dict:
    res, cfg = run["result"], run["cfg"]
    from .theme import APP_NAME
    return {"schema_version": SCHEMA_VERSION, "app": APP_NAME, "engine": "csvdiff",
            "duckdb_version": duckdb.__version__, "run_id": run["run_id"], "started_at": run["started_at"],
            "seconds": round(run["seconds"], 3), "pair": run["pair"],
            "sources": {"A": {**_source_block(A, res.rows_left_read), "name": name_a},
                        "B": {**_source_block(B, res.rows_right_read), "name": name_b}},
            "settings": {k: cfg.get(k) for k in SETTINGS_KEYS if k in cfg},
            "result": asdict(res), "verdict": asdict(run["verdict"]), "notes": list(notes or []),
            "files": [{"name": p.name, "format": p.suffix.lstrip("."), "bytes": p.stat().st_size,
                       "rows": _rows_in(p)} for p in sorted(Path(run["folder"]).iterdir()) if p.is_file()]}


def _rows_in(p: Path) -> int | None:
    if p.suffix == ".csv":
        with open(p, "rb") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    if p.suffix == ".parquet":
        import pyarrow.parquet as pq
        return pq.ParquetFile(p).metadata.num_rows
    return None


def write_summary(run: dict, A: Side, B: Side, name_a: str, name_b: str, notes=None, profile=None) -> None:
    folder, pair = Path(run["folder"]), run["pair"]
    res, v = run["result"], run["verdict"]
    columns_frame(run).to_csv(folder / f"{pair}__columns.csv", index=False, lineterminator="\n")
    if profile:
        profile_frame(profile, name_a, name_b).to_csv(folder / f"{pair}__profile.csv", index=False, lineterminator="\n")
    payload = summary_payload(run, A, B, name_a, name_b, notes)
    (folder / f"{pair}__summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n",
                                                   encoding="utf-8", newline="\n")
    row = {"schema_version": SCHEMA_VERSION, "run_id": run["run_id"], "started_at": run["started_at"],
           "pair": pair, "left": name_a, "right": name_b, "mode": run["mode"], "keys": "|".join(res.keys),
           **{k: getattr(res, k) for k in ("rows_left_read", "rows_right_read", "rows_left", "rows_right",
                                          "matched_rows", "only_left", "only_right", "diff_rows", "cell_diffs",
                                          "duplicate_keys_left", "duplicate_keys_right")},
           "status": v.status, "tone": v.tone, "seconds": round(run["seconds"], 3), "error": res.error}
    with open(folder / f"{pair}__summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerow(row)
    run["files"] = {p.name: p for p in folder.glob("*")}


def write_parquet_copies(run: dict) -> list[Path]:
    """Every CSV table of the run as Parquet next to it, through DuckDB."""
    folder, pair = Path(run["folder"]), run["pair"]
    con = duckdb.connect()
    written = []
    for t in TABLES:
        src = folder / f"{pair}__{t}.csv"
        if not src.exists():
            continue
        dst = folder / f"{pair}__{t}.parquet"
        con.execute(f"COPY (SELECT * FROM read_csv({lit(str(src))}, all_varchar=true, header=true)) "
                    f"TO {lit(str(dst))} (FORMAT PARQUET)")
        written.append(dst)
    con.close()
    run["files"] = {p.name: p for p in folder.glob("*")}
    return written


def zip_run(run: dict) -> Path:
    folder = Path(run["folder"])
    target = folder.parent / f"{run['pair']}__{run['run_id']}"
    z = Path(shutil.make_archive(str(target), "zip", root_dir=folder))
    run["zip"] = z
    return z


def default_save_folder(run: dict, base: Path) -> Path:
    root = out_dir() or base
    return root / f"{run['pair']}__{run['run_id']}"


def save_target(folder_text: str, run: dict) -> Path:
    """Where a save may go: anywhere, or only under COMPARE_OUT_DIR when it is set."""
    root = out_dir()
    if root is None:
        return Path(folder_text).expanduser().resolve()
    root = root.resolve()
    p = Path(folder_text)
    p = (p if p.is_absolute() else root / p).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"Saves must stay under {root}")
    return p


def sweep_work_dir(keep_hours: float | None = None) -> int:
    """Remove run folders, fetches and snapshots older than COMPARE_KEEP_HOURS (24)."""
    hours = keep_hours if keep_hours is not None else float(os.environ.get("COMPARE_KEEP_HOURS", "24") or 24)
    cutoff = time.time() - hours * 3600
    n = 0
    for p in work_dir().iterdir():
        if "__" not in p.name and not p.name.startswith("cmp_"):
            continue
        try:
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
                n += 1
        except OSError:
            pass
    return n
```

- [ ] **Step 4: Change `compare.py`**

`run_comparison` (lines 154-192) becomes:

```python
def run_comparison(A: Side, B: Side, cfg: dict, opts: ReadOptions, sig: str = "",
                   previous: dict | None = None, progress=None) -> dict:
    from .outputs import run_id, verdict_of
    say = progress or (lambda _m: None)
    mode = cfg["mode"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys = list(cfg["keys"]) if mode == "key" else []
    con = scratch(ordered=True)   # file order is what pairs duplicate keys (1st with 1st) - keep it
    started = datetime.now().astimezone()
    rid = run_id(started)
    out = work_dir() / f"{cfg['name']}__{rid}"
    while out.exists():                                  # two runs in one second
        rid += "a"
        out = work_dir() / f"{cfg['name']}__{rid}"
    folder = out / cfg["name"]                           # the engine writes under <out>/<name>
    folder.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ... (reading and register as before) ...
    if mode == "hash":
        res = hash_compare(con, cfg, folder, say)
    else:
        res = engine_compare(con, cfg, folder, out, keys, say)
    res.rows_left_read = res.rows_left_read or n_a
    res.rows_right_read = res.rows_right_read or n_b
    elapsed = time.perf_counter() - t0
    for p in folder.iterdir():                           # flatten: <out>/<name>/x -> <out>/x
        p.rename(out / p.name)
    folder.rmdir()
    run = {"result": res, "folder": out, "files": {p.name: p for p in out.glob("*")}, "seconds": elapsed,
           "con": con, "left": "src_a", "right": "src_b", "cfg": cfg, "signature": sig,
           "at": started.strftime("%H:%M:%S"), "mode": mode, "run_id": rid, "pair": cfg["name"],
           "started_at": started.isoformat(timespec="seconds"), "verdict": verdict_of(res, mode)}
    say("Writing the paired rows…")
    write_paired(run, keys, list(res.columns_compared or cfg["compare_columns"]))
    return run
```

(`from datetime import datetime`, `from .sources import Side, work_dir`; drop the old summary json/csv writing - `outputs.write_summary` does it, called by the app after the report is built.) In `engine_compare` add `"write_empty": True,` to the merged options. In `hash_compare` build the hash tables with every column and strip the helpers on COPY:

```python
        con.execute(f"CREATE OR REPLACE TABLE h_{side[-1]} AS "
                    f"SELECT {h} AS __h, row_number() OVER (PARTITION BY {h}) AS __k, * FROM {side}")
    ...
        con.execute(f"COPY (SELECT * EXCLUDE (__h, __k) FROM {mine} m WHERE NOT EXISTS (SELECT 1 FROM {other} o "
                    f"WHERE o.__h = m.__h AND o.__k = m.__k)) TO {lit(str(path))} (HEADER)")
```

Add `write_paired` and `value_pairs`; keep `paired_frame` for the screen:

```python
def write_paired(run: dict, keys: list[str], cols: list[str]) -> Path:
    """Every paired row side by side - keys, then a_<col>, b_<col> - straight from DuckDB."""
    con = run["con"]
    path = Path(run["folder"]) / f"{run['cfg']['name']}__paired.csv"
    if run["mode"] == "hash":
        pd.DataFrame(columns=cols).to_csv(path, index=False)
        run["files"][path.name] = path
        return path
    pair_views(run, keys)
    sel = ", ".join([f"l.{ident(k)} AS {ident(k)}" for k in keys]
                    + [f"l.{ident(c)} AS {ident('a_' + c)}" for c in cols]
                    + [f"r.{ident(c)} AS {ident('b_' + c)}" for c in cols])
    con.execute(f"COPY (SELECT {sel} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} ORDER BY l.__rn) "
                f"TO {lit(str(path))} (HEADER)")
    run["files"][path.name] = path
    return path


def value_pairs(run: dict, n: int = 5) -> dict[str, pd.DataFrame]:
    """Per differing column: the n most frequent (left value, right value) pairs with count and %."""
    if not cells_table(run):
        return {}
    con = run["con"]
    df = con.execute(f"""
        SELECT column_name AS col, coalesce(left_value, '∅ null') AS a, coalesce(right_value, '∅ null') AS b,
               count(*) AS n, count(*) * 100.0 / sum(count(*)) OVER (PARTITION BY column_name) AS pct
        FROM cd GROUP BY 1, 2, 3
        QUALIFY row_number() OVER (PARTITION BY column_name ORDER BY count(*) DESC, a, b) <= {int(n)}
        ORDER BY col, n DESC""").fetchdf()
    return {col: sub.drop(columns=["col"]).reset_index(drop=True) for col, sub in df.groupby("col", sort=False)}
```

`pair_views` for `keys == []` in position mode already works (`join_on` uses `__rn`).

- [ ] **Step 5: Run the tests and the gate**

Run: `python -m pytest tests -q` - Expected: pass. The gate script still calls the app, which does not yet call `write_summary` - it stays green; Task 7 wires it.

- [ ] **Step 6: Commit**

```bash
git add tablecmp/outputs.py tablecmp/compare.py tests/test_outputs.py
git commit -m "Outputs: named run folder, fixed file set, verdict, summary/columns/profile writers, Parquet and zip"
```

---

### Task 6: Key reasons, overlap, one profile reused

**Files:**
- Modify: `tablecmp/keys.py:93-197` (suggest_keys), `tablecmp/profile.py:67-79` (profile_tables), `tablecmp/auto.py:117-178` (auto_configure)
- Create: `tests/test_keys.py`

**Interfaces:**
- Produces: `suggest_keys(A, B, specs, name_a, name_b, opts, progress=None, max_cols=4, want=8, profile=None) -> (table, combos, note)` where `table` has the extra columns `Overlap %` and `Why`; `key_reasons` is internal. `profile_tables(...)` returns `{"stats": {...}, "freq": {...}, "both": DataFrame, "notes": list[str]}`; `profile_singles(profile, canon) -> dict | None` gives `{"A": distinct, "B": distinct, "nulls_A": n, "nulls_B": n, "constant": bool}`. `auto_configure(A, B, name_a, name_b, opts, say, profile=None, want_profile=False) -> (cmap, notes, chosen, profile_used)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keys.py
from pathlib import Path
import pytest
from tablecmp.keys import suggest_keys
from tablecmp.profile import profile_tables
from tablecmp.sources import Side, source_schema, file_stamp
from tablecmp.values import ColSpec, ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL",), trim=True, empty_null=True)


def _sides():
    A = Side(name="hr", label="hr_employees.csv", csv_path=str(EX / "hr_employees.csv"))
    B = Side(name="payroll", label="payroll_employees.csv", csv_path=str(EX / "payroll_employees.csv"))
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path)); s.source_columns = list(s.schema)
    specs = [ColSpec(canon="emp_id", a_src="emp_id", b_src="EmployeeId", kind="text"),
             ColSpec(canon="department", a_src="department", b_src="Dept", kind="text"),
             ColSpec(canon="salary", a_src="salary", b_src="Salary", kind="number", b_steps=[{"op": "remove thousands separators"}]),
             ColSpec(canon="active", a_src="active", b_src="IsActive", kind="boolean")]
    return A, B, specs


def test_reasons_and_overlap():
    A, B, specs = _sides()
    table, combos, note = suggest_keys(A, B, specs, "hr", "payroll", OPTS)
    assert combos[0] == ["emp_id"]
    top = table.iloc[0]
    assert top["Unique on both"] == "yes" and 95 < top["Overlap %"] < 100
    assert "identifier" in top["Why"] and "no nulls" in top["Why"]
    sal = table[table["Key columns"].str.contains("salary")]
    if len(sal):
        assert "measure" in sal.iloc[0]["Why"]


def test_disjoint_ids_rank_below_shared(tmp_path):
    import csv
    for name, start in (("a.csv", 1), ("b.csv", 5000)):
        with open(tmp_path / name, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["row_id", "code", "v"])
            for i in range(200):
                w.writerow([start + i, f"C{i}", i % 7])
    A = Side(label="a.csv", csv_path=str(tmp_path / "a.csv")); B = Side(label="b.csv", csv_path=str(tmp_path / "b.csv"))
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path)); s.source_columns = list(s.schema)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("row_id", "code", "v")]
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert combos[0] == ["code"]                          # unique on both AND shared
    row = table[table["Key columns"] == "row_id"].iloc[0]
    assert row["Overlap %"] == 0 and "no values in common" in row["Why"]


def test_profile_feeds_keys_and_notes():
    A, B, specs = _sides()
    prof = profile_tables(A, B, specs, OPTS)
    assert "both" in prof and set(prof["both"]["Column"]) == {s.canon for s in specs}
    table, combos, note = suggest_keys(A, B, specs, "hr", "payroll", OPTS, profile=prof)
    assert combos[0] == ["emp_id"] and "profile" in note.lower()


def test_constant_column_is_skipped(tmp_path):
    import csv
    for name in ("a.csv", "b.csv"):
        with open(tmp_path / name, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["id", "region"])
            for i in range(50):
                w.writerow([i, "EMEA"])
    A = Side(label="a.csv", csv_path=str(tmp_path / "a.csv")); B = Side(label="b.csv", csv_path=str(tmp_path / "b.csv"))
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path)); s.source_columns = list(s.schema)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "region")]
    prof = profile_tables(A, B, specs, OPTS)
    assert any("region" in n and "constant" in n for n in prof["notes"])
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS, profile=prof)
    assert all("region" not in c for c in combos)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_keys.py -q` - Expected: FAIL (`unexpected keyword argument 'profile'`, missing columns).

- [ ] **Step 3: Implement in `profile.py`**

At the end of `profile_tables`, before `return out`:

```python
    ia, ib = out["stats"]["A"].set_index("Column"), out["stats"]["B"].set_index("Column")
    both, notes = [], []
    for s in specs:
        c = s.canon
        if c not in ia.index or c not in ib.index:
            continue
        rec = {"Column": c, "Type": s.kind,
               "Nulls A": int(ia.at[c, "Nulls"]), "Nulls B": int(ib.at[c, "Nulls"]),
               "Distinct A": int(ia.at[c, "Distinct"]), "Distinct B": int(ib.at[c, "Distinct"]),
               "Rows A": int(ia.at[c, "Rows"]), "Rows B": int(ib.at[c, "Rows"]),
               "Min A": ia.at[c, "Min"], "Min B": ib.at[c, "Min"], "Max A": ia.at[c, "Max"], "Max B": ib.at[c, "Max"]}
        rec["constant"] = rec["Distinct A"] <= 1 and rec["Distinct B"] <= 1
        rec["empty"] = rec["Nulls A"] == rec["Rows A"] and rec["Nulls B"] == rec["Rows B"]
        if rec["empty"]:
            notes.append(f"{c}: empty on both sides")
        elif rec["constant"]:
            notes.append(f"{c}: constant - one value on each side, never a key")
        elif max(rec["Distinct A"], rec["Distinct B"]) > 2 * max(1, min(rec["Distinct A"], rec["Distinct B"])):
            notes.append(f"{c}: {rec['Distinct A']:,} distinct values on {A.name or 'A'} against "
                         f"{rec['Distinct B']:,} on {B.name or 'B'} - spelled differently, or a different field")
        both.append(rec)
    out["both"] = pd.DataFrame(both)
    out["notes"] = notes
```

Add:

```python
def profile_singles(profile: dict | None, canon: str) -> dict | None:
    """What the key search needs for one column, from a profile that already measured it."""
    if not profile or "both" not in profile or not len(profile["both"]):
        return None
    hit = profile["both"][profile["both"]["Column"] == canon]
    if not len(hit):
        return None
    r = hit.iloc[0]
    return {"probe_a": int(r["Distinct A"]), "probe_b": int(r["Distinct B"]), "nulls_a": int(r["Nulls A"]),
            "nulls_b": int(r["Nulls B"]), "constant": bool(r["constant"]) or bool(r["empty"])}
```

- [ ] **Step 4: Implement in `keys.py`**

`suggest_keys` gains `profile=None`. After `totals`:

```python
    say("Measuring every column…" if profile is None else "Reading the profile…")
    singles: dict[str, dict[str, int]] = {c: {} for c in candidates}
    nulls: dict[str, int] = {}
    skipped: list[str] = []
    from .profile import profile_singles
    from_profile = {c: profile_singles(profile, c) for c in candidates}
    measure = [c for c in candidates if from_profile[c] is None]
    if measure:
        for v in views:
            picks = ", ".join(f"count(DISTINCT {ident(c)}), count(*) - count({ident(c)})" for c in measure)
            row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
            for i, c in enumerate(measure):
                singles[c][v] = row[2 * i]
                nulls[c] = nulls.get(c, 0) + row[2 * i + 1]
    for c, p in from_profile.items():
        if p is not None:
            singles[c] = {"probe_a": p["probe_a"], "probe_b": p["probe_b"]}
            nulls[c] = p["nulls_a"] + p["nulls_b"]
            if p["constant"]:
                skipped.append(c)
    candidates = [c for c in candidates if c not in skipped]
```

Replace the `affinity` / `ranked` lines so they use the trimmed `candidates`, and add an overlap measure:

```python
    def overlap(cols: list[str]) -> float:
        """Share of A's distinct key values also present in B."""
        k = combo(cols)
        n = con.execute(f"SELECT count(DISTINCT {k}) FROM probe_a").fetchone()[0]
        if not n:
            return 0.0
        m = con.execute(f"SELECT count(DISTINCT {k}) FROM probe_a WHERE {k} IN (SELECT {k} FROM probe_b)").fetchone()[0]
        return m / n * 100
```

After `found = found[:want]`, compute `ov = {tuple(cols): overlap(cols) for cols, _ in found}` and re-sort:
`found.sort(key=lambda f: (not unique(f[1]), -sum(affinity[c] for c in f[0]), -round(ov[tuple(f[0])]), len(f[0]), -selectivity(f[1])))`. Note `ov` must be computed on the pre-cut list (`found` before `[:want]`) so ranking by overlap can lift a candidate: compute `ov` for `found[: want * 2]`, then sort, then cut to `want`.

Reasons:

```python
def key_reasons(cols, d, totals, affinity, nulls, ov, unique_sets, how, name_a, name_b, singles) -> str:
    bits = []
    idish = [c for c in cols if ID_WORDS.search(c)]
    measures = [c for c in cols if MEASURE_WORDS.search(c) or affinity[c] <= -4]
    if measures:
        bits.append(f"{', '.join(measures)}: a measure" + (", decimal" if any(affinity[c] <= -4 for c in measures) else "") + " - never a key")
    elif idish:
        bits.append("name says identifier" if len(cols) == 1 else f"{', '.join(idish)} say identifier")
    else:
        bits.append("a name, not an identifier" if any(re.search(r"name", c, re.I) for c in cols) else "no identifier in the name")
    n_null = sum(nulls.get(c, 0) for c in cols)
    bits.append("no nulls" if not n_null else f"{n_null:,} nulls")
    bits.append(f"{d['probe_a']:,} distinct of {totals['probe_a']:,} in {name_a}, {d['probe_b']:,} of {totals['probe_b']:,} in {name_b}")
    dup_a, dup_b = totals["probe_a"] - d["probe_a"], totals["probe_b"] - d["probe_b"]
    if dup_a or dup_b:
        bits.append(" and ".join(f"{n:,} rows in {nm} share it" for n, nm in ((dup_a, name_a), (dup_b, name_b)) if n))
    o = ov[tuple(cols)]
    bits.append("no values in common - the two sides number their rows differently" if o == 0
                else f"{o:.1f}% of {name_a}'s values found in {name_b}")
    for u in unique_sets:
        if u < set(cols):
            bits.append(f"adds nothing - {' + '.join(sorted(u))} is already unique")
            break
    return " · ".join(bits) + f" · {how}"
```

where `unique_sets = [frozenset(c) for c, dd in found if unique(dd)]` and `how` is "found with Desbordante HyUCC" / "grown from the most selective column" (track per candidate in `offer(cols, d, how)`). The table gains `"Overlap %": round(ov[tuple(cols)], 1)` and `"Why": key_reasons(...)`. `note` gains `" - single-column figures from the profile"` when `profile` was used.

- [ ] **Step 5: Implement in `auto.py`**

`auto_configure(A, B, name_a, name_b, opts, say, profile=None, want_profile=False)`: after `specs = specs_from(cmap)` and the type analysis, when `want_profile and profile is None`: `say("Profiling both sides…"); from .profile import profile_tables; profile = profile_tables(A, B, specs, opts, progress=say)`; then `notes += profile["notes"]`. Pass `profile=profile` to `suggest_keys`. The key note becomes `f"key: {' + '.join(chosen)} - {table.iloc[i]['Why']}"` plus `f" Runner-up: {' + '.join(combos[1])} - {table.iloc[1]['Why']}"` when there is a second candidate. Return `cmap, notes, chosen, profile`. Update the two callers (`compare_app.py:126` unpacks four values; the third value stays `chosen`).

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests -q` - Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add tablecmp/keys.py tablecmp/profile.py tablecmp/auto.py compare_app.py tests/test_keys.py
git commit -m "Suggest keys with reasons and an overlap check; one profile feeds keys and Auto"
```

---

### Task 7: The Database source panel, the Connections manager, the app wiring

**Files:**
- Create: `tablecmp/ui_database.py`
- Modify: `tablecmp/ui_sidebar.py:33-56` (source_panel head), `:112-139` (load and caption), `:163-178` (auto_panel)
- Modify: `compare_app.py:42-48` (bootstrap), `:78-81` (duckdb floor), `:119-140` (Auto), `:205-215` (profile), `:275-290` (pending, run), `:300-320` (after a run: write outputs)
- Modify: `tablecmp/state.py` DEFAULTS (`"db_passwords": dict`, `"fetched_A"`, `"fetched_B"`)

**Interfaces:**
- Consumes: `connections.load_all/save/delete/resolve/PasswordNeeded/redact/Connection/KINDS`, `databases.test/fetch_parquet/table_sql/has_order_by/origin_of/NotReadOnly/DriverMissing`, `outputs.pair_name/write_summary/sweep_work_dir`, `auto_configure(..., profile, want_profile)`.
- Produces: `ui_database.source_panel(tag) -> tuple[str, str, Side | None]` returning `(path, label, partial_side)`; `ui_database.manager() -> None`. Widget keys: `conn_{tag}`, `dbmode_{tag}`, `tbl_{tag}`, `sql_{tag}`, `cap_{tag}`, `fetch_{tag}`, `refetch_{tag}`, `pw_{tag}`, `same_as_A`, `auto_profile`, `test_conn`, `conn_new`, `conn_save`, `conn_delete`, `conn_pick`, `cf_name`, `cf_kind`, `cf_host`, `cf_port`, `cf_database`, `cf_schema`, `cf_user`, `cf_password`, `cf_save_pw`, `cf_timeout`, `cf_<extra>`.

- [ ] **Step 1: Write `ui_database.py`**

```python
# tablecmp/ui_database.py
"""The Database branch of the source panel, and the Connections manager."""
from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from . import connections as cx
from . import databases as db
from .sources import Side, work_dir

EXTRAS = {"snowflake": ["warehouse", "role", "authenticator"], "databricks": ["http_path", "token", "catalog"],
          "oracle": ["service_name"], "mssql": [], "postgresql": [], "duckdb": []}
FIELDS = {"snowflake": ["host", "user", "password", "database", "schema"],
          "databricks": ["host", "schema"], "mssql": ["host", "port", "database", "user", "password"],
          "oracle": ["host", "port", "user", "password"], "postgresql": ["host", "port", "database", "user", "password"],
          "duckdb": ["host"]}
LABELS = {"host": "Host", "port": "Port", "database": "Database", "schema": "Schema", "user": "User",
          "password": "Password", "warehouse": "Warehouse", "role": "Role", "authenticator": "Authenticator (optional)",
          "http_path": "HTTP path", "token": "Access token", "catalog": "Catalog", "service_name": "Service name"}
HOST_LABEL = {"snowflake": "Account", "databricks": "Server hostname", "mssql": "Server", "duckdb": "File path"}


def _passwords() -> dict[str, str]:
    return st.session_state.setdefault("db_passwords", {})


def source_panel(tag: str) -> tuple[str, str, Side | None]:
    """Connection, table or SQL, cap, Fetch. Returns (parquet path, label, side with origin) once fetched."""
    conns = cx.load_all()
    names = sorted(conns)
    if not names:
        st.info("No connections yet - make one under **Connections** below.")
        return "", "", None
    name = st.selectbox("Connection", names, key=f"conn_{tag}",
                        format_func=lambda n: f"{n} · {conns[n].label} · {conns[n].where}")
    c = conns[name]
    if c.password is None and c.kind != "duckdb" and name not in _passwords():
        pw = st.text_input("Password - kept for this session only", type="password", key=f"pw_{tag}")
        if pw:
            _passwords()[name] = pw
    mode = st.radio("Read", ["Table", "SQL query"], horizontal=True, key=f"dbmode_{tag}", label_visibility="collapsed")
    if mode == "Table":
        what = st.text_input("Table", key=f"tbl_{tag}", placeholder="hr.employees").strip()
        sql = db.table_sql(c.kind, what) if what else ""
    else:
        sql = st.text_area("SQL - SELECT or WITH only", key=f"sql_{tag}", height=110,
                           placeholder="SELECT emp_id, first_name, department, hire_date\nFROM hr.employees\nWHERE hire_date >= '2026-01-01'").strip()
        what = "query"
    c1, c2 = st.columns([1, 1])
    cap = int(c1.number_input("Fetch at most (0 = all)", 0, 1_000_000_000, 1_000_000, step=100_000, key=f"cap_{tag}"))
    if tag == "B" and st.session_state.get("how_A") == "Database" and c2.button("Same SQL as A", key="same_as_A", width="stretch"):
        for k in ("conn", "dbmode", "tbl", "sql", "cap"):
            if f"{k}_A" in st.session_state:
                st.session_state[f"{k}_B"] = st.session_state[f"{k}_A"]
        st.rerun()
    key = (name, " ".join(sql.split()), cap)
    held = st.session_state.get(f"fetched_{tag}")
    if held and held[0] == key and Path(held[1]).exists():
        st.caption(f"Fetched at {held[3]} - {held[4]:,} rows" + (" · capped" if held[5] else ""))
        if st.button("Fetch again", key=f"refetch_{tag}", width="stretch"):
            Path(held[1]).unlink(missing_ok=True)
            st.session_state.pop(f"fetched_{tag}")
            st.rerun()
    else:
        if cap and sql and not db.has_order_by(sql):
            st.warning("A cap without an ORDER BY can give the two sides different rows - add ORDER BY, or fetch everything.")
        if st.button(f"Fetch {tag}", key=f"fetch_{tag}", type="primary", width="stretch", disabled=not sql):
            try:
                conn = cx.resolve(name, _passwords())
                path = work_dir() / f"fetch_{tag}_{int(time.time())}.parquet"
                with st.status(f"Fetching from {name}…", expanded=True) as box:
                    r = db.fetch_parquet(conn, sql, str(path), cap, progress=box.write)
                    box.update(label=f"Fetched {r.rows:,} rows in {r.seconds:.1f}s", state="complete", expanded=False)
                if held:
                    Path(held[1]).unlink(missing_ok=True)
                st.session_state[f"fetched_{tag}"] = (key, str(path), what, time.strftime("%H:%M:%S"), r.rows, r.capped)
                st.rerun()
            except cx.PasswordNeeded:
                st.error("Type the password above first.")
            except db.NotReadOnly as exc:
                st.error(str(exc))
            except db.DriverMissing as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error("The fetch failed - " + cx.redact(exc))
        return "", "", None
    held = st.session_state[f"fetched_{tag}"]
    side = Side(conn=name, database=c.kind, query=sql, fetched_at=held[3], cap=cap, capped=held[5],
                origin=db.origin_of(c, held[2] if held[2] != "query" else sql))
    return held[1], f"{name}.parquet", side


def manager() -> None:
    with st.expander("Connections", expanded=False):
        conns = cx.load_all()
        for n, c in sorted(conns.items()):
            pw = ("env · read-only" if c.source == "env" else
                  "password saved" if c.password is not None else "password asked each session")
            st.markdown(f"**{n}** · {c.label} · {c.where} · {pw}")
        pick = st.selectbox("Edit", ["New connection"] + [n for n, c in sorted(conns.items()) if c.source == "file"],
                            key="conn_pick")
        cur = conns.get(pick) if pick != "New connection" else None
        kind = st.selectbox("Kind", list(cx.KINDS), key="cf_kind", format_func=cx.KINDS.get,
                            index=list(cx.KINDS).index(cur.kind) if cur else 0)
        name = st.text_input("Name", value=cur.name if cur else "", key="cf_name", help="letters, digits, _ and -")
        vals = {}
        for f in FIELDS[kind]:
            label = HOST_LABEL.get(kind, LABELS["host"]) if f == "host" else LABELS[f]
            if f == "password":
                vals[f] = st.text_input(label, type="password", key="cf_password", placeholder="unchanged" if cur and cur.password else "")
            elif f == "port":
                vals[f] = st.number_input(label, 0, 65535, int((cur.port if cur and cur.port else cx.DEFAULT_PORTS.get(kind, 0))), key="cf_port")
            else:
                vals[f] = st.text_input(label, value=getattr(cur, f, "") if cur else "", key=f"cf_{f}")
        for e in EXTRAS[kind]:
            vals[e] = st.text_input(LABELS[e], value=(cur.extra.get(e, "") if cur else ""), key=f"cf_{e}",
                                    type="password" if e == "token" else "default")
        save_pw = st.checkbox("Save password", value=bool(cur and cur.password is not None) if cur else True, key="cf_save_pw",
                              help="Unticked: the password is asked for once per session and never written to disk.")
        timeout = int(st.number_input("Query timeout, seconds", 10, 86400, cur.timeout if cur else 600, key="cf_timeout"))
        typed_pw = vals.pop("password", "")
        password = typed_pw or (cur.password if cur else None)
        if kind == "databricks" and vals.get("token"):
            password = vals["token"]
        conn = cx.Connection(name=name.strip(), kind=kind, host=vals.get("host", ""), port=int(vals["port"]) if vals.get("port") else None,
                             database=vals.get("database", ""), schema=vals.get("schema", ""), user=vals.get("user", ""),
                             password=password if save_pw else None, extra={e: vals.get(e, "") for e in EXTRAS[kind] if vals.get(e)},
                             timeout=timeout)
        b1, b2, b3 = st.columns(3)
        if b1.button("Test", key="test_conn", width="stretch"):
            probe = cx.Connection(**{**conn.__dict__, "password": password})
            r = db.test(probe)
            (st.success if r.ok else st.error)(r.message)
        if b2.button("Save", key="conn_save", type="primary", width="stretch"):
            try:
                cx.save(conn)
                if not save_pw and password:
                    _passwords()[conn.name] = password
                st.success(f"Saved {conn.name}")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if cur and b3.button("Delete", key="conn_delete", width="stretch"):
            cx.delete(cur.name)
            st.rerun()
```

- [ ] **Step 2: Wire the sidebar**

In `ui_sidebar.py` `source_panel`: `name = st.text_input("Name", ..., help="What to call this side everywhere - and it names every output file: left_compare_right. Defaults: Left and Right.")`; the radio becomes `["Upload", "Path on disk", "Database"]`; add a branch:

```python
    elif how == "Database":
        from .ui_database import source_panel as db_panel
        path, label, db_side = db_panel(tag)
        if db_side is not None:
            origin = db_side.origin
            if name.strip() in ("", DEFAULT_NAMES[tag]):
                name = db_side.conn
```

(`db_side = None` before the `if how == ...` chain.) In the "Path on disk" branch, after `Path(p).is_file()`, check `path_allowed(p)` and show `st.error("Not under an allowed folder (COMPARE_DATA_DIR).")` when false. In the Rows to read expander caption, when `how == "Database"`: "Applied to the fetched rows - to cut at the database, put a WHERE in the SQL." At `Load`, build the `Side` with `**({"conn": db_side.conn, "database": db_side.database, "query": db_side.query, "fetched_at": db_side.fetched_at, "cap": db_side.cap, "capped": db_side.capped} if db_side else {})`. Skip the snapshot when `kind == "parquet" and not (where.strip() or order or top)` (set `side.cache_path = ""`). The loaded caption adds `f" · fetched {side.fetched_at}"` and `" · capped at {side.cap:,}"` when `side.capped`. `auto_panel` adds `st.checkbox("Profile both sides first", value=True, key="auto_profile")` between the caption and the button, and after the button calls `ui_database.manager()` (import at top).

- [ ] **Step 3: Wire `compare_app.py`**

- Bootstrap: `"server.maxUploadSize": int(os.environ.get("COMPARE_UPLOAD_MB", THEME["upload_mb"]))`.
- DuckDB floor: `(1, 2)`.
- Once per process: `if not st.session_state.get("_swept") and "_swept" not in st.session_state: from tablecmp.outputs import sweep_work_dir; sweep_work_dir(); st.session_state["_swept"] = True` (guard with a module-level flag so it runs once per server, not per session: `_SWEPT = globals().setdefault("_SWEPT", False)`).
- Auto block: `prof = st.session_state.get("profile"); current = prof[1] if prof and prof[0] == profile_key else None` - but `profile_key` is computed later; move the `profile_key` computation up to just after `OPTS` (it needs `setup.specs` - compute it from `specs_from(st.session_state["cmap"])` when a cmap exists, else `None`). Call `auto_configure(A, B, NA, NB, OPTS, box.write, profile=current, want_profile=st.session_state.get("auto_profile", True))` and, when it returns a profile, store `st.session_state["profile"] = (profile_key_after, profile)` where `profile_key_after` is recomputed from the new cmap's specs after `st.session_state["cmap"] = new_map`.
- Suggest keys (`ui_keys.render`) receives `profile=current` and passes it to `suggest_keys`; the table shown gains the two columns (already in the frame).
- `pending["name"] = pair_name(A, B)` (import from `tablecmp.outputs`); `pending["notes"] = st.session_state.get("auto_notes") or []`; `pending["table_formats"] = sorted(table_formats(st.session_state.get("out_fmt")))`; `signature()` excludes `"notes"` and `"name"` (compare.py:149: `if k not in ("name", "notes")`).
- After a successful run (line ~306, after `st.session_state.result, previous = new_run, run`): `from tablecmp.report import build_report; from tablecmp.outputs import write_summary, write_parquet_copies; html = build_report(new_run, A, B, NA, NB, limit=min(int(display_rows), 2000)); new_run["_report"] = html; new_run["_report_key"] = ("report", new_run["at"], min(int(display_rows), 2000)); (Path(new_run["folder"]) / f"{new_run['pair']}__report.html").write_text(html, encoding="utf-8", newline="\n"); write_summary(new_run, A, B, NA, NB, notes=pending["notes"], profile=current); if "parquet" in pending["table_formats"]: write_parquet_copies(new_run)`.

- [ ] **Step 4: Run the gate, then a manual database check**

Run: `python <scratchpad>/apptest_auto.py t7.html` - Expected: the Task 3 counts, and the report path printed. Then `python - <<EOF` a short AppTest that sets `COMPARE_CONN_SAMPLE=duckdb:///<abs>/examples/sample.duckdb`, picks `how_A = "Database"`, `sql_A = "SELECT * FROM hr.employees"`, clicks `fetch_A`, then `load_A`, likewise B with `payroll.employees`, then `auto_btn` and asserts the same counts (Task 11 turns this into a test).

- [ ] **Step 5: Commit**

```bash
git add tablecmp/ui_database.py tablecmp/ui_sidebar.py tablecmp/state.py tablecmp/ui_keys.py compare_app.py tablecmp/compare.py
git commit -m "Database sources in the sidebar with a Connections manager; outputs written after every run"
```

---

### Task 8: The report - sources, key, values, filters, verdict, value pairs, anchors, print

**Files:**
- Modify: `tablecmp/report.py:14-88` (CSS), `:153-272` (build_report)
- Modify: `tablecmp/theme.py` (add `CELL_BUDGET = 150_000` near `APP_TAGLINE`)
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes: `run["verdict"]`, `run["run_id"]`, `run["started_at"]`, `value_pairs(run)`, `Side` database fields, `outputs.summary_payload`.
- Produces: `build_report(run, A, B, name_a, name_b, limit=500, notes=None, profile=None) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import re
from tablecmp.report import build_report
from tests.test_outputs import _run          # the sample run helper


def test_report_sections_and_no_secrets(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    A.conn, A.database, A.query, A.fetched_at = "prod", "snowflake", "SELECT * FROM hr.employees", "10:12:01"
    A.origin = "Snowflake · hr.employees"
    html = build_report(run, A, B, "prod", "payroll", limit=50, notes=["key: emp_id - name says identifier"])
    for anchor in ("setup", "counts", "columns", "by-key", "rows", "only-a", "only-b"):
        assert f'id="{anchor}"' in html
    assert "Differences" in html and "small differences" in html.lower()
    assert "connection <code>prod</code>" in html and "SELECT * FROM hr.employees" in html
    assert "How this was worked out" in html and "name says identifier" in html
    assert "Values" in html and "trim" in html.lower()
    assert "@media print" in html and 'class="vp"' in html      # value pairs block
    assert "Settings as JSON" in html
    assert not re.search(r"password|secret", html, re.I)
```

- [ ] **Step 2: Run to verify it fails** - `python -m pytest tests/test_report.py -q` - Expected: FAIL (missing anchors).

- [ ] **Step 3: Implement**

CSS additions (append inside `CSS`):

```
.note.warn{border-left-color:var(--fs-warn)}.note.warn .note-t{color:var(--fs-warn)}
.pill a{color:inherit;text-decoration:none}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:baseline;border:1px solid var(--fs-line);border-radius:var(--r-sm);background:var(--fs-panel);padding:14px 18px;margin-top:22px}
.verdict .w{font-family:var(--font-display);font-weight:300;font-size:26px;color:var(--fs-text)}
.verdict.ok .w{color:var(--fs-pos)}.verdict.warn .w{color:var(--fs-warn)}.verdict.bad .w{color:var(--fs-neg)}
.verdict .r{font-family:var(--font-mono);font-size:11px;color:var(--fs-text3)}
.vp{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin:14px 0 4px}
.vp .pcard .k{display:flex;justify-content:space-between}
.vp .pcard .k span{color:var(--fs-neg)}
details{margin-top:8px}summary{cursor:pointer;font-family:var(--font-mono);font-size:11px;color:var(--fs-text3)}
details pre{font-family:var(--font-mono);font-size:11px;white-space:pre-wrap;color:var(--fs-text2);background:var(--fs-surface);padding:12px;border-radius:var(--r-sm);max-height:420px;overflow:auto}
@media print{:root{--fs-bg:#fff;--fs-panel:#fff;--fs-surface:#f3f1ec;--fs-line:#d8d3c8;--fs-text:#111;--fs-text2:#333;--fs-text3:#666;--fs-text4:#888;--fs-accent:#8a5a1e;--fs-accent-h:#8a5a1e;--fs-border:#e2ddd2;--diff-left-bg:#f6d9d2;--diff-left-fg:#4a2521;--diff-right-bg:#f6d9d2;--diff-right-fg:#4a2521}
body{font-size:11px}.main{max-width:none;padding:0}td,th{white-space:normal}.tw{overflow:visible}.card,.m,.note,.pcard,tr{break-inside:avoid}
tr.a td{background:#fff;color:#111}tr.b td{background:#eee;color:#111}tr.b td.side,tr.b td.key{color:#555}.side-b td{background:#eee;color:#111}.legend .lb{background:#eee;color:#111}details{display:none}}
```

`build_report` changes, in order:
1. Signature `(run, A, B, name_a, name_b, limit=500, notes=None, profile=None)`; `from .outputs import summary_payload`; `from .theme import CELL_BUDGET`; `v = run["verdict"]`; `pairs = value_pairs(run)` (import from `.compare`).
2. `sec()` also yields an id: keep a list `IDS = ["setup", "counts", "columns", "by-key", "rows", "only-a", "only-b"]` and write `<section class="sec" id="{IDS[i]}">` for each section in that order (the by-key / rows / only sections keep their ids even when skipped - only emitted sections get ids, so use fixed ids per section rather than the counter).
3. Hero pills: source pills `f'<span class="pill">{esc(name_a)} · {esc(A.origin.split(" · ")[0]) if A.is_database else esc(A.label)}</span>'` (same for B), then key and columns pills, then `<span class="pill"><a href="#setup">setup</a></span>` for every section that exists. After the pills: `f'<div class="verdict {v.tone}"><div class="w">{v.word}</div><div class="r">judged by: {esc(v.rule)}</div></div>'`.
4. Settings card rows: replace `("Files", ...)` with `("Sources", src_a + "<br>" + src_b)` where for a side `s` with rows `n`: `f"{esc(nm)} - {esc(s.origin) if s.is_database else esc(s.label)}"` + (`f" · connection <code>{esc(s.conn)}</code>"` if database) + (`f" · {esc(path)}"` when `s.csv_path` is outside `work_dir()` and not database) + (`f" ({esc(s.cut)})"` if cut) + (" · Parquet snapshot" if `s.cache_path`) + `f" - {n:,} rows"` + (`f" · fetched {esc(s.fetched_at)}"` if database) + (`f" · capped at {s.cap:,}"` if `s.capped`) + (`f'<div class="small">{esc(s.query)}</div>'` if database). Insert `("Key", key_row)` after Sources when `by_key`: `esc(" + ".join(keys))` + ` - unique on both sides` or ` - {dup_l:,} rows in A and {dup_r:,} in B share their key with an earlier row` + ` · {matched:,} of {min(rows_l, rows_r):,} matched ({pct}%)` + (the `why` text: the first note starting with "key:" from `notes`, with its "key: ... - " prefix stripped) + (`<details><summary>How this was worked out - {len(notes)} decisions</summary><pre>` + "\n".join(esc(n) for n in notes) + `</pre></details>` when notes). Add `("Values", ...)`: `"trim spaces" if cfg["trim"] else "<b>keep spaces</b>"`, `"empty is null" if cfg["empty_as_null"] else "<b>empty is a value</b>"`, `"<b>case ignored</b>" if cfg["ignore_case"] else "case matters"`, `f"tolerance {cfg['tolerance']}"` (bold when non-zero), `"null tokens: " + ", ".join(cfg.get("null_tokens") or [])`, joined by " · ". Filters row: the user's filters from `cfg["filters"] / left_filters / right_filters` rendered as `f"{col} {op} {val} · both sides"` (op words from the spec dict keys: eq "=", ne "!=", gt ">", ge ">=", lt "<", le "<=", in "in", not_in "not in", between "between", like "like", is_null "is null", not_null "is not null"; values joined with ", "), then the engine SQL in `.small` from `res.filter_left/right` as today; plus `f"{name_a}: {A.cut}"` when a side has a cut; "none" when nothing.
5. Row counts grid: after the six tiles add `Rows after filter` tiles for each side when `res.rows_left != res.rows_left_read` (or right). Move the `dup_note` here (shown whenever `res.duplicate_keys_left or res.duplicate_keys_right`).
6. After the column table: `<div class="vp">` + for each `col, df in pairs.items()` (sorted by `res.diffs_by_column` desc, first 15): `<div class="pcard"><div class="k"><code>{esc(col)}</code><span>{n:,} differ</span></div><table>` rows `<tr><td>{esc(a)} → {esc(b)}</td><td class="num">{n:,} · {pct:.0f}%</td></tr>` + `</table></div>`; when `n >= 0.99 * matched_rows` add `<div class="small">every matched row differs on this column - two fields paired by mistake, or a value that converts on one side only</div>`.
7. Row caps: `cap = min(limit, max(50, CELL_BUDGET // (len(cols) + len(keys) + 1)))` used for `differing_rows(run, keys, cols, cap)` and `.head(cap)`, subtitle `f"{min(total, cap):,} of {total:,} rows · capped at {limit:,} rows or {CELL_BUDGET:,} cells"`. One-sided frames: `pd.read_csv(path, nrows=cap, dtype=str, keep_default_na=False)` instead of `load_csv(...).head(limit)`.
8. Footer: `f"Built {esc(run['at'])} in {run['seconds']:.1f}s · run {esc(run['run_id'])} · rows shown are capped at {limit:,} per section and {CELL_BUDGET:,} cells; the downloads hold everything · values are the canonical form both sides were compared on · self-contained apart from the web fonts, which fall back when offline"` + `<details><summary>Settings as JSON</summary><pre>` + esc(json.dumps({k: payload[k] for k in ("sources", "settings")}, indent=1, default=str)) + `</pre></details>` where `payload = summary_payload(run, A, B, name_a, name_b, notes)` computed with `run["files"]` as it is (the report is built before `write_summary` - `summary_payload` tolerates that).

- [ ] **Step 4: Run** `python -m pytest tests -q` and the gate; open the gate's HTML in a browser (or `python <scratchpad>/shot.py <html> t8.png --full`) and check the verdict band, Sources, Key, Values and the value pairs render.

- [ ] **Step 5: Commit**

```bash
git add tablecmp/report.py tablecmp/theme.py tests/test_report.py
git commit -m "Report: verdict with its rule, sources, key reasons, values and filters, value pairs, anchors, print"
```

---

### Task 9: Results page - verdict from the run, the Downloads tab

**Files:**
- Modify: `tablecmp/ui_results.py:19-40` (verdict), `:150-180` (columns tab value pairs), `:242-278` (save_row), `:281-320` (report_tab), `:322-355` (downloads_tab)

**Interfaces:**
- Consumes: `run["verdict"]`, `outputs.zip_run/default_save_folder/save_target/table_formats`, `value_pairs`, `write_paired` output in `run["files"]`.

- [ ] **Step 1: Implement**

`verdict()`: `v = run["verdict"]; tone = v.tone`; the banner text starts with `f"<b>{esc(v.word)}</b> · "` then the existing sentence.

`columns_tab` (lines 172-179): replace the pandas groupby with `pairs = value_pairs(run, 10)` computed once above the loop; `pair = pairs.get(col)`; when present rename columns to `[f"{NA} · {col}", f"{NB} · {col}", "Count", "%"]` (from `a, b, n, pct`) and `st.dataframe(pair, ...)`.

`default_save_dir()` stays; `save_row(files, label, key, run)`: the default value is `str(default_save_folder(run, Path(default_save_dir())))`; on click `target = save_target(folder, run)` inside the try, catching `ValueError` as `st.error(str(exc))`; the success message counts files.

`report_tab`: `ensure_report(run, A, B, NA, NB, limit)` factored out (build if `_report_key` differs, write `<pair>__report.html` into `run["folder"]`, register in `run["files"]`), called at the top; the Save row passes `run`.

`downloads_tab`:
```python
    st.markdown("#### Downloads")
    st.caption("Complete results, not just the rows displayed. Values are the canonical form both sides were compared on.")
    fmt = st.radio("Tables as", ["csv", "parquet", "both"], horizontal=True, key="out_fmt",
                   format_func={"csv": "CSV", "parquet": "Parquet", "both": "both"}.get,
                   help="Parquet: typed counts, a fraction of the size, straight into DuckDB, pandas or a warehouse. Applies to the next run; COMPARE_TABLE_FORMATS sets the default.")
    if fmt in ("parquet", "both") and not any(p.suffix == ".parquet" for p in run["files"].values()):
        if st.button("Write Parquet copies for this run", key="write_pq"):
            write_parquet_copies(run); st.rerun()
    ensure_report(run, A, B, NA, NB, limit)
    z = run.get("zip") or zip_run(run)
    st.download_button("Download all as zip", z.read_bytes(), file_name=z.name, mime="application/zip",
                       type="primary", key=f"dl_zip_{run['at']}", on_click="ignore")
    name = run["pair"]
    labels = [("cell_diffs.csv", "Cell differences"), ("left_only.csv", f"Rows only in {NA}"),
              ("right_only.csv", f"Rows only in {NB}"), ("paired.csv", "Paired rows"), ("columns.csv", "Columns"),
              ("profile.csv", "Profile"), ("summary.csv", "Summary"), ("summary.json", "Settings and result"),
              ("report.html", "Report"), ("diff.html", "Engine report")]
    ... five per row as before, skipping files that do not exist, plus every *.parquet present labelled "<table> (Parquet)" ...
    everything = {p.name: p.read_bytes() for p in run["files"].values() if p.exists()}
    save_row(everything, "Save everything to folder", key="save_all", run=run)
```

`downloads_tab` signature gains `A, B` (from `render`). The "Export the side-by-side view" expander is removed (the paired file is always written). Note: `zip_run` must run after `write_parquet_copies` when parquet was requested at run time - `compare_app` does that in Task 7; here the zip is built lazily on first visit, so it contains whatever exists. Rebuild the zip (`run.pop("zip")`) after `write_parquet_copies` on the button above.

- [ ] **Step 2: Run the gate** - `python <scratchpad>/apptest_auto.py t9.html` (it presses `save_report` and `save_all`; both must succeed and the saved folder must be `<dir>/<pair>__<run_id>`). Expected: counts unchanged, "Saved N files to ...".

- [ ] **Step 3: Commit**

```bash
git add tablecmp/ui_results.py
git commit -m "Downloads: one zip, every file, Parquet on a switch, saves in a per-run folder under COMPARE_OUT_DIR"
```

---

### Task 10: Packaging - requirements, lock, Dockerfile, compose, dockerignore

**Files:**
- Modify: `requirements.txt`
- Create: `requirements.lock`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`

- [ ] **Step 1: requirements.txt**

```
streamlit>=1.49
duckdb>=1.2
pandas
pyarrow
snowflake-connector-python      # Snowflake
databricks-sql-connector        # Databricks
pymssql                         # SQL Server - FreeTDS is inside the wheel, no ODBC driver needed
oracledb                        # Oracle - thin mode, no Oracle client needed
psycopg[binary]                 # Postgres
# desbordante                   # optional: exact key discovery (HyUCC / PyroUCC); without it a DuckDB greedy search runs
```

- [ ] **Step 2: requirements.lock**

Run in a clean venv on Python 3.12 (or the newest available here): `python -m venv <scratchpad>/lockenv && <scratchpad>/lockenv/Scripts/pip install -r requirements.txt && <scratchpad>/lockenv/Scripts/pip freeze > requirements.lock` (LF line endings). Commit the file.

- [ ] **Step 3: Dockerfile, compose, dockerignore, env example**

```dockerfile
FROM python:3.12-slim
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY compare_app.py csvdiff.py ./
COPY tablecmp/ tablecmp/
ENV STREAMLIT_SERVER_HEADLESS=true STREAMLIT_SERVER_ADDRESS=0.0.0.0 STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false STREAMLIT_LOGGER_LEVEL=warning \
    COMPARE_DATA_DIR=/data COMPARE_OUT_DIR=/out COMPARE_WORK_DIR=/work
RUN mkdir -p /data /out /work /home/app/.crosshire-compare && chown -R app:app /data /out /work /home/app
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["python", "compare_app.py"]
```

```yaml
# docker-compose.yml
services:
  compare:
    build: .
    ports: ["8501:8501"]
    env_file: .env                 # COMPARE_CONN_<NAME>=<uri>, one per line - see .env.example
    volumes:
      - ./data:/data:ro            # files to compare
      - ./out:/out                 # saved runs
      - connections:/home/app/.crosshire-compare
      - work:/work
    mem_limit: 4g
volumes:
  connections: {}
  work: {}
```

`.dockerignore`: `.git`, `docs/`, `examples/`, `README.html`, `__pycache__/`, `*.pyc`, `*.parquet`, `*__*/`, `out/`, `.env`, `.env.*`, `connections*.json`, `*.duckdb`, `*.duckdb.wal`, `tests/`, `.pytest_cache/`, `.venv/`.

`.env.example`: two commented lines showing `COMPARE_CONN_PROD=snowflake://USER:PASSWORD@ACCOUNT/DB/SCHEMA?warehouse=WH&role=ROLE` and `COMPARE_CONN_SAMPLE=duckdb:////data/sample.duckdb`.

- [ ] **Step 4: Check** `docker build -t crosshire-compare .` if Docker is available here; otherwise state in the commit message that the image was not built locally. `pip install -r requirements.txt` in the lock venv must succeed on this machine (it did in the dry run: all wheels exist for 3.12-3.14).

- [ ] **Step 5: Commit**

```bash
git add requirements.txt requirements.lock Dockerfile docker-compose.yml .dockerignore .env.example
git commit -m "Packaging: every driver as a pip wheel, a lock file, Dockerfile and compose"
```

---

### Task 11: The two headless flows as tests

**Files:**
- Create: `tests/test_apptest.py` (from the scratchpad gate script)

- [ ] **Step 1: Write the tests**

```python
# tests/test_apptest.py
"""The whole app, headless: files in, Auto, compare, save - and the same through a DuckDB database."""
import json, os, re
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

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
    return at.run()


def _finish(at):
    at.button(key="auto_btn").click().run()
    at = at.run()                                  # the auto_go rerun
    res = at.session_state["result"]
    r = res["result"]
    assert (r.matched_rows, r.only_left, r.only_right, r.diff_rows, r.cell_diffs) == tuple(
        int(COUNTS[k]) for k in ("matched", "only_left", "only_right", "diff_rows", "cells"))
    folder = Path(res["folder"])
    pair = res["pair"]
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "report.html", "diff.html", "profile.csv"):
        assert (folder / f"{pair}__{suffix}").exists(), suffix
    at.button(key="save_all").click().run()
    saved = list((Path(os.environ["COMPARE_OUT_DIR"])).glob(f"{pair}__*"))
    assert saved and (saved[0] / f"{pair}__summary.json").exists()
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in folder.iterdir() if p.suffix in (".csv", ".json", ".html"))
    assert FAKE_PW not in blob and "example-not" not in blob
    return res


def test_file_flow(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        at.radio(key=f"how_{tag}").set_value("Path on disk").run()
        at.text_input(key=f"pt_{tag}").input(str(EX / f)).run()
        at.button(key=f"load_{tag}").click().run()
    res = _finish(at)
    assert res["pair"] == "hr_employees_compare_payroll_employees"


def test_database_flow(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    for tag, table in (("A", "hr.employees"), ("B", "payroll.employees")):
        at.radio(key=f"how_{tag}").set_value("Database").run()
        at.selectbox(key=f"conn_{tag}").select("SAMPLE").run()
        at.radio(key=f"dbmode_{tag}").set_value("Table").run()
        at.text_input(key=f"tbl_{tag}").input(table).run()
        at.button(key=f"fetch_{tag}").click().run()
        at = at.run()
        at.button(key=f"load_{tag}").click().run()
    res = _finish(at)
    assert res["pair"] == "SAMPLE_compare_SAMPLE"
    js = json.loads((Path(res["folder"]) / f"{res['pair']}__summary.json").read_text(encoding="utf-8"))
    assert js["sources"]["A"]["connection"] == "SAMPLE" and js["sources"]["A"]["sql"].startswith("SELECT")
```

Note: with both sides on the same connection the pair is `SAMPLE_compare_SAMPLE`; that is the naming rule working as specified (the user can type names). Widget lookups must be re-fetched after every `run()`, as written.

- [ ] **Step 2: Run** `python -m pytest tests/test_apptest.py -q -x` - Expected: 2 passed (takes ~1 minute). Fix whatever the database flow shows - the most likely gap is `fetch_{tag}` needing the second `at.run()` to see `fetched_{tag}` (already included).

- [ ] **Step 3: Commit**

```bash
git add tests/test_apptest.py
git commit -m "Headless tests: the file flow and the database flow, with a secret grep over every output"
```

---

### Task 12: README.md, README.html, screenshots, push

**Files:**
- Modify: `README.md`, `README.html`, `docs/*.png`, `docs/banner.svg` if it names files

- [ ] **Step 1: README.md** - rewrite these sections, keeping the existing voice and layout:
  - "Files" -> "Sources": upload, path, **Database** (the six kinds, the panel, cap, Same SQL as A, fetch cache).
  - New "Connections": sidebar manager, the file and its path, `COMPARE_CONN_<NAME>` URIs with the six examples, save-password rule, Test, what is read-only, "not tested here" note for the five network databases.
  - "Try it on the sample pair": the new files, the new counts from `COUNTS.md`, and a second walkthrough through `COMPARE_CONN_SAMPLE`.
  - "Auto": the profile tick; "The key": reasons and overlap; "Values": the `length` step.
  - "Outputs": the naming rule, the folder tree, the file table (as in the design preview), formats, zip, `summary.json` shape, `COMPARE_OUT_DIR`.
  - "Settings": every `COMPARE_*` variable from the spec section 11.
  - New "Docker": build and compose, volumes, `.env`.
  - "Install and run": Python 3.12-3.14, one `pip install -r requirements.txt`, no ODBC.
  - "Development": the tests (`python -m pytest tests -q`), the AppTest keys, "Streamlit does not hot-reload tablecmp/".
  - Every example uses the employee domain.
- [ ] **Step 2: README.html** - the same content in the house style: add rail entries 09 Databases, 10 Outputs, 11 Docker; update 01 Files, 08 Auto, the key section, the settings table, the troubleshooting rows (a missing driver, a refused statement, a password asked each session, "Not under an allowed folder").
- [ ] **Step 3: Screenshots** - run `python <scratchpad>/final_shots.py` adapted to the sample pair (paths `examples/hr_employees.csv` / `payroll_employees.csv`), plus three new captures: the Database panel with SAMPLE fetched (`docs/app-database.png`), the Connections manager (`docs/app-connections.png`), the Downloads tab (`docs/app-downloads.png`); and the report in both themes via `COMPARE_THEME`. Copy into `docs/` with the existing names.
- [ ] **Step 4: Check** - `grep -rniE "order_id|trade_|ccy|currency|acme|globex|initech|umbrella|hooli|sales\.orders" README.md README.html docs/banner.svg` returns nothing; `python -m pytest tests -q` passes; the gate passes.
- [ ] **Step 5: Commit and push**

```bash
git add README.md README.html docs
git commit -m "Docs: databases, connections, outputs, Docker; employee sample and new screenshots"
git push origin main
```

---

## Self-review

- Spec coverage: connections (T1), databases and guard (T2), sample and scrub (T3), Side/work/out/UTC/hex/length (T4), outputs, verdict, formats, zip, saves, sweep (T5, T9), keys reasons, overlap, profile (T6), sidebar, manager, app wiring, notes, pair name, `COMPARE_UPLOAD_MB`, duckdb floor (T7), report (T8), packaging (T10), tests incl. secret grep (T11), docs and screenshots (T12). `.gitignore` in T3; `.dockerignore` in T10; `COMPARE_DATA_DIR` path check in T4 + T7.
- Types: `Verdict` fields `status/tone/word/rule`; `run["verdict"]` is a `Verdict`; `summary_payload` uses `asdict(run["verdict"])`; `suggest_keys(..., profile=)` returns a table with `Overlap %` and `Why`; `auto_configure` returns four values and `compare_app.py` unpacks four; `write_paired` registers `<pair>__paired.csv` in `run["files"]`; `outputs.TABLES` names match the file suffixes written.
- Placeholders: none - every step has the code or the exact edit.
