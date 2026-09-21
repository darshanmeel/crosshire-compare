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
    for i in range(0, len(picked), COLUMNS_A_STATEMENT):
        part = picked[i:i + COLUMNS_A_STATEMENT]
        rows = con.execute(" UNION ALL ".join(_decide_sql(c, n, opts) for c in part)).fetchall()
        for row in rows:
            out[row[0]] = _decide(row[1:])
    return out


def _decide_sql(col: str, n: int, opts: ReadOptions) -> str:
    """One query over the column's distinct values, every check as an aggregate, the
    column's name first."""
    tokens = ", ".join(lit(t.upper()) for t in opts.tokens) or lit("")
    words = ", ".join(lit(w) for w in BOOL_WORDS)
    fmts = list(FORMAT_PRESETS.values())
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
            "count(*) FILTER (WHERE try_cast(v AS TIMESTAMP) <> CAST(try_cast(v AS DATE) AS TIMESTAMP))"]
    for f in fmts:
        aggs += [f"count(try_strptime(v, {lit(f)}))",
                 f"arg_min(v, rn) FILTER (WHERE try_strptime(v, {lit(f)}) IS NOT NULL)"]
    return (f"SELECT {', '.join(aggs)} FROM (SELECT v, min(__rn) AS rn "
            f"FROM (SELECT trim({ident(col)}) AS v, __rn FROM vals) "
            f"WHERE v IS NOT NULL AND v <> '' AND upper(v) NOT IN ({tokens}) "
            f"GROUP BY v ORDER BY rn LIMIT {int(n)})")


def _decide(row: tuple) -> str:
    """The suggestion from one column's row of _decide_sql figures."""
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
    known = [(f, ex) for f, (cnt, ex) in zip(fmts, zip(row[8::2], row[9::2])) if ok(cnt)]
    if ok(iso):
        kind = "timestamp" if timed else "date"
        fmt, ex = known[0] if known else ("ISO, no format needed", iso_ex)
        return f"{kind} · {ex} → {fmt}"
    if known:
        fmt, ex = known[0]
        return f"{'timestamp' if has_time(fmt) else 'date'} · {ex} → {fmt}"
    return ""
