"""A boolean column's page: how its values split, the spellings it was written in, and its true
rate across the groups of a category column - read-only, counted in DuckDB on the loaded table."""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident, scratch
from ..values import register, typed_exprs
from .routes_profiling import _held, _spec, read_options
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

GROUPS = (2, 30)            # distinct values a text column needs to group a true rate by
RATES_TOP = 20              # groups listed, the highest rate first
SPELLINGS_TOP = 20          # spellings listed, the most used first
# pairs a flag is commonly written in; only those the engine reads as true / false are offered
PAIRS = (("True", "False"), ("true", "false"), ("TRUE", "FALSE"), ("Yes", "No"), ("yes", "no"),
         ("YES", "NO"), ("Y", "N"), ("y", "n"), ("1", "0"), ("T", "F"), ("t", "f"),
         ("On", "Off"), ("on", "off"))


def _probe(text: str) -> str:
    """The engine's own boolean read of a text value - NULL when it does not read as one."""
    return typed_exprs(text, "boolean")[0]


@lru_cache(maxsize=1)
def accepts() -> list[list[str]]:
    """The pairs the engine reads as a boolean, asked of DuckDB rather than written down."""
    con = scratch()
    try:
        vals = ", ".join(f"({i}, '{t}', '{f}')" for i, (t, f) in enumerate(PAIRS))
        got = con.execute(f"SELECT i, {_probe('t')}, {_probe('f')} FROM (VALUES {vals}) v(i, t, f) "
                          "ORDER BY i").fetchall()
    finally:
        con.close()
    return [list(PAIRS[i]) for i, t, f in got if t is True and f is False]


def _groups(prof: dict, column: str) -> list[str]:
    """Text columns with a few values, the fewest first - the most category-like leads; ties keep
    the table's order."""
    st = prof["stats"]
    lo, hi = GROUPS
    found = [(int(r["Distinct"]), i, str(r["Column"])) for i, (_, r) in enumerate(st.iterrows())
             if r["Type"] == "text" and str(r["Column"]) != column and lo <= int(r["Distinct"]) <= hi]
    return [name for _, _, name in sorted(found)]


@router.get("/flag")
def column_flag(column: str = Query(..., max_length=1000), by: str = Query("", max_length=1000),
                ws: Workspace = Depends(workspace)) -> dict:
    """A boolean column: true / false / null counts, the spellings it was written in (the text as
    read, before it became a boolean) and its true rate per value of a category column `by`
    (default the one with the fewest values) - [{group, n, true, rate}], rate a % of the filled values."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    groups = _groups(prof, column)
    if by and by not in groups:
        raise HTTPException(400, f"Group by one of {', '.join(groups) or 'no column'}.")
    by = by or (groups[0] if groups else "")
    opts = read_options(ws)
    raw = replace(spec, kind="text")              # the same column read as text: its spelling
    specs = [raw] + ([_spec(prof, by)] if by else [])
    con = scratch()
    try:
        register(con, P, "prof", specs, "A", opts)
        c = ident(column)
        b = _probe(c)
        spell = con.execute(f"SELECT {c} AS v, {b} AS b, count(*) AS n FROM prof GROUP BY ALL "
                            "ORDER BY n DESC, v").fetchall()
        rates = []
        if by:
            g = ident(by)
            rates = con.execute(
                f"SELECT CAST({g} AS VARCHAR) AS g, count(*) AS n, count(*) FILTER (WHERE {b}) AS t, "
                f"count({b}) AS f FROM prof GROUP BY 1").fetchall()
    finally:
        con.close()
    true = sum(int(n) for v, x, n in spell if x is True)
    false = sum(int(n) for v, x, n in spell if x is False)
    nulls = sum(int(n) for v, x, n in spell if v is None)
    seen = [{"value": v, "n": int(n), "reads": x} for v, x, n in spell if v is not None][:SPELLINGS_TOP]
    out = [{"group": gv, "n": int(n), "true": int(t), "rate": round(100 * t / f, 2) if f else 0.0}
           for gv, n, t, f in rates]
    out.sort(key=lambda r: (-r["rate"], -r["n"], str(r["group"])))
    return {"column": column, "true": true, "false": false, "nulls": nulls, "spellings": seen,
            "accepts": accepts(), "groups": groups, "by": by, "rates": out[:RATES_TOP]}
