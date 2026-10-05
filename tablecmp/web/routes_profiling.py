"""The Profiling page's routes: Profile as a job, the profile as the page draws it (keys,
statistics, what stands out, outliers, patterns, dependencies), one column's value frequencies
when the page lists it, profile.csv, and the six-file save. The profile stays in the
workspace - its DataFrames never leave Python, only their rows do."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import profiling, setup
from ..loading import DEFAULT_NAMES
from ..outputs import default_save_folder, run_id
from ..sql import ident, lit, scratch
from ..values import ColSpec, ReadOptions, register
from . import jobs
from .sides import PAGE, side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")
BUILT = "profile_view_P"       # (the profile, the view built from it) - the profile is turned into rows once
HELD = "profile_P"            # (key, profile, run id) - sides.put_side drops it when P is loaded again


class NameIn(BaseModel):
    name: str = Field("", max_length=200)


class RunIn(NameIn):
    key_cols: int = Field(profiling.KEY_COLS, ge=1, le=6)      # combinations up to this many columns
    top_keys: int = Field(profiling.TOP_KEYS, ge=1, le=20)     # candidates listed
    shortlist: int = Field(profiling.SHORTLIST, ge=1, le=50)   # checked on every row


class SaveIn(NameIn):
    folder: str = Field("", max_length=4096)


class HistBin(BaseModel):
    lo: float | str
    hi: float | str
    n: int


class HistOut(BaseModel):
    column: str
    kind: str
    bins: list[HistBin]


def read_options(ws: Workspace) -> ReadOptions:
    """How values are read - the switches set on the Compare page or by a config."""
    return setup.read_options(ws.data.get("settings"))


def frame(df: pd.DataFrame) -> dict:
    """A table as the page draws it: the column names and the rows, NaN and NaT as null."""
    return {"columns": [str(c) for c in df.columns],
            "rows": json.loads(df.to_json(orient="values", date_format="iso", default_handler=str))}


def _name(text: str) -> str:
    return text.strip() or DEFAULT_NAMES["P"]


def _run(name: str, made: str) -> dict:
    return {"pair": profiling.file_stem(name), "run_id": made}


def _held(ws: Workspace) -> tuple[str, dict, str]:
    held = ws.data.get(HELD)
    if not held:
        raise HTTPException(409, "Profile the table first.")
    return held


def profile_view(prof: dict) -> dict:
    tone, text = profiling.keys_line(prof)
    best = profiling.best_key(prof) or []
    have = list(prof["freq"])
    return {"headline": prof["headline"],
            "keys": {"tone": tone, "text": text, "table": frame(prof["keys"][0])},
            "stats": frame(prof["stats"]), "notes": list(prof["notes"]),
            "outliers": frame(prof["outliers"]), "patterns": frame(prof["patterns"]),
            "deps": frame(prof["deps"]), "corr": frame(prof["corr"]),
            "matrix": frame(prof.get("matrix", pd.DataFrame(columns=["Column"]))),
            "matrix_note": prof.get("matrix_note", ""),
            "search": {"key_cols": prof.get("key_cols", profiling.KEY_COLS),
                       "top_keys": prof.get("top_keys", profiling.TOP_KEYS),
                       "key_sample": prof.get("key_sample", 0),
                       "shortlist": prof.get("shortlist", profiling.SHORTLIST)},
            "freq": {"columns": have, "picked": [c for c in best if c in have][:2],
                     "titles": profiling.fold_titles(prof["stats"], have)}}


@router.get("")
def view(ws: Workspace = Depends(workspace)) -> dict:
    """The profile held. The Name only changes the save folder - see /defaults - so the profile
    is built once per run and kept, not again on every request."""
    held = ws.data.get(HELD)
    P = side(ws, "P")
    if not held or not P.loaded:
        ws.data.pop(BUILT, None)
        return {"profile": None, "stale": False, "made": ""}
    key, prof, made = held
    built = ws.data.get(BUILT)
    if not built or built[0] is not prof:
        built = (prof, profile_view(prof))
        ws.data[BUILT] = built
    return {"profile": built[1], "stale": key != profiling.profile_key(P, read_options(ws)), "made": made}


@router.get("/defaults")
def defaults(name: str = Query("", max_length=200), ws: Workspace = Depends(workspace)) -> dict:
    """The file name and the save folder a Name gives - asked again as the Name is typed."""
    held = ws.data.get(HELD)
    P = side(ws, "P")
    if not held or not P.loaded:
        return {"csv_name": "", "save_folder": ""}
    name = _name(name)
    base = Path(ws.data.get("save_dir") or profiling.default_save_base(P))
    return {"csv_name": f"{profiling.file_stem(name)}__profile.csv",
            "save_folder": str(default_save_folder(_run(name, held[2]), base))}


@router.post("/run")
def run_profile(body: RunIn, ws: Workspace = Depends(workspace)) -> dict:
    """Profile as a job: the table read once, every column measured, the keys looked for and
    what stands out noted - minutes on a wide or big table."""
    if not side(ws, "P").loaded:
        raise HTTPException(409, "Load a table in the sidebar first.")
    name = _name(body.name)

    def work(ctx: jobs.JobCtx) -> None:
        P = side(ws, "P")                        # under the lock: the table as it is now
        if not P.loaded:
            raise ValueError("Load a table in the sidebar first.")
        opts = read_options(ws)
        key = profiling.profile_key(P, opts)
        found = profiling.make_profile(P, name, opts, ctx.say, body.key_cols, body.top_keys,
                                       shortlist=body.shortlist)
        ws.data[HELD] = (key, found, run_id())
        ctx.label = profiling.ready_label(found)
        # the notes as their own entry, the way Auto's decisions are logged
        jobs.note(ws, "Profile notes", profiling.notes_label(found["notes"]), found["notes"])

    return jobs.public(jobs.start(ws, "Profile", "Profiling…", work, page=PAGE["P"]))


@router.get("/freq")
def freq(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """One column's ten most and ten least frequent values - measured already, sent when listed."""
    _, prof, _ = _held(ws)
    if column not in prof["freq"]:
        raise HTTPException(404, f"No column called {column} in this profile.")
    top, bottom = prof["freq"][column]
    return {"column": column, "title": profiling.fold_title(prof["stats"], column),
            "top": frame(top), "bottom": frame(bottom)}


