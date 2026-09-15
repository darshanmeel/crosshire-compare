# Database sources, named connections, defined outputs - design

Date: 2026-09-15. Status: approved in conversation; design preview at
https://claude.ai/artifact/5Aq3sXjfWdY7A36RA9wZWi (private).

## 1. Goal

Let either side of a comparison come from a database (Snowflake, Databricks, SQL Server,
Oracle, Postgres, or a DuckDB file) as well as a file; keep connections the way Airflow does
(named, in the sidebar, in a file in the home folder, overridable by environment variables);
make every run leave one folder with a fixed, documented set of files in HTML, JSON, CSV and
optionally Parquet; extend the report so it says where each side came from and why the key was
chosen; ship a single `requirements.txt` that installs everything with plain pip wheels (no
ODBC, no system packages) on Python 3.12-3.14, plus a Dockerfile; and replace every
company-specific word, name and sample with a generic employee / department domain.

The comparison itself - `csvdiff.py` - is a black box and is not modified.

## 2. Rules that hold throughout

- `csvdiff.py` is not modified. Everything new sits in `tablecmp/` or beside it.
- `st.*` only in `ui_*.py`, `compare_app.py`, `state.py`. `connections.py`, `databases.py`,
  `outputs.py` and every other module are plain Python and unit-testable.
- No `.streamlit/` folder. Streamlit settings come from the bootstrap dict in `compare_app.py`
  or `STREAMLIT_*` environment variables.
- Plain human wording, no emojis. Identifiers through `sql.ident`, literals through `sql.lit`.
- The headless Streamlit AppTest flow keeps working with the existing widget keys
  (`how_A/B`, `pt_A/B`, `load_A/B`, `auto_btn`, `go`, `disp_rows`, `auto_rerun`,
  `bucket_pick`, `save_report`, `save_all`). New keys are listed in section 12.
- Read-only against databases: only `SELECT` / `WITH` statements are ever sent; no `commit()`.
- No credential ever reaches an output, a report, a log line, an error message shown on
  screen, session state that the report reads, or the repository.
- Nothing company-specific anywhere: code, placeholders, sample data, README.md, README.html,
  screenshots, comments, docstrings.

## 3. Connections - `tablecmp/connections.py`

```python
@dataclass
class Connection:
    name: str                  # what the user calls it; [A-Za-z0-9_-]+
    kind: str                  # snowflake | databricks | mssql | oracle | postgresql | duckdb
    host: str = ""             # account (Snowflake), host, server, or the file path (duckdb)
    port: int | None = None
    database: str = ""
    schema: str = ""
    user: str = ""
    password: str | None = None   # None: not saved - asked for in the session
    extra: dict[str, str] = field(default_factory=dict)  # warehouse, role, authenticator,
                                                         # http_path, token, service_name, catalog
    timeout: int = 600         # query timeout, seconds; login timeout is min(timeout, 10)
    source: str = "file"       # file | env
```

- `to_uri(conn)` / `from_uri(name, uri)`: Airflow-like URIs, e.g.
  `snowflake://USER:PASS@ACCOUNT/DB/SCHEMA?warehouse=WH&role=R`,
  `databricks://token:TOKEN@host/?http_path=/sql/1.0/warehouses/x&catalog=c&schema=s`,
  `mssql://user:pass@server:1433/db`, `oracle://user:pass@host:1521/?service_name=X`,
  `postgresql://user:pass@host:5432/db`, `duckdb:///C:/data/sample.duckdb`.
  Percent-encoding for user, password and query values; round-trip tested.
- Store: `connections.json` in `~/.crosshire-compare/` (path from `COMPARE_CONNECTIONS` when
  set). Folder created `0o700`, file written `0o600` through `os.open`, atomically (temp file
  in the same folder + `os.replace`). Shape: `{"version": 1, "connections": [ {...}, ... ]}`;
  a connection whose password was not saved has no `password` key.
