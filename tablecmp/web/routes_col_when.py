"""A date or timestamp column's page (GET /api/profiling/when): its range and span, how fine
its stamps are, which repeat, the calendar checks (future, before 1900, placeholders, weekends,
month starts) and rows per minute / hour / day / month / year / weekday. A text or number
column read as a date or a timestamp is read the way /parts reads it. Read-only, counted in
DuckDB on the loaded table with its steps applied."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident, lit, scratch
from ..values import register
from .routes_profiling import MONTHS, WEEKDAYS, _casts_held, _held, _spec, _value, read_options, read_when
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

BINS = ("minute", "hour", "day", "month", "year", "weekday")
MAX_BINS = 2000                 # bins a chart is drawn with at most - a finer bin over a long span is refused
PLACEHOLDERS = ("1900-01-01", "1970-01-01", "9999-12-31", "0001-01-01")
REPEATED = 5
QUARTERS = ("Jan - Mar", "Apr - Jun", "Jul - Sep", "Oct - Dec")
_STEP = {"minute": 60, "hour": 3600, "day": 86400}


def _default_bin(kind: str, first: datetime | None, last: datetime | None) -> str:
    if kind == "date" or first is None:
        return "year"
    if first.date() == last.date():
        return "hour"
    return "day" if (last - first).total_seconds() <= 90 * 86400 else "month"


def _show(t: datetime | None, kind: str, digits: int) -> str | None:
    """A date or a stamp as the page shows it - a stamp to the fractional digits its column uses."""
    if t is None:
        return None
    if isinstance(t, date) and not isinstance(t, datetime):
        t = datetime(t.year, t.month, t.day)
    if kind == "date":
        return t.date().isoformat()
    s = t.strftime("%Y-%m-%d %H:%M:%S")
    return s + "." + f"{t.microsecond:06d}"[:digits] if digits else s


def _next_month(t: datetime) -> datetime:
    return t.replace(year=t.year + (t.month == 12), month=t.month % 12 + 1)


def _label(t: datetime, bin: str, one_day: bool) -> str:
    if bin == "year":
        return f"{t.year:04d}"
    if bin == "month":
        return t.strftime("%Y-%m")
    if bin == "day":
        return t.date().isoformat()
    clock = t.strftime("%H:%M")
    return clock if one_day else f"{t.date().isoformat()} {clock}"


def _count(t: datetime, end: datetime, bin: str) -> int:
    """How many bins run from `t` to `end`, both included."""
    if bin in _STEP:
        return int((end - t).total_seconds() // _STEP[bin]) + 1
    if bin == "month":
        return (end.year - t.year) * 12 + end.month - t.month + 1
    return end.year - t.year + 1


def _series(rows: list[tuple[datetime, int]], bin: str, one_day: bool) -> list[dict]:
    """Every bin from the first to the last, empty ones too, so a gap shows as a gap - only the
    filled ones when that would be more than MAX_BINS (a 0001-01-01 among this year's dates)."""
    if not rows:
        return []
    counts = {k: int(n) for k, n in rows}
    t, end = min(counts), max(counts)
    if _count(t, end, bin) > MAX_BINS:
        return [{"label": _label(k, bin, one_day), "n": counts[k]} for k in sorted(counts)]
    out = []
    while t <= end:
        out.append({"label": _label(t, bin, one_day), "n": counts.get(t, 0)})
        if bin in _STEP:
            t += timedelta(seconds=_STEP[bin])
        elif bin == "month":
            t = _next_month(t)
        else:
            if t.year >= 9999:
                break
            t = t.replace(year=t.year + 1)
    return out


@router.get("/when")
def column_when(column: str = Query(..., max_length=1000), read: str = Query("", alias="as", max_length=20),
                bin: str = Query("", max_length=20), ws: Workspace = Depends(workspace)) -> dict:
    """One date or timestamp column for its page: range, span, precision, repeats, calendar checks
    and rows per bin. `as` reads a text or number column as a date or a timestamp first."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if bin and bin not in BINS:
        raise HTTPException(400, f"Bin by one of {', '.join(BINS)}.")
    if spec.kind in ("date", "timestamp"):
        kind, read_from = spec.kind, ""
    elif read in ("date", "timestamp") and spec.kind in ("text", "number"):
        kind, read_from = read, read
    else:
        raise HTTPException(400, "Read the column as a date or a timestamp.")
    if kind == "date" and bin in ("minute", "hour"):
        raise HTTPException(400, "A date has no time to bin by.")
    form = ""
    if read_from:
        row = next((r for r in _casts_held(ws, prof)["columns"] if r["column"] == column), None)
        form = (row or {}).get(kind, {}).get("form", "")
    today = date.today()
    con = scratch()
    try:
        register(con, P, "prof", [spec], "A", read_options(ws))
        c = ident(spec.canon)
        if read_from:
            raw = _value(spec)
            # read as /parts reads it: the form /casts found first, each form kept for a plausible year
            con.execute(f"CREATE TEMP TABLE t AS SELECT v, r FROM (SELECT {read_when(raw, kind, form)} AS v, "
                        f"{raw} AS r FROM prof) WHERE v IS NOT NULL")
            # the digits after the seconds' point as the values are written
            frac = "coalesce(max(length(regexp_extract(r, ':[0-9]{2}[.]([0-9]+)', 1))), 0)"
        else:
            con.execute(f"CREATE TEMP TABLE t AS SELECT try_cast({c} AS TIMESTAMP) AS v FROM prof "
                        f"WHERE try_cast({c} AS TIMESTAMP) IS NOT NULL")
            # the most digits a microsecond part needs once its trailing zeros go
            frac = ("coalesce(max(CASE WHEN f = 0 THEN 0 ELSE 6 - length(regexp_extract("
                    "lpad(CAST(f AS VARCHAR), 6, '0'), '0*$')) END), 0)")
        f = "((epoch_us(v) % 1000000) + 1000000) % 1000000"
        place = ", ".join(f"count(*) FILTER (WHERE CAST(v AS DATE) = DATE {lit(d)})" for d in PLACEHOLDERS)
        got = con.execute(
            f"SELECT count(v), count(DISTINCT v), min(v), max(v), count(DISTINCT CAST(v AS DATE)), "
            f"count(*) FILTER (WHERE v = date_trunc('day', v)), count(*) FILTER (WHERE isodow(v) >= 6), "
            f"count(*) FILTER (WHERE day(v) = 1), count(*) FILTER (WHERE CAST(v AS DATE) > DATE {lit(today.isoformat())}), "
            f"count(*) FILTER (WHERE year(v) < 1900), count(*) FILTER (WHERE f % 1000 = 0), {frac}, {place} "
            f"FROM (SELECT *, {f} AS f FROM t)").fetchone()
        filled, distinct, first, last, days, date_only, weekend, fom, future, old, whole, digits = got[:12]
        filled, distinct, digits = int(filled), int(distinct), int(digits or 0) if kind == "timestamp" else 0
        placeholders = [{"value": d, "n": int(n)} for d, n in zip(PLACEHOLDERS, got[12:]) if n]
        repeated = con.execute(f"SELECT v, count(*) AS n, isodow(v) FROM t GROUP BY v HAVING count(*) > 1 "
                               f"ORDER BY n DESC, v LIMIT {REPEATED}").fetchall()
        cal = con.execute("SELECT isodow(v), month(v), count(*) FROM t GROUP BY ALL").fetchall()
        span = (last - first).total_seconds() if filled else 0.0
        use = bin or _default_bin(kind, first, last)
        if use in _STEP and span / _STEP[use] > MAX_BINS:
            raise HTTPException(400, f"Too many bins by {use} - pick a wider one.")
        if use == "weekday":
            bins = [{"label": w, "n": sum(int(n) for d, _, n in cal if d == i + 1)} for i, w in enumerate(WEEKDAYS)]
        elif filled:
            rows = con.execute(f"SELECT date_trunc('{use}', v) AS k, count(*) FROM t GROUP BY k").fetchall()
            rows = [(k if isinstance(k, datetime) else datetime(k.year, k.month, k.day), n) for k, n in rows]
            bins = _series(rows, use, first.date() == last.date())
        else:
            bins = []
    finally:
        con.close()
    return {
        "column": column, "kind": kind, "form": form, "filled": filled, "distinct": distinct,
        "first": _show(first, kind, digits), "last": _show(last, kind, digits), "span_seconds": span,
        "days": int(days), "date_only": int(date_only), "weekend": int(weekend), "first_of_month": int(fom),
        "future": int(future), "today": today.isoformat(), "before_1900": int(old), "placeholders": placeholders,
        "fraction_digits": digits, "whole_ms": int(whole) if digits == 6 else None, "shared": filled - distinct,
        "repeated": [{"value": _show(v, kind, digits), "n": int(n), "weekday": WEEKDAYS[int(d) - 1]} for v, n, d in repeated],
        "bin": use, "bins": bins,
        "weekday": [{"label": w, "n": sum(int(n) for d, _, n in cal if d == i + 1)} for i, w in enumerate(WEEKDAYS)],
        "months": [{"label": m, "n": sum(int(n) for _, mo, n in cal if mo == i + 1)} for i, m in enumerate(MONTHS)],
        "quarters": [{"label": q, "n": sum(int(n) for _, mo, n in cal if (mo - 1) // 3 == i)} for i, q in enumerate(QUARTERS)],
    }
