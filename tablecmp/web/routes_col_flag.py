"""A boolean column's page: how its values split, the spellings it was written in, and its true
rate across the groups of another column - read-only, counted in DuckDB on the loaded table.

The analysis is plain functions on a DuckDB connection and a relation name (flag_counts,
true_rates, flag_reads, group_options) so the Compare page can run them on its own rows; the
routes only register the profiled table as `prof` and call them."""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import profiling
from ..sql import ident, scratch
from ..values import ColSpec, register, typed_exprs
from .profile_held import memo
from .routes_profiling import _casts_held, _held, _spec, _value, read_options, read_when, reads_as
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

GROUPS = (2, 50)            # distinct values a column needs to group a true rate by as it is
BANDS = 5                   # a number column with more values is grouped into this many equal-count bands
SPELLINGS_TOP = 20          # spellings listed, the most used first
FLAG_DISTINCT = 26          # a text column with more distinct values is not checked as a boolean
# pairs a flag is commonly written in; only those the engine reads as true / false are offered
PAIRS = (("True", "False"), ("true", "false"), ("TRUE", "FALSE"), ("Yes", "No"), ("yes", "no"),
         ("YES", "NO"), ("Y", "N"), ("y", "n"), ("1", "0"), ("T", "F"), ("t", "f"),
         ("On", "Off"), ("on", "off"))


def probe(text: str) -> str:
    """The engine's own boolean read of a text value - NULL when it does not read as one."""
    return typed_exprs(text, "boolean")[0]


@lru_cache(maxsize=1)
def accepts() -> list[list[str]]:
    """The pairs the engine reads as a boolean, asked of DuckDB rather than written down."""
    con = scratch()
    try:
        vals = ", ".join(f"({i}, '{t}', '{f}')" for i, (t, f) in enumerate(PAIRS))
        got = con.execute(f"SELECT i, {probe('t')}, {probe('f')} FROM (VALUES {vals}) v(i, t, f) "
                          "ORDER BY i").fetchall()
    finally:
        con.close()
    return [list(PAIRS[i]) for i, t, f in got if t is True and f is False]


# --- analysis: (con, relation, column, ...) -> plain data ---------------------------------------

def flag_counts(con, rel: str, column: str) -> dict:
    """A column read as text, then as a boolean: {true, false, nulls, blanks, odd, spellings:
    [{value, n, reads}]} - reads true / false, or None for a value that is not a boolean; blanks
    are values of spaces only, odd the filled values that do not read as one."""
    c = ident(column)
    b = probe(c)
    spell = con.execute(f"SELECT {c} AS v, {b} AS b, count(*) AS n FROM {ident(rel)} GROUP BY ALL "
                        "ORDER BY n DESC, v").fetchall()
    true = sum(int(n) for v, x, n in spell if x is True)
    false = sum(int(n) for v, x, n in spell if x is False)
    nulls = sum(int(n) for v, x, n in spell if v is None)
    blanks = sum(int(n) for v, x, n in spell if v is not None and not str(v).strip())
    odd = sum(int(n) for v, x, n in spell if v is not None and str(v).strip() and x is None)
    seen = [{"value": v, "n": int(n), "reads": x} for v, x, n in spell if v is not None][:SPELLINGS_TOP]
    return {"true": true, "false": false, "nulls": nulls, "blanks": blanks, "odd": odd, "spellings": seen}