- Environment: every `COMPARE_CONN_<NAME>` holds a URI; the connection is called `<NAME>`
  exactly as given after the prefix. Env connections are `source="env"`, shown read-only in
  the sidebar, and override a file connection of the same name.
- `load_all() -> dict[str, Connection]`, `save(conn)`, `delete(name)`,
  `resolve(name, session_passwords) -> Connection` (fills a missing password from the
  session dict or raises `PasswordNeeded(name)`).
- `redact(text) -> str`: blanks the value after `password=`, `pwd=`, `token=`, `secret=`,
  `authorization:` (case-insensitive) and the `user:pass@` part of any URI. Applied to every
  driver error before it is shown or stored.

## 4. Databases - `tablecmp/databases.py`

- `DIALECTS`: per kind - `driver` (pip name, import name), `quote(ident)`,
  `limit(sql, n)`, `probe(sql)` (`SELECT * FROM (<sql>) q WHERE 1=0`), `test_sql`
  (`SELECT 1`, `SELECT 1 FROM dual`), `identity_sql` (current user / role / warehouse /
  database as one row), `read_only` connect options where they exist:
  DuckDB `read_only=True`; Postgres `options='-c default_transaction_read_only=on'`;
  Oracle `SET TRANSACTION READ ONLY` before each statement; SQL Server (pymssql)
  `SET TRANSACTION ISOLATION LEVEL READ COMMITTED` and no commit (pymssql autocommit off,
  rollback on close); Snowflake / Databricks: rely on the role, documented.
- Limit syntax: `SELECT * FROM (<sql>) q LIMIT n` for snowflake / postgresql / databricks /
  duckdb; `SELECT * FROM (<sql>) q FETCH FIRST n ROWS ONLY` for oracle; SQL Server
  `SELECT TOP (n) * FROM (<sql>) q` only when the SQL has no leading `WITH` and no `ORDER BY`,
  otherwise the batch loop stops at n (always the backstop on every dialect).
- `check_read_only(sql) -> str`: strips `--` and `/* */` comments and one trailing `;`;
  refuses any remaining `;`; the first keyword must be `SELECT` or `WITH`; refuses a bare
  `INTO` token outside string literals and double-quoted identifiers. Returns the cleaned SQL
  or raises `NotReadOnly("...")` with a sentence naming the token.
- `connect(conn) -> DB-API connection`: imports the driver lazily; `ImportError` becomes
  `DriverMissing("SQL Server needs the pymssql package: pip install pymssql")`. Login
  timeout min(timeout, 10) s, statement timeout `conn.timeout` s, per driver.
- `test(conn) -> TestResult(ok, message, identity, seconds)`.
- `fetch_parquet(conn, sql, path, cap, progress) -> FetchResult(rows, bytes, capped, seconds,
  columns)`: `check_read_only`, apply the cap, execute, stream: Snowflake
  `fetch_arrow_batches()`, Databricks `fetchmany_arrow(50_000)`, DuckDB
  `fetch_record_batch(50_000)`, others `fetchmany(50_000)` + `pyarrow.Table.from_pylist`
  with a schema fixed from the first batch (later batches `cast()` to it; values Arrow
  cannot map - UUID, memoryview, LOB, Decimal beyond float - are stringified first).
  `pyarrow.parquet.ParquetWriter`, one row group per batch. `progress("120,000 rows · 38 MB ·
  12 s")` per batch. `try/finally` closes the connection and unlinks the half-written file on
  any `BaseException`. Stops with a plain message when the work folder has under 1 GB free.
- Table mode: `schema.table` is quoted per dialect into `SELECT * FROM <schema>.<table>`.

## 5. Sources - changes to `tablecmp/sources.py`

- `Side` gains `conn: str = ""` (connection name), `query: str = ""`, `fetched_at: str = ""`,
  `cap: int = 0`, `capped: bool = False`, `database: str = ""` (the kind). `origin` becomes
  `"<Kind> · <schema.table or query>"`. A database side has `kind="parquet"` and
  `csv_path=<fetched parquet>`; downstream code is unchanged.
