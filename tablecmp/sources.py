"""One data file (CSV, JSON, Parquet, an Excel sheet), and which of its rows to read. DuckDB
streams it from disk; an Excel sheet is read once into Parquet first (excel.py)."""
from __future__ import annotations

import collections
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
    bad_rows: str = "set_aside"   # csv: rows with too few or too many fields - set_aside | keep (padded, extra columns) | first:N | join_numbers
    fixed_rows: int = 0                               # join_numbers - the rows with a split number or time joined
    fixed_guess: int = 0                              # join_numbers - those where the comma could have belonged to another number
    first_kept: int = 0                               # first:N - the fields each row was cut to
    first_cut_rows: int = 0                           # first:N - the rows that did not have exactly that many
    first_cut_by: dict[int, int] = field(default_factory=dict)   # their field count -> rows
    clean_path: str = ""    # csv: the rows that fit, when others were set aside - read in place of the file
    set_aside_valid: int = 0                          # the rows that fit, when the file was split
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
        if o.get("bad_rows") == "keep":
            bits.append("wrong-width rows kept")
        elif o.get("bad_rows") == "join_numbers":
            bits.append("split numbers joined")
        elif first_fields_of(o.get("bad_rows", "")):
            bits.append(f"first {self.first_kept or first_fields_of(o['bad_rows']):,} fields of each row")
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
BAD_ROWS = ("keep", "set_aside", "join_numbers")   # a CSV row with too few or too many fields
READ_DEFAULTS = {"sheet": "", "cell_range": "", "stop_at_blank": False, "skip_rows": 0,
                 "quote": '"', "bad_rows": "set_aside"}
SET_ASIDE_KEPT = 10_000                  # rows set aside kept to show and download; the count is always all
SNIFF_ROWS = 20_480                      # rows that say a header-less file's width


def first_fields_of(bad_rows: str) -> int:
    """N of a first:N choice - read each row as its first N fields; 0 for any other choice."""
    head, _, n = str(bad_rows).partition(":")
    return int(n) if head == "first" and n.isdecimal() and n.isascii() else 0


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
        if bad_rows not in BAD_ROWS and not first_fields_of(bad_rows):
            raise ValueError(f"Rows with too few or too many fields: {bad_rows!r} - use keep, set_aside, join_numbers or first:N.")
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
                  skip_rows: int = 0, quote: str = '"', bad_rows: str = "keep") -> str:
    """The quote and escape are always given: left to the sniffer, one quote that never closes
    makes it read the whole file unquoted, silently. Keep pads a short row and gives a long one
    extra columns; set_aside and first:N are strict - capture_set_aside has made every row fit."""
    keep = bad_rows == "keep"
    return (f"read_csv({lit(path)}, delim={lit(delimiter)}, quote={lit(quote)}, escape={lit(quote)}, "
            f"header={'true' if header else 'false'}, null_padding={'true' if keep else 'false'}"
            + (f", skip={int(skip_rows)}" if skip_rows and int(skip_rows) > 0 else "")
            + (", all_varchar=true" if all_varchar else "") + ")")


QUOTE_SAID = ("{file}: a quote never closes, so the rows cannot be told apart - fix the file, "
              "or pick another quote character under Advanced.")
TOO_WIDE_SAID = ("an unquoted delimiter does this, often a decimal comma, 12,33 in a comma-separated file. "
                 "Export the file again with another delimiter or with decimal points, or under Advanced join the split numbers or read the first fields of each row.")
WIDTH_SAID = ("{file}: line {line} has {found} fields where the rows before it have {expected}, so the columns "
              "cannot be lined up. An unquoted delimiter does this - often a decimal comma, 12,33 in a "
              "comma-separated file. Export the file again with another delimiter or with decimal points.")


def quote_problem(exc: Exception, file: str) -> str:
    """The plain sentence for a CSV whose quotes do not balance, then DuckDB's own text up to its
    list of fixes; the plain sentence for a row wider than the rows DuckDB sampled - '' for any
    other error."""
    text = str(exc)
    wide = re.search(r"CSV Error on Line: (\d+).*?Expected Number of Columns: (\d+) Found: (\d+)", text, re.S)
    if wide and "unterminated quote" not in text.lower():
        return WIDTH_SAID.format(file=Path(file).name, line=f"{int(wide[1]):,}", expected=wide[2], found=wide[3])
    if "Error when sniffing file" not in text and "unterminated quote" not in text.lower():
        return ""
    own = " ".join(text.split("Possible fixes")[0].split())
    return QUOTE_SAID.format(file=Path(file).name) + (f" {own}" if own else "")


