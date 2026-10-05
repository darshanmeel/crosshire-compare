# tablecmp/web/routes_compare.py
"""The Compare section's routes: where the comparison stands, the settings it keeps, and Compare
and Auto as jobs. The names are the Name boxes the page PUTs to /api/setup/names (phase 3)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import jobs, runs
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api")


class SettingsIn(BaseModel):
    display_rows: int | None = Field(None, ge=100, le=10_000)
    auto_rerun: bool | None = None
    out_fmt: Literal["csv", "parquet", "both"] | None = None
    auto_profile: bool | None = None


@router.get("/compare")
def compare_state(ws: Workspace = Depends(workspace)) -> dict:
    return runs.state_view(ws)


@router.put("/compare/settings")
def put_settings(body: SettingsIn, ws: Workspace = Depends(workspace)) -> dict:
    """Rows to display, Re-run on every change, Tables as and Auto's tick - kept beside phase 3's
    switches in ws.data["settings"]. None of them makes a run stale."""
    with ws.lock:
        ws.data["settings"] = {**(ws.data.get("settings") or {}), **body.model_dump(exclude_none=True)}
    s = runs.settings(ws)
    return {k: s[k] for k in runs.PAGE_SETTINGS}


@router.post("/compare")
def start_compare(ws: Workspace = Depends(workspace)) -> dict:
    p = runs.plan(ws)
    if p.gate:
        raise HTTPException(409, runs.GATE_SAID[p.gate])
    if p.filter_error:
        raise HTTPException(400, p.filter_error)
    return jobs.public(runs.start_guarded(ws, lambda: runs.start_compare(ws)))


@router.post("/auto")
def start_auto(ws: Workspace = Depends(workspace)) -> dict:
    if not (side(ws, "A").loaded and side(ws, "B").loaded):
        raise HTTPException(409, runs.LOAD_FIRST)
    return jobs.public(runs.start_guarded(ws, lambda: runs.start_auto(ws)))
