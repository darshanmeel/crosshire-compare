# tablecmp/web/routes_downloads.py
"""The run's files: the report (for the viewer, or to download), each file by its name, the
paired rows, the zip and the Parquet copies on request, and saves to a folder on this machine.
A file is served only by an exact name the run lists - never a path."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .. import results as rs
from ..compare import cd_occ, cells_table, have_paired, join_on, pair_views, paired_path, row_key
from ..outputs import default_save_folder, write_parquet_copies, zip_run
from ..sql import ident
from . import runs
from . import setupws as sw
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/results")
NO_SCRIPTS = {"Content-Security-Policy": "script-src 'none'"}   # the report has none; served here, it never may


class SaveIn(BaseModel):
    what: Literal["report", "config", "all"]
    folder: str = Field("", max_length=1024)


def report_html(ws: Workspace, run: dict, limit: int | None = None) -> str:
    NA, NB = run["names"]
    rows = int(limit or runs.settings(ws)["display_rows"])
    return rs.ensure_report(run, side(ws, "A"), side(ws, "B"), NA, NB, rows, runs.report_profile(ws))


def _sized(p: Path | None) -> dict | None:
    return {"name": p.name, "bytes": p.stat().st_size} if p is not None and p.exists() else None


def files_view(ws: Workspace, run: dict) -> dict:
    """What Downloads shows: the config on its own row, every other file, the paired rows and the
    zip when they are there, the Tables as switch, and the folder a save goes to by default."""
    NA, NB = run["names"]
    report_html(ws, run)                       # the report listed is the one for the rows shown now
    base = Path(ws.data.get("save_dir") or rs.default_save_base(side(ws, "A")))
    z = run.get("zip")
    return {"config": _sized(rs.config_path(run)), "engine": _sized(rs.engine_path(run)),
            "engine_gone": rs.engine_gone(run), "report": f"{run['pair']}__report.html",
            "files": rs.download_rows(run, NA, NB), "paired": have_paired(run),
            "zip": _sized(Path(z)) if z else None,
            "parquet": any(p.suffix == ".parquet" for p in run["files"].values()),
            "out_fmt": runs.settings(ws)["out_fmt"], "save_folder": str(default_save_folder(run, base))}


@router.get("/{run_id}/files")
def files(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Downloads"):
            return files_view(ws, run)


@router.get("/{run_id}/report")
def report(run_id: str, limit: int | None = Query(None, ge=100, le=10_000), download: bool = False,
           ws: Workspace = Depends(workspace)) -> HTMLResponse:
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Report"):
            html = report_html(ws, run, limit)
    headers = dict(NO_SCRIPTS)
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{run["pair"]}__report.html"'
    return HTMLResponse(html, headers=headers)


@router.get("/{run_id}/file/{name}")
def one_file(run_id: str, name: str, ws: Workspace = Depends(workspace)) -> FileResponse:
    with ws.lock:
        run = runs.run_of(ws, run_id)
        if not Path(run["folder"]).exists():
            raise HTTPException(410, rs.GONE)
        path = run["files"].get(name)
        z = run.get("zip")
        if path is None and z and Path(z).name == name:
            path = Path(z)
        if path is None or not Path(path).is_file():
            raise HTTPException(404, f"This run has no file called {name}.")
    p = Path(path)
    return FileResponse(p, filename=p.name, media_type=rs.MIME.get(p.suffix, "application/octet-stream"))


@router.post("/{run_id}/paired")
def write_paired(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    """The paired rows - every matched row, both sides beside each other - written when asked for."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Downloads"):
            paired_path(run)
            return files_view(ws, run)