class BadQuote(ValueError):
    """A CSV whose quotes do not balance - the message is quote_problem's."""


def csv_rows(f, delimiter: str, quote: str, skip: int = 0):
    """(first line, fields, raw text) of each row of an open CSV, skipped lines and blank lines
    apart - a quoted delimiter is no field, a quoted line end no new row. DuckDB's own count is
    not used: its ignore_errors keeps a row whose extra fields are empty, shifted. BadQuote's
    text says where when a quote never closes."""
    n, start, count, inq, buf = 0, 0, 1, False, []
    for line in f:
        n += 1
        if n <= skip:
            continue
        if not buf:
            start = n
        buf.append(line)
        pieces = line.split(quote) if quote else [line]
        for i, piece in enumerate(pieces):
            if (i % 2 == 0) != inq:                       # outside the quotes
                count += piece.count(delimiter)
        if (len(pieces) - 1) % 2:
            inq = not inq
        if not inq:
            raw = "".join(buf)
            if raw.strip("\r\n"):
                yield start, count, raw
            count, buf = 1, []
    if inq:
        raise BadQuote(f"Line {start:,} opens a quote that never closes.")


def _open_csv(path: str):
    # bytes that are not UTF-8 come back out as they went in
    return open(path, encoding="utf-8", errors="surrogateescape", newline="")


def row_width(path: str, delimiter: str, header: bool, skip: int, quote: str) -> int:
    """The fields a row should have: the header's, or without one the commonest among the first rows."""
    with _open_csv(path) as f:
        got: dict[int, int] = {}
        for i, (_, count, _raw) in enumerate(csv_rows(f, delimiter, quote, skip)):
            if header:
                return count
            got[count] = got.get(count, 0) + 1
            if i >= SNIFF_ROWS:
                break
    return max(got, key=got.get) if got else 0


def fields_of(text: str, delimiter: str, quote: str) -> list[str]:
    """One row's fields as they are written: a quoted delimiter is no field, quotes stay."""
    if not quote or quote not in text:
        return text.split(delimiter)
    out, now = [], ""
    for i, piece in enumerate(text.split(quote)):
        if i:
            now += quote
        if i % 2:
            now += piece
            continue
        first, *rest = piece.split(delimiter)
        now += first
        for p in rest:
            out.append(now)
            now = p
    return out + [now]


def first_fields(raw: str, delimiter: str, quote: str, n: int) -> str:
    """The row cut to its first n fields, a short one filled with empty ones; its line end stays."""
    text = raw.rstrip("\r\n")
    got = fields_of(text, delimiter, quote)[:n]
    return delimiter.join(got + [""] * (n - len(got))) + raw[len(text):]


def _capture_first(side: Side, n: int, clean: str, file: str) -> None:
    """first:N: every row goes on to `clean_path`, cut or filled to n fields, and those that did not
    have n are counted. n is at most the columns the side has."""
    o = side.read_opts
    by: dict[int, int] = {}
    valid, first = 0, True
    try:
        with _open_csv(side.csv_path) as f, open(clean, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
            for _, count, raw in csv_rows(f, side.delimiter, o["quote"], o["skip_rows"]):
                out.write(raw if count == n else first_fields(raw, side.delimiter, o["quote"], n))
                if not (first and side.header):
                    valid += 1
                    if count != n:
                        by[count] = by.get(count, 0) + 1
                first = False
    except BadQuote as exc:
        Path(clean).unlink(missing_ok=True)
        raise BadQuote(QUOTE_SAID.format(file=file) + f" {exc}") from exc
    side.clean_path, side.set_aside_valid = clean, valid
    side.first_kept, side.first_cut_rows, side.first_cut_by = n, sum(by.values()), dict(sorted(by.items()))
    _types_from_clean(side)


TIME_END = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}$")
WHOLE = re.compile(r"-?[0-9]+$")
JOIN_SAID = ("{file}: its text is not quoted, or its columns do not add up to the header, so split "
             "numbers cannot be told apart - use the first fields of each row, or export it again.")


def _runs(text: str, delimiter: str, quote: str) -> tuple[list[list[str]], list[str]]:
    """A row as the unquoted fields around each quoted one: (runs, quoted), with one run more than
    quoted. A time split at its fraction, 12:11:35,284, is joined already."""
    runs: list[list[str]] = [[]]
    quoted: list[str] = []
    for f in fields_of(text, delimiter, quote):
        if f.startswith(quote):
            quoted.append(f)
            runs.append([])
        elif runs[-1] and TIME_END.search(runs[-1][-1]) and f.isdecimal():
            runs[-1][-1] += "." + f
        else:
            runs[-1].append(f)
    return runs, quoted