HIST_KINDS = ("number", "date", "timestamp")


EPOCH = datetime(1970, 1, 1)


def _when(seconds: float, kind: str) -> str:
    # not datetime.fromtimestamp: on Windows it refuses anything before 1970 (a birth date)
    t = EPOCH + timedelta(seconds=seconds)
    return t.date().isoformat() if kind == "date" else t.isoformat(sep=" ")


def histogram(P, spec: ColSpec, opts: ReadOptions, bins: int) -> list[dict]:
    """Equal-width bins over one number, date or timestamp column of the table as it is read
    now (its steps and type applied): [{lo, hi, n}], the last bin closed at the top. Dates and
    timestamps are binned on their epoch seconds and given back as ISO text."""
    con = scratch()
    try:
        register(con, P, "prof", [spec], "A", opts)
        c = ident(spec.canon)
        x = (f"try_cast({c} AS DOUBLE)" if spec.kind == "number"
             else f"epoch(try_cast({c} AS TIMESTAMP))")
        x = f"(SELECT {x} AS x FROM prof) WHERE isfinite(x)"   # NaN and Infinity read as numbers but have no bin
        lo, hi = con.execute(f"SELECT min(x), max(x) FROM {x}").fetchone()
        if lo is None:
            return []
        lo, hi = float(lo), float(hi)
        width = (hi - lo) / bins
        rows = con.execute(
            f"SELECT least(coalesce(CAST(floor((x - ?) / nullif(?, 0)) AS BIGINT), 0), ?) AS k, count(*) "
            f"FROM {x} GROUP BY k", [lo, width, bins - 1]).fetchall()
    finally:
        con.close()
    counts = {int(k): int(n) for k, n in rows}
    if width == 0:                                    # one value: one bin
        edges = [(lo, hi)]
        bins = 1
    else:
        edges = [(lo + i * width, hi if i == bins - 1 else lo + (i + 1) * width) for i in range(bins)]
    out = []
    for i, (a, b) in enumerate(edges):
        if spec.kind == "number":
            out.append({"lo": round(a, 6), "hi": round(b, 6), "n": counts.get(i, 0)})
        else:
            out.append({"lo": _when(a, spec.kind), "hi": _when(b, spec.kind), "n": counts.get(i, 0)})
    return out


@router.get("/hist", response_model=HistOut)
def hist(column: str = Query(..., max_length=1000), bins: int = Query(10, ge=1, le=50),
         ws: Workspace = Depends(workspace)) -> dict:
    """One column's distribution in equal bins, for the column detail - numbers, dates and
    timestamps only (any other type answers no bins). Read-only: the held profile names the
    column and its type, DuckDB counts on the loaded table."""
    _, prof, _ = _held(ws)
    spec = next((ColSpec(**s) for s in prof.get("specs", []) if s["canon"] == column), None)
    if spec is None:
        raise HTTPException(404, f"No column called {column} in this profile.")
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if spec.kind not in HIST_KINDS:
        return {"column": column, "kind": spec.kind, "bins": []}
    return {"column": column, "kind": spec.kind, "bins": histogram(P, spec, read_options(ws), bins)}


