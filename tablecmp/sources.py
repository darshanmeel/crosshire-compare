"""One data file (CSV, JSON, Parquet, an Excel sheet), and which of its rows to read. DuckDB
streams it from disk; an Excel sheet is read once into Parquet first (excel.py)."""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .sql import ident, lit, scratch


@dataclass
class Side:
    name: str = ""          # what you call it - shown everywhere
    label: str = ""         # the file name
    csv_path: str = ""      # the file read: CSV / Parquet / JSON / Excel, or the Parquet a database fetch produced
    kind: str = "csv"       # csv | parquet | json | excel
    origin: str = ""        # where a database fetch came from, for display ("Snowflake · HR.EMPLOYEES")
    cache_path: str = ""    # Parquet snapshot of the rows read, when one was taken
    delimiter: str = ","
    header: bool = True
    sheet: str = ""         # excel: the sheet to read, "" = the first
    cell_range: str = ""    # excel: where the table sits - "B4", "B4:H500", "B4:H"; "" = from A1
    stop_at_blank: bool = False   # excel: the table ends at its first fully empty row
    skip_rows: int = 0      # csv: lines above the header to skip (a title, notes)
    quote: str = '"'        # csv: the quote character - '"', "'" or "" for none; the escape is the same
    bad_rows: str = "keep"  # csv: rows with too few or too many fields - keep (padded, extra columns) | set_aside
    set_aside_rows: int = 0                           # rows left out at Load (bad_rows set_aside), all of them
    set_aside_by: dict[int, int] = field(default_factory=dict)   # their field count -> rows
    set_aside_fields: int = 0                         # the fields a row should have
    set_aside_path: str = ""                          # Parquet of them (line, fields, raw), the first SET_ASIDE_KEPT
    where: str = ""                                   # on the file's own columns
    order_by: list[str] = field(default_factory=list)
    desc: bool = False
    limit: int = 0                                    # 0 = every row
    schema: dict[str, str] = field(default_factory=dict)      # column -> detected type
    source_columns: list[str] = field(default_factory=list)  # names as the file has them
    rows: int | None = None
    conn: str = ""          # connection name for a database side - never a URI or password
    database: str = ""      # its kind: snowflake | databricks | mssql | oracle | postgresql | duckdb
    query: str = ""         # the SQL that was fetched
    fetched_at: str = ""    # HH:MM:SS of the fetch
    cap: int = 0            # "fetch at most" that was applied (0 = all)
    capped: bool = False    # the fetch hit the cap
    folder: str = ""        # the folder connection a Path on disk side was picked from
    derived: dict[str, str] = field(default_factory=dict)   # added column -> DuckDB expression on the file's columns
    stamp: str = ""         # the file's size:mtime at Load (file_stamp), "" when not taken

    @property
    def loaded(self) -> bool:
        return bool(self.schema)

    @property
    def is_database(self) -> bool:
        return bool(self.conn)

    @property
    def stem(self) -> str:
        """The connection for a database, else the file's stem, slugged. Output files are named
        after the side names instead (outputs.pair_name)."""
        return slug(self.conn if self.is_database else Path(self.label).stem if self.label else "")

    @property
    def columns(self) -> list[str]:
        return list(self.schema)

    @property
    def source_of(self) -> dict[str, str]:
        """column name as shown -> the name the file actually uses."""
        return dict(zip(self.columns, self.source_columns or self.columns))

    @property
    def read_key(self) -> list:
        """Everything that decides which rows come out of this file."""
        return [self.csv_path, self.kind, self.cache_path, self.delimiter, self.header, self.where,
                self.order_by, self.desc, self.limit, self.conn, self.query, self.cap, self.fetched_at,
                sorted(self.derived.items()), sorted(self.read_opts.items())]

    @property
    def read_opts(self) -> dict:
        """Where in the file the table sits - only the options this kind of file takes."""
        return read_opts(self.kind, self.sheet, self.cell_range, self.stop_at_blank, self.skip_rows,
                         self.quote, self.bad_rows)

    @property
    def read_from(self) -> str:
        """Those options in words, for the loaded line: "sheet Sales · B4:H500"."""
        o = self.read_opts
        bits = []
        if o.get("sheet"):
            bits.append(f"sheet {o['sheet']}")
        if o.get("cell_range"):
            bits.append(o["cell_range"])
        if o.get("stop_at_blank"):
            bits.append("stops at the first blank row")
        if o.get("skip_rows"):
            n = o["skip_rows"]
            bits.append(f"skips {n:,} line" + ("s" if n != 1 else ""))
        if o.get("quote", '"') != '"':
            bits.append(f"quote {o['quote']}" if o["quote"] else "no quoting")
        if o.get("bad_rows") == "set_aside":
            bits.append("wrong-width rows set aside")
        return " · ".join(bits)

    @property
    def cut(self) -> str:
        bits = []
        if self.where.strip():
            bits.append("WHERE " + " ".join(self.where.split()))
        if self.order_by:
            bits.append("ORDER BY " + ", ".join(self.order_by) + (" DESC" if self.desc else ""))
        if self.limit:
            bits.append(f"TOP {self.limit:,}")
        return " · ".join(bits)