def join_template(path: str, delimiter: str, header: bool, skip: int, quote: str, file: str = "") -> list[int]:
    """The unquoted columns between each two quoted ones. A number with a decimal comma only makes
    a run longer, so a run's shortest length that rows really have is its columns. BadQuote unless
    those and the quoted columns add up to the header, read on a sample and then on the whole file."""
    said = JOIN_SAID.format(file=file or Path(path).name)
    if not quote:
        raise BadQuote(said)
    want = row_width(path, delimiter, header, skip, quote) if header else 0
    for limit in (SNIFF_ROWS, None):
        seen: dict[int, list[collections.Counter]] = {}
        rows = 0
        with _open_csv(path) as f:
            for i, (_, _c, raw) in enumerate(csv_rows(f, delimiter, quote, skip)):
                if i == 0 and header:
                    continue
                runs, _q = _runs(raw.rstrip("\r\n"), delimiter, quote)
                gaps = seen.setdefault(len(runs), [collections.Counter() for _ in runs])
                for g, r in zip(gaps, runs):
                    g[len(r)] += 1
                rows += 1
                if limit and rows >= limit:
                    break
        if not seen:
            return []
        gaps = max(seen.values(), key=lambda g: sum(g[0].values()))
        enough = max(1, rows // 1000)              # a stray short row says nothing about the columns
        template = [min((n for n, c in g.items() if c >= enough), default=min(g)) for g in gaps]
        if not want or sum(template) + len(template) - 1 == want:
            return template
    raise BadQuote(said)


def join_row(raw: str, delimiter: str, quote: str, template: list[int]) -> tuple[str, bool] | None:
    """(the row with its split numbers joined, whether a comma could have belonged elsewhere); None
    when it cannot be placed. An extra comma has whole numbers on both sides; with more than one
    such pair the last wins - the columns of a run that hold decimals, prices, tend to be its last."""
    text = raw.rstrip("\r\n")
    runs, quoted = _runs(text, delimiter, quote)
    if len(runs) != len(template):
        return None
    guess = False
    for r, k in zip(runs, template):
        if len(r) < k:
            return None
        while len(r) > k:
            pairs = [i for i in range(len(r) - 1) if WHOLE.match(r[i]) and r[i + 1].isdecimal()]
            if not pairs:
                return None
            guess = guess or len(pairs) > 1
            r[pairs[-1]:pairs[-1] + 2] = [r[pairs[-1]] + "." + r[pairs[-1] + 1]]
    out = list(runs[0])
    for q, r in zip(quoted, runs[1:]):
        out += [q, *r]
    return delimiter.join(out) + raw[len(text):], guess


def _capture_join(side: Side, clean: str, path: str, file: str) -> None:
    """join_numbers: every row that can be placed goes on to `clean_path` with its split numbers
    joined; the others are set aside as a row of the wrong width is."""
    o = side.read_opts
    template = join_template(side.csv_path, side.delimiter, side.header, o["skip_rows"], o["quote"], file)
    by: dict[int, int] = {}
    kept: list[tuple[int, int, str]] = []
    valid, fixed, guessed, first = 0, 0, 0, True
    with _open_csv(side.csv_path) as f, open(clean, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
        for line, count, raw in csv_rows(f, side.delimiter, o["quote"], o["skip_rows"]):
            if first and side.header:
                out.write(raw)
                first = False
                continue
            first = False
            got = join_row(raw, side.delimiter, o["quote"], template)
            if got is None:
                by[count] = by.get(count, 0) + 1
                if len(kept) < SET_ASIDE_KEPT:
                    kept.append((line, count, raw.strip("\r\n").encode("utf-8", "replace").decode("utf-8")))
                continue
            out.write(got[0])
            valid += 1
            fixed += got[0] != raw
            guessed += got[1]
    side.clean_path, side.set_aside_valid, side.fixed_rows, side.fixed_guess = clean, valid, fixed, guessed
    if by:
        side.set_aside_rows, side.set_aside_fields = sum(by.values()), sum(template) + len(template) - 1
        side.set_aside_by = dict(sorted(by.items()))
        frame = pd.DataFrame(kept, columns=["line", "fields", "raw"])       # noqa: F841 - read by DuckDB by name
        scratch().execute(f"COPY (SELECT * FROM frame ORDER BY line) TO {lit(path)} (FORMAT PARQUET)")
        side.set_aside_path = path
    _types_from_clean(side)


def join_said(side: Side) -> str:
    """'344,605 rows had a split number or time joined - 282,182 where ...'; '' when none had."""
    n = side.fixed_rows
    if not n:
        return ""
    return (f"{n:,} row{'s' if n != 1 else ''} had a split number or time joined"
            + (f" - in {side.fixed_guess:,} the comma could have belonged to another number, and went to the last one" if side.fixed_guess else "")
            + ".")


def join_preview(path: str, delimiter: str, header: bool, skip: int, quote: str, names: list[str], show: int = 10) -> dict:
    """What join_numbers does to a sample of the file: the first rows joined, and how many could not be placed or were a choice."""
    template = join_template(path, delimiter, header, skip, quote)
    width = sum(template) + len(template) - 1
    by: dict[int, int] = {}
    rows, sampled, unplaced, guessed, first = [], 0, 0, 0, True
    with _open_csv(path) as f:
        for line, count, raw in csv_rows(f, delimiter, quote, skip):
            if first and header:
                first = False
                continue
            first = False
            sampled += 1
            by[count] = by.get(count, 0) + 1
            got = join_row(raw, delimiter, quote, template)
            if got is None:
                unplaced += 1
            else:
                guessed += got[1]
                if len(rows) < show:
                    vals = [_shown(v, quote) for v in fields_of(got[0].rstrip("\r\n"), delimiter, quote)]
                    rows.append({"line": line, "fields": count, "values": vals, "left_out": ""})
            if sampled >= SNIFF_ROWS:
                break
    return {"fields": width, "width": width, "columns": names[:width], "sampled": sampled, "unplaced": unplaced, "guessed": guessed,
            "by": [{"fields": k, "rows": v} for k, v in sorted(by.items())], "rows": rows}


def _shown(v: str, quote: str) -> str:
    bare = v[len(quote):-len(quote)] if quote and len(v) >= 2 * len(quote) and v.startswith(quote) and v.endswith(quote) else v
    return bare.encode("utf-8", "replace").decode("utf-8")


def first_fields_said(side: Side) -> str:
    """'344,605 rows read as their first 46 fields - 36,022 had 47, ...'; '' when none was cut."""
    n = side.first_cut_rows
    if not n:
        return ""
    bits = [f"{c:,} had {f:,}" for f, c in side.first_cut_by.items()]
    return (f"{n:,} row{'s' if n != 1 else ''} read as {'their' if n != 1 else 'its'} first {side.first_kept:,} fields - " + ", ".join(bits)
            + ". If a value holds the delimiter, the columns after it hold the wrong values - check them before trusting a difference.")


def first_fields_preview(path: str, delimiter: str, header: bool, skip: int, quote: str, n: int, names: list[str],
                         show: int = 10) -> dict:
    """What first:n does to a sample of the file: the field counts met, and the first rows cut."""
    width = row_width(path, delimiter, header, skip, quote)
    n = min(n or width, len(names)) if names else (n or width)
    by: dict[int, int] = {}
    rows, sampled, first = [], 0, True
    with _open_csv(path) as f:
        for line, count, raw in csv_rows(f, delimiter, quote, skip):
            if first and header:
                first = False
                continue
            first = False
            sampled += 1
            by[count] = by.get(count, 0) + 1
            if len(rows) < show:
                got = fields_of(raw.rstrip("\r\n"), delimiter, quote)
                rows.append({"line": line, "fields": count, "values": [_shown(v, quote) for v in (got + [""] * n)[:n]],
                             "left_out": delimiter.join(got[n:]).encode("utf-8", "replace").decode("utf-8")})
            if sampled >= SNIFF_ROWS:
                break
    return {"fields": n, "width": width, "columns": names[:n], "sampled": sampled,
            "by": [{"fields": k, "rows": v} for k, v in sorted(by.items())], "rows": rows}


def capture_set_aside(side: Side, path: str) -> None:
    """Read the whole file once and split it: the rows with the fields a row should have go on to
    `clean_path` (the same bytes, so they read as they would have) when any other row exists, the
    others are counted by field count on the side and the first SET_ASIDE_KEPT kept (line, fields,
    raw) in a Parquet file at `path`. BadQuote when a quote never closes."""
    side.set_aside_rows, side.set_aside_by, side.set_aside_fields, side.set_aside_path = 0, {}, 0, ""
    side.clean_path, side.set_aside_valid = "", 0
    side.first_kept, side.first_cut_rows, side.first_cut_by = 0, 0, {}
    side.fixed_rows, side.fixed_guess = 0, 0
    o = side.read_opts
    if side.kind != "csv" or o["bad_rows"] == "keep":
        return
    file = side.label or Path(side.csv_path).name
    clean = str(Path(path).with_suffix("")) + "_valid.csv"
    if o["bad_rows"] == "join_numbers":
        _capture_join(side, clean, path, file)
        return
    n = first_fields_of(o["bad_rows"])
    if n:
        _capture_first(side, min(n, len(side.source_columns) or n), clean, file)
        return
    by: dict[int, int] = {}
    kept: list[tuple[int, int, str]] = []
    want, valid, first = 0, 0, True
    try:
        with _open_csv(side.csv_path) as f, open(clean, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
            want = row_width(side.csv_path, side.delimiter, side.header, o["skip_rows"], o["quote"])
            for line, count, raw in csv_rows(f, side.delimiter, o["quote"], o["skip_rows"]):
                if count == want:
                    out.write(raw)
                    valid += 0 if first and side.header else 1
                else:
                    by[count] = by.get(count, 0) + 1
                    if len(kept) < SET_ASIDE_KEPT:
                        kept.append((line, count, raw.strip("\r\n").encode("utf-8", "replace").decode("utf-8")))
                first = False
    except BadQuote as exc:
        Path(clean).unlink(missing_ok=True)
        raise BadQuote(QUOTE_SAID.format(file=file) + f" {exc}") from exc
    side.set_aside_valid = valid
    if not by:
        Path(clean).unlink(missing_ok=True)
        return
    side.clean_path = clean
    side.set_aside_rows, side.set_aside_fields = sum(by.values()), want
    side.set_aside_by = dict(sorted(by.items()))
    con = scratch()
    frame = pd.DataFrame(kept, columns=["line", "fields", "raw"])       # noqa: F841 - read by DuckDB by name
    con.execute(f"COPY (SELECT * FROM frame ORDER BY line) TO {lit(path)} (FORMAT PARQUET)")
    side.set_aside_path = path
    _types_from_clean(side)


def _types_from_clean(side: Side) -> None:
    """The types the valid rows carry - the mixed file's sample read as text."""
    o = side.read_opts
    if not side.set_aside_valid:
        return
    try:
        found = _source_schema(side.clean_path, "csv", side.delimiter, side.header, file_stamp(side.clean_path),
                               tuple(sorted({**o, "bad_rows": "keep"}.items())))
    except Exception:           # the types are a nicety; the rows themselves read below or say why not
        return
    if len(found) == len(side.schema):
        side.schema = dict(zip(side.schema, found.values()))


def set_aside_said(side: Side) -> str:
    """'12 rows set aside - 7 with 49 fields, 5 with 51 (the header has 50)'; '' for none."""
    n = side.set_aside_rows
    if not n:
        return ""
    bits = [f"{c:,} with {f:,}" + ("" if i else " field" + ("s" if f != 1 else "")) if f >= 0
            else f"{c:,} other" for i, (f, c) in enumerate(side.set_aside_by.items())]
    whose = "the header has" if side.header else "the rest have"
    return (f"{n:,} row{'s' if n != 1 else ''} set aside - " + ", ".join(bits)
            + (f" ({whose} {side.set_aside_fields:,})" if side.set_aside_fields else "")
            + (f". {'No row fits' if not side.set_aside_valid else 'More rows left out than kept'} - " + TOO_WIDE_SAID
               if side.set_aside_valid < n else ""))


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
    o = dict(opts)
    first = first_fields_of(o.get("bad_rows", "")) if kind == "csv" else 0
    strict = kind == "csv" and (first or o.get("bad_rows") in ("set_aside", "join_numbers"))
    if strict:                                     # the sample may hold rows of another width: named by the header, cut to its width
        o["bad_rows"] = "keep"
    q = f"DESCRIBE SELECT * FROM {raw_expr(path, kind, delimiter, header, all_varchar=False, **o)}"
    got = {r[0]: r[1] for r in con.execute(q).fetchall()}
    if strict:
        want = row_width(path, delimiter, header, o.get("skip_rows", 0), o.get("quote", '"'))
        got = dict(list(got.items())[:want]) if want else got
        if first:
            got = dict(list(got.items())[:first])
    return got


def select_sql(side: Side) -> str:
    """The rows to read from the file, with the sidebar's filter, order and top-N."""
    sql = f"SELECT * FROM {read_expr(side.clean_path or side.csv_path, side.kind, side.delimiter, side.header, **side.read_opts)}"
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
    return read_expr(side.clean_path or side.csv_path, side.kind, side.delimiter, side.header, **side.read_opts)


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
