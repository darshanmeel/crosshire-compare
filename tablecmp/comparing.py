# tablecmp/comparing.py
"""A comparison with no page attached - what compare_app.py and the React server both call: the
page's own switches, the engine's cfg, the status strip, one run and the files it leaves behind,
and Auto. The column table's parts, the switches of How values are read and the profile key are
phase 3's (setup.py, keying.py)."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd

from .auto import auto_configure
from .columns import specs_from
from .compare import build_filters, column_rules, discard_run, run_comparison
from .keying import profile_key_for
from .outputs import pair_name, table_formats, verdict_of, write_parquet_copies, write_summary
from .report import build_report
from .setup import Setup
from .sources import Side
from .values import ColSpec, ReadOptions

Said = list[tuple[str, str]]          # (tone, sentence) - tone is error | warning | info | success

# the Compare section's own switches and Auto's tick, beside phase 3's (setup.SETTINGS_DEFAULT)
PAGE_DEFAULTS = {"display_rows": 1000, "auto_rerun": False, "out_fmt": "", "auto_profile": False}
NOTHING_PAIRED = "Nothing is paired yet - pick a counterpart for at least one column in the table."
TICK_COMPARE = "Tick **Compare** on at least one column in the table."
STILL_SHOWN = " - the previous result is still shown below."


# ---- switches --------------------------------------------------------------------------
def default_out_fmt() -> str:
    """The Tables as switch before anyone touches it: what COMPARE_TABLE_FORMATS asks for."""
    env = table_formats()
    return "both" if {"csv", "parquet"} <= env else "parquet" if "parquet" in env else "csv"


def page_settings(settings: dict) -> dict:
    """setup.settings_of's switches, with the Compare section's own filled in where they are unset."""
    s = {**PAGE_DEFAULTS, **{k: v for k, v in settings.items() if v is not None}}
    s["out_fmt"] = s["out_fmt"] or default_out_fmt()
    return s


def values_of(settings: dict) -> dict:
    """How values are read, as the engine's cfg carries them."""
    return {"trim": bool(settings["trim"]), "empty_as_null": bool(settings["empty_as_null"]),
            "ignore_case": bool(settings["ignore_case"]), "tolerance": float(settings["tolerance"]),
            "null_tokens": settings["null_tokens"]}


def mode_of(keys: list[str], nokey_mode: str) -> str:
    """How rows are paired: on the key when there is one, else hashing or position."""
    return "key" if keys else nokey_mode


# ---- the engine's cfg ----------------------------------------------------------------
def filters_of(rows: pd.DataFrame | None, NA: str, NB: str,
               specs: list[ColSpec]) -> tuple[tuple[dict, dict, dict], str]:
    """The Rows filters as the engine takes them - or none, and the sentence why not."""
    if rows is None:
        return ({}, {}, {}), ""
    try:
        return build_filters(rows, NA, NB, specs), ""
    except ValueError as exc:
        return ({}, {}, {}), str(exc)


def pending_cfg(setup: Setup, NA: str, NB: str, mode: str, values: dict, filters: tuple[dict, dict, dict],
                notes: list[str] | None, out_fmt: str | None, display_rows: int) -> dict:
    """What the engine is told - every setting the run takes, display-only ones included
    (compare.DISPLAY_KEYS keeps those out of the signature)."""
    both_f, left_f, right_f = filters
    return {"name": pair_name(NA, NB), "notes": list(notes or []),
            "table_formats": sorted(table_formats(out_fmt)),
            "matched_by": {str(r["Common name"]): str(r["Matched by"]) for _, r in setup.cmap.iterrows()
                           if r["A column"] and r["B column"]},
            "mode": mode, "keys": setup.keys, "specs": [asdict(s) for s in setup.specs],
            "compare_columns": setup.compare, "only_a": list(setup.only_a), "only_b": list(setup.only_b),
            **values, "column_rules": column_rules(setup.specs, setup.compare),
            "filters": both_f, "left_filters": left_f, "right_filters": right_f,
            "display_rows": int(display_rows)}


# ---- the status strip ----------------------------------------------------------------
def _strip(files: str, columns: str, key: str, compare: str, result: str, tones: dict) -> dict:
    return {"cells": {"Files": files, "Columns": columns, "Key": key, "Compare": compare, "Result": result},
            "tones": tones}


def strip_cells(A: Side, B: Side, NA: str, NB: str, setup: Setup | None = None, mode: str = "",
                run: dict | None = None, stale: bool = False) -> dict:
    """The strip's five cells and their tones, for the place the Compare page stops: not loaded,
    nothing paired or no mode yet, nothing ticked, no run, or a run - stale or not."""
    if not (A.loaded and B.loaded):
        n = sum(1 for s in (A, B) if s.loaded)
        return _strip(f"{n} of 2 loaded", "-", "-", "-", "-", {"Files": "warn"})
    s = setup or Setup(None, [], [], [], [], [])
    files = f"{NA} {A.rows or 0:,} · {NB} {B.rows or 0:,} rows"
    cols = f"{len(s.specs)} paired · {len(s.only_a) + len(s.only_b)} one-sided"
    key_tone = "" if s.keys else "warn"
    if not s.specs or not mode:
        return _strip(files, cols, " + ".join(s.keys) if s.keys else "none", f"{len(s.compare)} columns",
                      "not run", {"Key": key_tone, "Columns": "" if s.specs else "warn"})
    key = " + ".join(s.keys) if s.keys else f"none - {mode}"
    if not s.compare:
        return _strip(files, cols, key, "none", "not run", {"Compare": "warn"})
    compare = f"{len(s.compare)} columns"
    if run is None:
        return _strip(files, cols, key, compare, "press Compare", {"Result": "warn", "Key": key_tone})
    res = run["result"]
    tone = (run.get("verdict") or verdict_of(res, run["mode"])).tone
    result = "identical" if tone == "ok" else f"{res.diff_rows:,} differ · {res.only_left + res.only_right:,} one-sided"
    return _strip(files, cols, key, compare, result + (" · stale" if stale else ""),
                  {"Result": "warn" if stale else tone, "Key": key_tone})


