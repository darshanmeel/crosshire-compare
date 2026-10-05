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
from ..sql import ident, scratch
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