FILE_KINDS = {".csv": "csv", ".txt": "csv", ".tsv": "csv", ".dat": "csv",
              ".parquet": "parquet", ".pq": "parquet",
              ".json": "json", ".jsonl": "json", ".ndjson": "json",
              ".xlsx": "excel", ".xlsm": "excel", ".xls": "excel"}


QUOTES = ('"', "'", "")                 # a CSV's quote character: double, single, none
BAD_ROWS = ("keep", "set_aside")         # a CSV row with too few or too many fields
READ_DEFAULTS = {"sheet": "", "cell_range": "", "stop_at_blank": False, "skip_rows": 0,
                 "quote": '"', "bad_rows": "keep"}
SET_ASIDE_KEPT = 10_000                  # rows set aside kept to show and download; the count is always all


def read_opts(kind: str, sheet: str = "", cell_range: str = "", stop_at_blank: bool = False,
              skip_rows: int = 0, quote: str = '"', bad_rows: str = "keep") -> dict:
    """The read options that apply to a kind of file: the sheet, range and stop for Excel, the
    lines to skip, the quote and what becomes of a wrong-width row for a CSV, none for the
    rest - so an option left from another kind never changes a read or a cache key."""
    if kind == "excel":
        return {"sheet": (sheet or "").strip(),
                "cell_range": (cell_range or "").strip().upper().replace(" ", ""),
                "stop_at_blank": bool(stop_at_blank)}
    if kind == "csv":
        if quote not in QUOTES:
            raise ValueError(f"The quote character is {quote!r} - use \", ' or none.")
        if bad_rows not in BAD_ROWS:
            raise ValueError(f"Rows with too few or too many fields: {bad_rows!r} - use keep or set_aside.")
        return {"skip_rows": max(0, int(skip_rows or 0)), "quote": quote, "bad_rows": bad_rows}
    return {}


def kind_of(path: str) -> str:
    return FILE_KINDS.get(Path(path).suffix.lower(), "csv")


FOLDER_LIST_MAX = 2000


def folder_files(root: str, limit: int = FOLDER_LIST_MAX) -> list[str]:
    """The data files under a folder, as paths relative to it (with /), sorted - subfolders
    too, at most ``limit``: a folder of a million files lists its first ones, and a name is typed."""
    base = Path(root)
    if not base.is_dir():
        return []
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):              # not a hidden file, nor the ~$ lock file Excel keeps beside an open workbook
            if Path(f).suffix.lower() in FILE_KINDS and not f.startswith((".", "~$")):
                out.append(Path(dirpath, f).relative_to(base).as_posix())
                if len(out) >= limit:
                    return out
    return out


def in_folder(root: str, name: str) -> str:
    """A file named in a folder: the name as given when it is a full path, else under the folder."""
    p = Path(name.strip())
    return str(p if p.is_absolute() else Path(root) / p)


def read_csv_expr(path: str, delimiter: str, header: bool, all_varchar: bool = True,
                  skip_rows: int = 0, quote: str = '"', bad_rows: str = "keep", rejects: bool = False) -> str:
    """The quote and escape are always given: left to the sniffer, one quote that never closes
    makes it read the whole file unquoted, silently. Keep pads a short row and gives a long one
    extra columns; set_aside skips both (`rejects` lists them in the connection's reject_errors)."""
    keep = bad_rows != "set_aside"
    return (f"read_csv({lit(path)}, delim={lit(delimiter)}, quote={lit(quote)}, escape={lit(quote)}, "
            f"header={'true' if header else 'false'}, null_padding={'true' if keep else 'false'}"
            + ("" if keep else ", ignore_errors=true")
            + (", store_rejects=true" if rejects and not keep else "")
            + (f", skip={int(skip_rows)}" if skip_rows and int(skip_rows) > 0 else "")
            + (", all_varchar=true" if all_varchar else "") + ")")


