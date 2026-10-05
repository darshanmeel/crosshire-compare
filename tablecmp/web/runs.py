# tablecmp/web/runs.py
"""The comparison a workspace holds - the run (with its DuckDB connection), the engine's cfg
worked out from phase 3's column table, names, switches and filters, whether the run is stale -
and Compare and Auto as jobs. The engine's objects stay here; the page gets a view of them."""
from __future__ import annotations

import hashlib
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import duckdb
import pandas as pd
from fastapi import HTTPException

from .. import comparing, results
from .. import setup as su
from ..compare import signature
from ..runconfig import make_config
from . import jobs
from . import setupws as sw
from .sides import side
from .workspace import Workspace

PAGE_SETTINGS = ("display_rows", "auto_rerun", "out_fmt", "auto_profile")
LOAD_FIRST = "Load A and B in the sidebar first."
BUSY = "A comparison or Auto is running already - wait for it to finish."
REPLACED = "This run is not the one on the page any more - the page shows the newest run."
GATE_SAID = {"load": LOAD_FIRST, "pair": comparing.NOTHING_PAIRED, "tick": comparing.TICK_COMPARE}
RUN_KINDS = ("Compare", "Auto", "Config")
_starting = threading.Lock()          # one check-then-start at a time, across request threads


def settings(ws: Workspace) -> dict:
    return comparing.page_settings(sw.settings(ws))


def current(ws: Workspace) -> dict | None:
    return ws.data.get("result")


def filters_now(ws: Workspace) -> pd.DataFrame | None:
    """The Rows filters a run takes - setupws.filter_rows once the table has its looks-like sample,
    else the rows as held: building that sample takes ws.lock, which the state route never waits on."""
    if "looks_like" in ws.data:
        return sw.filter_rows(ws)
    return ws.data.get("filter_rows")


@dataclass
class Plan:
    """What Compare would run now - or the gate it stops at, and why."""
    NA: str
    NB: str
    setup: su.Setup
    mode: str = ""
    cfg: dict | None = None
    sig: str = ""
    filter_error: str = ""
    gate: str = ""                    # "" | "load" | "pair" | "tick"


def plan(ws: Workspace) -> Plan:
    A, B = side(ws, "A"), side(ws, "B")
    NA, NB = sw.names(ws)
    cmap = ws.data.get("cmap")
    s_up = su.setup_of(cmap) if cmap is not None else su.Setup(None, [], [], [], [], [])
    if not (A.loaded and B.loaded):
        return Plan(NA, NB, su.Setup(None, [], [], [], [], []), gate="load")
    if not s_up.specs:
        return Plan(NA, NB, s_up, gate="pair")
    s = settings(ws)
    mode = comparing.mode_of(s_up.keys, s["nokey_mode"])
    if not s_up.compare:
        return Plan(NA, NB, s_up, mode, gate="tick")
    filters, error = comparing.filters_of(filters_now(ws), NA, NB, s_up.specs)
    cfg = comparing.pending_cfg(s_up, NA, NB, mode, comparing.values_of(s), filters,
                                ws.data.get("auto_notes"), s["out_fmt"], s["display_rows"])
    return Plan(NA, NB, s_up, mode, cfg, signature(A, B, cfg), error)


def running(ws: Workspace, kinds: tuple[str, ...] = RUN_KINDS) -> bool:
    return any(e["state"] == "running" and e["kind"] in kinds for e in list(ws.running.values()))


def _short(sig: str) -> str:
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12] if sig else ""


def run_view(run: dict, stale: bool, fallback: tuple[str, str]) -> dict:
    NA, NB = run.get("names") or fallback
    res = run["result"]
    v = results.verdict_parts(run, NA, NB)
    return {"id": run["run_id"], "at": run["at"], "pair": run["pair"], "mode": run["mode"], "names": [NA, NB],
            "keys": results.run_keys(run), "columns": results.run_columns(run), "matched": res.matched_rows,
            "diff_rows": res.diff_rows, "stale": stale,
            "verdict": {"tone": v["tone"], "word": v["word"], "when": v["when"],
                        "segments": [{"text": t, "bold": b} for t, b in v["segments"]]}}