def true_rates(con, rel: str, column: str, by: str, how: str = "value") -> list[dict]:
    """The share of true among the filled flag values in each group of `by` - [{group, n, true,
    rate}], rate a % to two places. `by` is an SQL expression; how="value" groups by it as text
    (the highest rate first), "year" by it already reduced to a year (in year order), "band" into
    BANDS equal-count bands of the number (low to high, each with its lo and hi)."""
    b = probe(ident(column))
    src = ident(rel)
    if how == "band":
        got = con.execute(
            f"WITH x AS (SELECT {b} AS f, try_cast({by} AS DOUBLE) AS x FROM {src}), "
            f"k AS (SELECT f, x, CASE WHEN x IS NOT NULL THEN ntile({BANDS}) OVER "
            f"(PARTITION BY x IS NULL ORDER BY x) END AS k FROM x) "
            "SELECT k, min(x), max(x), count(*), count(*) FILTER (WHERE f), count(f) FROM k "
            "GROUP BY k ORDER BY k NULLS LAST").fetchall()
        return [{"group": None if k is None else f"{lo:g} - {hi:g}", "lo": lo, "hi": hi,
                 "n": int(n), "true": int(t), "rate": round(100 * t / f, 2) if f else 0.0}
                for k, lo, hi, n, t, f in got]
    got = con.execute(
        f"SELECT CAST({by} AS VARCHAR) AS g, count(*) AS n, count(*) FILTER (WHERE {b}) AS t, "
        f"count({b}) AS f FROM {src} GROUP BY 1").fetchall()
    out = [{"group": g, "n": int(n), "true": int(t), "rate": round(100 * t / f, 2) if f else 0.0}
           for g, n, t, f in got]
    if how == "year":
        out.sort(key=lambda r: (r["group"] is None, str(r["group"])))
    else:
        out.sort(key=lambda r: (-r["rate"], -r["n"], str(r["group"])))
    return out


def flag_reads(con, rel: str, columns: list[str], numbers: tuple[str, ...] = ()) -> list[dict]:
    """Columns whose every filled value reads as a boolean - [{column, filled, true, false}], one
    pass over the relation; a column with no filled value is left out. Those named in `numbers`
    are numbers, read as their text with a trailing .0 dropped (so 1 / 0 reads as a pair)."""
    if not columns:
        return []
    aggs = []
    for col in columns:
        c = ident(col)
        if col in numbers:
            c = f"regexp_replace(CAST({c} AS VARCHAR), '[.]0+$', '')"
        aggs += [f"count(nullif(trim({c}), ''))", f"count({probe(c)})",
                 f"count(*) FILTER (WHERE {probe(c)})"]
    got = con.execute(f"SELECT {', '.join(aggs)} FROM {ident(rel)}").fetchone()
    out = []
    for i, col in enumerate(columns):
        filled, reads, t = (int(x) for x in got[3 * i: 3 * i + 3])
        if filled and reads == filled:
            out.append({"column": col, "filled": filled, "true": t, "false": filled - t})
    return out


def group_options(stats: list[dict], column: str, when_of: dict[str, str] | None = None,
                  skip: frozenset[str] | set[str] = frozenset()) -> list[dict]:
    """The columns a true rate can be grouped by - [{column, how, distinct}]: any column with
    2-50 distinct values as it is (the fewest first, then the table's order), then by year a
    date, a timestamp or text read as one (`when_of` names those), then a number in bands - a
    number with every value different too (an amount), but not the columns in `skip` (the key)."""
    when_of = when_of or {}
    lo, hi = GROUPS
    plain, year, band = [], [], []
    for i, r in enumerate(stats):
        name, kind, d = str(r["Column"]), str(r["Type"]), _distinct(r)
        filled = _distinct({"Distinct": r.get("Rows")}) - _distinct({"Distinct": r.get("Nulls")})
        if name == column or name in skip:
            continue
        if lo <= d <= hi and not (filled > 0 and d >= filled):    # every value different: nothing to group
            plain.append((d, i, {"column": name, "how": "value", "distinct": d}))
        elif d > hi and (kind in ("date", "timestamp") or when_of.get(name)):
            year.append({"column": name, "how": "year", "distinct": d})
        elif d > hi and kind == "number":
            band.append({"column": name, "how": "band", "distinct": d})
    return [o for _, _, o in sorted(plain, key=lambda t: t[:2])] + year + band


def group_expr(spec: ColSpec, how: str, when: str = "", form: str = "") -> str:
    """The SQL a group option reads its column with: as it is, its year, or as a number."""
    c = ident(spec.canon)
    if how == "year":
        t = read_when(_value(spec), when, form) if when else f"try_cast({c} AS TIMESTAMP)"
        return f"CAST(year({t}) AS VARCHAR)"
    return c


# --- routes --------------------------------------------------------------------------------------