QUOTE_SAID = ("{file}: a quote never closes, so the rows cannot be told apart - fix the file, "
              "or pick another quote character under Advanced.")


def quote_problem(exc: Exception, file: str) -> str:
    """The plain sentence for a CSV whose quotes do not balance, then DuckDB's own text up to its
    list of fixes - '' for any other error."""
    text = str(exc)
    if "Error when sniffing file" not in text and "unterminated quote" not in text.lower():
        return ""
    own = " ".join(text.split("Possible fixes")[0].split())
    return QUOTE_SAID.format(file=Path(file).name) + (f" {own}" if own else "")


class BadQuote(ValueError):
    """A CSV whose quotes do not balance - the message is quote_problem's."""


def capture_set_aside(side: Side, path: str) -> None:
    """Read the whole file once (before its WHERE and top N) with the rows of the wrong width set
    aside, and keep what DuckDB listed: the count by field count on the side, the first
    SET_ASIDE_KEPT rows (line, fields, raw) in a Parquet file at `path`. BadQuote when a quote
    never closes - DuckDB would set that row and the next aside, glued together."""
    side.set_aside_rows, side.set_aside_by, side.set_aside_fields, side.set_aside_path = 0, {}, 0, ""
    o = side.read_opts
    if side.kind != "csv" or o["bad_rows"] != "set_aside":
        return
    con = scratch()
    expr = read_csv_expr(side.csv_path, side.delimiter, side.header, True, o["skip_rows"], o["quote"], "set_aside",
                         rejects=True)
    con.execute(f"SELECT count(*) FROM {expr}").fetchall()     # fetched to the end: the rejects land as it finishes
    # one error per missing or extra field, so one row per line: the most fields DuckDB found on it
    con.execute(r"""CREATE TEMP TABLE aside AS SELECT line, any_value(trim(csv_line, chr(13) || chr(10))) AS raw,
        max(TRY_CAST(regexp_extract(error_message, 'Found: (\d+)', 1) AS INTEGER)) AS fields,
        max(TRY_CAST(regexp_extract(error_message, 'Expected Number of Columns: (\d+)', 1) AS INTEGER)) AS expected,
        bool_or(error_type = 'UNQUOTED VALUE') AS broken, any_value(error_message) AS error_message
        FROM reject_errors GROUP BY line""")
    broken = con.execute("SELECT line, error_message FROM aside WHERE broken ORDER BY line LIMIT 1").fetchone()
    if broken:
        raise BadQuote(QUOTE_SAID.format(file=side.label or Path(side.csv_path).name)
                       + f" Line {broken[0]}: {broken[1]}")
    n, fields = con.execute("SELECT count(*), coalesce(max(expected), 0) FROM aside").fetchone()
    if not n:
        return
    side.set_aside_rows, side.set_aside_fields = int(n), int(fields)
    side.set_aside_by = {int(f) if f is not None else -1: int(c) for f, c in con.execute(
        "SELECT fields, count(*) FROM aside GROUP BY fields ORDER BY fields NULLS LAST").fetchall()}
    con.execute(f"COPY (SELECT line, fields, raw FROM aside ORDER BY line LIMIT {SET_ASIDE_KEPT}) "
                f"TO {lit(path)} (FORMAT PARQUET)")
    side.set_aside_path = path


def set_aside_said(side: Side) -> str:
    """'12 rows set aside - 7 with 49 fields, 5 with 51 (the header has 50)'; '' for none."""
    n = side.set_aside_rows
    if not n:
        return ""
    bits = [f"{c:,} with {f:,}" + ("" if i else " field" + ("s" if f != 1 else "")) if f >= 0
            else f"{c:,} other" for i, (f, c) in enumerate(side.set_aside_by.items())]
    whose = "the header has" if side.header else "the rest have"
    return (f"{n:,} row{'s' if n != 1 else ''} set aside - " + ", ".join(bits)
            + (f" ({whose} {side.set_aside_fields:,})" if side.set_aside_fields else ""))