- `read_key` includes `conn`, `query`, `cap`, `fetched_at` so `signature()` and
  `profile_key` go stale on a re-fetch.
- `Side.stem` property: `Path(label).stem` for a file, the connection name for a database.
  Slugged: `[A-Za-z0-9_]` kept, runs of anything else become `_`.
- `work_dir()`: `COMPARE_WORK_DIR` or `<tempdir>/crosshire-compare`, created on first use;
  used for staged uploads, snapshots, fetches, run folders, the UCC CSV.
- `out_dir()`: `COMPARE_OUT_DIR` or `None`.
- `data_roots()`: `COMPARE_DATA_DIR` split on `os.pathsep`, or `[]`. When non-empty a
  "Path on disk" must resolve under one root, else "Not under an allowed folder".
- `read_expr` casts BLOB columns with `hex(col)` instead of `::VARCHAR`.
- `sql.scratch()` runs `SET TimeZone = 'UTC'` and `SET temp_directory` under the work folder;
  `SET memory_limit` when `COMPARE_DUCKDB_MEMORY` is set.

## 6. Sidebar - `tablecmp/ui_sidebar.py` and new `tablecmp/ui_database.py`

- Name box help: "names every output file - left_compare_right". A database side whose Name
  box still holds the default takes the connection name.
- `From` radio: `["Upload", "Path on disk", "Database"]`. Database branch (`ui_database.
  source_panel(tag)`): connection select `conn_{tag}` (saved + env, "New connection..." at
  the end opens the manager); mode radio `dbmode_{tag}` `["Table", "SQL query"]`; table input
  `tbl_{tag}` or SQL text area `sql_{tag}`; cap `cap_{tag}` (default 1,000,000; 0 = all);
  `Fetch {tag}` button `fetch_{tag}`; a password box `pw_{tag}` when the connection has no
  saved password (kept only in `st.session_state["db_passwords"]`); on side B a `Same SQL as
  A` button `same_as_A` (copies connection mode, SQL/table and cap from A via session_state +
  rerun). Fetch runs under `st.status` with the progress line; the result
  `(key, path, fetched_at, rows, capped)` is held in `st.session_state[f"fetched_{tag}"]`,
  keyed by (connection, normalised SQL, cap); reused while the key matches and the file
  exists; `Fetch again` (`refetch_{tag}`) clears it; a replaced fetch file is unlinked.
  A cap with no `ORDER BY` shows a warning before fetching. After a fetch the rest of the
  panel is the file panel: columns caption, Rows to read (caption for a database side:
  "applied to the fetched rows - to cut at the database, put a WHERE in the SQL"), Advanced,
  `Load {tag}`. The load caption reads
  `prod · Snowflake · HR.EMPLOYEES - 3,000 rows, 7 columns · fetched 10:12 · Parquet snapshot`
  and adds "capped at N" when capped. When the source is already Parquet and there is no
  cut, the snapshot step is skipped (no second copy).
- Connections manager (`ui_database.manager()`, an expander "Connections" under the Auto
  panel): the list (name, kind, where, "password saved" / "password asked each session",
  env ones marked "env · read-only"), New / Edit / Test / Save / Delete. The form's fields
  depend on the kind (section 3). `Test` (`test_conn`) shows "OK - user · role · warehouse ·
  database - 0.6 s" or the redacted driver message; the last result is cached per name. A
  saved password is never echoed into a text box.
- Auto panel: one caption (already trimmed), a checkbox `auto_profile` "Profile both sides
  first" (default on), the button `auto_btn`.

## 7. Keys and profile - `keys.py`, `profile.py`, `auto.py`