# the forms a text value is tried in: ISO by a plain cast, then these, the best one kept
DATE_FORMATS = ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%Y%m%d")
TIME_FORMATS = ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
                "%Y/%m/%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y%m%d%H%M%S")
CASTS = "profile_casts_P"     # (profile, answer) - worked out once per profile


def _when_ok(t: str) -> str:
    """A date or time read from a form, kept when its year is a plausible one - so a long id
    does not pass for a date."""
    return f"year({t}) BETWEEN 1900 AND 2100"


def _tries(v: str, number: bool = False) -> dict[str, list[tuple[str, str]]]:
    """For one value: (form, condition) pairs per type the value might be read as - a number
    column is only tried as a date or a timestamp (20260504 or 20260504004217)."""
    # a plain cast reads '2026-05-06 08:00' as a DATE too, so the length tells a date from a timestamp
    iso_ts = f"length({v}) > 10 AND try_cast({v} AS TIMESTAMP) IS NOT NULL"
    ok = {
        "number": [("plain", f"isfinite(try_cast({v} AS DOUBLE))"),
                   ("with , removed", f"isfinite(try_cast(replace({v}, ',', '') AS DOUBLE))")],
        "date": [("ISO", f"length({v}) <= 10 AND try_cast({v} AS DATE) IS NOT NULL")]
                + [(f, _when_ok(f"try_strptime({v}, {lit(f)})")) for f in DATE_FORMATS],
        "timestamp": [("ISO", iso_ts)]
                     + [(f, _when_ok(f"try_strptime({v}, {lit(f)})")) for f in TIME_FORMATS],
    }
    if number:
        ok.pop("number")
    return ok


def casts(P, specs: list[ColSpec], opts: ReadOptions) -> list[dict]:
    """Every text and number column, one read: how many filled values would read as a number
    (text only), a date or a
    timestamp - in any of the forms tried, and in the one most of them take: [{column, filled,
    number|date|timestamp: {any, form, n}}], a type left out when no value takes it. A number
    also says its most digits before and after the point."""
    text = [s for s in specs if s.kind in ("text", "number")]
    if not text:
        return []
    con = scratch()
    try:
        register(con, P, "prof", text, "A", opts)
        aggs, keys = [], []
        for s in text:
            c = ident(s.canon)
            v = (f"nullif(trim({c}), '')" if s.kind == "text"
                 else f"regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '')")
            aggs.append(f"count({v})")
            keys.append((s.canon, "filled", ""))
            for kind, tries in _tries(v, s.kind == "number").items():
                anyway = " OR ".join(f"({c})" for _, c in tries)
                aggs.append(f"count(*) FILTER (WHERE {anyway})")
                keys.append((s.canon, kind, None))
                if kind == "number":      # the widest of them, for the DECIMAL(p, s) they would fit
                    bare = f"regexp_replace(replace({v}, ',', ''), '^[-+]', '')"
                    aggs += [f"max(length(split_part({bare}, '.', 1))) FILTER (WHERE {anyway})",
                             f"max(length(split_part({bare}, '.', 2))) FILTER (WHERE {anyway})"]
                    keys += [(s.canon, kind, "before"), (s.canon, kind, "after")]
                for form, cond in tries:
                    aggs.append(f"count(*) FILTER (WHERE {cond})")
                    keys.append((s.canon, kind, form))
        got = con.execute(f"SELECT {', '.join(aggs)} FROM prof").fetchone()
    finally:
        con.close()
    kinds = {s.canon: s.kind for s in text}
    out: dict[str, dict] = {}
    for (col, kind, form), n in zip(keys, got):
        row = out.setdefault(col, {"column": col, "kind": kinds[col]})
        if kind == "filled":
            row["filled"] = int(n)
        elif form is None:
            if n:
                row[kind] = {"any": int(n), "form": "", "n": 0}
        elif form in ("before", "after"):
            if kind in row:
                row[kind][form] = int(n or 0)
        elif kind in row and n > row[kind]["n"]:
            row[kind].update(form=form, n=int(n))
    return [r for r in out.values() if r["filled"] and any(k in r for k in ("number", "date", "timestamp"))]


@router.get("/casts")
def cast_counts(ws: Workspace = Depends(workspace)) -> dict:
    """Text and number columns that could be read as another type, and how many of their values would -
    read-only, counted in DuckDB on the loaded table with its steps applied."""
    _, prof, _ = _held(ws)
    held = ws.data.get(CASTS)
    if held and held[0] is prof:
        return held[1]
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    answer = {"columns": casts(P, [ColSpec(**s) for s in prof.get("specs", [])], read_options(ws))}
    ws.data[CASTS] = (prof, answer)
    return answer