def set_aside_view(side: Side) -> dict | None:
    """The rows set aside at Load, counted: all of them, those kept to show, the width a row
    should have, the count by field count (fields None: DuckDB gave none) and the sentence."""
    if not side.set_aside_rows:
        return None
    return {"rows": side.set_aside_rows, "kept": min(side.set_aside_rows, SET_ASIDE_KEPT),
            "fields": side.set_aside_fields, "said": set_aside_said(side),
            "by": [{"fields": f if f >= 0 else None, "rows": n} for f, n in side.set_aside_by.items()]}


def set_aside_page(side: Side, page: int = 1, size: int = 25) -> dict:
    """One page of the rows set aside, in file order: line, fields, the raw line."""
    out = {**(set_aside_view(side) or {"rows": 0, "kept": 0, "fields": 0, "said": "", "by": []}),
           "page": page, "size": size, "lines": []}
    if side.set_aside_path and Path(side.set_aside_path).exists():
        got = scratch().execute(f"SELECT line, fields, raw FROM read_parquet({lit(side.set_aside_path)}) "
                                f"ORDER BY line LIMIT {int(size)} OFFSET {(int(page) - 1) * int(size)}").fetchall()
        out["lines"] = [{"line": int(ln), "fields": f, "raw": raw} for ln, f, raw in got]
    return out


def raw_expr(path: str, kind: str, delimiter: str = ",", header: bool = True,
             all_varchar: bool = True, *, sheet: str = "", cell_range: str = "",
             stop_at_blank: bool = False, skip_rows: int = 0, quote: str = '"',
             bad_rows: str = "keep") -> str:
    """A DuckDB table expression for the file as it is, typed columns and all. An Excel sheet
    is its Parquet copy (made on first use; ValueError for a bad sheet or range)."""
    if kind == "parquet":
        return f"read_parquet({lit(path)})"
    if kind == "json":
        return f"read_json_auto({lit(path)}, maximum_object_size=67108864)"
    if kind == "excel":
        from .excel import to_parquet
        return f"read_parquet({lit(to_parquet(path, sheet, cell_range, header, stop_at_blank))})"
    return read_csv_expr(path, delimiter, header, all_varchar, skip_rows, quote, bad_rows)


def text_expr(col: str, typ: str) -> str:
    """One column as text. A BLOB reads as hex. A column DuckDB types JSON (a JSON file
    mixing numbers and strings in one field) reads as the bare value - "hello" becomes
    hello like the CSV field, not the quoted JSON spelling a plain cast keeps."""
    t = str(typ).upper()
    if "BLOB" in t:
        return f"hex({ident(col)}) AS {ident(col)}"
    if t == "JSON":
        return f"json_extract_string({ident(col)}, '$') AS {ident(col)}"
    return f"{ident(col)}::VARCHAR AS {ident(col)}"


def read_expr(path: str, kind: str, delimiter: str = ",", header: bool = True, **opts) -> str:
    """The same file with every column as text - the one form the rest of the app reads,
    so a Parquet DATE, a JSON number and a CSV field all go through the same typing.
    `opts` are the read options (read_opts): sheet, cell_range, stop_at_blank, skip_rows,
    quote, bad_rows."""
    o = read_opts(kind, **opts)
    if kind == "csv":
        return read_csv_expr(path, delimiter, header, all_varchar=True, skip_rows=o["skip_rows"],
                             quote=o["quote"], bad_rows=o["bad_rows"])
    if kind == "excel":                           # every column is text already
        return raw_expr(path, kind, delimiter, header, **o)
    cols = source_schema(path, kind, delimiter, header, file_stamp(path))
    sel = ", ".join(text_expr(c, t) for c, t in cols.items()) or "*"
    return f"(SELECT {sel} FROM {raw_expr(path, kind, delimiter, header)})"


def file_stamp(path: str) -> str:
    try:
        s = Path(path).stat()
        return f"{s.st_size}:{s.st_mtime_ns}"
    except OSError:
        return ""