# ---- one run -------------------------------------------------------------------------
class CompareFailed(Exception):
    """The run did not take the shown one's place - the message says why, in a sentence."""


def close_run(run: dict | None) -> None:
    """A run's DuckDB connection, closed - once nothing will read the run again."""
    con = (run or {}).get("con")
    if con is not None:
        try:
            con.close()
        except duckdb.Error:
            pass


def write_outputs(run: dict, cfg: dict, A: Side, B: Side, NA: str, NB: str, profile: dict | None = None,
                  strict: bool = False) -> Said:
    """The report, the config, the summary sheets and the Parquet copies land in the run folder
    right away, so Save everything and the zip always hold the full set. The paired rows are the
    exception - they are written when they are asked for. On the page a failure is a warning
    (`strict` False); the command line raises."""
    said: Said = []
    folder, pair = Path(run["folder"]), run["pair"]
    limit = int(cfg["display_rows"])
    try:
        html = build_report(run, A, B, NA, NB, limit=min(limit, 2000), notes=cfg.get("notes") or [],
                            profile=profile)
        run["_report"] = html
        run["_report_key"] = ("report", run["at"], limit)
        (folder / f"{pair}__report.html").write_text(html, encoding="utf-8", newline="\n")
    except Exception as exc:                 # whatever it is, the run is made - the page says what is missing
        if strict:
            raise
        said.append(("warning", f"The report could not be written to the run folder: {exc}"))
    if run.get("config"):                    # rerun it from the command line, or load it on the page
        from .runconfig import config_json
        try:
            (folder / f"{pair}__config.json").write_text(config_json(run["config"]), encoding="utf-8",
                                                         newline="\n")
        except OSError as exc:
            if strict:
                raise
            said.append(("warning", f"The config could not be written to the run folder: {exc}"))
    try:
        write_summary(run, A, B, NA, NB, notes=cfg.get("notes") or [], profile=profile)
        if "parquet" in cfg.get("table_formats", []):
            write_parquet_copies(run)
    except Exception as exc:                 # whatever it is, the run is made - the page says what is missing
        if strict:
            raise
        said.append(("warning", f"The summary files could not be written to the run folder: {exc}"))
    return said


def compare_once(A: Side, B: Side, NA: str, NB: str, cfg: dict, opts: ReadOptions, sig: str,
                 old: dict | None, profile: dict | None, config: dict | None,
                 say: Callable[[str], None]) -> tuple[dict, Said]:
    """One comparison. The new run takes the old one's place (its folder and connection go) and
    its outputs are written. When the engine fails the old run stays, and CompareFailed says why."""
    still = STILL_SHOWN if old else ""
    try:
        new = run_comparison(A, B, cfg, opts, sig, previous=old, progress=say, names=(NA, NB))
    except (duckdb.Error, RuntimeError, ValueError, KeyError) as exc:
        raise CompareFailed(f"The comparison failed: {exc}{still}") from exc
    if new["result"].error:
        discard_run(new)
        close_run(new)
        raise CompareFailed(f"The engine reported: {new['result'].error}{still}")
    discard_run(old)                         # only now is it safe to drop the old files
    close_run(old)
    new["config"] = config
    return new, write_outputs(new, cfg, A, B, NA, NB, profile=profile)


# ---- Auto ----------------------------------------------------------------------------
@dataclass
class AutoDone:
    cmap: pd.DataFrame
    notes: list[str]
    chosen: list[str]
    profile: tuple[str, dict] | None        # (profile key, profile) when one fed the key search
    key_formats: tuple | None               # (key columns, [(Fix, applied?)]) for the Key section
    seconds: float

    @property
    def label(self) -> str:
        return (f"Worked out in {self.seconds:.1f}s - key: "
                + (" + ".join(self.chosen) if self.chosen else "none, hashing") + " - comparing now")


def key_formats_of(fixes: list) -> tuple | None:
    return (tuple(dict.fromkeys(f.canon for f in fixes)), [(f, f.simple) for f in fixes]) if fixes else None


def decisions_label(notes: list[str]) -> str:
    return f"{len(notes)} decisions - every one a cell in the column table"


def auto_stopped(exc: Exception) -> str:
    return f"Auto stopped: {exc}"


def run_auto(A: Side, B: Side, NA: str, NB: str, opts: ReadOptions, say: Callable[[str], None],
             before: dict | None = None, want_profile: bool = False) -> AutoDone:
    """Pair the columns, type them, pick the key, profile when asked - auto.auto_configure, with
    `before`, the profile held while it is current, reused for the key search."""
    t0 = time.perf_counter()
    fixes: list = []
    new_map, notes, chosen, made = auto_configure(A, B, NA, NB, opts, say, profile=before,
                                                  want_profile=want_profile, found_fixes=fixes)
    prof = (profile_key_for(A, B, specs_from(new_map), opts), made) if made is not None else None
    return AutoDone(new_map, notes, chosen, prof, key_formats_of(fixes), time.perf_counter() - t0)
