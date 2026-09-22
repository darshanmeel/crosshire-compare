"""What the values in a text column look like: a type suggestion per column, per side.

The column table shows it next to the detected type and never applies it - the
Type stays what the user set. A column DuckDB already typed (DATE, DOUBLE,
BOOLEAN...) gets no suggestion: the detected cell says it.
"""
from __future__ import annotations

import duckdb

from .sources import Side, source_expr
from .sql import COLUMNS_A_STATEMENT, ident, lit, scratch
from .values import DATE_TYPES, FORMAT_PRESETS, NUMERIC_TYPES, ReadOptions, raw_text

SAMPLE_ROWS = 50_000        # the rows the distinct values are taken from
SHARE = 0.98                # of the values that must convert
BOOL_WORDS = ("true", "false", "t", "f", "yes", "no", "y", "n")
TEXT_MARKS = ("VARCHAR", "CHAR", "TEXT", "STRING", "JSON")
TYPED_MARKS = NUMERIC_TYPES + DATE_TYPES + ("BOOL", "TIME", "BLOB", "UUID", "INTERVAL",
                                            "STRUCT", "LIST", "MAP", "[]", "UNION")


def text_like(typ: str) -> bool:
    """A detected type that says nothing about the values: text, JSON, or unknown."""
    t = str(typ).upper()
    if not t or any(m in t for m in TEXT_MARKS):
        return True
    return not any(m in t for m in TYPED_MARKS)


def has_time(fmt: str) -> bool:
    return any(m in fmt for m in ("%H", "%I", "%M", "%S", "%p"))


def looks_like(side: Side, cols: list[str], n: int = 2000,
               opts: ReadOptions | None = None) -> dict[str, str]:
    """{column: suggestion} for each column: 'boolean · Y/N', 'number',
    'number · 12,686.95 has thousands separators', 'date · 06-Nov-2019 → %d-%b-%Y',
    'timestamp · ...' - or '' when the values are plain text, the column is empty,
    or DuckDB already typed it.

    Up to n distinct non-null trimmed values from the first SAMPLE_ROWS rows, null
    tokens and empty strings skipped; the sample is read once, then one query per
    column decides in this order: boolean, number, date or timestamp - the columns'
    queries run a few at a time as one statement (COLUMNS_A_STATEMENT branches), so a
    wide table's are decided in parallel and not one after the other.

    Two passes: the first asks the cheap questions of every column - boolean, number,
    ISO timestamp, and whether any known spelling reads its values at all (one
    try_strptime over the whole list) - and only a column that pass calls a date goes
    through the second, which tries the spellings one at a time to name the format and
    its example. A wide table is mostly text and numbers, and none of those reach the
    second pass: it is the one that costs, 17 spellings x 2 aggregates a column.
    """
    opts = opts or ReadOptions()
    out = {c: "" for c in cols}
    picked = [c for c in cols if text_like(side.schema.get(c, ""))]
    if not picked:
        return out
    con = scratch(ordered=True)
    sel = ", ".join(f"{raw_text(side, c)} AS {ident(c)}" for c in picked)
    con.execute(f"CREATE TEMP TABLE vals AS SELECT row_number() OVER () AS __rn, {sel} "
                f"FROM (SELECT * FROM {source_expr(side)} LIMIT {SAMPLE_ROWS})")
    base: dict[str, tuple] = {}
    for i in range(0, len(picked), COLUMNS_A_STATEMENT):
        part = picked[i:i + COLUMNS_A_STATEMENT]
        rows = con.execute(" UNION ALL ".join(_decide_sql(c, n, opts) for c in part)).fetchall()
        for row in rows:
            base[row[0]] = row[1:]
    datey = [c for c in picked if _wants_formats(base.get(c))]
    spellings: dict[str, tuple] = {}
    for i in range(0, len(datey), COLUMNS_A_STATEMENT):
        part = datey[i:i + COLUMNS_A_STATEMENT]
        rows = con.execute(" UNION ALL ".join(_formats_sql(c, n, opts) for c in part)).fetchall()
        for row in rows:
            spellings[row[0]] = row[1:]
    for c in picked:
        out[c] = _decide(base[c], spellings.get(c)) if c in base else ""
    return out


