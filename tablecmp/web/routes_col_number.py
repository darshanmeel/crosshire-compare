"""GET /api/profiling/numform - a number column's form for its page: rows per order of magnitude
(the log bins), digits before the point, places after it and the DECIMAL(p, s) they fit, round
lots among the most frequent values, and values seen once. Read-only, counted in DuckDB on the
loaded table with its steps applied.

The analysis is `number_form(con, relation, column)`: it reads any relation on an open DuckDB
connection, so the same form can be worked out on other rows (a comparison's differing rows, a
one-sided column); the route only registers the profiled table and calls it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident
from ..values import ColSpec
from .profile_held import held_answer
from .routes_profiling import _band, _held, _spec
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

TOP = 10          # most frequent values listed, and values seen once
NEG, ZERO, UNDER = -3, -2, -1      # the bins before the orders of magnitude: < 0, 0, between 0 and 1


def _num(x: float) -> int | float:
    x = float(x)
    return int(x) if x.is_integer() and abs(x) < 2 ** 53 else x


def _label(k: int, hi: float, last: bool) -> str:
    if k == NEG:
        return "< 0"
    if k == ZERO:
        return "0"
    if k == UNDER:
        return "0 - 1"
    lo = 10 ** k
    top = _num(hi) if last else 10 ** (k + 1) - 1
    if isinstance(top, float) and top.is_integer():      # past 2**53: a whole number still, no .00
        top = int(top)
    return f"{lo:,} - {top:,}" if isinstance(top, int) else f"{lo:,} - {top:,.2f}"


def _empty(column: str) -> dict:
    return {"column": column, "filled": 0, "zeros": 0, "negatives": 0, "log_bins": [], "before": [],
            "places": {"min": 0, "max": 0}, "fits": "", "round_lots": [], "lot_step": 0, "top": [], "once": []}


def _lots(values: list) -> tuple[list, int]:
    """The most frequent values that are whole multiples of 1,000 - or of 100 when none are - and that step."""
    for step in (1000, 100):
        got = [v for v in values if v and float(v).is_integer() and int(v) % step == 0]
        if got:
            return got, step
    return [], 0


def number_form(con, relation: str, column: ColSpec | str) -> dict:
    """The form of one number column of `relation` on `con` - see the module's docstring. Leaves
    temp objects __nf_t, __nf_f and __nf_g on the connection, so give it a scratch one."""
    name = column.canon if isinstance(column, ColSpec) else column
    c, rel = ident(name), ident(relation)
    # the value as a number and as the shapes read it: text, a trailing .0 dropped
    con.execute(f"CREATE OR REPLACE TEMP VIEW __nf_t AS SELECT x, regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '') AS v "
                f"FROM (SELECT {c}, try_cast({c} AS DOUBLE) AS x FROM {rel}) WHERE isfinite(x)")
    # digits before and after the point as written - a double DuckDB writes as 1e+16 or 1.5e-05
    # counted as 10000000000000000 and 0.000015 would be
    m, ex = "split_part(v, 'e', 1)", "try_cast(split_part(v, 'e', 2) AS INTEGER)"
    ib, fa = f"length(regexp_replace(split_part({m}, '.', 1), '[^0-9]', '', 'g'))", f"length(split_part({m}, '.', 2))"
    b = f"(CASE WHEN {ex} IS NULL THEN {ib} WHEN {ex} >= 0 THEN {ib} + {ex} ELSE 1 END)"
    a = f"(CASE WHEN {ex} IS NULL THEN {fa} ELSE greatest(0, {fa} - {ex}) END)"
    # digits before the point of |x| - 1, as an integer: 1 - 9 is 0, 10 - 99 is 1, ...
    mag = ("coalesce(length(CAST(try_cast(floor(abs(x)) AS HUGEINT) AS VARCHAR)) - 1, "
           "CAST(floor(log10(abs(x))) AS INTEGER))")
    k = f"CASE WHEN x < 0 THEN {NEG} WHEN x = 0 THEN {ZERO} WHEN abs(x) < 1 THEN {UNDER} ELSE {mag} END"
    # one scan of the table: rows per distinct value; everything below reads this smaller table
    con.execute("CREATE OR REPLACE TEMP TABLE __nf_f AS SELECT x, v, count(*) AS n FROM __nf_t GROUP BY x, v")
    # rows per (order of magnitude, band of digits before the point), with their places
    groups = con.execute(f"SELECT {k} AS k, {_band(b, 15)} AS band, sum(n), min({a}), max({a}), "
                         f"max({b}), min(x), max(x) FROM __nf_f GROUP BY k, band").fetchall()
    con.execute("CREATE OR REPLACE TEMP TABLE __nf_g AS SELECT x, sum(n) AS n FROM __nf_f GROUP BY x")
    freq = con.execute(f"SELECT x, n FROM __nf_g ORDER BY n DESC, x LIMIT {TOP}").fetchall()
    once = con.execute(f"SELECT x FROM __nf_g WHERE n = 1 ORDER BY x LIMIT {TOP}").fetchall()
    out = _empty(name)
    if not groups:
        return out
    bins: dict[int, list] = {}
    bands: dict[str, int] = {}
    pmin, pmax, before = None, 0, 0
    for kk, band, n, lo_p, hi_p, digits, lo, hi in groups:
        kk, n = int(kk), int(n)
        row = bins.setdefault(kk, [0, float(lo), float(hi)])
        row[0] += n
        row[1], row[2] = min(row[1], float(lo)), max(row[2], float(hi))
        bands[band] = bands.get(band, 0) + n
        pmin = int(lo_p) if pmin is None else min(pmin, int(lo_p))
        pmax, before = max(pmax, int(hi_p)), max(before, int(digits))
    mags = [k for k in bins if k >= 0]
    last = max(mags) if mags else None
    for kk in range(min(mags), last) if mags else ():      # an order of magnitude with no value still shows, empty
        bins.setdefault(kk, [0, 10.0 ** kk, 10.0 ** kk])
    order = sorted(bins)
    log_bins = []
    for kk in order:
        n, lo, hi = bins[kk]
        if kk == NEG:
            edges = (lo, 0)
        elif kk == ZERO:
            edges = (0, 0)
        elif kk == UNDER:
            edges = (0, 1)
        else:
            edges = (10 ** kk, hi if kk == last else 10 ** (kk + 1))
        log_bins.append({"label": _label(kk, hi, kk == last), "lo": _num(edges[0]), "hi": _num(edges[1]), "n": n})
    top = [{"value": _num(x), "n": int(n)} for x, n in freq]
    lots, step = _lots([t["value"] for t in top])
    out.update(
        filled=sum(r[0] for r in bins.values()), zeros=bins.get(ZERO, [0])[0], negatives=bins.get(NEG, [0])[0],
        log_bins=log_bins,
        before=[{"label": k, "n": n} for k, n in sorted(bands.items(), key=lambda r: (len(r[0].split("-")[0].rstrip("+")), r[0]))],
        places={"min": pmin or 0, "max": pmax}, fits=f"DECIMAL({max(1, before + pmax)}, {pmax})",
        round_lots=lots, lot_step=step, top=top, once=[_num(x) for (x,) in once])
    return out


@router.get("/numform")
def column_numform(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """A number column's form - any other type answers an empty one."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if spec.kind != "number":
        return _empty(column)
    return held_answer(ws, prof, ("numform", column), lambda con: number_form(con, "prof", spec))
