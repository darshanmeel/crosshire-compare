"""A date or timestamp column's page (GET /api/profiling/when): its range and span, how fine
its stamps are and how they are written, which repeat, the calendar checks (future, before 1900,
placeholders, weekends, month starts, stamps outside the session) and rows per minute / hour /
day / month / year / weekday, with the column taken apart by year, month, weekday and hour.

The counting is `when_facts` - a plain function on any DuckDB connection and relation, so the
Compare page can run it on its own rows later; the route only registers the profiled table and
calls it. A text or number column read as a date or a timestamp is read the way /parts reads it."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident, lit
from ..values import ColSpec
from .profile_held import held_answer
from .routes_profiling import MONTHS, WEEKDAYS, _casts_held, _held, _reads, _spec, _value, _when_ok, read_when
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

BINS = ("minute", "hour", "day", "month", "year", "weekday")
MAX_BINS = 2000                 # bins a chart is drawn with at most - a finer bin over a long span is refused
PLACEHOLDERS = ("1900-01-01", "1970-01-01", "9999-12-31", "0001-01-01")
REPEATED = 5
SHAPES = 3
QUARTERS = ("Jan - Mar", "Apr - Jun", "Jul - Sep", "Oct - Dec")
_STEP = {"minute": 60, "hour": 3600, "day": 86400}
_T = "__when_t"               # the column read once, as a temp table on the caller's connection


class WhenError(ValueError):
    """A question the column cannot answer - a bin it has no time for, or too many bins."""


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


def _clock(seconds: float) -> str:
    s = max(0, min(86400, int(round(seconds))))
    return f"{s // 3600:02d}:{s // 60 % 60:02d}"


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


def spell(example: str) -> str:
    """How a written date or stamp is built, read off one value: "8 digits · space · hh:mm:ss ·
    point · 6 digits · Z" - a run of letters longer than one is counted, a single one shown."""
    out = []
    for t in re.findall(r"\d{2}:\d{2}:\d{2}|\d{2}:\d{2}|\d+|[A-Za-z]+|\s+|.", example):
        if ":" in t and t[0].isdigit():
            out.append("hh:mm:ss" if t.count(":") == 2 else "hh:mm")
        elif t.isdigit():
            out.append(f"{len(t)} digit{'s' if len(t) > 1 else ''}")
        elif t.isalpha():
            out.append(t if len(t) == 1 else f"{len(t)} letters")
        elif t.isspace():
            out.append("space")
        else:
            out.append("point" if t == "." else t)
    return " · ".join(out)