def _distinct(r: dict) -> int:
    d = r.get("Distinct")
    return int(d) if d == d and d is not None and d != "" else 0      # NaN != NaN


def _stats(prof: dict) -> list[dict]:
    """The profile's statistics rows, their Distinct a plain int."""
    return [{**r, "Distinct": _distinct(r)} for r in prof["stats"].to_dict("records")]


def _whens(ws: Workspace, prof: dict) -> dict[str, tuple[str, str]]:
    """Text and number columns that read as a date or a timestamp: {column: (kind, form)}."""
    out = {}
    for r in _casts_held(ws, prof)["columns"]:
        k = reads_as(r)
        if k:
            out[r["column"]] = (k, r[k].get("form", ""))
    return out


@router.get("/flag")
def column_flag(column: str = Query(..., max_length=1000), by: str = Query("", max_length=1000),
                how: str = Query("", max_length=10), ws: Workspace = Depends(workspace)) -> dict:
    """A column read as a boolean (typed boolean, or text whose values read as one): true /
    false / null counts, the spellings it was written in (the text as read, before it became a
    boolean), and its true rate per group of `by` - read as it is, by year or in number bands
    (`how`, default the first way `by` is offered) - by default the first of `groups`."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    stats = _stats(prof)
    whens = _whens(ws, prof) if any(r["Type"] in ("text", "number") and r["Distinct"] > GROUPS[1]
                                    for r in stats) else {}
    key = profiling.best_key(prof) or []
    groups = group_options(stats, column, {k: v[0] for k, v in whens.items()},
                           set(key) if len(key) == 1 else set())
    pick = (next((g for g in groups if g["column"] == by and (not how or g["how"] == how)), None) if by
            else groups[0] if groups else None)
    if by and pick is None:
        raise HTTPException(400, f"Group by one of {', '.join(g['column'] for g in groups) or 'no column'}.")
    opts = read_options(ws)
    raw = replace(spec, kind="text")              # the same column read as text: its spelling
    specs = [raw]
    if pick:
        by_spec = _spec(prof, pick["column"])
        specs.append(by_spec)

    def work() -> tuple[dict, list]:
        con = scratch()
        try:
            register(con, P, "prof", specs, "A", opts)
            counts = flag_counts(con, "prof", column)
            rates = []
            if pick:
                typed = by_spec.kind in ("date", "timestamp")
                when, form = ("", "") if typed else whens.get(pick["column"], ("", ""))
                rates = true_rates(con, "prof", column, group_expr(by_spec, pick["how"], when, form), pick["how"])
        finally:
            con.close()
        return counts, rates
    counts, rates = memo(ws, prof, ("flag", column, pick["column"] if pick else "", pick["how"] if pick else ""), work)
    return {"column": column, **counts, "accepts": accepts(), "groups": groups,
            "by": pick["column"] if pick else "", "how": pick["how"] if pick else "", "rates": rates}


@router.get("/flags")
def column_flags(ws: Workspace = Depends(workspace)) -> dict:
    """Text columns whose every filled value reads as a boolean (Y / N, True / False, 1 / 0 and
    the other pairs in `accepts`), and number columns of only 1 and 0 - so the page can offer to
    read them as one:
    {columns: [{column, filled, true, false}]}, worked out once per profile."""
    _, prof, _ = _held(ws)
    return memo(ws, prof, ("flags",), lambda: _flags(ws, prof))


def _flags(ws: Workspace, prof: dict) -> dict:
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    few = {str(r["Column"]) for r in _stats(prof)
           if (r["Type"] == "text" and 0 < r["Distinct"] <= FLAG_DISTINCT) or (r["Type"] == "number" and 0 < r["Distinct"] <= 2)}
    specs = [ColSpec(**s) for s in prof.get("specs", []) if s["canon"] in few and s["kind"] in ("text", "number")]
    cols = []
    if specs:
        con = scratch()
        try:
            register(con, P, "prof", specs, "A", read_options(ws))
            cols = flag_reads(con, "prof", [s.canon for s in specs],
                              tuple(s.canon for s in specs if s.kind == "number"))
        finally:
            con.close()
    return {"columns": cols}