def _values_sql(col: str, n: int, opts: ReadOptions) -> str:
    """The column's distinct values, first seen first - what both passes measure."""
    tokens = ", ".join(lit(t.upper()) for t in opts.tokens) or lit("")
    return (f"FROM (SELECT v, min(__rn) AS rn "
            f"FROM (SELECT trim({ident(col)}) AS v, __rn FROM vals) "
            f"WHERE v IS NOT NULL AND v <> '' AND upper(v) NOT IN ({tokens}) "
            f"GROUP BY v ORDER BY rn LIMIT {int(n)})")


def _formats_sql(col: str, n: int, opts: ReadOptions) -> str:
    """The second pass: each known spelling on its own - how many values it reads and the
    first value it reads - the column's name first."""
    aggs = [f"{lit(col)} AS col"]
    for f in FORMAT_PRESETS.values():
        aggs += [f"count(try_strptime(v, {lit(f)}))",
                 f"arg_min(v, rn) FILTER (WHERE try_strptime(v, {lit(f)}) IS NOT NULL)"]
    return f"SELECT {', '.join(aggs)} " + _values_sql(col, n, opts)


def _wants_formats(row: tuple | None) -> bool:
    """Whether a column goes through the second pass: not a boolean, not a number, and
    either ISO timestamps or some known spelling reads it - no single spelling can read
    more values than the whole list did, so a column the list could not read has no
    format to find."""
    if not row:
        return False
    total, bools, _seen, nums, _comma, iso, _ex, _timed, anydate = row
    if not total or bools == total or nums / total >= SHARE:
        return False
    return iso / total >= SHARE or anydate / total >= SHARE


def _decide_sql(col: str, n: int, opts: ReadOptions) -> str:
    """The first pass: one query over the column's distinct values, the cheap checks as
    aggregates, the column's name first."""
    words = ", ".join(lit(w) for w in BOOL_WORDS)
    fl = "[" + ", ".join(lit(f) for f in FORMAT_PRESETS.values()) + "]"
    aggs = [f"{lit(col)} AS col", "count(*)",
            f"count(*) FILTER (WHERE lower(v) IN ({words}))",
            f"list(v ORDER BY rn) FILTER (WHERE lower(v) IN ({words}))",
            "count(try_cast(replace(v, ',', '') AS DOUBLE))",
            "arg_min(v, rn) FILTER (WHERE regexp_matches(v, '[0-9],[0-9]'))",
            "count(try_cast(v AS TIMESTAMP))",
            "arg_min(v, rn) FILTER (WHERE try_cast(v AS TIMESTAMP) IS NOT NULL)",
            # a time of day: the timestamp is past its own date. Not CAST(... AS TIME), which
            # throws on the infinite timestamp 'inf' / 'Infinity' cast to (and DuckDB does not
            # short-circuit an isfinite() guard in front of it)
            "count(*) FILTER (WHERE try_cast(v AS TIMESTAMP) <> CAST(try_cast(v AS DATE) AS TIMESTAMP))",
            # any known spelling at all, the whole list in one go: what sends a column to
            # the second pass, where the spellings are tried one at a time
            f"count(try_strptime(v, {fl}))"]
    return f"SELECT {', '.join(aggs)} " + _values_sql(col, n, opts)


def _decide(row: tuple, spellings: tuple | None = None) -> str:
    """The suggestion from one column's row of _decide_sql figures, with its row of
    _formats_sql figures when it went through the second pass."""
    fmts = list(FORMAT_PRESETS.values())
    total, bools, bool_seen, nums, comma, iso, iso_ex, timed = row[:8]
    if not total:
        return ""

    def ok(count) -> bool:
        return count / total >= SHARE

    if bools == total:
        seen: dict[str, str] = {}
        for w in bool_seen:
            seen.setdefault(w.lower(), w)         # the first spelling of each word
        return "boolean · " + "/".join(seen[w] for w in BOOL_WORDS if w in seen)
    if ok(nums):
        return "number" if comma is None else f"number · {comma} has thousands separators"
    known = ([(f, ex) for f, (cnt, ex) in zip(fmts, zip(spellings[0::2], spellings[1::2])) if ok(cnt)]
             if spellings else [])
    if ok(iso):
        kind = "timestamp" if timed else "date"
        fmt, ex = known[0] if known else ("ISO, no format needed", iso_ex)
        return f"{kind} · {ex} → {fmt}"
    if known:
        fmt, ex = known[0]
        return f"{'timestamp' if has_time(fmt) else 'date'} · {ex} → {fmt}"
    return ""