def source_schema(path: str, kind: str, delimiter: str, header: bool, stamp: str = "",
                  sheet: str = "", cell_range: str = "", stop_at_blank: bool = False,
                  skip_rows: int = 0, quote: str = '"', bad_rows: str = "keep") -> dict[str, str]:
    """Column names and the types the file itself carries (or DuckDB sniffs for a CSV) -
    cheap on a big file, DuckDB reads only what it needs to know the shape. The read options
    that do not apply to the kind are dropped, so they never split the cache. ValueError for
    an Excel sheet or range that is not there."""
    o = read_opts(kind, sheet, cell_range, stop_at_blank, skip_rows, quote, bad_rows)
    return dict(_source_schema(path, kind, delimiter, header, stamp, tuple(sorted(o.items()))))


@lru_cache(maxsize=64)
def _source_schema(path: str, kind: str, delimiter: str, header: bool, stamp: str,
                   opts: tuple) -> dict[str, str]:
    con = scratch()
    q = f"DESCRIBE SELECT * FROM {raw_expr(path, kind, delimiter, header, all_varchar=False, **dict(opts))}"
    return {r[0]: r[1] for r in con.execute(q).fetchall()}


def select_sql(side: Side) -> str:
    """The rows to read from the file, with the sidebar's filter, order and top-N."""
    sql = f"SELECT * FROM {read_expr(side.csv_path, side.kind, side.delimiter, side.header, **side.read_opts)}"
    if side.where.strip():
        sql += f" WHERE {side.where.strip()}"
    if side.order_by:
        sql += " ORDER BY " + ", ".join(
            f"{ident(c)} {'DESC' if side.desc else 'ASC'}" for c in side.order_by)
    if side.limit:
        sql += f" LIMIT {int(side.limit)}"
    return sql


def base_expr(side: Side) -> str:
    """The rows as the file gives them: the Parquet snapshot, or the CSV with the cut."""
    if side.cache_path:
        return f"read_parquet({lit(side.cache_path)})"
    return f"({select_sql(side)})"


def source_expr(side: Side) -> str:
    """What every query reads from: the file's rows, and the columns added to them."""
    if not side.derived:
        return base_expr(side)
    extra = ", ".join(f"({e}) AS {ident(n)}" for n, e in side.derived.items())
    return f"(SELECT *, {extra} FROM {base_expr(side)})"


def derived_type(side: Side, expr: str) -> str:
    """The type `expr` gives on this side's rows - duckdb.Error when it does not read there."""
    q = f"DESCRIBE SELECT ({expr}) AS v FROM {base_expr(side)}"
    con = scratch()
    got = con.execute(q).fetchall()[0][1]
    con.execute(f"SELECT count(({expr})) FROM (SELECT * FROM {base_expr(side)} LIMIT 1000)").fetchone()
    return got


def add_derived(side: Side, name: str, expr: str) -> None:
    """`name` = `expr` joins the side's columns, last. duckdb.Error when it does not read."""
    typ = derived_type(side, expr)
    side.derived[name] = expr
    side.schema[name] = typ
    side.source_columns = [*(side.source_columns or list(side.schema)[:-1]), name]


def drop_derived(side: Side, name: str) -> None:
    side.derived.pop(name, None)
    side.source_columns = [c for c in (side.source_columns or side.columns) if c != name]
    side.schema.pop(name, None)


def snapshot(side: Side, path: str) -> None:
    """Read the CSV once with its cut and keep the rows as Parquet."""
    con = scratch(ordered=True)
    con.execute(f"COPY ({select_sql(side)}) TO {lit(path)} (FORMAT PARQUET)")
    side.cache_path = path


class FileChanged(Exception):
    """The side's file is gone or was saved again after Load - what it holds can no longer be read again."""


def whole_expr(side: Side) -> str:
    """The side's rows before its WHERE, order and top N, under the file's own column names: the
    snapshot when there was no cut to take, else the file read again - for a database side that
    is the fetched Parquet, never the database. FileChanged when the file is not the one loaded."""
    if side.cache_path and not side.where.strip() and not side.limit:
        return f"read_parquet({lit(side.cache_path)})"
    now = file_stamp(side.csv_path)
    if not now or (side.stamp and now != side.stamp):
        raise FileChanged(side.csv_path)
    return read_expr(side.csv_path, side.kind, side.delimiter, side.header, **side.read_opts)