def state_view(ws: Workspace) -> dict:
    """Where the comparison stands, for the page: the gate, the strip, the switches, stale or
    not, what the last run said, and the run itself. Takes no lock - the page polls it while a
    job runs."""
    p = plan(ws)
    run = current(ws) if p.gate == "" else None
    stale = bool(run) and run.get("signature") != p.sig
    s = settings(ws)
    return {"gate": p.gate, "names": [p.NA, p.NB],
            "strip": comparing.strip_cells(side(ws, "A"), side(ws, "B"), p.NA, p.NB, p.setup, p.mode, run, stale),
            "settings": {k: s[k] for k in PAGE_SETTINGS}, "filter_error": p.filter_error, "sig": _short(p.sig),
            "stale": stale, "busy": running(ws),
            "said": [{"tone": t, "text": x} for t, x in ws.data.get("compare_said") or []],
            "run": run_view(run, stale, (p.NA, p.NB)) if run else None}


def report_profile(ws: Workspace) -> dict | None:
    """The profile the report is handed - the one held, as the Streamlit page did."""
    prof = ws.data.get("profile")
    return prof[1] if prof else None


# ---- jobs ------------------------------------------------------------------------------
def start_guarded(ws: Workspace, start: Callable[[], dict]) -> dict:
    """Start a Compare or Auto - unless one is running already (or a config is loading)."""
    with _starting:
        if running(ws):
            raise HTTPException(409, BUSY)
        return start()


def start_compare(ws: Workspace) -> dict:
    """Compare as a job. What it runs is worked out under the lock, when the job starts - after
    Auto or a config before it has settled the table."""
    def work(ctx: jobs.JobCtx) -> str:
        ws.data["compare_said"] = []
        p = plan(ws)
        problem = GATE_SAID.get(p.gate) or p.filter_error
        if problem:
            ws.data["compare_said"] = [("error", problem)]
            raise RuntimeError(problem)
        A, B = side(ws, "A"), side(ws, "B")
        opts = su.read_options(settings(ws))
        config = make_config(p.cfg, A, B, p.NA, p.NB, ws.data["cmap"], filters_now(ws))
        t0 = time.perf_counter()
        try:
            run, said = comparing.compare_once(A, B, p.NA, p.NB, p.cfg, opts, p.sig, current(ws),
                                               sw.current_profile(ws), config, ctx.say)
        except comparing.CompareFailed as exc:
            ws.data["compare_said"] = [("error", str(exc))]
            raise
        run["names"] = (p.NA, p.NB)
        ws.data["result"] = run
        ws.data["compare_said"] = said
        ctx.label = f"Compared in {time.perf_counter() - t0:.1f}s"
        return run["run_id"]

    return jobs.start(ws, "Compare", "Comparing…", work, page="Compare")


def start_auto(ws: Workspace) -> dict:
    """Auto as a job: the column table worked out from the data and put in place as a new version
    (setupws.put_table), its decisions noted in the Log, then a Compare started - it waits for this
    job's lock, and compares what Auto settled on."""
    def work(ctx: jobs.JobCtx) -> int:
        ws.data["compare_said"] = []
        A, B = side(ws, "A"), side(ws, "B")
        if not (A.loaded and B.loaded):
            raise RuntimeError(LOAD_FIRST)
        NA, NB = sw.names(ws)
        s = settings(ws)
        try:
            done = comparing.run_auto(A, B, NA, NB, su.read_options(s), ctx.say, before=sw.current_profile(ws),
                                      want_profile=bool(s["auto_profile"]))
        except (duckdb.Error, RuntimeError) as exc:
            said = comparing.auto_stopped(exc)
            ws.data["compare_said"] = [("error", said)]
            raise RuntimeError(said) from None
        sw.put_table(ws, done.cmap, drop=True)         # profile, key report, suggestions, data match go
        ws.data.update(cmap_seed=su.seed_key(A, B), auto_notes=done.notes, key_formats=done.key_formats)
        if done.profile is not None:
            ws.data["profile"] = done.profile
        jobs.note(ws, "Auto decisions", comparing.decisions_label(done.notes), done.notes)
        ctx.label = done.label
        start_compare(ws)
        return len(done.notes)

    return jobs.start(ws, "Auto", "Working it out…", work, page="Compare")


# ---- what the results routes share --------------------------------------------------------
def run_of(ws: Workspace, run_id: str) -> dict:
    """The run on the page - asked for by its id, so an old tab never reads a newer run."""
    run = current(ws)
    if run is None or run["run_id"] != run_id:
        raise HTTPException(404, REPLACED)
    return run


@contextmanager
def guard(run: dict, view: str) -> Iterator[None]:
    """An engine error while a view is built, said in a sentence: the folder swept, or the reason."""
    try:
        yield
    except (duckdb.Error, KeyError, ValueError, OSError) as exc:
        if not Path(run["folder"]).exists():
            raise HTTPException(410, results.GONE) from exc
        raise HTTPException(400, f"Could not build the {view} view: {exc}") from exc