- `profile.py`: `profile_tables()` result gains a per-column `both` frame with nulls,
  null %, distinct, distinct %, min, max on each side, and `notes` (constant columns,
  all-null columns, distinct counts that differ by more than 2x between sides). Cached in
  `st.session_state["profile"]` under `profile_key` (already exists); `compare_app.py` passes
  it to Suggest keys and Auto when present and current.
- `keys.py`: `suggest_keys(..., profile=None)` - when a profile is given, single-column
  distinct counts, null shares and constant columns come from it (no re-measuring); columns
  with nulls are penalised, constant columns skipped. New measurement per candidate:
  **overlap** = share of A's distinct key values present in B (`count(DISTINCT combo) in both /
  count(DISTINCT combo) in A`). Ranking: unique on both, then affinity, then overlap, then
  fewer columns, then selectivity. Each candidate gets `why`: a sentence built from the
  reasons (name says identifier / a name, not an identifier / a measure, decimal; no nulls or
  N nulls; distinct of total on each side; unique on both / duplicates per side; how found;
  "adds nothing - X is already unique" for supersets of a unique key). The table gains
  `Overlap` and `Why` columns.
- `auto.py`: takes `profile` (runs it first when `auto_profile` is on and no current profile
  exists, narrating "Profiling both sides..."), passes it to `suggest_keys`, and writes the
  key's `why` into the notes, plus the runner-up when there is one, plus profile notes
  (constant / empty columns).
- `values.py`: a named step `"length"` (`length(x)`) beside `left` / `right`.

## 8. Outputs - `tablecmp/outputs.py` and `compare.py`

- Pair name: `pair_name(A, B) = f"{A.stem}_compare_{B.stem}"`, defaults
  `Left_compare_Right`. Run id: `YYYYMMDD-HHMMSS` from the run's `started_at`. Run folder:
  `<work_dir>/<pair>__<run_id>/`. `cfg["name"]` is the pair name (the engine prefixes its
  files with it).
- Files, always present after a run (empty ones written with their header):
  `<pair>__summary.json`, `<pair>__summary.csv`, `<pair>__columns.csv`,
  `<pair>__cell_diffs.csv`, `<pair>__left_only.csv`, `<pair>__right_only.csv`,
  `<pair>__paired.csv`, `<pair>__report.html`, `<pair>__diff.html` (engine). When a profile
  exists for the loaded pair: `<pair>__profile.csv`. Engine option `write_empty=True`.
- Hash mode: `h_a` / `h_b` built with `*` so left_only / right_only carry every compared
  column like the other modes.
- `paired.csv`: written by a DuckDB `COPY` of the wide layout (keys, `a_<col>`, `b_<col>`)
  at run time; the on-screen A-above-B frame is unchanged; the "Build export" button is
  replaced by a download of the file.
- `verdict_of(res, mode) -> Verdict(status, tone, word)`: identical / ok / "Identical" when
  no diff rows and no one-sided rows; differences / warn / "Small differences" when
  diff % < 5 and one-sided <= matched; differences / bad / "Differences" otherwise; error /
  bad / "Error" on `res.error`. Stored on the run dict, used by `ui_results.verdict`,
  `build_report`, the status strip, `summary.json` and `summary.csv`.
- `summary.json` (schema_version 1): `app`, `app_version`, `engine: "csvdiff"`,
  `duckdb_version`, `run_id`, `started_at` (ISO-8601 with offset), `seconds`, `pair`,
  `sources: {A, B}` (name, kind, database, connection, origin, label, path when not under the
  work folder, sql, fetched_at, cap, capped, rows, cut, delimiter, header, columns), `settings`
  (allowlist: mode, keys, compare_columns, only_a, only_b, trim, empty_as_null, ignore_case,
  tolerance, column_rules, filters, left_filters, right_filters, null_tokens, specs), `result`
  (`asdict(Outcome)`), `verdict`, `notes` (Auto's decisions when Auto ran), `files`
  (`[{name, format, rows, bytes}]`). Nothing from a `Connection` but its name.
- `summary.csv`: fixed header `schema_version, run_id, started_at, pair, left, right, mode,
  keys, rows_left_read, rows_right_read, rows_left, rows_right, matched_rows, only_left,
  only_right, diff_rows, cell_diffs, duplicate_keys_left, duplicate_keys_right, status, tone,
  seconds, error`; list fields joined with `|`.
- `columns.csv`: `column, name_a, name_b, role, read_as, matched, mismatched, match_pct,
  values_only_a, values_only_b` (machine headers; the UI and report rename for display).
- `profile.csv`: `column, side, rows, nulls, null_pct, distinct, distinct_pct, min, max, mean,
  avg_length`.
- Formats: `table_formats` = `{"csv"}` by default; `COMPARE_TABLE_FORMATS=csv,parquet` sets
  the default; the Downloads tab radio `out_fmt` (CSV / Parquet / both) overrides per run.
  With parquet on, every table (cell_diffs, left_only, right_only, paired, columns, profile)
  is also written as `.parquet` - DuckDB `COPY ... (FORMAT PARQUET)` in the same pass for the
  ones the app writes, `read_csv` → `COPY` for the engine's cell_diffs. `summary.json` lists
  every file with its format.
- Zip: `<pair>__<run_id>.zip` of the run folder, built once per run on first click
  (`shutil.make_archive`), offered by a primary "Download all as zip" button.
- Report written at run time (`ensure_report`), so Save everything always has it.
- Saves (`save_row`): default folder `<default_save_dir>/<pair>__<run_id>`; with
  `COMPARE_OUT_DIR` set the target must resolve under it (else refused with a sentence) and
  the default is `<out_dir>/<pair>__<run_id>`. Widget keys `save_report`, `save_all`,
  `<key>_dir` unchanged. Success message: "Saved 10 files to <folder>".
- Sweep: at first run of a server process delete `<work_dir>/*__*` run folders and `cmp_*`
  files older than `COMPARE_KEEP_HOURS` (default 24).

## 9. Report - `tablecmp/report.py`

Same look and tokens. Changes:
- Hero pills become anchors to the sections (`#setup`, `#counts`, `#columns`, `#by-key`,
  `#rows`, `#only-a`, `#only-b`); source pills show `name · Kind` for database sides.
- Verdict band under the lede: the word (Identical / Small differences / Differences) and
  the rule in a `.small` line. `.note.warn` styled (border and title in `--fs-warn`).
- Setup card rows: **Sources** (per side: name, origin, connection name and SQL in `<code>`
  for a database side, path when it was a path on disk outside the work folder, kind, cut,
  "Parquet snapshot", rows read, fetched-at, "capped at N"), **Key** (columns; unique on both
  or duplicate counts; match rate matched / min(rows); overlap; the `why`; the runner-up; a
  collapsed `<details>` "How this was worked out" with Auto's notes when present), Rows
  paired, Columns compared, Read as, **Values** (trim / empty is null / ignore case /
  tolerance / null tokens, non-defaults in `<b>`), **Filters** (as typed, side named; the
  engine SQL beneath in `.small`; the sidebar cut listed too).
- Row counts: "After filter" metrics when `rows_left` / `rows_right` differ from the read
  counts; the duplicate-key note moved here, shown whenever duplicates exist.
- Every column: unchanged table, then **value pairs**: for each differing column (worst
  first, up to 15) a card with the top 5 `left → right · count · %` pairs from one DuckDB
  query over `cd` (`value_pairs(run, n)` in `compare.py`, also used by `ui_results.
  columns_tab` instead of the pandas groupby); a note when a column differs on >= 99% of
  matched rows.
- Rows that differ / only-in sections: rows capped by `min(limit, CELL_BUDGET //
  (len(cols) + 1))` with `CELL_BUDGET = 150_000` in `theme.py`; the subtitle states the cap;
  one-sided frames read with `nrows=limit` rather than whole.
- Footer: run id, caps, a collapsed `<details>` "Settings as JSON" holding the `settings` and
  `sources` blocks of `summary.json`.
- `@media print`: tokens re-declared for paper (white ground, near-black text, light lines),
  tables wrap, `break-inside: avoid` on cards and notes.
- The Google Fonts link stays; the caption says "self-contained apart from the web fonts,
  which fall back when offline".

## 10. App page - `compare_app.py`, `ui_results.py`, `ui_columns.py`

- `pending["name"] = pair_name(A, B)`; `pending["notes"] = auto_notes` (excluded from the
  signature). Bootstrap reads `COMPARE_UPLOAD_MB`. The sweep runs once per process.
- Downloads tab: zip button first, then per-file buttons (cell differences, rows only in
  `<A>`, rows only in `<B>`, paired rows, columns, profile when present, summary, settings and
  result, report, engine report), the `out_fmt` radio, Save everything (per-run folder).
- Results verdict and status strip read `run["verdict"]`.
- Columns tab uses `value_pairs`.

## 11. Packaging and deployment

- `requirements.txt`: `streamlit>=1.49`, `duckdb>=1.2`, `pandas`, `pyarrow`,
  `snowflake-connector-python`, `databricks-sql-connector`, `pymssql`, `oracledb`,
  `psycopg[binary]`; `desbordante` commented as optional. `requirements.lock` from a clean
  `pip freeze`. The floor check in `compare_app.py` bumps to duckdb 1.2.
- `Dockerfile` (python:3.12-slim, user `app` uid 1000, `WORKDIR /app`, copy
  `compare_app.py`, `csvdiff.py`, `tablecmp/`, requirements files; `pip install
  --no-cache-dir -r requirements.lock`; `ENV STREAMLIT_SERVER_HEADLESS=true
  STREAMLIT_SERVER_ADDRESS=0.0.0.0 STREAMLIT_SERVER_PORT=8501
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false STREAMLIT_LOGGER_LEVEL=warning
  COMPARE_DATA_DIR=/data COMPARE_OUT_DIR=/out COMPARE_WORK_DIR=/work`; `EXPOSE 8501`;
  `HEALTHCHECK` on `/_stcore/health`; `CMD ["python", "compare_app.py"]`).
- `docker-compose.yml`: build, port 8501, `env_file: .env`, volumes `./data:/data:ro`,
  `./out:/out`, named `connections` at `/home/app/.crosshire-compare`, named `work` at
  `/work`, `mem_limit: 4g`.
- `.dockerignore`: `.git`, `docs/`, `examples/`, `README.html`, `__pycache__`, `*.parquet`,
  `out/`, `.env*`, `connections*.json`, `*.duckdb*`, `tests/`, `scratch*`.
- `.gitignore` additions: `connections*.json`, `.env`, `.env.*`, `*.duckdb`, `*.duckdb.wal`,
  `*__row_count_diffs.csv`, `*__columns.csv`, `*__profile.csv`, `*_compare_*__*/`, `out/`,
  `.ruff_cache/`. `requirements.lock` is committed. `examples/sample.duckdb` is committed
  deliberately (small) via a negated pattern.
- Environment variables, documented in README: `COMPARE_CONN_<NAME>`, `COMPARE_CONNECTIONS`,
  `COMPARE_OUT_DIR`, `COMPARE_WORK_DIR`, `COMPARE_KEEP_HOURS`, `COMPARE_DATA_DIR`,
  `COMPARE_TABLE_FORMATS`, `COMPARE_UPLOAD_MB`, `COMPARE_DUCKDB_MEMORY`, `COMPARE_THEME`,
  `COMPARE_APP_NAME`, `COMPARE_APP_TAGLINE`.

## 12. Widget keys (AppTest)

Existing, unchanged: `how_A/B`, `pt_A/B`, `load_A/B`, `auto_btn`, `go`, `disp_rows`,
`auto_rerun`, `bucket_pick`, `save_report`, `save_all`, `nick_A/B`, `sugg_btn`, `check_btn`,
`do_profile`. New: `conn_A/B`, `dbmode_A/B`, `tbl_A/B`, `sql_A/B`, `cap_A/B`, `fetch_A/B`,
`refetch_A/B`, `pw_A/B`, `same_as_A`, `auto_profile`, `out_fmt`, `dl_zip`, `test_conn`,
`conn_new`, `conn_save`, `conn_delete`, and the manager's field keys `cf_<field>`.

## 13. Sample data and wording

- `examples/make_sample.py` (seed 7) writes `examples/hr_employees.csv` (3,000 rows:
  `emp_id, first_name, last_name, department, salary, hire_date, active`),
  `examples/payroll_employees.csv` (2,985 rows: `EmployeeId, FullName, Dept, Salary,
  HireDate, IsActive, CostCenter` - renamed columns, `4,739.85`, `12/01/2026`, `Y/N`, one
  column only on that side, 40 rows only in HR, 25 only in payroll, 956 rows differing in
  1,046 cells: department 678 (renamed departments), salary 338, active 30) and
  `examples/sample.duckdb` with the same rows as `hr.employees` and `payroll.employees`.
  The exact counts are what the generator produces; the README and the tests use those.
- Every placeholder and example moves to the employee domain: `employees_2026-09.csv`,
  `hire_date >= '2026-07-20'\nAND department = 'Finance'`, `2026-07-20 · Finance · 100`,
  `emp_id, first_name, dept_name, ...`, `"Snowflake · HR.EMPLOYEES"`, `hired_at` for the
  timestamp example; `theme.py` docstring uses `Employee Table Check`; README.md and
  README.html lose the old sales-domain column names and company names.
- Screenshots in `docs/` retaken: home, loaded, columns, keys with reasons, result, rows,
  report tab, downloads, database panel, connections manager, and the report in both themes.

## 14. Tests

- `tests/test_connections.py`: URI round-trips per kind; env override; save without
  password; permissions; atomic write; `redact`.
- `tests/test_databases.py`: limit SQL per dialect; `check_read_only` cases (CTE, `;`
  injection, `INTO`, UPDATE in a comment, a column named `into` in quotes accepted);
  `fetch_parquet` against a fake DB-API cursor (schema fixed on the first batch, cap,
  cleanup on exception); `DriverMissing` message; DuckDB end to end.
- `tests/test_keys.py`: `why` text for a unique key, a non-unique one, a measure; overlap
  ranks a shared id above a disjoint one; profile reuse; constant column skipped; `length`
  step.
- `tests/test_outputs.py`: the file set after a run, `summary.csv` header, `columns.csv`
  rows, parquet on the switch, zip contents, `pair_name` defaults and slugging, saves under
  `COMPARE_OUT_DIR` and refused outside it, the sweep.
- `tests/test_apptest.py`: the headless file flow on the sample pair; the headless database
  flow via `COMPARE_CONN_SAMPLE=duckdb:///examples/sample.duckdb` asserting the same counts
  and grepping every output and the report for the fake password.
- Real Snowflake / Databricks / SQL Server / Oracle / Postgres are not available here; those
  connectors are covered by the fake-cursor tests only, and the README says so.

## 15. Documentation

README.md and README.html: new sections Databases (connections, env vars, per-database install
line, read-only guarantee, what is and is not tested), Outputs (the file table, formats, naming
rule, `summary.json` shape), Deploy (requirements, Docker, env vars, Python 3.12-3.14);
updated walkthrough counts and screenshots; the brief's "do not advertise Snowflake / SQL
Server" rule is retired.

## 16. Left out

Rows that differ in position mode; a metadata-only "peek columns" before fetching; an
on-demand wide `diff_rows.csv`; Excel export; browsing schema.table lists; per-driver query
cancel.