@router.post("/{run_id}/zip")
def write_zip(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    """Every file of the run in one archive beside the run folder - the paired rows written first."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Downloads"):
            paired_path(run)
            zip_run(run)
            return files_view(ws, run)


@router.post("/{run_id}/parquet")
def write_parquet(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    """Parquet copies of the run's tables, the paired rows among them - the zip goes, to be rebuilt."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Downloads"):
            paired_path(run)
            write_parquet_copies(run)
            return files_view(ws, run)


@router.post("/{run_id}/save")
def save(run_id: str, body: SaveIn, ws: Workspace = Depends(workspace)) -> dict:
    """The report, the config, or everything (the paired rows written first), copied into a folder
    on this machine - under COMPARE_OUT_DIR when it is set."""
    if not body.folder.strip():
        raise HTTPException(400, rs.SAVE_BLANK)
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Downloads"):
            if body.what == "report":
                chosen: dict = {f"{run['pair']}__report.html": report_html(ws, run).encode("utf-8")}
            elif body.what == "config":
                p = rs.config_path(run)
                if p is None:
                    raise HTTPException(404, "This run has no config file.")
                chosen = {p.name: p}
            else:
                report_html(ws, run)
                chosen = {p.name: p for p in run["files"].values() if p.exists()}
                chosen.update(rs.paired_first(run))
            try:
                target, written = rs.save_files(chosen, body.folder, run)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            ws.data["save_dir"] = rs.save_base_after(target, run)
            return {"tone": "success", "text": rs.saved_line(target, written), "files": files_view(ws, run)}


def diff_rows_body(run: dict, offset: int, limit: int, column: str) -> dict:
    """A page of the rows that paired but differ, the most differing cells first (then file order):
    each row twice - A, then B - under a Side column, with the key, every compared column and the
    columns only one side has (A's on the A row, B's on the B row), plus the columns that differ
    on each pair. `column` keeps the rows where that column differs."""
    res = run["result"]
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    sided = run.get("one_sided") or {}
    only_a, only_b = list(sided.get("A") or []), list(sided.get("B") or [])
    cells = f"{run['pair']}__cell_diffs.csv"
    by_col = sorted(((c, int(res.diffs_by_column.get(c, 0))) for c in cols if res.diffs_by_column.get(c, 0)),
                    key=lambda x: (-x[1], x[0]))
    out: dict = {"keys": keys, "columns": cols, "only_a": only_a, "only_b": only_b,
                 "by_column": [{"column": c, "n": n} for c, n in by_col], "column": column,
                 "total": 0, "offset": offset, "frame": {"columns": [], "rows": []}, "marks": [], "cells": [],
                 "file": cells if cells in run["files"] else "", "note": ""}
    if column and column not in cols:
        raise HTTPException(404, f"This run did not compare a column called {column}.")
    if run["mode"] == "hash":
        out["note"] = ("With hashing there are no matched-but-different rows: a row is either identical "
                       "on the other side or one-sided.")
        return out
    if not keys:
        out["note"] = "Rows were paired by position - the cells that differ are in the cell differences file."
        return out
    if not res.diff_rows or not cells_table(run):
        return out
    con = run["con"]
    pair_views(run, keys)
    occ = cd_occ(run)
    having = " HAVING list_contains(list(column_name), ?)" if column else ""
    params: list = [column] if column else []
    m = (f"SELECT {row_key(keys, '', occ)} AS rk, count(DISTINCT column_name) AS n, "
         f"list_distinct(list(column_name)) AS cs FROM cd GROUP BY 1{having}")
    out["total"] = int(con.execute(f"SELECT count(*) FROM ({m})", params).fetchone()[0])
    sel = ", ".join([f"l.{ident(k)} AS {ident('k_' + k)}" for k in keys]
                    + [f"l.{ident(c)} AS {ident('l_' + c)}" for c in cols]
                    + [f"r.{ident(c)} AS {ident('r_' + c)}" for c in cols]
                    + [f"l.{ident(c)} AS {ident('oa_' + c)}" for c in only_a]
                    + [f"r.{ident(c)} AS {ident('ob_' + c)}" for c in only_b]
                    + ["m.n AS __n", "m.cs AS __cs"])
    df = con.execute(
        f"SELECT {sel} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} "
        f"JOIN ({m}) m ON {row_key(keys, 'l.', '__occ' if occ else None)} = m.rk "
        f"ORDER BY m.n DESC, l.__rn LIMIT ? OFFSET ?", params + [int(limit), int(offset)]).fetchdf()
    rows, marks, counts = [], [], []
    for _, row in df.iterrows():
        kv = [row[f"k_{k}"] for k in keys]
        rows.append(["A", *kv, *(row[f"l_{c}"] for c in cols), *(row[f"oa_{c}"] for c in only_a), *([None] * len(only_b))])
        rows.append(["B", *kv, *(row[f"r_{c}"] for c in cols), *([None] * len(only_a)), *(row[f"ob_{c}"] for c in only_b)])
        marks.append(sorted(str(c) for c in row["__cs"]))
        counts.append(int(row["__n"]))
    out["frame"] = sw.frame(pd.DataFrame(rows, columns=["Side", *keys, *cols, *only_a, *only_b]))
    out["marks"], out["cells"] = marks, counts
    return out


@router.get("/{run_id}/diff-rows")
def diff_rows(run_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=10_000),
              column: str = "", ws: Workspace = Depends(workspace)) -> dict:
    """The Differing rows tab, a page at a time - read-only, from the run's own tables."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Differing rows"):
            return diff_rows_body(run, offset, limit, column)
