<p align="center"><img src="docs/banner.svg" alt="CrossHire Compare" width="100%"></p>

# CrossHire Compare

Two tables, every difference, in one page.

A Streamlit front end over DuckDB that compares two tables row by row. Load a CSV, a JSON file or a database table on either side, pair their columns in one table, set the type once, add transform steps where a side needs them, tick the key and press **Compare** - or press **Auto** and let it work the whole thing out, narrating each step. It is built for reconciling two exports of the same data: two systems, two dates, two vendors. Every run leaves one folder with a fixed set of files - a self-contained HTML report you can hand to someone who never opened the app, the differences as CSV or Parquet, and a JSON with every setting the run used. A second page, **Profiling**, takes one table on its own and says what a reader wants to know first: which column identifies a row, what stands out, the statistics of every column, its outliers, shapes and dependencies.

![Streamlit 1.49+](https://img.shields.io/badge/Streamlit-1.49%2B-f4b87c?style=flat-square&labelColor=0e0d0b)
![DuckDB 1.2+](https://img.shields.io/badge/DuckDB-1.2%2B-f4b87c?style=flat-square&labelColor=0e0d0b)
![Python 3.12-3.14](https://img.shields.io/badge/Python-3.12--3.14-f4b87c?style=flat-square&labelColor=0e0d0b)
![MIT](https://img.shields.io/badge/License-MIT-f4b87c?style=flat-square&labelColor=0e0d0b)

## Contents

- [What it looks like](#what-it-looks-like)
- [Install and run](#install-and-run)
- [Try it on the sample pair](#try-it-on-the-sample-pair)
- [How a run goes](#how-a-run-goes)
- [What it does](#what-it-does): [Sources](#sources), [Connections](#connections), [The column table](#the-column-table), [Values](#values), [The key](#the-key), [Rows](#rows), [Compare and results](#compare-and-results) (the run disc and the Log), [Auto](#auto), [Profiling](#profiling)
- [The report](#the-report)
- [Outputs](#outputs)
- [Speed](#speed)
- [Settings](#settings)
- [Docker](#docker)
- [Theme](#theme)
- [The files](#the-files)
- [The engine on its own](#the-engine-on-its-own)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Related](#related)
- [License](#license)

## What it looks like

Every screenshot in this file is the app or its report on the sample pair in `examples/` - `hr_employees.csv` against `payroll_employees.csv`, the sides named **HR** and **Payroll** in the sidebar (3,000 employees on the HR side, 2,985 on the Payroll side, every column renamed, the two names joined into one, salaries with thousands separators, dates as dd/mm/yyyy, booleans as Y/N). The run is the one in [Try it on the sample pair](#try-it-on-the-sample-pair): **Figure it all out and compare**, then the one step Auto's guess needs, then **Compare**. The other screenshots sit next to the text they illustrate.

The result: the verdict line, then the Summary tab - the key as a green chip with the rows matched on it, the row counts, the column counts, and the one-sided columns called out, before any table.

```
Differences · 2,960 rows matched on emp_id · 5 columns compared · 649 rows (21.93%) differ in 687 cells · 40 only in HR · 25 only in Payroll · 0.4s at 22:32:04
```

![The Summary tab](docs/app-result.png)

## Install and run

```
pip install -r requirements.txt   # Streamlit, DuckDB, pandas, pyarrow and the five database drivers
pip install desbordante           # optional - exact key discovery (HyUCC / PyroUCC)

python compare_app.py             # starts the app with its own settings: theme, 4 GB uploads
streamlit run compare_app.py      # also works; uploads are then capped at Streamlit's 200 MB default
                                  # (Path on disk and Database sources have no size limit either way)
```

Python 3.12 to 3.14. Streamlit 1.49 and DuckDB 1.2 are the floors the app checks at start. One `pip install` is the whole install: every database driver is a plain wheel - `snowflake-connector-python`, `databricks-sql-connector`, `pymssql` (FreeTDS is inside the wheel, no ODBC driver), `oracledb` (thin mode, no Oracle client), `psycopg[binary]` - so there is no system package and nothing to install outside pip. `requirements.lock` is the pinned set the Docker image installs; `pip install -r requirements.lock` reproduces it exactly. A driver is only imported when a connection of its kind is used, so a missing one stops that kind alone, with a message naming the package.

Keep `compare_app.py`, `csvdiff.py` (the comparison engine) and the `tablecmp/` folder together - the app stops with a clear message if any of them is missing. There is no config file and no `.streamlit/` folder: the app applies its theme itself when it starts (`python compare_app.py` passes the settings to Streamlit's bootstrap; `streamlit run` sets them on the first script run and reruns once). Streamlit does not hot-reload files inside `tablecmp/`, so restart the app after updating them.

## Try it on the sample pair

`examples/` holds the same 3,000 employees as exported by three systems, plus a database with two of them:

| File | What it is | What was planted |
|---|---|---|
| `hr_employees.csv` | The HR system, 3,000 rows: `emp_id, first_name, last_name, department, salary, hire_date, active` | ISO dates, `True`/`False` booleans - the clean side. |
| `payroll_employees.csv` | Payroll, 2,985 rows: `EmployeeId, FullName, Dept, Salary, HireDate, IsActive, CostCenter` | Every column renamed; the two names joined into `FullName`; three departments spelled its own way on about 30% of rows (`Finance & Control`, `Eng`, `Sales EMEA`); salaries as `4,739.85`; dates as `12/01/2026`; `Y`/`N`; a column HR does not have (`CostCenter`); the last 40 employees missing; 25 of its own; a few changed salaries and active flags. |
| `directory_employees.json` | The staff directory, 2,990 objects: `id, name, dept, salary, hire_date, active, manager_id` - numbers and booleans as JSON types | 3% of ids in lower case; one `name` for both names; 10% of departments spelled the directory's way (`People & Culture`, `Customer Support`, `Legal Affairs`), 5% with stray spaces; 8% of salaries changed and 5% with float noise inside a 0.01 tolerance; dates as `06-Nov-2019`; `manager_id` null for 10%; the first 30 HR employees missing; 20 of its own; 1% of active flags flipped. |
| `sample.duckdb` | A DuckDB file with `hr.employees` and `payroll.employees` - the two CSVs as text columns | The database route, with no server to set up. |
| `mapping_hr_directory.json` | The column mapping that reads the directory correctly | Used in the third walkthrough. |

`examples/make_sample.py` regenerates all four data files (seed 7).

### 1. HR against Payroll, with Auto

1. Start the app. In the sidebar type `HR` in File A's **Name** box, pick **Path on disk** and give the full path to `examples/hr_employees.csv`; press **Load A**. Same for File B: `Payroll`, `payroll_employees.csv`, **Load B**. (The names are what every output file is called after: `HR_compare_Payroll__report.html` and so on; leave them and the files are `Left_compare_Right__*`.)
2. Press **Figure it all out and compare**.

Auto pairs six columns - `salary` by name, `hire_date` with `HireDate` and `active` with `IsActive` by similar name, `emp_id` with `EmployeeId` as a guess it flags to check, `department` with `Dept` by their values - reads `salary` as a number with a *remove thousands separators* step on Payroll, `hire_date` as a date with *to date (%d/%m/%Y)* on Payroll, `active` as a boolean, finds the key `emp_id` (its reason: *name says identifier · no nulls · 3,000 distinct of 3,000 in HR, 2,985 of 2,985 in Payroll · 98.7% of HR's values found in Payroll · unique by itself*) and compares - the red disc under the page switch narrating each step, then ending on *Worked out in 1.6s - key: emp_id - comparing now* (the seconds are the machine's own). The verdict is:

```
Differences · 2,960 rows matched on emp_id · 5 columns compared · 2,960 rows (100.0%) differ in 3,647 cells · 40 only in HR · 25 only in Payroll
```

Every matched row differs, and that is Auto's one wrong guess, flagged as such: it paired `last_name` with `FullName` by similar name (*Matched by* says `guess - check`), and `Okafor` is never `Omar Okafor`. The tell is in its decisions, in the Log at the foot of the page - *last_name: 18 distinct values on HR against 361 on Payroll - spelled differently, or a different field* - and the column's expander under Columns & values says *every matched row differs on this column*.

3. Open **Transform and convert values**, pick the column `last_name` and the side `Payroll`, add the step *part N split by S* with the separator a single space and N = 2, press **Add**, then **Compare**:

```
Differences · 2,960 rows matched on emp_id · 5 columns compared · 649 rows (21.93%) differ in 687 cells · 40 only in HR · 25 only in Payroll
```

`department` differs on 337 rows (the renamed departments), `salary` on 319, `active` on 31, `last_name` and `hire_date` on none. Those are the numbers the Summary screenshot at the top shows. The Auto-only counts - 2,960 matched, 40 and 25 one-sided, 2,960 differing rows, 3,647 cells - are what the tests assert (`docs/superpowers/plans/COUNTS.md`).

### 2. The same pair through a database

Set one environment variable before starting the app - the path is taken as written, so make it absolute or relative to the folder you start from:

```
set COMPARE_CONN_SAMPLE=duckdb:///D:/data/crosshire-compare/examples/sample.duckdb     (Windows)
export COMPARE_CONN_SAMPLE=duckdb:////home/me/crosshire-compare/examples/sample.duckdb  (macOS / Linux)
```

1. For File A pick **Database**. The connection `SAMPLE · DuckDB file · …` is already selected; leave **Table** ticked, type `hr.employees`, press **Fetch A**. The rows land as a Parquet file in the work folder and the panel says *Fetched at 10:12:38 - 3,000 rows*; press **Load A**.
2. For File B pick **Database** too, press **Same SQL as A**, change the table to `payroll.employees`, **Fetch B**, **Load B**. The caption under each Load button reads `SAMPLE · DuckDB file · hr.employees - 3,000 rows, 7 columns · fetched 10:12:38`.
3. Press **Figure it all out and compare** - the same verdict as the file route, and the files are `SAMPLE_compare_SAMPLE__*`, because a database side left at its default name takes the connection's name.

The DuckDB file holds every column as text, so here the column table's *looks like* cells have something to say - `hire_date` *looks like* `date · 2023-03-04 → %Y-%m-%d` on one side and `date · 04/03/2023 → %d/%m/%Y` on the other, `active` `boolean · True/False` and `boolean · Y/N`, `salary` `number · 12,686.95 has thousands separators` - which is exactly what Auto then decides. (Loaded from the CSV, DuckDB's own sniffer types `hire_date` DATE on both sides, and a column DuckDB already typed gets no suggestion.)

### 3. HR against the directory JSON

Name the sides `HR` and `Directory`, load `examples/hr_employees.csv` and `examples/directory_employees.json`, press Auto. This time Auto walks into every trap on purpose:

```
Differences · 2,874 rows matched on emp_id · 5 columns compared · 2,874 rows (100.0%) differ in 3,377 cells · 126 only in HR · 116 only in Directory
```

`emp_id` and `id` were paired by their values, but the 3% of ids the directory writes in lower case find no partner, so 96 employees show up as one-sided on each side instead of 30 and 20; `first_name` was paired with the directory's single `name` (`guess - check` again, and every row differs on it); `salary` differs on 369 rows because the float noise counts; `department` on 105, `active` on 29.

Now load the mapping: in the column table press **Upload** in the box under **Save mapping** and give it `examples/mapping_hr_directory.json`; open **How values are read** and set *Numeric tolerance* to `0.01`; press **Compare**:

```
Differences · 2,970 rows matched on emp_id · 6 columns compared · 357 rows (12.02%) differ in 362 cells · 30 only in HR · 20 only in Directory
```

`salary` differs on 225 rows, `department` on 107, `active` on 30; `first_name`, `last_name` and `hire_date` on none - the planted differences and nothing else. What each entry in the mapping does, and why:

| Pair | Type and steps | Why |
|---|---|---|
| `emp_id` ↔ `id`, key | text · Directory: *upper* | The directory writes 3% of ids as `e10042`. Upper-casing that side pairs them; the one-sided counts drop to the real 30 and 20. |
| `first_name` ↔ `name` | text · Directory: *part N split by S* (separator a space, N = 1) | The directory has one `name` for both names. Part 1 is the first name. |
| `last_name` ↔ `name` | text · Directory: *part N split by S* (separator a space, N = 2) | The same source column in a second pair - part 2 is the last name. The setup card says *name used 2 times on the Directory*. |
| `department` ↔ `dept` | text · case: ignore | The pair's own Case cell, carried in the file as `"case": "ignore"`. The stray spaces go with *Trim whitespace*; the 107 that remain are the directory's own department names, which differ by more than case - real differences, reported as such. |
| `salary` ↔ `salary` | number | With *Numeric tolerance* at `0.01` the float noise is not a difference; the 225 changed salaries are. |
| `hire_date` ↔ `hire_date` | date · Directory: *to date (%d-%b-%Y)* | `06-Nov-2019` spelled out. (The built-in list of spellings reads it too - Auto did - but a format in the mapping is explicit and fast.) |
| `active` ↔ `active` | boolean | `true` = `True`. |

`manager_id` has no counterpart and stays one-sided, as the setup card and the report's column sheet say.

## How a run goes

Before anything is loaded: File A's panel in the sidebar - the Name box, the **Upload** / **Path on disk** / **Database** radio, the upload box, the delimiter and header tick, *Rows to read* and *Advanced* folded, **Load A** - and on the page the **Compare** | **Profiling** switch, the status strip at *0 of 2 loaded*, the one hint that matters next, and the folded Log.

![The app before anything is loaded](docs/app-home.png)

1. **Load A and B in the sidebar.** Upload, give a path, or fetch from a database. Each side has a name (Left and Right by default) that is shown everywhere and names every output file - `<left>_compare_<right>__report.html` - so name them; the sidebar reminds you under a file side that is still called Left or Right, and under either side when both carry the same name. For a big file open *Rows to read* first and cut it down. Both sides get a 10-row preview and nothing else runs. The sidebar holds the sources; the page walks down numbered sections and the strip under the headline says where things stand.

   ![The app with both files loaded](docs/app-loaded.png)

2. **Check the column table.** Pairs by name are already made. Fix the rest with the dropdowns, set Type, tick Key and Compare - the **Role** column and the chips under the table turn green for the key and red for what is left out, as you tick. The table never folds; the setup card under it says what it amounts to: the key, what is compared, what is missing on each side.
3. **Transform where a side needs it.** Pick a column and a side, add steps - trim, left 10, to date (%d/%m/%Y) - previewed on the first five rows.
4. **Press Compare.** The red disc under the status strip pulses through each step and settles with a check mark and the time it took; the steps are kept in the Log at the foot of the page. The result stays on screen until the next run - a failure never wipes it, a settings change only marks it stale. Changing a Name box or *Rows to display* does not; the next Compare picks the new name up.

Or press **Figure it all out and compare** in the sidebar. Auto pairs the columns, works out every type and date spelling, finds the key, compares - narrating each step in the disc; every decision is a cell in the column table or a step in the transform section, and the list of them is in the Log.

To measure one table on its own - its key, what stands out, the statistics, outliers, patterns and dependencies - switch to **Profiling** under the headline - see [Profiling](#profiling).

## What it does

### Sources

Each side comes from one of three places, picked with the radio under its Name box: **Upload**, **Path on disk**, or **Database** (the Profiling page's one **File** panel is the same panel). Only **Upload** has a size limit - the file travels through the browser, so it is capped at 200 MB under `streamlit run` and 4 GB under `python compare_app.py`. **Path on disk** and **Database** never go through the browser: DuckDB reads the file, or the fetched table, straight from disk, and a multi-GB file is fine. For a big file, Path on disk is the route.

A file is a **CSV** (any delimiter), a **JSON** file - an array of objects, or one object per line (`.jsonl` / `.ndjson`) - or a **Parquet** file. A JSON value that is itself an object or list arrives as text, in DuckDB's own spelling of the object or list rather than as JSON; a Parquet BLOB column arrives as hex. With `COMPARE_DATA_DIR` set, a path on disk must sit under one of its folders or the sidebar says *Not under an allowed folder*. Each side has a **Name** (shown everywhere, and the name of every output file), for CSV a delimiter and a *First row is a header* tick, and **Rows to read**: a WHERE filter on the file's own column names, an order, a top N. All three are applied by DuckDB as the file is read - this is how a 20 GB file becomes the 100,000 rows you actually want. The column / condition / value pickers build the filter for you.

**Snapshot the rows read to Parquet** (under *Advanced*, on by default) reads the file once with its cut and keeps the rows as a compact Parquet file in the work folder. Everything after - previews, key search, comparison - reads that instead of re-parsing the file. Untick it only for small files you are re-loading constantly. A Parquet source with no cut is already what a snapshot would be, so none is taken.

Also under **Advanced**, a comma-separated list of column names overrides a header row that is missing or short. The app warns when the header looks like a data row, or names fewer columns than the data has.

**Database** fetches a table or a query out of Snowflake, Databricks, SQL Server, Oracle, Postgres or a DuckDB file into a Parquet file in the work folder, once; from there on the side is a Parquet file like any other. The panel:

- **Connection** - the saved and environment connections by name, kind and host; none yet, and it says so and points at the [Connections](#connections) manager below. A connection whose password was not saved gets a **Password - kept for this session only** box; the password lives in the session and nowhere else.
- **Table** or **SQL query**. A table is `schema.table`, quoted for the dialect: a part you quote yourself (`"My Table"`, `[My Table]`, `` `my table` ``) is kept as written, a bare part is folded the way that database folds it (Snowflake and Oracle to upper case, Postgres to lower), so `hr.employees` finds `HR.EMPLOYEES` on Snowflake. A query is one `SELECT` or `WITH` statement - see *read-only* below.
- **Fetch at most (0 = all)**, default 1,000,000. The cap goes into the SQL where the dialect can take it (`LIMIT`, `FETCH FIRST n ROWS ONLY`, `TOP (n)`) and is enforced by the fetch loop everywhere, so it holds on every kind. A cap on a query with no `ORDER BY` gets a warning: the two sides could get different rows.
- **Fetch A** / **Fetch B**. The statement runs, the rows stream in batches of 50,000 straight into Parquet, and the run disc under the status strip counts along - *Fetching from SAMPLE…*, *120,000 rows · 38 MB · 12 s* - and ends on *Fetched 120,000 rows in 12.3s*, kept in the Log. The fetch stops with a plain message when the work folder has under 1 GB free; on any error the half-written file is removed. Afterwards the panel says *Fetched at 10:12:38 - 3,000 rows* (and *capped* when the cap was hit) and offers **Fetch again**. The fetch is kept while the connection, the SQL and the cap stay the same, so changing the name, the cut or the column table below does not fetch again; changing any of the three does.
- **Same SQL as A** on side B copies A's connection, Table / SQL choice, text and cap, for the case where both sides are the same query against two databases or two dates.

After a fetch the rest of the panel is the file panel: the columns caption, **Rows to read** (applied to the fetched rows - to cut at the database, put a WHERE in the SQL), **Advanced**, **Load**. The caption under Load reads `SAMPLE · DuckDB file · hr.employees - 3,000 rows, 7 columns · fetched 10:12:38`, with *capped at N* when it was. A database side left at its default name takes the connection's name.

A database side: the `SAMPLE` connection (a DuckDB file, set through `COMPARE_CONN_SAMPLE`), the table `hr.employees`, fetched and loaded. From the fetch on it is a Parquet file like any other.

![The Database panel with the SAMPLE connection fetched](docs/app-database.png)

### Connections

Connections are kept the way Airflow keeps them: named, in a file in your home folder, overridable one by one with an environment variable. The **Connections** expander sits under the Auto panel in the sidebar and lists every connection known - `PROD · Snowflake · ACCOUNT - DB.SCHEMA - WH · password saved`, or *password asked each session*, or *env · read-only* - with the form under it: **Edit** (a saved connection, or *New connection*), **Kind**, **Name** (letters, digits, `_` and `-`), the fields that kind wants, **Save password**, **Query timeout, seconds** (default 600), and **Test**, **Save**, **Delete**.

| Kind | Fields |
|---|---|
| Snowflake | Account, User, Password, Database, Schema, Warehouse, Role, Authenticator (optional) |
| Databricks | Server hostname, Schema, HTTP path, Access token, Catalog |
| SQL Server | Server, Port (1433), Database, User, Password |
| Oracle | Host, Port (1521), User, Password, Service name |
| Postgres | Host, Port (5432), Database, User, Password |
| DuckDB file | File path |

The connections known (the env one marked read-only), and the form for a new one - the fields follow the kind:

![The Connections manager](docs/app-connections.png)

**Test** connects, runs the smallest query (`SELECT 1`, or `SELECT 1 FROM dual`) and says who the database thinks you are: *OK - USER · ROLE · WH · DB - 0.6 s* (for a DuckDB file, how many tables it holds), or the driver's own message with every credential blanked.

**The store** is `~/.crosshire-compare/connections.json` (`COMPARE_CONNECTIONS` points it elsewhere): `{"version": 1, "connections": [ … ]}`, one record per connection with its name, kind, host, port, database, schema, user, `extra` (the kind's own fields: warehouse, role, HTTP path, service name) and timeout. The folder is created `0700` and the file written `0600` through a temp file and a rename, so it is never half-written. **Save password** unticked - the rule for anything shared - writes the record with no `password` key at all; the app then asks for the password once per session, in the sidebar, and keeps it in the session only. A saved password is never echoed back into the form.

**The environment** wins over the file: every `COMPARE_CONN_<NAME>=<uri>` is a connection called `<NAME>`, shown *env · read-only* in the manager, overriding a file connection of the same name (compared ignoring case, because Windows upper-cases variable names). The URI form is Airflow's, one example per kind:

```
COMPARE_CONN_PROD=snowflake://USER:PASSWORD@ACCOUNT/DB/SCHEMA?warehouse=WH&role=ROLE
COMPARE_CONN_LAKE=databricks://token:TOKEN@HOST/?http_path=/sql/1.0/warehouses/ID&catalog=CATALOG&schema=SCHEMA
COMPARE_CONN_MSSQL=mssql://USER:PASSWORD@SERVER:1433/DB
COMPARE_CONN_ORA=oracle://USER:PASSWORD@HOST:1521/?service_name=SERVICE
COMPARE_CONN_PG=postgresql://USER:PASSWORD@HOST:5432/DB
COMPARE_CONN_SAMPLE=duckdb:///C:/data/sample.duckdb
```

Percent-encode a user name or password with `@`, `:` or `/` in it; add `&timeout=900` for a longer query timeout; leave `:PASSWORD` out and the password is asked for each session. For `duckdb` the path is everything after `duckdb:///`, exactly as written. The manager's **Save** writes the same URI fields to the file, so a connection made in the sidebar and one set in the environment behave the same.

**Read-only** means three things. Only a single `SELECT` or `WITH` statement is ever sent: the guard strips comments and one trailing `;`, refuses a second statement, refuses `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `EXEC`, `EXECUTE` and `CALL` anywhere outside a string or a quoted name (quote a column called `update`), and refuses `SELECT … INTO` - each with a sentence naming the word, before a connection is even opened. The session is read-only where the driver has such a thing: a DuckDB file is opened `read_only`, Postgres gets `default_transaction_read_only=on`, Oracle runs `SET TRANSACTION READ ONLY` first, SQL Server connects with read-only intent and autocommit off; Snowflake and Databricks rely on the role of the user. And nothing ever commits: every connection is rolled back and closed when the fetch ends. The login timeout is 10 seconds (or the query timeout when that is shorter); the query timeout is the connection's, 600 s by default.

No credential reaches an output, a report, a log line or the screen: driver messages go through a redaction that blanks the value after `password=`, `pwd=`, `token=`, `secret=`, `api_key=` and `authorization:` and the `user:password@` part of any URI, and the only thing about a connection that lands in a report or `summary.json` is its name. `connections*.json`, `.env` and `*.duckdb` (bar the sample) are in `.gitignore` and `.dockerignore`.

What was and was not exercised: the DuckDB kind runs end to end here (the sample database, the headless tests). Snowflake, Databricks, SQL Server, Oracle and Postgres were **not** run against a live server in this repository - their dialects, the read-only guard, the read-only switch each driver is connected with, the cap and the streamed fetch (row batches and Arrow batches alike) are covered by tests against a stub driver and a fake DB-API cursor only. The first fetch against a real one is yours; **Test** is the place to start.

### The column table

Every column from either file is a row; one place to decide everything. The table is always open - it never folds away.

| Column | What it is |
|---|---|
| Role | What the row is - `key`, `compared`, `not compared`, `only in HR` / `only in Payroll` - in colour: green for a key, red for a row that takes no part in the comparison, no colour for a compared one. Not editable; it changes the moment you tick Key or Compare. |
| Left column, Right column | Dropdowns. Each row is one column from either file with its counterpart on the other side, or blank. Pick a counterpart for a blank row and the two rows merge; pick a column already used elsewhere and it moves - the row you edited wins. A column that is in no pair always has a row of its own; a row with nothing on either side disappears. |
| Common name | What the pair is called from here on: in transforms, filters, results, downloads. |
| Type · both sides | What both sides are converted to before comparing: `text`, `number`, `date`, `timestamp`, `boolean`. `number`: 100.00 = 100 = 1e2. `date`: 27/08/2026 = 2026-08-27. `timestamp` keeps the time of day. `boolean`: 1 = yes = true. A value that will not convert keeps its text, so it shows as a difference rather than vanishing. The type is a property of the pair. |
| Key | Part of the row key. Several ticks make a compound key. |
| Compare | Compare this column. Ignored on key columns. |
| Case | For a text pair: `ignore` or `exact`, or blank to follow the *Ignore case in values* switch under *How values are read*. A pair of any other Type takes no notice of it. |
| Matched by | Information: how the pair was made - `name`, `similar name`, `guess - check`, `data`, `you`, `file`. It also lands in `columns.csv`. |
| Left detected, Right detected | The type DuckDB sniffed or the file carries: `VARCHAR`, `DOUBLE`, `DATE`, `BOOLEAN`... |
| Left looks like, Right looks like | What a sample of the values looks like, for a column DuckDB left as text: `boolean · Y/N`, `number`, `number · 12,686.95 has thousands separators`, `date · 06-Nov-2019 → %d-%b-%Y`, `timestamp · 27/08/2026 10:11 → %d/%m/%Y %H:%M`, or `timestamp · … → ISO, no format needed`; blank for plain text or an empty column. Suggestions only - the Type never changes by itself. A column DuckDB already typed gets none, because the detected cell already says it. |

The *looks like* cells come from up to 2,000 distinct values of the first 50,000 rows (null tokens and empty strings skipped), decided in this order: boolean when every value is one of true/false/t/f/yes/no/y/n (the spellings seen are shown), number when 98% cast once commas are removed, else date or timestamp when 98% parse with one of the preset formats - the same list as the *to date* / *to timestamp* step picker, so the format can go straight into a step. To take a suggestion, change the pair's Type, or add a *to date* / *to number* step with that format in the transform section; the setup card's *Read as* row lists every suggestion not taken (`active · Payroll looks like boolean (Y/N) - read as text`) until the pair's Type agrees or the side gets a conversion step.

**A column may be used in more than one pair** - one `name` split into `first_name` and `last_name` with a *part N split by S* step on each pair, N = 1 and N = 2. To pair a column a second time, pick it in the dropdown of a row that is still unpaired on the other side. It keeps a one-sided row only while it is in no pair. The setup card's *Paired* row says `name used 2 times on the Right` when it happens, and the column sheet, the profile and the report list both pairs, each with its own step.

**Match by data** reads a sample of both files and pairs the unpaired columns that hold the same values, whatever they are called - `Dept` with `department`. **Reset to name matches** starts the table over. **Save mapping** writes the pairs as JSON - one entry per pair with `a`, `b`, `name`, `type`, `key`, `compare`, `case`, `a_steps` and `b_steps`, each step as `{"op": "to date", "params": {"fmt": "%d-%b-%Y"}}` - and the upload box under it (a JSON file) loads one back for the next run of the same two feeds: every pair whose columns both exist is taken, a column named in several entries is paired several times, an identical entry listed twice is taken once, and the unpaired rows are rebuilt from the files. `examples/mapping_hr_directory.json` is one to read. The *looks like* cells are not in the file.

**The colours.** The Role cell carries them - the editable cells stay plain - and the **chips** under the table say the same in one line: a green chip per key column, a plain one per compared column, a red one for a column that is not compared (`salary · not compared`) or is only in one file (`CostCenter · only in Payroll`). Tick Key or Compare and the row and its chip change colour at once. The **setup card** under the table always shows what it amounts to: how many pairs and any column used twice, the key, the compare list, how every typed or transformed column is read (`department text · ignore case`, `hire_date date · B: to date (format=%d-%b-%Y)`) with the suggestions not taken, and the columns that exist on one side only - those are null on the other side and are not compared.

The column table after Auto and the one transform step on the sample pair: `emp_id` is the key, green; five compared rows; `first_name` only in HR and `CostCenter` only in Payroll, red - and the same in one line as chips under the table. Off to the right (out of the frame) sit the pair's own Case, how the pair was made, what DuckDB detected and what the values *look like*.

![The column table](docs/app-columns.png)

### Values

Both files are read as text. Every value on every side goes through the same four stages and comes out as canonical text, so both sides compare on the same thing:

1. the side's transform steps
2. null folding (empty, `NULL`, `\N`, `N/A`, `NA`, `NaN`, `None`, `(null)`)
3. trim
4. the pair's Type

Open **Transform and convert values**, pick a column and a side, and add steps. Each step runs on the result of the one before.

| Group | Steps |
|---|---|
| Text | trim, upper, lower, left N characters, right N characters, length, characters from N, M long, replace text, regex replace, remove spaces, collapse repeated spaces, strip leading zeros, pad left to N with C, digits only, letters and digits only, part N split by S, remove thousands separators |
| Conversions | to number, to timestamp (format), to date (format), to boolean. A conversion step sets the pair's Type for you. Formats come from a picker of what the value looks like - `27/08/2026` becomes `%d/%m/%Y` - or are typed in; blank tries the usual spellings. |
| Custom expression | Any DuckDB expression with `x` as the value - `upper(split_part(x, '-', 1))`. A searchable catalog of DuckDB's own text, regex and date functions sits next to it, with a template, a description and an example for each. |

A text parameter is taken exactly as typed: one space is a real separator for *part N split by S* and a real find text for *replace text*; only nothing at all is blank, and a step whose find, separator or pad character is blank is refused with *Type the separator first - one space counts*.

The preview shows the first five rows of that file: in the file, after the steps, compared as - and whether the type conversion succeeds. **Check this column on all rows** counts the values on each side that do not convert, with examples. **Copy to Right** (or **Copy to Left**) repeats the same steps on the other side; **Remove last** and **Clear** undo them. When both sides have the same name the Side radio and the Copy button say `A · SAMPLE` and `B · SAMPLE`.

An example: `hired_at` holds `2026-08-27 10:11:12.123` on Left and `27/08/2026 10:11` on Right, and you only care about the day. Right: *left 10*, then *to date (%d/%m/%Y)*. Type becomes `date`; Left's ISO text converts on its own. Both compare as `2026-08-27`.

**How values are read** holds the global switches: *Trim whitespace*, *Empty = null*, *Ignore case in values*, *Numeric tolerance*, and the list of tokens folded to null. Case can also be decided per column: the table's **Case** cell on a text pair - `ignore` or `exact` - beats the switch for that column, travels in the mapping JSON as `"case"`, and shows in the setup card, in the report (`case matters · ignored on: department`) and in `columns.csv` as `text · ignore case`. The tolerance applies to every number pair, and only to them: two values within it are equal, while a text pair keeps its exact match, so a code of `001` against `1` stays a difference.

### The key

Tick **Key** in the table and rows are matched on it; you can always change it by hand - tick another column, untick this one. Nothing measures the key until you ask.

**Suggest keys** finds the combinations of up to four columns that identify a row on both sides - with Desbordante when it is installed (HyUCC for exact keys on the first 200,000 rows of each side, verified on every row; PyroUCC's almost-unique combinations when nothing is exact), otherwise by measuring every column and growing the most selective ones. Every candidate gets its **Overlap %** - the share of the Left side's distinct key values that exist on the Right, which is what a key is for - and a **Why**: one line of plain reasons. *name says identifier · no nulls · 3,000 distinct of 3,000 in HR, 2,985 of 2,985 in Payroll · 98.7% of HR's values found in Payroll · unique by itself*; or *salary: a measure, decimal - never a key*; or *no values in common - none of HR's hire_date values found in Payroll* for a key that pairs nothing because one column is spelled differently. Every combination grown is minimal: nothing is grown onto a key that already works - a column unique by itself is a key, not a seed - and a grown combination is cut back to the fewest columns that tell as many rows apart, so `emp_id` is never followed by `hire_date + emp_id`; the columns that look like a key are tried before a measure, and a measure is taken only while no key has been found at all - a key with an amount in it beats no key, and is a coincidence beside one. Only keys end the search - the closest never do. Candidates rank by unique on both sides, then whether they share any values at all - a row number each side counts for itself pairs nothing, so it ranks under a name and a date shared by both, and is no reason to stop looking for a key that pairs - then whether a measure is among them, then whether an identifier is - `emp_id` above a name and a date - then how much the names look like a key, then overlap, then fewer columns. The search runs in the red disc like every other run and ends on the best - *Best key: emp_id in 0.8s* - with its steps kept in the Log; pick rows from the list and press **Use as key**. When a profile of the same columns exists (Auto's *Profile both sides first*, or **Profile both files** under Rows), the single-column counts come from it and are not measured twice; a column with nulls is penalised and a constant column is skipped.

**Check key** counts, per side, the rows, the distinct key values and the duplicate rows among the rows that have a full key, and the **Null keys** - rows where any key column is null, which identify nothing. A key with duplicates or nulls is not unique, and the warning says which: *This key is null on 12 rows of Left - those rows cannot match*, then *This key is not unique on Right (40 duplicate rows). Rows sharing a key are paired in file order, which can produce differences that are really mis-pairing. Tick another column.*

With no key ticked, choose how rows are paired:

| Mode | How | When |
|---|---|---|
| hash | Every row is hashed over the compared columns and the two multisets are matched. Identical rows pair; the rest are one-sided. The result also says, per column, how many distinct values exist on one side only - where the one-sided rows differ. | No key at all, or you want to know whether the two files are the same set of rows. |
| position | Line 1 against line 1. | Both files sorted identically, same row count. |

If everything differs: a key that pairs every row and then finds every row different usually means the key columns are spelled differently on the two sides - `e10042 ` against `E10042`. The summary shows sample unmatched key values; give the key column a Type or an *upper* / *trim* step.

### Rows

**Filters** apply to both sides, or one, after types: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`, `between`, `like`, `is null`, `is not null`, on the common names, each with a Type of `auto`, `string`, `number` or `date`. Values are matched exactly - the *Ignore case* switch does not apply to filters - but they are spelled the way the column is before the engine sees them: on a boolean column `True`, `t`, `yes`, `y` and `1` mean `true` (and their opposites `false`), in lists and ranges too; on a date or timestamp column a value becomes the ISO text the column holds, read with the format the column's own *to date* or *to timestamp* step names on the side the filter applies to, else in any of the usual spellings (`05/01/2024` is `2024-05-01` on a column read with `%m/%d/%Y` and `2024-01-05` without a format; a value the two sides' formats read as different days is refused and asked for in ISO; the time of day is kept on a timestamp column); on a number column the value compares as a number - `10 > 9`, also when the column is the key and never compared, or when rows pair by hashing - and a value that is not a date, or not a number, is refused in a sentence - *filter on 'hire_date': 'not-a-date' is not a date* - shown once above the result, whether or not Compare was pressed. `between` takes two values, comma separated. To shrink a big file before it is even read, use *Rows to read* under that file in the sidebar instead; the caption over the filters says so.

**Profile both files** runs only when pressed: per column, a *Both sides* sheet with the null %, distinct count, min and max of each file and the null % gap, then each file's own statistics table - the same columns the [Profiling](#profiling) page's Statistics has - and the 10 most and 10 least frequent values, on the same typed values the comparison uses. It runs in the red disc (*Profiling…*, then *Profile ready in 1.2s*) and lands in the Log. A profile also feeds **Suggest keys** and Auto, goes into the run folder as `profile.csv`, and is dropped when the column table or the reads change; the one Auto takes with *Profile both sides first* shows here too, without the press. To profile one table with no second side, use the [Profiling](#profiling) page.

### Compare and results

Press **Compare**. Both sides are materialised once as DuckDB tables under the common names with the canonical values applied, then the engine (or the hash matcher) runs on those. The run disc narrates: reading Left, reading Right, matching on the key and comparing N columns, writing the paired rows. The result gets a **verdict**: *Identical* when no row differs and none is one-sided; *Small differences* when the rows that differ are under 5% of the matched rows and the one-sided rows are no more than the matched rows; *Differences* otherwise; *Error* when the engine reported one. The verdict is the run's own: it sits on the banner, in the status strip, in the report and in `summary.json` / `summary.csv`.

**While it runs.** Every long run - Auto, a profile, the key search, a database fetch, Compare - shows in one place, right under the status strip: a big red disc that pulses while the run works, the run's label beside it (*Comparing…*) and its latest step under that in mono. When the run finishes the disc stays red and takes a check mark, and the label carries the elapsed time: *Compared in 3.2s*, *Profile ready in 1.2s* (on the Profiling page *Profile ready - key: emp_id in 0.4s*), *Best key: emp_id in 0.8s*, *Fetched 3,000 rows in 0.4s*, *Worked out in 1.6s - key: emp_id - comparing now*. A run that fails leaves a red ring saying *could not finish*, and the error message is shown as before. The last disc stays until the next run, on the page it ran on; a run pressed far down the page - Profile, Suggest keys, Compare - draws it a second time next to its button, so there is no scrolling up to watch it.

![Auto running: the red disc pulsing, its latest step under the label](docs/app-running.png)

**The Log.** The last thing on either page is the **Log** expander - *Log - 4 entries*, *Log - empty* before the first run - folded by default. Every run is an entry, newest first: the time of day it started as HH:MM:SS, what it was (Auto, Profile, Key search, Fetch, Compare), the label it ended with - the elapsed time included - and every progress line under it; Auto adds a second entry, *Auto decisions*, with one line per decision: the pairs it made and how, the type and steps of every column, the key and why, the columns compared; the Profiling page's Profile adds *Profile notes* the same way, one line per thing that stands out. A run that failed says *could not finish*. The Log keeps the last 50 entries across reruns and page switches, and **Clear** empties it. The report keeps Auto's decisions as well, under its Key row as *How this was worked out*, and `summary.json` carries them as `notes`.

![The Log opened: two Compare runs, Auto's decisions and Auto's own steps, newest first](docs/app-log.png)

**Re-run on every change** is off by default - the last result stays on screen and is marked stale when a setting that changes the answer changes. The side names, *Rows to display per section* and the table format do not: *Rows to display* (100 to 10,000, default 1,000) caps the tables on screen and in the report only, and changing it redraws them without a run; downloads always contain everything. The engine's own `diff.html` is capped at 2,000 rows per tab.

| Tab | What it holds |
|---|---|
| Summary | A **Key** block first: the key columns as green chips and the line *Rows are matched on emp_id - 2,960 rows matched* - or *No key - rows were matched by hashing the 5 compared columns*, or *No key - rows were paired by position, line 1 against line 1* - with the warning under it when the key is not unique. Then the row counts; then every column from either file on one sheet - its name on each side, its role (key, compared, paired but not compared, only in Left, only in Right) in the column table's colours, green for the key and red for a column that took no part, how it was read, and for compared columns matched / mismatched / match % - with the one-sided columns called out above it. **Profile by bucket**: the top values of every column for the rows whose keys matched, matched but differ, or exist on one side only, key columns first. The matched-but-different bucket opens with **differences by key value** - the rows that paired on the key but disagree, grouped by each key column's value, with the columns that differ. The key is identical on both sides for these rows: this is where the differences sit, not what they are. |
| Columns & values | The rows that differ, Left above Right, differing cells marked. Then every compared column, worst first: the value pairs behind the count (one DuckDB pass over the cell differences), the distribution on each side. **Near-match analysis** says whether differences are formatting or data. |
| Report | The house-style HTML report, viewed in the page and downloaded with one button; **Download engine report** is the second button. |
| Downloads | The whole run as one zip, then every file of the run folder, the table format switch and **Save everything to folder** - see [Outputs](#outputs). |

Columns & values: the rows that differ, HR above Payroll, differing cells marked. Left rows are black, Right rows are cream, everywhere the two sides sit together.

![Rows that differ, HR above Payroll](docs/app-rows.png)

### Auto

Auto does everything by itself - pairs the columns, works out the types, finds the key, compares - narrating each step in the red disc and listing each decision in the Log, every one a cell in the column table or a step in the transform section that you can change. It reads both files several times over, so on big files cut them first with *Rows to read*.

1. **Pair columns.** By name, then similar name, then by their values for whatever is left over.
2. **Analyse types.** One pass over the first 50,000 rows of each side: how many values read as a number, a number once commas go, an ISO date, day-first, month-first, any known spelling, with a time of day, a boolean. Each pair gets a Type; a side that needs it gets a step - *remove thousands separators*, *to date (%d/%m/%Y)*. Two spellings are only merged when both sides read cleanly.
3. **Check case.** Text pairs whose sides only agree once case is ignored get an *upper* step on both. (Auto does not set the Case cell; the step is the decision, visible in the transform section.)
4. **Profile both sides** - the **Profile both sides first** tick under the button, on by default. Counts, nulls and distinct values per column feed the key search, show under Rows as the Profile, and land in the run folder as `profile.csv`; a constant column, an empty one, or a distinct count that differs more than twice between the sides becomes a note. Untick it on a very big pair. A profile already taken on the same columns and Types is reused; one taken before Auto changed a Type is measured again, on the typed values.
5. **Find the key.** Same as Suggest keys. The disc ends on the key it chose - *Worked out in 1.6s - key: emp_id - comparing now* - and the decision carries its *Why* and the runner-up - another key unique on both sides when the chosen one is, else the next closest, never the chosen key with a column added; if nothing is unique, the closest is used and said so; if nothing at all, hash mode.
6. **Compare.** Every paired non-key column, immediately. Every decision is a line of the *Auto decisions* entry in the Log - *12 decisions - every one a cell in the column table* - and is a cell in the table or a step in the transform section; the report keeps the list under its Key row as *How this was worked out*.

### Profiling

The **Compare** | **Profiling** switch under the headline picks the page. Profiling takes one table on its own - the headline reads *One table, every column.* - and says what a person opening an unfamiliar table wants to know first: which column identifies a row, what stands out, the statistics of every column, where the numbers and dates run wild, what shape the text takes, which columns determine which, and the most and least frequent values. The sidebar holds a single **File** panel, the same panel File A has: a **Name** (*Table* by default - it names the saved files, and a database table left at the default takes its connection's name), the **Upload** / **Path on disk** / **Database** radio, the delimiter and header tick, *Rows to read*, *Advanced*, **Load**; for a database the same Connection, Table or SQL query, cap and **Fetch**, with the Connections manager under it. Load, then press **Profile**.

What the values look like decides the types - there is no column table here to take a suggestion in - so a text column of `12,686.95` profiles as a number, `06-Nov-2019` as a date with its format, `Y`/`N` as a boolean; a column DuckDB typed keeps that type. The table is read into DuckDB once and every measure below runs on that one read; only the checks for stray spaces, case variants and leading zeros go back to the file, because they need the value as written. The run shows in the red disc under the switch - *Profiling…*, then *Looking for keys…* and *What stands out…* on the way, ending on *Profile ready - key: emp_id in 0.4s* (or *Profile ready - no key in 0.4s*) - and lands in the Log as two entries: the run with its steps, and *Profile notes* - *8 things stand out* - with one line per note, the way Auto's decisions are logged. The page then reads, top to bottom: **File**, **Profile** with its headline, **Keys**, **What stands out**, **Statistics** with the download and save row, the **Outliers**, **Patterns** and **Dependencies** folds, then **Value frequencies**.

**File** - the name, the file, rows × columns and the cut, with *First 10 rows* folded under it.

**Profile** - one line under the heading: `3,000 rows × 7 columns · key: emp_id · 0 duplicate rows`. The rows and columns, the key (or *no key up to 4 columns*), the exact duplicate rows - always said, even at 0 - and then only what is there: *1 empty column*, *1 constant column*, *2 columns with outliers*.

**Keys** - a green line when the best candidate is unique on every row: *Key: emp_id - unique on every row. Found by measuring every column and growing the most selective ones - `pip install desbordante` for exact key discovery (HyUCC / PyroUCC) - single-column figures from the profile.* Otherwise a warning, *Nothing up to 4 columns is unique - the closest are below.*, with the same note after it. The candidate table sits under it: the best three. Beside a key only keys are listed - each minimal, no two the same, none the key with a column added - and when nothing is unique, the three closest. This is the Compare page's **Suggest keys** on one table: every column unique by itself, then combinations of up to four columns grown from the most selective ones - the columns that look like a key before a measure - with Desbordante when it is installed (HyUCC on the first 200,000 rows, verified on every row; PyroUCC's almost-unique combinations when nothing is exact). Nothing is grown onto a key that already works, a combination is cut back to the fewest columns that tell as many rows apart, a measure is taken only while no key has been found at all, and a column with a null can never complete a key - a row with no key is never told apart - so the columns without one are tried first. On `hr_employees.csv` that is `emp_id` and, under it, the natural key `hire_date + first_name + last_name`. The distinct and null counts of the single columns come from the statistics just measured, so nothing is counted twice - that is what the note's last words say - and a column with one value is never a candidate. There is no other side, so no Overlap %; candidates rank by unique first, then whether a measure is among them, then whether an identifier is, then how much the names look like a key, then fewer columns. The columns:

| Column | What it is |
|---|---|
| Key columns | The column, or the combination joined with `+`. |
| Distinct | The distinct values of the combination among the rows that have a full key. |
| Unique | `yes` when Duplicate rows and Null keys are both 0. |
| Duplicate rows | Rows minus null keys minus distinct: the rows that share their key with another. |
| Null keys | Rows where any key column is null; they identify nothing. |
| Looks like a key | `yes` when the names and detected types read as identifiers, `measure columns` when one of them is a measure - an amount, a rate, a decimal. |
| Why | The reasons in one line, as on the Compare page but naming no side. `emp_id`: *name says identifier · no nulls · 3,000 distinct of 3,000 · unique by itself*. `hire_date + first_name + last_name`, ranked under it: *a name, not an identifier · no nulls · 3,000 distinct of 3,000 · grown from the most selective column*. When nothing is unique, the closest: *name says identifier · 10 nulls · 90 distinct of 100 · on its own - adding a column told no more rows apart* for an `id` column with 10 empty cells that no other column improves on - the 10 rows with no id have no key, so they are neither distinct nor duplicates - or *on its own - no other column to add* when there was none to try; *50 distinct of 100 · 50 rows share it* for one where every row appears twice. |

**What stands out** - one line per thing, as a list: the table-level lines first, then column by column in the table's order. When there is nothing, *Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.* On `hr_employees.csv`:

```
key: emp_id - unique on every row
patterns: the 3 most common shapes per column are listed - more exist in first_name (4 shapes), last_name (5 shapes), department (6 shapes)
first_name: 20 values - Jonas, Nadia, Ines, Aarav, Rafael, Uma, Fatima, Elena, Amara, Omar, Tomasz, Priya, …
last_name: 18 values - Ibrahim, Silva, Rossi, Costa, Larsen, Haddad, Nakamura, Schmidt, Mensah, Moreau, Novak, Okafor, …
department: 8 values - Support, Marketing, Operations, Engineering, Finance, Sales, People, Legal
salary: nearly unique - 5 rows share a value with another
hire_date: 16 dates after today
active: 2 values - true, false
```

(The sample's hire dates run to 2026-09-28, so how many fall after today depends on the day you run it.) Every kind of line, in the order they come - a line marked with a sample file is that file's own, the others show the form:

| Line | When it appears |
|---|---|
| `12 exact duplicate rows - the same values in every column` | Rows that repeat another one in every column, a null equal to a null. |
| `key: emp_id - unique on every row` (HR), or `no single column or combination up to 4 is unique - closest: first_name + last_name (2,998 distinct of 3,000)` | The best candidate from Keys, measured again on the table. |
| `Dept → CostCenter: every Dept has one CostCenter` (Payroll), `cust_id ↔ cust_email: one-to-one` | One line per row of the Dependencies fold, the first 10, then `… and n more in Dependencies`. |
| `tenure_years ~ leave_days: correlated, r = 0.93` | One line per correlated pair, the first 5, then `… and n more`. |
| `patterns: the 3 most common shapes per column are listed - more exist in first_name (4 shapes), …` (HR) | A text column has more shapes than the Patterns fold shows. A line of the same kind says when the dependency search or the correlations were capped. |
| `notes: empty - null on every row` | Null on every row; nothing else is said about the column. |
| `company: constant - one value on every row (ACME)` | One distinct value. |
| `manager_id: null on 9.3% of rows` (Directory) | Null on 5% of rows or more - or on any row at all when the name says identifier: `id`, `key`, `code`, `ref`, `no`, `num`, `account` and the like. |
| `salary: nearly unique - 5 rows share a value with another` (HR) | The distinct values are 99% or more of the filled rows, but not all of them. |
| `manager_id: says identifier but 2,653 rows share a value` (Directory) | The name says identifier and the values do not: neither unique nor nearly so. |
| `department: 8 values - Support, Marketing, Operations, Engineering, Finance, Sales, People, Legal` (HR) | Between 2 and 20 distinct values, covering at most half the rows - a category. The values by count, the first 12, then `…`. |
| `status: active on 97.3% of rows` | One value on 95% of rows or more, and it is not the only value. |
| `Salary: read as a number - 12,686.95 has thousands separators` (Payroll), `hire_date: read as a date - 06-Nov-2019 → %d-%b-%Y` (Directory), `IsActive: read as a boolean - Y/N` (Payroll) | What the *looks like* sniff decided for a text column, in its own words - what the column was read as. |
| `zip: reads as a number but 120 values have leading zeros - keep it as text` | A column read as a number whose values in the file start with a zero - a code, not an amount. |
| `city: 5 values differ only in case - Paris / paris / PARIS` | The same value in more than one case in the file; one example group of up to three spellings. |
| `dept: 123 values have leading or trailing spaces - trimmed before measuring` (Directory) | Values in the file with a space at either end; the tail is there when *Trim whitespace* is on. |
| `salary: 2 outliers - above 21,489.10 (1.5 × IQR) · highest 1,000,000` | Values outside Tukey's fences (see Outliers below), with the fence and the extreme on each side that is crossed; a side nothing crosses is left out. |
| `salary: 3 negative values · 40 zeros` | Either count above zero, on a number column. |
| `ratio: 2 values are NaN, infinite or beyond 1e150 - left out of the outliers`, `valid_to: 30 values are infinite - left out of the outliers` | Values no percentile, standard deviation or correlation can hold - `NaN`, `inf`, a number so large its square overflows, a date written `infinity` - are values to the reader and nulls to the Outliers fold, and this line says how many. |
| `hire_date: 16 dates after today` (HR), `birth_date: 3 dates before 1900` | Either count above zero, on a date or timestamp column. |
| `emp_id: 99.7% of values are A9999 - 3 are not (e1234, E12, 12E4)` | One shape covers 90% or more of a text column's values but not all of them; up to three of the others, then `…` when there are more. |

**Statistics** - the statistics table, one row per column: Column, Type, Rows, Nulls, Null %, Distinct, **Distinct % of filled** (distinct ÷ the non-null rows) and **Distinct % of rows** (distinct ÷ all rows - the two differ only where there are nulls: `manager_id` in the directory JSON is 2.21% of filled and 2.01% of rows), **Top value** and **Top %** (the most frequent value and its share of all rows, a null counting as a value and shown as `∅ null` - `department` has `Support` on 13.73%), Min, Max, Mean (numbers only), Avg length, **Min length** and **Max length** (of the text as read; blank on a column with nothing filled). **Download profile.csv** hands the table out through the browser as `<Table>__profile.csv`; **Save to folder** writes six files to the folder in the box beside it - `<COMPARE_OUT_DIR>/<Table>__<run_id>` when the variable is set (and then the save must stay under it), else a folder of that name next to the file, or under your Downloads folder - the same rule as the Compare page's saves:

```
Table__profile.csv        the statistics table, the columns above
Table__keys.csv           the candidate table: Key columns, Distinct, Unique, Duplicate rows, Null keys,
                          Looks like a key, Why
Table__notes.txt          the headline, a blank line, then one note per line
Table__outliers.csv       the Outliers fold: Column, Type, P1, P5, P25, Median, P75, P95, P99, Std dev,
                          Low fence, High fence, Outliers, Outlier %, Lowest, Highest, Zeros, Negatives
Table__patterns.csv       the Patterns fold: Column, Pattern, Collapsed, Count, %, Example
Table__dependencies.csv   the dependencies and the correlated pairs on one sheet: Column A, Column B,
                          Kind (many-to-one, one-to-one, correlated), Distinct, r
```

A fold with nothing in it writes a file with the header alone, so a script can rely on the set.

**Outliers** - folded: one row per number, date and timestamp column. The percentiles P1, P5, P25, Median, P75, P95, P99 and the standard deviation - `salary`: `5384.155`, `8672.865` and `11826.135` for P25, the median and P75, std dev `3714.9289` - then Tukey's fences, P25 − 1.5 × IQR and P75 + 1.5 × IQR with the IQR being P75 − P25 (`-4278.815` and `21489.105`), Outliers and Outlier % for the values outside them (none in the sample), Lowest and Highest (`2152.33`, `14979.57`), Zeros and Negatives. A date column takes the same percentiles on the dates - `hire_date`: median `2022-06-27`, fences `2013-06-08` and `2031-07-25` - with Std dev, Zeros and Negatives left blank; its dates after today and before 1900 go to What stands out only.

**Patterns** - folded: the three most common shapes of each text column, each with its Count, its % of the non-null values and the first value of that shape in the file. A shape turns every letter into `A` and every digit into `9` and keeps the rest as written - `E10001` is `A99999`, `2026-01-12` is `9999-99-99`, `Finance & Control` is `AAAAAAA & AAAAAAA` - and Collapsed folds the runs, `A+9+`, `9+-9+-9+`, `A+ & A+`, so `CC-220` and `CC-1100` read as one. On the sample `emp_id` is `A99999` on all 3,000 rows; `first_name` is `AAAAA` on 1,243 (41.43%), `AAAA` on 999 and `AAAAAA` on 596, and the note above says a fourth shape exists.

**Dependencies** - folded, two tables. First the functional dependencies: X → Y when every value of X goes with one value of Y, found by counting - X determines Y when X alone and X with Y have the same number of distinct values, a null counting as a value. The columns are Determines, Determined, Kind (`many-to-one`, or `one-to-one` when it holds the other way round too - listed once, the column that comes first in the table first) and Distinct, the values of X. Tried as X: every column that is neither unique, nor nearly unique (99% of the filled rows), nor constant - those determine everything and say nothing - the fewest values first, at most 40; any other non-constant column can be Y. Payroll's `Dept → CostCenter` is one, many-to-one with 11 distinct values. Then the correlated number columns: Pearson's r for every pair of the first 30 number columns, keeping the pairs with |r| ≥ 0.7, the strongest first - Column A, Column B, r. Where either cap cut columns, What stands out says so.

**Value frequencies** - one fold per column, labelled *emp_id - text · 3,000 distinct · 0.0% null*, with the 10 most and the 10 least frequent values side by side.

The profile goes when another table is loaded; measured under other null tokens or another *Trim whitespace* setting than the page's (both set under *How values are read* on the Compare page, and they apply here too), it says so (*This profile is from earlier settings - run it again to refresh*). Compare is untouched: switch back and the sides, the column table, the result and the Log are where they were.

![The Profiling page: the done disc naming the key, the File section, the headline, the Keys block with its candidate table, and What stands out](docs/app-profiling.png)

## The report

The Report tab shows the report in the page - the same report the download button hands out. **Download report** saves it through the browser as `<pair>__report.html`. **Save report to folder** writes it straight to the folder in the box beside it - `<COMPARE_OUT_DIR>/<pair>__<run_id>` when the variable is set, else a folder of that name next to file A or under your Downloads folder - and prints the path: the reliable route for big runs. The Downloads tab has the same **Save everything to folder** for the whole run folder at once.

![The Report tab](docs/app-report-tab.png)

It is one self-contained file - fonts from Google, everything else inline - so it can be mailed or dropped in a ticket and opens without the app; offline, the fonts fall back to the system's and the page is otherwise whole. It prints: a `@media print` block turns the ground white and keeps cards and rows in one piece. It is written for the person who did not run the comparison: what was compared, how, and where it went wrong, in that order.

| Section | What it says |
|---|---|
| Header | The two sides and the verdict in one line: rows matched, columns compared, rows that differ, one-sided rows. Under it a row of pills - each side with its file name or database kind, the key, the column count, and one anchor per section (`setup`, `counts`, `columns`, `by-key`, `rows`, `only-a`, `only-b`) so a reader can be sent to the line that matters - then the **verdict band**: *Identical*, *Small differences* or *Differences*, with the rule it was judged by spelled out beside it. |
| The setup | **Sources**: per side its name, file or `Kind · schema.table`, the connection name and the SQL for a database side, the path for a file given by path, the *Rows to read* cut, *Parquet snapshot*, rows read, when it was fetched and whether the cap was hit. **Key**: the columns; unique on both sides or how many rows share their key; the match rate; and, when Auto chose it, its reason, with the whole list of Auto's decisions folded under *How this was worked out*. Then rows paired (the key, *by hashing the compared columns*, or *by position*), the columns compared, how each typed or transformed column was read, **Values** (trim, empty is null, case - with the columns whose own Case overrides the switch - tolerance, null tokens, anything off the default in bold) and **Filters** as typed, with the side they applied to and the engine's SQL under them. Enough to re-run it by hand. |
| Row counts | Rows read on each side, rows after a filter when it changed the count, rows paired, rows only in Left, rows only in Right, rows that differ - as figures, with the verdict under them and a note when the key is not unique. |
| Every column | The same sheet as the Summary tab: every column from either file with its name on each side, role, how it was read, and matched / mismatched / match % (as a bar) for the compared ones, worst first. Columns present on one side only are listed in a note above the table so a missing or extra column is never silent. In hash mode the match figures become the number of distinct values present on one side only. Under the sheet, one card per differing column (worst first, up to 15) with the five most frequent **value pairs** behind its count - `Finance → Finance & Control · 112 · 33%` - and a warning on a column that differs on every matched row, which is nearly always two different fields paired by mistake. |
| Differences by key value | For rows that paired on the key but disagree: each key column's values with how many rows differ under each value and in which columns. Tells you *where* the differences cluster - one department, one date - before you look at what they are. If the key is not unique the section says so up front: rows sharing a key are paired in file order, and a difference under a repeated key may be two rows swapped rather than a changed value. Below it, every column across the differing rows: top values counted on each side. |
| Rows that differ | The paired rows, Left above Right, key columns first. **Left rows are black with cream text, Right rows are cream with black text**, and the cells that differ are picked out in the trouble colour on both. A legend sits above the table. Capped at *Rows to display* (at most 2,000) or 150,000 cells, whichever comes first - the subtitle says which; the CSVs hold everything. |
| Only in Left / Only in Right | The one-sided rows on the same black and cream - the paired columns under their common names, key columns included; a column present on one side only is not in them - each section opening with the top values per column, key columns first - the key values are the reason those rows found no partner. Capped the same way. |
| Footer | When the run happened, how long it took, the run id, the caps that applied, and a folded *Settings as JSON* - the `sources` and `settings` blocks of `summary.json`. |

The report opened on its own: the headline, the verdict with the rule it was judged by, and the setup - where each side came from, the key and why it was chosen, how every column was read.

![The report, Aurora theme](docs/report-aurora.png)

Its column sheet (every column from either file, its role, how it was read, matched / mismatched / match %) and its rows-that-differ section.

![The report's column sheet](docs/report-columns.png)

![The report's rows that differ](docs/report-rows.png)

The same report with `COMPARE_THEME=violet`.

![The report, violet theme](docs/report-violet.png)

**Download engine report** is the second button: the comparison engine's own side-by-side HTML (`<pair>__diff.html`) with its tabs, row search and *only columns with differences* toggle. Same numbers, different presentation; keep whichever the reader prefers.

## Outputs

Every run writes one folder with a fixed set of files, named after the two sides. The pair name is `<left>_compare_<right>`, each half the side's **Name** box from the sidebar slugged to letters, digits and underscores (anything else becomes one underscore) - else a database side's connection name, else `Left` / `Right`. The file names play no part. `HR` and `Payroll` give `HR_compare_Payroll`; both sides on the `SAMPLE` connection give `SAMPLE_compare_SAMPLE`; nothing named gives `Left_compare_Right`, and the sidebar reminds you under a file side that is still called Left or Right. Two sides with one name - both on the `SAMPLE` connection - are told apart by their tag wherever one is picked: the transform panel's Side, the filters' *Apply to* and the *Profile by bucket* radio offer `A · SAMPLE` and `B · SAMPLE`, and the sidebar says so under each. The run id is the start time, `YYYYMMDD-HHMMSS`, and the folder is `<COMPARE_WORK_DIR>/<pair>__<run_id>/` (the temp folder when the variable is not set). The Downloads tab hands each file out; the names are always:

```
HR_compare_Payroll__report.html      the house-style report (Download report)
HR_compare_Payroll__diff.html        the engine's own side-by-side report (Download engine report)
HR_compare_Payroll__cell_diffs.csv   one line per differing cell: the key columns (the row number in position
                                     mode; an extra occurrence column when a key value repeats), column_name,
                                     left_value, right_value
HR_compare_Payroll__left_only.csv    rows found only in Left: the paired columns under their common names, key
                                     columns included; one-sided columns are not in these files
HR_compare_Payroll__right_only.csv   rows found only in Right, the same way
HR_compare_Payroll__paired.csv       every paired row on one line: the key columns, then a_<column>, b_<column>
                                     for each compared column, in file order - a header only in hash mode
HR_compare_Payroll__columns.csv      the column sheet: column, name_a, name_b, role, read_as, matched_by,
                                     matched, mismatched, match_pct, values_only_a, values_only_b - matched_by is
                                     how the pair was made (name, similar name, guess - check, data, you, file),
                                     blank on a one-sided column
HR_compare_Payroll__profile.csv      when a profile ran: column, side, rows, nulls, null_pct, distinct,
                                     distinct_pct (of the filled rows), distinct_pct_rows (of all rows),
                                     top_value, top_pct, min, max, mean, avg_length, min_length, max_length
HR_compare_Payroll__summary.csv      one row: schema_version, run_id, started_at, pair, left, right, mode, keys,
                                     rows_left_read, rows_right_read, rows_left, rows_right, matched_rows,
                                     only_left, only_right, diff_rows, cell_diffs, duplicate_keys_left,
                                     duplicate_keys_right, status, tone, seconds, error - lists joined with |
HR_compare_Payroll__summary.json     the whole run for a script: app, engine, duckdb_version, run_id,
                                     started_at, seconds, pair, sources (per side: name, kind, database,
                                     connection name, origin, path, sql, fetched_at, cap, rows, cut, columns -
                                     never a URI or a password), settings (mode, keys, compare_columns, the
                                     specs with their steps and case, column_rules, filters, trim, tolerance,
                                     null_tokens...), result, verdict, notes (Auto's decisions) and files
                                     (every file above with its format, rows and bytes)
```

In key and position mode every file is present after every run - an empty table is written with its header - so a script can rely on the set; `summary.csv` and `summary.json` carry `schema_version` 1. Read `columns.csv` by header, not by position: `matched_by` was inserted after `read_as`. In hash mode the engine does not run, so there is no `cell_diffs` file and no engine report - rows either match whole or land in `left_only` / `right_only`, which carry every column, and `paired.csv` is a header only. The engine's CSVs are complete; only the tables on screen and in the report are capped by *Rows to display*.

**Formats.** Tables are CSV; the **Tables as** radio on the Downloads tab - *CSV*, *Parquet*, *both* - applies from the next run, and **Write Parquet copies for this run** adds them to the run on screen. `COMPARE_TABLE_FORMATS=csv,parquet` sets the default. With Parquet on, every table - cell differences, one-sided rows, paired rows, columns, profile - is also written as `.parquet` next to its CSV, typed and a fraction of the size, straight into DuckDB, pandas or a warehouse; `summary.json` lists both.

**The zip.** **Download all as zip** is the first button on the Downloads tab: `<pair>__<run_id>.zip`, the whole run folder, built once per run on the first visit and rebuilt when Parquet copies are added. Under it one button per file - *Cell differences*, *Rows only in HR*, *Rows only in Payroll*, *Paired rows*, *Columns*, *Profile*, *Summary*, *Settings and result*, *Report*, *Engine report* - and the Parquet copies when they exist.

The Downloads tab: the whole run as one zip, then every file of the run folder, the table format switch, and **Save everything to folder**.

![The Downloads tab](docs/app-downloads.png)

**Save everything to folder** copies the run folder to the folder in the box beside it. The default is `<COMPARE_OUT_DIR>/<pair>__<run_id>` when the variable is set - and then every save must stay under it, or it is refused with *Saves must stay under …* - otherwise a folder of that name next to file A, or under your Downloads folder for an upload; the next run's box defaults beside the last save. The report is written at run time, so the folder and the zip always hold it.

**The sweep.** At the first run of a server process the app removes run folders, zips, staged uploads, snapshots, fetches and key-search scratch files in the work folder older than `COMPARE_KEEP_HOURS` (24). Saved folders under `COMPARE_OUT_DIR` are never touched.

## Speed

Nothing heavy runs unless you press it.

- Loading sniffs the schema from a sample and takes one pass to snapshot and count. The 10-row preview stops after 10 rows.
- A plain rerun - editing the table, opening an expander - runs nothing beyond the two 10-row previews and the five-row transform preview.
- Key suggestion, key check, profile, type check and the comparison run only on their buttons. Auto runs them all, once, on purpose, and the key search reuses the profile it just made.
- A database fetch runs once, streams in 50,000-row batches into Parquet and is kept until the connection, the SQL or the cap changes; put the WHERE in the SQL so the database does the cutting, and give a capped query an ORDER BY.
- The comparison and the key search materialise each side as a DuckDB table under the common names, so the engine reads each file once. Numbers go through a fast 8-decimal decimal first and the wide one only when needed. The value pairs behind every column's count come from one DuckDB pass over the cell differences.
- A one-off measurement, 500,000 rows x 6 columns with the real engine: load 1.2 s a side, the comparison itself 7 s (both sides materialised, keyed join, cell differences written), the whole Auto run 16 s including Desbordante and the report. Treat it as an order of magnitude; there is no benchmark script in the repo. The sample pair above compares in about a second.
- For a very big file, cut it in *Rows to read* first - a date filter or a top N - and keep the Parquet snapshot on. `COMPARE_DUCKDB_MEMORY` caps DuckDB's memory when the machine is shared.
- Every long run ends with its elapsed time on the disc and in its Log entry, so the Log says which step of which run took the time.

## Settings

There is no settings file. Everything is either in the page or an environment variable read when the app starts:

| Variable | Default | What it does |
|---|---|---|
| `COMPARE_THEME` | `aurora` | `violet` switches the whole look - app, report, Streamlit's own widgets - to the violet variant. Anything else falls back to Aurora. |
| `COMPARE_APP_NAME` | `CrossHire Compare` | The name in the browser tab, the sidebar mark, the page eyebrow, the report header and `summary.json`. |
| `COMPARE_APP_TAGLINE` | `Tables, side by side` | The line under the name in the sidebar mark. |
| `COMPARE_WORK_DIR` | `<temp>/crosshire-compare` | Where staged uploads, Parquet snapshots, database fetches, run folders and zips go, and DuckDB's own temp directory. Created on first use; swept. |
| `COMPARE_OUT_DIR` | unset | When set, the root every save lands under: the save boxes default to `<COMPARE_OUT_DIR>/<pair>__<run_id>` and a folder outside it is refused. |
| `COMPARE_DATA_DIR` | unset | When set, the folders a *Path on disk* may come from, separated by the OS path separator (`;` on Windows, `:` elsewhere). A path outside them is refused: *Not under an allowed folder*. |
| `COMPARE_KEEP_HOURS` | `24` | How old a run folder, zip, upload, snapshot or fetch in the work folder must be before the sweep at server start removes it. |
| `COMPARE_TABLE_FORMATS` | `csv` | The default of the Downloads tab's *Tables as* radio: `csv`, `parquet` or `csv,parquet`. |
| `COMPARE_CONNECTIONS` | `~/.crosshire-compare/connections.json` | The connections file. |
| `COMPARE_CONN_<NAME>` | - | One connection each, as a URI (see [Connections](#connections)); named `<NAME>`, read-only in the manager, wins over a file connection of the same name. |
| `COMPARE_UPLOAD_MB` | `4096` | The upload limit under `python compare_app.py`. (`streamlit run` keeps Streamlit's 200 MB.) |
| `COMPARE_DUCKDB_MEMORY` | unset | DuckDB's `memory_limit` for every connection the app opens, e.g. `4GB`. |

```
set COMPARE_THEME=violet                              (Windows)
export COMPARE_APP_NAME="Employee Table Check"        (macOS / Linux)
```

Under Docker the image also sets Streamlit's own `STREAMLIT_SERVER_HEADLESS`, `STREAMLIT_SERVER_ADDRESS`, `STREAMLIT_SERVER_PORT`, `STREAMLIT_BROWSER_GATHER_USAGE_STATS` and `STREAMLIT_LOGGER_LEVEL`; `python compare_app.py` reads these and every other `STREAMLIT_*` variable the way `streamlit run` does, so they work outside Docker too. The radii, fonts and colours live in `tablecmp/theme.py`.

## Docker

```
docker build -t crosshire-compare .
docker run --rm -p 8501:8501 -v ./data:/data:ro -v ./out:/out --env-file .env crosshire-compare
```

Or `docker compose up` with the `docker-compose.yml` in the repo. The image is `python:3.12-slim` with the pinned `requirements.lock` installed, runs as the user `app` (uid 1000), starts `python compare_app.py` on port 8501, and answers a `HEALTHCHECK` on `/_stcore/health`. It sets `COMPARE_DATA_DIR=/data`, `COMPARE_OUT_DIR=/out` and `COMPARE_WORK_DIR=/work`, so inside the container a *Path on disk* must be under `/data`, every save lands under `/out`, and the scratch lives in `/work`.

Compose mounts four things: `./data` read-only at `/data` (the files to compare), `./out` at `/out` (saved runs), a named volume `connections` at `/home/app/.crosshire-compare` (the connections file survives a rebuild) and a named volume `work` at `/work`; and caps the container at 4 GB. Connections come from `.env` - copy `.env.example` to `.env` and put one `COMPARE_CONN_<NAME>=<uri>` per line (a DuckDB file under `./data` is `duckdb:////data/sample.duckdb`). `.env`, `connections*.json`, `*.duckdb`, `docs/`, `examples/` and `tests/` are in `.dockerignore`, so nothing private and nothing large is in the image.

## Theme

The look is the Crosshire apps theme - the same colour and type tokens the Crosshire web apps use, carried here as `--fs-*` CSS variables: a warm near-black ground, cream text, an amber accent, Fraunces for headlines, Inter for text and JetBrains Mono for figures, labels and code. **Aurora** is the default; **violet** is the second palette (`COMPARE_THEME=violet`), with Inter for the headlines as well.

Every colour and font is defined once, in `THEMES` in `tablecmp/theme.py`. `tokens_css()` turns the active palette into a `:root` block; the app's CSS, the report and `README.html` all start with it and refer only to the variables, so the three read as one thing and a palette change is one edit. Streamlit's own widgets (grids, menus, code, focus rings) take the same colours through `STREAMLIT_THEME`, which `compare_app.py` passes to Streamlit at start - no `.streamlit/config.toml`.

Left is black (page background, cream text) and Right is cream (cream background, black text) everywhere rows are shown side by side - in the app's grids, in the report, in the legend. Under the violet palette "cream" is a cool off-white; the legend keeps the word.

## The files

```
compare_app.py        entry point: bootstrap, theme, the page flow
csvdiff.py            the comparison engine (a black box to the app; runs on its own, see below)
README.html           how it works, in the house style - the same content as this file, for the app's users
README.md             this file
requirements.txt      streamlit, duckdb, pandas, pyarrow and the five database drivers (desbordante optional)
requirements.lock     the pinned set the Docker image installs
Dockerfile            python:3.12-slim, the lock file, user app, port 8501
docker-compose.yml    build, port, .env, the data / out / connections / work volumes
.env.example          one COMPARE_CONN_<NAME>=<uri> per line
docs/                 banner and screenshots; the design spec and plan under docs/superpowers/
examples/             hr_employees.csv, payroll_employees.csv, directory_employees.json, sample.duckdb,
                      mapping_hr_directory.json and make_sample.py, which regenerates the data
tests/                the pytest suite: units per module, and the app headless through AppTest
tablecmp/
  theme.py            colours, fonts, page CSS, STREAMLIT_THEME, status strip, cards - the only place to change the look
  sql.py              quoting, the scratch DuckDB connection (UTC, temp directory, memory limit)
  state.py            session defaults; what survives the switch between the Compare and Profiling pages
  sources.py          one side: a file or a fetched table, which rows to read; schema sniff, snapshot, preview; the work, out and data folders
  connections.py      named connections: the URI form, the home-folder store, COMPARE_CONN_* overrides, redaction
  databases.py        the six dialects, the read-only guard, connect, test, the streamed Parquet fetch
  values.py           transform steps, null folding, types, canonical text, registration, type check
  sniff.py            what a text column's values look like - the looks-like suggestions
  columns.py          the column table: pairing, normalisation, specs, roles and chips, mapping JSON, match by data
  keys.py             key uniqueness, overlap, reasons, Desbordante / DuckDB suggestion - for a pair or one table
  profile.py          statistics and value frequencies, of a pair or of one table; what the key search reads from them
  observe.py          what stands out in one table: duplicates, the key, dependencies, correlations, outliers, patterns, the notes
  compare.py          running a comparison (engine, position, hash), filters, and reading it back
  outputs.py          the run folder: pair name, verdict, summary / columns / profile writers, Parquet copies, zip, saves, sweep
  report.py           the HTML report
  auto.py             two sides in, the rest worked out
  ui_sidebar.py       the sidebar: loading files (A and B, or the one table P), the Auto panel
  ui_database.py      the Database branch of the sidebar and the Connections manager
  ui_columns.py       the column table and the setup card
  ui_transform.py     transform steps with the five-row preview
  ui_keys.py          Suggest keys, Check key, hash / position without a key
  ui_results.py       the verdict and the four result tabs
  ui_log.py           the run disc and the Log panel - every long run reports to one place
  ui_profile.py       the Profiling page: one table - keys, what stands out, statistics, outliers, patterns, dependencies, frequencies
```

The engine is a black box to the app: it receives two DuckDB tables named `src_a` and `src_b` with the common column names and canonical values already applied, and the app reads back its counts and its CSV outputs. Only the `ui_*.py` modules, `compare_app.py` and `state.py` touch Streamlit; everything else is plain Python over DuckDB and pandas, which is what makes the headless tests below possible.

## The engine on its own

`csvdiff.py` is a generic, config-driven CSV comparison powered by DuckDB, and it runs on its own from the command line - two CSV files, or two folders of them. Everything runs inside DuckDB, so files much larger than RAM are fine. It reports rows present only on the left or only on the right, cell-level differences for rows that matched, and schema differences.

```
python csvdiff.py file  a.csv b.csv --keys id --out out/
python csvdiff.py folder dir_a dir_b --out out/ --keys id
python csvdiff.py config diff_config.yaml --out out/
python csvdiff.py init-config dir_a dir_b -o diff_config.yaml
```

Matching strategies: `key` (join on one or more business-key columns, recommended), `row_number` (line 1 against line 1), `multiset` (order-independent set comparison with duplicate counts), `auto` (key if keys are configured, else row_number). Exit codes: 0 = identical, 1 = differences found, 2 = error.

## Development

Small, verified steps. Before handing over a change:

1. `python -m py_compile compare_app.py tablecmp/*.py` - everything must compile.
2. `python -m pytest tests -q` - the suite (223 tests, about two minutes): units for every module - the start-up settings, connections and URIs, the dialects and the read-only guard, the read-only switches passed to a stub driver, the fetch against a fake cursor and DuckDB end to end, the column table with its roles and chips, the looks-like sniff, keys and reasons for a pair and for one table, the profile of one table and what stands out in it, the outputs and the sweep, the report, the run disc and the Log - and the whole app headless through Streamlit's `AppTest`: the file flow and the database flow on the sample pair, asserting the counts in `docs/superpowers/plans/COUNTS.md` and grepping every output for the fake password, the Summary tab's Key block, and the Profiling page from a file and from the sample database. The database tests set `COMPARE_CONNECTIONS` to a temp file, so your own connections are never read or written.
3. To drive the app yourself, the same way the tests do - check the numbers, not just that it ran:

```python
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("compare_app.py", default_timeout=300); at.run()
for tag, path in (("A", "examples/hr_employees.csv"), ("B", "examples/payroll_employees.csv")):
    at.sidebar.radio(key=f"how_{tag}").set_value("Path on disk"); at.run()
    at.sidebar.text_input(key=f"pt_{tag}").set_value(path); at.run()
    at.sidebar.button(key=f"load_{tag}").click(); at.run()
at.sidebar.button(key="auto_btn").click(); at.run()
assert not at.exception
res = at.session_state["result"]["result"]          # the Outcome
assert (res.matched_rows, res.only_left, res.only_right, res.diff_rows, res.cell_diffs) == (2960, 40, 25, 2960, 3647)
```

Re-fetch widgets after every `at.run()`; elements go stale, and `at.session_state` has no `.get`. The column table is a data editor and cannot be edited headlessly - set `at.session_state["cmap"]` through `tablecmp.columns.apply_mapping_json` (or `set_steps`) and bump `at.session_state["map_rev"]` instead. Widget keys worth knowing: `page` (the Compare | Profiling radio), `nick_A` / `nick_B` (the Name boxes), `how_A` / `how_B`, `pt_A` / `pt_B`, `load_A` / `load_B`, `auto_btn`, `auto_profile`, `go` (Compare), `disp_rows`, `auto_rerun`, `opt_tol`, `sugg_btn`, `check_btn`, `do_profile`, `bucket_pick`, `out_fmt`, `save_report`, `save_all`, `log_clear`; for a database side `conn_A` / `conn_B`, `dbmode_A` / `dbmode_B`, `tbl_A` / `tbl_B`, `sql_A` / `sql_B`, `cap_A` / `cap_B`, `fetch_A` / `fetch_B`, `refetch_A` / `refetch_B`, `pw_A` / `pw_B`, `same_as_A`; on the Profiling page the same panel keys with `_P` (`nick_P`, `how_P`, `pt_P`, `load_P`, `conn_P`, `fetch_P`, ...) and `do_profile_P`, `dl_profile_P`, `save_profile_P`; in the manager `conn_pick`, `cf_kind`, `cf_name`, `cf_<field>`, `cf_save_pw`, `cf_timeout`, `test_conn`, `conn_save`, `conn_delete`. The Log is `at.session_state["log"]`, a list of entries with `at`, `kind`, `label`, `state`, `seconds` and `lines`, newest last; the last run's disc is the markdown with `class="runbox done"`. Download buttons are not in `at.button` - read them with `at.main.get("download_button")`. Under `streamlit run` the app does one `st.rerun()` on its first run to apply the theme; AppTest handles it. Set `COMPARE_THEME=violet` in the environment and run the same test to cover the second palette; set `COMPARE_CONN_SAMPLE=duckdb:///examples/sample.duckdb` and pick *Database* to cover the database route.

4. For anything visible, look at it: `streamlit run compare_app.py --server.headless true` and a Playwright screenshot, or the app in a browser. The screenshots in `docs/` were taken that way. `examples/make_sample.py` regenerates the sample data (seed 7) when the samples need to change - and then the counts in `COUNTS.md` and here do too.

Conventions the code keeps: identifiers go through `sql.ident`, literals through `sql.lit`, never f-strings into SQL; `st.*` only in the `ui_*.py` modules, `compare_app.py` and `state.py`; the app is read-only against databases and no credential reaches an output, a log or the screen; plain, human wording in the UI with captions that say why, and no emojis anywhere; every long run goes through `ui_log.running`, so it shows in the disc and lands in the Log - `st.status` is not used; tables shown to people use thousands separators, blank for not-applicable and a null glyph for a real null; `README.html` is updated when behaviour changes; `csvdiff.py` is not modified by the app's changes; no config file and no `.streamlit/` folder, ever; Streamlit does not hot-reload `tablecmp/`, so restart after editing it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every matched row differs on one column | Two different fields paired by mistake (*Matched by* says `guess - check`), or a value that converts on one side only. Check the column in the transform section and press *Check this column on all rows*; the report's value-pair card says the same. |
| Few rows match on the key | Key values spelled differently - case, padding, a date format. The summary lists sample unmatched values; *Check key* counts null keys. Give the key column a Type or a step. |
| A date column shows as text | Look at its *looks like* cell: add *to date* with that format on the side that needs it, or pick the Type and let the built-in spellings read it. Ambiguous day/month order needs the format spelled out. |
| Auto picked a key that is not unique | It says so, with the reason. Suggest keys shows the alternatives with their overlap; or tick a column in the table. |
| Where Auto's decisions went | Open the **Log** at the foot of the page: the *Auto decisions* entry lists them, one line each, newest run first; the report keeps them under *How this was worked out*. |
| The comparison failed | The message is shown, the disc says *could not finish* and the previous result stays on screen; the Log keeps the steps up to the failure. Usually a filter value or a custom expression DuckDB cannot read - the preview shows DuckDB's own message; a filter value that is not a date or not a number is refused before the run. |
| Header names look like data | Untick *First row is a header* and load again; give names under Advanced if you have them. |
| An upload over 200 MB is refused | Start the app with `python compare_app.py` (4 GB, or `COMPARE_UPLOAD_MB`) instead of `streamlit run`, or load the file by path. |
| *Not under an allowed folder (COMPARE_DATA_DIR)* | The server restricts paths on disk to the folders in `COMPARE_DATA_DIR` (`/data` under Docker). Put the file there, or upload it. |
| *Saves must stay under …* | `COMPARE_OUT_DIR` is set; every save goes under it. Use the default folder the box offers. |
| *SQL Server needs the pymssql package: pip install pymssql* | That driver is not installed. `pip install -r requirements.txt` installs all five; a single one installs on its own. |
| *Only SELECT or WITH statements are sent - this one starts with …* / *UPDATE is not allowed in a read-only statement* | The read-only guard. One statement, `SELECT` or `WITH`; a column that happens to be called `update` or `into` must be quoted. |
| *Type the password above first* | The connection was saved without its password (or came from the environment without one): type it in the sidebar box, once per session. |
| *The fetch failed - …* | The driver's own message, credentials blanked. Press *Test* in the Connections manager to see whether it is the connection or the statement. |
| *A cap without an ORDER BY can give the two sides different rows* | A warning, not a stop: add an ORDER BY to the query, or fetch everything. |
| *Stopped: under 1 GB free in the work folder* | The fetch or the run needs room: point `COMPARE_WORK_DIR` at a bigger disk, or lower the cap. |
| A change to a file in `tablecmp/` does nothing | Streamlit does not reload that folder; restart the app. |
| streamlit / duckdb too old | `pip install -U streamlit duckdb`. Streamlit 1.49+ and DuckDB 1.2+ are needed. |

## Related

- [crosshire.ch](https://crosshire.ch), [learn.crosshire.ch](https://learn.crosshire.ch), [blogs.crosshire.ch](https://blogs.crosshire.ch)
- Sibling repos: [crosshire-audit-snowflake-admin](https://github.com/darshanmeel/crosshire-audit-snowflake-admin) - who can actually read a table, transitively; [crosshire-audit-databricks-admin](https://github.com/darshanmeel/crosshire-audit-databricks-admin) - a query library over Databricks system tables.

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Darshan Singh / Crosshire.