PART_TOP = 10
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _band(x: str, top: int) -> str:
    """Digits counted into bands of three: 0, 1-3, 4-6, ... up to `top`+."""
    return (f"CASE WHEN {x} = 0 THEN '0' WHEN {x} > {top} THEN '{top + 1}+' ELSE "
            f"CAST((({x} - 1) // 3) * 3 + 1 AS VARCHAR) || '-' || CAST((({x} - 1) // 3) * 3 + 3 AS VARCHAR) END")


def parts(P, spec: ColSpec, opts: ReadOptions, n: int) -> list[dict]:
    """One column taken apart: a number by its digits before and after the point, a date or a
    timestamp by year, month, weekday (and hour), text by its first and last `n` characters -
    [{title, total, rows: [{label, n}]}] - total counts every value, the top ten shown or not - each group's rows in their natural order or by count."""
    con = scratch()
    try:
        register(con, P, "prof", [spec], "A", opts)
        c = ident(spec.canon)
        if spec.kind == "number":
            # as the shapes read it: the number as text, a trailing .0 dropped, the sign ignored
            con.execute(f"CREATE TEMP VIEW t AS SELECT regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '') AS v "
                        f"FROM prof WHERE isfinite(try_cast({c} AS DOUBLE))")
            b = "length(regexp_replace(split_part(v, '.', 1), '[^0-9]', '', 'g'))"
            a = "length(split_part(v, '.', 2))"
            groups = [("Digits before the point", _band(b, 15), "k"), ("Places after the point", _band(a, 9), "k"),
                      ("Before · after", f"({_band(b, 15)}) || ' · ' || ({_band(a, 9)})", "n")]
        elif spec.kind in ("date", "timestamp"):
            con.execute(f"CREATE TEMP VIEW t AS SELECT v FROM (SELECT try_cast({c} AS TIMESTAMP) AS v FROM prof) "
                        "WHERE v IS NOT NULL")
            groups = [("Year", "CAST(year(v) AS VARCHAR)", "k"), ("Month", "month(v)", "m"),
                      ("Weekday", "isodow(v)", "w")]
            if spec.kind == "timestamp":
                groups.append(("Hour", "lpad(CAST(hour(v) AS VARCHAR), 2, '0')", "k"))
        else:
            con.execute(f"CREATE TEMP VIEW t AS SELECT CAST({c} AS VARCHAR) AS v FROM prof WHERE {c} IS NOT NULL AND {c} <> ''")
            groups = [(f"First {n} characters", f"left(v, {n})", "n"), (f"Last {n} characters", f"right(v, {n})", "n")]
        out = []
        for title, expr, order in groups:
            rows = con.execute(f"SELECT {expr} AS k, count(*) AS n FROM t GROUP BY k").fetchall()
            total = sum(int(m) for _, m in rows)
            if order == "n":
                rows = sorted(rows, key=lambda r: (-r[1], str(r[0])))[:PART_TOP]
            elif order == "k":
                rows = sorted(rows, key=lambda r: (len(str(r[0]).split("-")[0].rstrip("+")), str(r[0])))
            else:
                rows = sorted(rows)
            name = (lambda k: MONTHS[int(k) - 1]) if order == "m" else (lambda k: WEEKDAYS[int(k) - 1]) if order == "w" else str
            out.append({"title": title, "total": total, "rows": [{"label": name(k), "n": int(m)} for k, m in rows]})
    finally:
        con.close()
    return out


@router.get("/parts")
def column_parts(column: str = Query(..., max_length=1000), n: int = Query(3, ge=1, le=10),
                 ws: Workspace = Depends(workspace)) -> dict:
    """One column taken apart for its detail - read-only, counted in DuckDB on the loaded table."""
    _, prof, _ = _held(ws)
    spec = next((ColSpec(**s) for s in prof.get("specs", []) if s["canon"] == column), None)
    if spec is None:
        raise HTTPException(404, f"No column called {column} in this profile.")
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    if spec.kind not in ("number", "date", "timestamp", "text"):
        return {"column": column, "kind": spec.kind, "groups": []}
    return {"column": column, "kind": spec.kind, "groups": parts(P, spec, read_options(ws), n)}


@router.get("/profile.csv")
def profile_csv(name: str = Query("", max_length=200), ws: Workspace = Depends(workspace)) -> Response:
    _, prof, _ = _held(ws)
    fname = f"{profiling.file_stem(_name(name))}__profile.csv"
    return Response(profiling.csv_bytes(prof["stats"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/save")
def save(body: SaveIn, ws: Workspace = Depends(workspace)) -> dict:
    """The six files written into the folder typed - no browser involved, the reliable route."""
    _, prof, made = _held(ws)
    name = _name(body.name)
    run = _run(name, made)
    try:
        target, written = profiling.save_files(profiling.profile_files(prof, name), body.folder, run)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ws.data["save_dir"] = profiling.save_base_after(target, run)
    return {"text": profiling.saved_line(target, written), "folder": str(target)}