def when_facts(con, rel: str, spec: ColSpec, *, kind: str, read_from: bool = False, form: str = "",
               bin: str = "", today: date | None = None) -> dict:
    """One date or timestamp column of `rel` (registered on `con`) counted for its page - a plain
    dict, no HTTP. `read_from` reads a text or number column as `kind` in `form` first (the form
    /casts found most values take), and then also says how the values are written: their shapes,
    the digits after the seconds' point, the first two number slots above 12 and the latest value
    as text. Raises WhenError for a bin the column cannot be drawn by."""
    if bin and bin not in BINS:
        raise WhenError(f"Bin by one of {', '.join(BINS)}.")
    if kind == "date" and bin in ("minute", "hour"):
        raise WhenError("A date has no time to bin by.")
    today = today or date.today()
    c = ident(spec.canon)
    text = read_from and spec.kind == "text"
    if read_from:
        raw = _value(spec)
        # DuckDB works out every form of read_when on every row it is given (16 s on a million),
        # so the values are read in the form most of them take first, into a table, and only the
        # rows that form does not read are given all the others
        mine = next((e for f, e in _reads("r", kind) if f == form), "NULL::TIMESTAMP")
        con.execute(f"CREATE OR REPLACE TEMP TABLE {_T} AS SELECT CASE WHEN {_when_ok(mine)} THEN {mine} END AS v, r "
                    f"FROM (SELECT {raw} AS r FROM {rel}) WHERE r IS NOT NULL")
        con.execute(f"UPDATE {_T} SET v = {read_when('r', kind, form)} WHERE v IS NULL")
        con.execute(f"DELETE FROM {_T} WHERE v IS NULL")
        # the digits after the seconds' point as the values are written
        frac = "coalesce(max(length(regexp_extract(r, ':[0-9]{2}[.]([0-9]+)', 1))), 0)"
    else:
        con.execute(f"CREATE OR REPLACE TEMP TABLE {_T} AS SELECT try_cast({c} AS TIMESTAMP) AS v FROM {rel} "
                    f"WHERE try_cast({c} AS TIMESTAMP) IS NOT NULL")
        # the most digits a microsecond part needs once its trailing zeros go
        frac = ("coalesce(max(CASE WHEN f = 0 THEN 0 ELSE 6 - length(regexp_extract("
                "lpad(CAST(f AS VARCHAR), 6, '0'), '0*$')) END), 0)")
    try:
        f = "((epoch_us(v) % 1000000) + 1000000) % 1000000"
        place = ", ".join(f"count(*) FILTER (WHERE CAST(v AS DATE) = DATE {lit(d)})" for d in PLACEHOLDERS)
        got = con.execute(
            f"SELECT count(v), count(DISTINCT v), min(v), max(v), count(DISTINCT CAST(v AS DATE)), "
            f"count(*) FILTER (WHERE v = date_trunc('day', v)), count(*) FILTER (WHERE isodow(v) >= 6), "
            f"count(*) FILTER (WHERE day(v) = 1), count(*) FILTER (WHERE CAST(v AS DATE) > DATE {lit(today.isoformat())}), "
            f"count(*) FILTER (WHERE year(v) < 1900), count(*) FILTER (WHERE f % 1000 = 0), {frac}, {place} "
            f"FROM (SELECT *, {f} AS f FROM {_T})").fetchone()
        filled, distinct, first, last, days, date_only, weekend, fom, future, old, whole, digits = got[:12]
        filled, distinct, digits = int(filled), int(distinct), int(digits or 0) if kind == "timestamp" else 0
        placeholders = [{"value": d, "n": int(n)} for d, n in zip(PLACEHOLDERS, got[12:]) if n]
        repeated = con.execute(f"SELECT v, count(*) AS n, isodow(v) FROM {_T} GROUP BY v HAVING count(*) > 1 "
                               f"ORDER BY n DESC, v LIMIT {REPEATED}").fetchall()
        cal = con.execute(f"SELECT isodow(v), month(v), hour(v), year(v), count(*) FROM {_T} GROUP BY ALL").fetchall()
        span = (last - first).total_seconds() if filled else 0.0
        use = bin or _default_bin(kind, first, last)
        if use in _STEP and span / _STEP[use] > MAX_BINS:
            raise WhenError(f"Too many bins by {use} - pick a wider one.")
        if use == "weekday":
            bins = [{"label": w, "n": sum(int(n) for d, *_, n in cal if d == i + 1)} for i, w in enumerate(WEEKDAYS)]
        elif filled:
            rows = con.execute(f"SELECT date_trunc('{use}', v) AS k, count(*) FROM {_T} GROUP BY k").fetchall()
            rows = [(k if isinstance(k, datetime) else datetime(k.year, k.month, k.day), n) for k, n in rows]
            bins = _series(rows, use, first.date() == last.date())
        else:
            bins = []
        session = None
        if kind == "timestamp" and filled:
            # the session is the time of day most stamps fall in: a stamp outside the quartiles'
            # 1.5 x IQR fence (kept within the day) is before the open or after the close
            tod = "epoch(v - date_trunc('day', v))"
            q1, q3 = con.execute(f"SELECT quantile_cont({tod}, 0.25), quantile_cont({tod}, 0.75) FROM {_T}").fetchone()
            lo, hi = max(0.0, q1 - 1.5 * (q3 - q1)), min(86400.0, q3 + 1.5 * (q3 - q1))
            before, after = con.execute(f"SELECT count(*) FILTER (WHERE {tod} < {lo}), count(*) FILTER (WHERE {tod} > {hi}) "
                                        f"FROM {_T}").fetchone()
            session = {"from": _clock(lo), "to": _clock(hi), "before": int(before), "after": int(after)}
        written = None
        if read_from and filled:
            shape = "regexp_replace(regexp_replace(r, '[0-9]', '9', 'g'), '[A-Za-z]', 'A', 'g')"
            shapes = con.execute(f"SELECT {shape} AS k, count(*) AS n, min(r) FROM {_T} GROUP BY k "
                                 f"ORDER BY n DESC, k").fetchall()
            fr = con.execute(f"SELECT length(regexp_extract(r, ':[0-9]{{2}}[.]([0-9]+)', 1)) AS d, count(*) FROM {_T} "
                             f"GROUP BY d ORDER BY d").fetchall() if kind == "timestamp" else []
            s1, s2 = con.execute(
                f"SELECT count(*) FILTER (WHERE try_cast(regexp_extract(r, '^([0-9]{{1,2}})[/.-]', 1) AS INT) > 12), "
                f"count(*) FILTER (WHERE try_cast(regexp_extract(r, '^[0-9]{{1,2}}[/.-]([0-9]{{1,2}})[/.-]', 1) AS INT) > 12) "
                f"FROM {_T}").fetchone()
            top_text = con.execute(f"SELECT r, v FROM {_T} ORDER BY r DESC LIMIT 1").fetchone() if text else None
            written = {
                "shapes": [{"shape": k, "n": int(n), "example": eg, "spelled": spell(eg)} for k, n, eg in shapes[:SHAPES]],
                "shape_count": len(shapes),
                "fractions": [{"digits": int(d), "n": int(n)} for d, n in fr],
                "first_over_12": int(s1), "second_over_12": int(s2),
                "text_last": {"text": top_text[0], "read": _show(top_text[1], kind, digits)} if top_text else None,
            }
    finally:
        con.execute(f"DROP TABLE IF EXISTS {_T}")

    def by(i: int, names, start: int = 1) -> list[dict]:
        return [{"label": w, "n": sum(int(r[-1]) for r in cal if r[i] == j + start)} for j, w in enumerate(names)]

    years = sorted({int(r[3]) for r in cal})
    return {
        "column": spec.canon, "kind": kind, "form": form, "filled": filled, "distinct": distinct,
        "first": _show(first, kind, digits), "last": _show(last, kind, digits), "span_seconds": span,
        "days": int(days), "date_only": int(date_only), "weekend": int(weekend), "first_of_month": int(fom),
        "future": int(future), "today": today.isoformat(), "before_1900": int(old), "placeholders": placeholders,
        "fraction_digits": digits, "whole_ms": int(whole) if digits == 6 else None, "shared": filled - distinct,
        "repeated": [{"value": _show(v, kind, digits), "n": int(n), "weekday": WEEKDAYS[int(d) - 1]} for v, n, d in repeated],
        "bin": use, "bins": bins,
        "weekday": by(0, WEEKDAYS),
        "months": by(1, MONTHS),
        "quarters": [{"label": q, "n": sum(int(r[-1]) for r in cal if (r[1] - 1) // 3 == i)} for i, q in enumerate(QUARTERS)],
        "hours": by(2, [f"{h:02d}" for h in range(24)], 0) if kind == "timestamp" else [],
        "years": [{"label": f"{y:04d}", "n": sum(int(r[-1]) for r in cal if r[3] == y)} for y in years],
        "session": session, "written": written,
    }


@router.get("/when")
def column_when(column: str = Query(..., max_length=1000), read: str = Query("", alias="as", max_length=20),
                bin: str = Query("", max_length=20), ws: Workspace = Depends(workspace)) -> dict:
    """One date or timestamp column for its page: range, span, precision, repeats, calendar checks,
    rows per bin and its parts. `as` reads a text or number column as a date or a timestamp first."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if spec.kind in ("date", "timestamp"):
        kind, read_from = spec.kind, False
    elif read in ("date", "timestamp") and spec.kind in ("text", "number"):
        kind, read_from = read, True
    else:
        raise HTTPException(400, "Read the column as a date or a timestamp.")
    form = ""
    if read_from:
        row = next((r for r in _casts_held(ws, prof)["columns"] if r["column"] == column), None)
        form = (row or {}).get(kind, {}).get("form", "")
    try:
        return held_answer(ws, prof, ("when", column, kind, bin), lambda con: when_facts(
            con, "prof", spec, kind=kind, read_from=read_from, form=form, bin=bin))
    except WhenError as e:
        raise HTTPException(400, str(e)) from None