def column_values(side: Side, column: str, search: str = "", limit: int = 200) -> dict:
    """A column's distinct values (as text, null kept) over the whole side, the most frequent
    first, then by value. `search` keeps those containing it, any case, taken literally.
    KeyError for a column the file does not have, an added column included (a shown name is
    mapped to the file's)."""
    src = column if column in side.source_columns else side.source_of.get(column)
    if src is None or src in side.derived or src not in (side.source_columns or side.columns):
        raise KeyError(column)
    frm = whole_expr(side)
    con = scratch()
    rows = int(con.execute(f"SELECT count(*) FROM {frm}").fetchone()[0])
    cond, args = ("WHERE contains(lower(v), lower(?))", [search]) if search else ("", [])
    got = con.execute(f"SELECT v, count(*) AS n, count(*) OVER () AS groups "
                      f"FROM (SELECT {ident(src)}::VARCHAR AS v FROM {frm}) {cond} "
                      f"GROUP BY v ORDER BY n DESC, v ASC NULLS LAST LIMIT {int(limit)}", args).fetchall()
    distinct = int(got[0][2]) if got else 0
    return {"column": column, "rows": rows, "distinct": distinct,
            "values": [{"value": v, "n": int(n)} for v, n, _ in got], "more": distinct > len(got)}


def row_count(side: Side) -> int:
    return int(scratch().execute(f"SELECT count(*) FROM {source_expr(side)}").fetchone()[0])


def preview_rows(side: Side, n: int = 10) -> pd.DataFrame:
    """The first n rows as the file has them - cheap, DuckDB stops after n."""
    df = scratch(ordered=True).execute(f"SELECT * FROM {source_expr(side)} LIMIT {int(n)}").fetchdf()
    back = {raw: shown for shown, raw in side.source_of.items()}
    return df.rename(columns=back)


def quick_clause(col: str, op: str, value: str, values: list[str] | None = None) -> str:
    """One condition from the sidebar's column / condition / value pickers. `values` are values
    picked from the column's own, taken exactly as they are (a comma or a quote in one is fine):
    all of them for "in", ahead of what is typed; the first one in place of the typed text otherwise."""
    c, v = ident(col), value.strip()
    picked = list(values or [])
    if op == "is null":
        return f"{c} IS NULL"
    if op == "is not null":
        return f"{c} IS NOT NULL"
    if op.startswith("in"):
        items = list(dict.fromkeys(picked + [x.strip() for x in v.split(",") if x.strip()]))
        return f"{c} IN ({', '.join(lit(x) for x in items) or lit('')})"
    if picked:
        v = picked[0]
    if op == "contains":
        return f"{c} ILIKE {lit('%' + v + '%')}"
    if op == "starts with":
        return f"{c} ILIKE {lit(v + '%')}"
    if op in (">", ">=", "<", "<=") and re.fullmatch(r"[-+]?\d+(\.\d+)?", v):
        return f"try_cast({c} AS DOUBLE) {op} {v}"      # a number: compare as one
    return f"{c} {op} {lit(v)}"


AUTO_NAME = re.compile(r"^column\d+$", re.I)


def apply_names(schema: dict[str, str], names: list[str]) -> dict[str, str]:
    """Rename columns by position, for a file whose header is wrong or short."""
    types = list(schema.values())
    out, seen = {}, {}
    for i, t in enumerate(types):
        base = names[i].strip() if i < len(names) and names[i].strip() else list(schema)[i]
        n = seen.get(base, 0) + 1
        seen[base] = n
        out[base if n == 1 else f"{base}_{n}"] = t
    return out


def short_header(schema: dict[str, str]) -> int:
    """How many trailing columns the header row failed to name."""
    return sum(1 for c in schema if AUTO_NAME.match(str(c)))


def looks_headerless(schema: dict[str, str]) -> bool:
    """Header names that are really a data row: numbers, dates, duplicate stems."""
    names = list(schema)
    if not names:
        return False

    def datalike(n: str) -> bool:
        n = n.strip()
        if re.fullmatch(r"[-+]?\d[\d,.]*", n):
            return True
        if re.match(r"^\d{4}-\d{2}-\d{2}", n):
            return True
        return bool(re.fullmatch(r".*_\d+", n)) and n[0].isdigit()
    return sum(datalike(n) for n in names) >= max(2, len(names) // 4)


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
    """The folders a 'Path on disk' may come from: COMPARE_DATA_DIR split on os.pathsep, or none."""
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
