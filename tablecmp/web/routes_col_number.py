"""GET /api/profiling/numform - a number column's form for its page: rows per order of magnitude
(the log bins), digits before the point, places after it and the DECIMAL(p, s) they fit, round
lots among the most frequent values, and values seen once. Read-only, counted in DuckDB on the
loaded table with its steps applied."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident, scratch
from ..values import register
from .routes_profiling import _band, _held, _spec, read_options
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
    return f"{lo:,} - {top:,}" if isinstance(top, int) else f"{lo:,} - {top:,.2f}"


def _empty(column: str) -> dict:
    return {"column": column, "filled": 0, "zeros": 0, "negatives": 0, "log_bins": [], "before": [],
            "places": {"min": 0, "max": 0}, "fits": "", "round_lots": [], "top": [], "once": []}


def _lots(values: list) -> list:
    """The most frequent values that are whole multiples of 1,000 - or of 100 when none are."""
    for step in (1000, 100):
        got = [v for v in values if v and float(v).is_integer() and int(v) % step == 0]
        if got:
            return got
    return []


def numform(P, spec, opts) -> dict:
    con = scratch()
    try:
        register(con, P, "prof", [spec], "A", opts)
        c = ident(spec.canon)
        # the value as a number and as the shapes read it: text, a trailing .0 dropped
        con.execute(f"CREATE TEMP VIEW t AS SELECT x, regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '') AS v "
                    f"FROM (SELECT {c}, try_cast({c} AS DOUBLE) AS x FROM prof) WHERE isfinite(x)")
        b = "length(regexp_replace(split_part(v, '.', 1), '[^0-9]', '', 'g'))"
        a = "length(split_part(v, '.', 2))"
        # digits before the point of |x| - 1, as an integer: 1 - 9 is 0, 10 - 99 is 1, ...
        mag = ("coalesce(length(CAST(try_cast(floor(abs(x)) AS HUGEINT) AS VARCHAR)) - 1, "
               "CAST(floor(log10(abs(x))) AS INTEGER))")
        k = f"CASE WHEN x < 0 THEN {NEG} WHEN x = 0 THEN {ZERO} WHEN abs(x) < 1 THEN {UNDER} ELSE {mag} END"
        # one scan of the table: rows per distinct value; everything below reads this smaller table
        con.execute("CREATE TEMP TABLE f AS SELECT x, v, count(*) AS n FROM t GROUP BY x, v")
        # rows per (order of magnitude, band of digits before the point), with their places
        groups = con.execute(f"SELECT {k} AS k, {_band(b, 15)} AS band, sum(n), min({a}), max({a}), "
                             f"max({b}), min(x), max(x) FROM f GROUP BY k, band").fetchall()
        con.execute("CREATE TEMP TABLE g AS SELECT x, sum(n) AS n FROM f GROUP BY x")
        freq = con.execute(f"SELECT x, n FROM g ORDER BY n DESC, x LIMIT {TOP}").fetchall()
        once = con.execute(f"SELECT x FROM g WHERE n = 1 ORDER BY x LIMIT {TOP}").fetchall()
    finally:
        con.close()
    out = _empty(spec.canon)
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
    out.update(
        filled=sum(r[0] for r in bins.values()), zeros=bins.get(ZERO, [0])[0], negatives=bins.get(NEG, [0])[0],
        log_bins=log_bins,
        before=[{"label": k, "n": n} for k, n in sorted(bands.items(), key=lambda r: (len(r[0].split("-")[0].rstrip("+")), r[0]))],
        places={"min": pmin or 0, "max": pmax}, fits=f"DECIMAL({max(1, before + pmax)}, {pmax})",
        round_lots=_lots([t["value"] for t in top]), top=top, once=[_num(x) for (x,) in once])
    return out


@router.get("/numform")
def number_form(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """A number column's form - any other type answers an empty one."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if spec.kind != "number":
        return _empty(column)
    return numform(P, spec, read_options(ws))
