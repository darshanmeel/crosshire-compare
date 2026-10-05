"""The key column's page: GET /api/profiling/keycheck - what makes one column safe to match rows
on (unique, nulls, blanks, case and space variants, width) and how its ids are built (shapes, a
letters prefix, the number part, its gaps, the order in the file, the next id). Read-only: one
SELECT on the loaded table with its steps applied."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident, scratch
from .routes_profiling import _held, _spec, read_options
from .sides import side
from .workspace import Workspace, workspace
from ..values import register

router = APIRouter(prefix="/api/profiling")

SHAPES = 3
ID = "^([A-Za-z]*)([0-9]+)$"      # letters then digits, or digits alone: a number part to read


def keycheck(P, spec, opts) -> dict:
    c = ident(spec.canon)
    v = (f"regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '')" if spec.kind == "number"
         else f"CAST({c} AS VARCHAR)")
    shape = "regexp_replace(regexp_replace(v, '[A-Za-z]', 'A', 'g'), '[0-9]', '9', 'g')"
    # f is read once (materialized); every count and the order comes from one aggregate over it,
    # the shapes and the prefix from one GROUP BY each. regexp_extract gives '' when the value is
    # not letters then digits, so dig <> '' says the number part is there.
    sql = f"""
    WITH f AS MATERIALIZED (
        SELECT rn, v, regexp_extract(v, '{ID}', ['pre', 'dig']) AS m
        FROM (SELECT row_number() OVER () AS rn, {v} AS v FROM prof) WHERE v IS NOT NULL AND v <> ''),
    n AS (SELECT rn, v, m.pre AS pre, m.dig AS dig, try_cast(nullif(m.dig, '') AS HUGEINT) AS x FROM f),
    o AS (SELECT *, lag(x) OVER (ORDER BY rn) AS px, lag(v) OVER (ORDER BY rn) AS pv FROM n),
    c AS (SELECT *, CASE WHEN pv IS NULL THEN NULL WHEN x IS NOT NULL AND px IS NOT NULL THEN sign(x - px)
                         WHEN v > pv THEN 1 WHEN v < pv THEN -1 ELSE 0 END AS cmp FROM o),
    s AS (SELECT {shape} AS k, count(*) AS m, min(v) AS eg FROM f GROUP BY k ORDER BY m DESC, k LIMIT {SHAPES}),
    p AS (SELECT regexp_extract(v, '^[A-Za-z]+') AS k, count(*) AS m FROM f
          WHERE regexp_matches(v, '^[A-Za-z]') GROUP BY k ORDER BY m DESC, k LIMIT 1),
    a AS (SELECT count(*) AS filled, count(DISTINCT v) AS d, count(DISTINCT lower(v)) AS folded,
                 count(*) FILTER (WHERE v <> trim(v) OR v LIKE '% %') AS spaces,
                 min(length(v)) AS wmin, max(length(v)) AS wmax,
                 count(x) AS numbered, min(x) AS lo, max(x) AS hi, count(DISTINCT x) AS nd,
                 count(*) FILTER (WHERE dig LIKE '0%' AND length(dig) > 1) AS zeros,
                 arg_max(pre, x) AS pre, arg_max(length(dig), x) AS digits,
                 count(*) FILTER (WHERE cmp > 0) AS up, count(*) FILTER (WHERE cmp < 0) AS down FROM c)
    SELECT (SELECT count(*) FROM prof), (SELECT count(*) FILTER (WHERE {v} IS NULL) FROM prof),
           (SELECT count(*) FILTER (WHERE {v} = '') FROM prof),
           a.filled, a.d, a.folded, a.spaces, a.wmin, a.wmax, a.numbered, a.lo, a.hi, a.nd, a.zeros,
           a.pre, a.digits, a.up, a.down,
           (SELECT list({{'shape': k, 'n': m, 'example': eg}} ORDER BY m DESC, k) FROM s),
           (SELECT first(k) FROM p), (SELECT first(m) FROM p)
    FROM a
    """
    con = scratch(ordered=True)          # the file's own order: "order in the file" reads it
    try:
        register(con, P, "prof", [spec], "A", opts)
        (rows, nulls, blanks, filled, distinct, folded, spaces, wmin, wmax, numbered, lo, hi, nd,
         zeros, pre, digits, up, down, shapes, ptext, pn) = con.execute(sql).fetchone()
    finally:
        con.close()
    number = None
    next_id = ""
    if filled and numbered == filled:          # every filled value is letters then digits
        lo, hi, nd = int(lo), int(hi), int(nd)
        number = {"min": lo, "max": hi, "distinct": nd, "gaps": hi - lo + 1 - nd, "leading_zeros": int(zeros)}
        next_id = f"{pre or ''}{str(hi + 1).zfill(int(digits or 0))}"
    order = ("ascending" if up and not down else "descending" if down and not up else "neither")
    return {"rows": int(rows), "filled": int(filled), "nulls": int(nulls), "blanks": int(blanks),
            "distinct": int(distinct), "duplicates": int(filled - distinct),
            "case_variants": int(distinct - folded), "spaces": int(spaces),
            "width": {"min": int(wmin or 0), "max": int(wmax or 0)},
            "shapes": [{"shape": s["shape"], "n": int(s["n"]), "example": s["example"]} for s in (shapes or [])],
            "prefix": {"text": ptext, "n": int(pn)} if ptext else None,
            "number": number, "order": order, "next_id": next_id}


@router.get("/keycheck")
def key_check(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """One column checked as a key: unique, nulls and blanks, case and space variants, width,
    its shapes, prefix and number part, the order in the file and the next id - read-only."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    return {"column": column, **keycheck(P, spec, read_options(ws))}
