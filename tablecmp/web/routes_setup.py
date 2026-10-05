# tablecmp/web/routes_setup.py
"""The Compare page's setup over HTTP: the column table (a cell at a time), Match by data, Reset,
Save and Load mapping, the setup card - then Transform and convert, How values are read, the Rows
filters, the Key section and Profile both files."""
from __future__ import annotations

from typing import Literal

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .. import keying as kg
from .. import setup as su
from ..columns import with_added, without_added
from ..sources import add_derived, drop_derived
from ..columns import apply_mapping_json, build_table, mapping_json, match_columns_by_data, pair_rows
from ..compare import OPS
from ..keys import key_uniqueness, suggest_keys
from ..loading import BLANK_FILTER, FILTER_COLS
from ..profile import profile_tables
from ..values import (FORMAT_PRESETS, NUMERIC_PARAMS, PARAM_LABELS, STEPS, TYPES, conversion_report,
                      function_catalog, try_steps)
from . import jobs
from . import setupws as sw
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/setup")


class NamesIn(BaseModel):
    A: str = ""
    B: str = ""


class CellIn(BaseModel):
    rev: str
    row: int
    column: str
    value: str | bool = ""


class MappingIn(BaseModel):
    text: str


@router.get("")
def get_setup(ws: Workspace = Depends(workspace)) -> dict:
    return sw.setup_view(ws)


@router.put("/names")
def put_names(body: NamesIn, ws: Workspace = Depends(workspace)) -> dict:
    """The Name boxes, as typed in the side panels - the table's headers and the card use them."""
    ws.data["names"] = {"A": body.A, "B": body.B}
    return sw.setup_view(ws)


@router.post("/cell")
def edit_cell(body: CellIn, ws: Workspace = Depends(workspace)) -> dict:
    """One cell of the column table changed; the table comes back whole - rows may have moved."""
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        sw.check_rev(ws, body.rev)
        try:
            new, reshaped = su.edit_cell(sw.table(ws), ws.data.get("looks_like"), A, B, body.row,
                                         body.column, body.value)
        except (ValueError, IndexError) as exc:
            raise HTTPException(400, str(exc)) from exc
        sw.put_table(ws, new, drop=reshaped)
    return sw.setup_view(ws)


@router.post("/match")
def match_by_data(ws: Workspace = Depends(workspace)) -> dict:
    """Reads a sample of both files and pairs the unpaired columns that hold the same values."""
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        NA, NB = sw.names(ws)
        s = su.setup_of(sw.table(ws))
        if not (s.only_a and s.only_b):
            raise HTTPException(400, "Both sides need a column with no partner first.")
        try:
            ws.data["data_match"] = match_columns_by_data(A, B, s.only_a, s.only_b, NA, NB, sw.opts(ws))
        except duckdb.Error as exc:
            raise HTTPException(400, f"Could not compare the values: {exc}") from exc
    return sw.setup_view(ws)


@router.post("/match/apply")
def apply_match(ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        dm = ws.data.get("data_match")
        if dm is None:
            raise HTTPException(409, "There is no Match by data result to apply.")
        new = pair_rows(sw.table(ws), dm[1], A, B, looks=ws.data.get("looks_like"))
        sw.put_table(ws, new, drop=True)            # drops data_match too
    return sw.setup_view(ws)


@router.delete("/match")
def dismiss_match(ws: Workspace = Depends(workspace)) -> dict:
    with ws.lock:
        ws.data.pop("data_match", None)
    return sw.setup_view(ws)


@router.post("/reset")
def reset(ws: Workspace = Depends(workspace)) -> dict:
    """Reset to name matches: the table as a new pair of files gets it."""
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        sw.table(ws)
        sw.put_table(ws, build_table(A, B, ws.data.get("looks_like")), drop=True)
    return sw.setup_view(ws)


@router.get("/mapping")
def save_mapping(ws: Workspace = Depends(workspace)) -> Response:
    """Save mapping: the pairs, types, keys and steps as mapping.json."""
    sw.sides(ws)
    return Response(mapping_json(sw.table(ws)), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="mapping.json"'})


@router.post("/mapping")
def load_mapping(body: MappingIn, ws: Workspace = Depends(workspace)) -> dict:
    """Load mapping: every pair in the file whose columns both sides have."""
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        sw.table(ws)
        try:
            new = apply_mapping_json(body.text, A, B, ws.data.get("looks_like"))
        except (ValueError, KeyError, AttributeError, TypeError) as exc:
            raise HTTPException(400, f"Could not read the mapping file: {exc}") from exc
        sw.put_table(ws, new, drop=True)
    return sw.setup_view(ws)


# ---- Values: How values are read, Transform and convert ------------------------------------
class SettingsIn(BaseModel):
    trim: bool | None = None
    empty_as_null: bool | None = None
    ignore_case: bool | None = None
    tolerance: float | None = Field(None, ge=0, le=1e9)
    null_tokens: str | None = None
    nokey_mode: Literal["hash", "position"] | None = None


class StepIn(BaseModel):
    op: str
    params: dict[str, str] = Field(default_factory=dict)


class StepsIn(BaseModel):
    canon: str
    which: Literal["A", "B"]
    action: Literal["add", "pop", "clear", "copy"]
    step: StepIn | None = None


class TypeIn(BaseModel):
    canon: str
    kind: str


class CanonIn(BaseModel):
    canon: str


class DerivedIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    a: str = Field("", max_length=4000)        # the DuckDB expression on A's columns; blank - A has none
    b: str = Field("", max_length=4000)


# Ready-made expressions for an added column; {c} is the column it is made from.
DERIVED_PRESETS = [
    {"id": "date", "label": "date from a datetime", "expr": "CAST(TRY_CAST({c} AS TIMESTAMP) AS DATE)"},
    {"id": "hour", "label": "hour from a datetime", "expr": "date_trunc('hour', TRY_CAST({c} AS TIMESTAMP))"},
    {"id": "minute", "label": "minute from a datetime", "expr": "date_trunc('minute', TRY_CAST({c} AS TIMESTAMP))"},
    {"id": "month", "label": "month (YYYY-MM)", "expr": "strftime(TRY_CAST({c} AS TIMESTAMP), '%Y-%m')"},
    {"id": "year", "label": "year", "expr": "year(TRY_CAST({c} AS TIMESTAMP))"},
    {"id": "upper", "label": "upper-cased, trimmed", "expr": "upper(trim(CAST({c} AS VARCHAR)))"},
    {"id": "round", "label": "number rounded to 2 places", "expr": "round(TRY_CAST({c} AS DOUBLE), 2)"},
]


@router.get("/derived")
def derived_meta() -> dict:
    return {"presets": DERIVED_PRESETS}


@router.post("/derived")
def add_column(body: DerivedIn, ws: Workspace = Depends(workspace)) -> dict:
    """A column made from an expression joins A, B or both, and the column table as its own
    pair - the key, the steps and the other pairs stay as they are."""
    A, B = sw.sides(ws)
    name, ea, eb = body.name.strip(), body.a.strip(), body.b.strip()
    if not name or any(ch in name for ch in ('"', chr(10))):
        raise HTTPException(400, "Give the column a name (no quotes).")
    if not (ea or eb):
        raise HTTPException(400, "Give an expression for at least one side.")
    NA, NB = sw.names(ws)
    for side, e, said in ((A, ea, NA), (B, eb, NB)):
        if e and name in side.schema:
            raise HTTPException(400, f"{said} already has a column called {name}.")
    with ws.lock:
        cmap = sw.table(ws)
        for side, e, said in ((A, ea, NA), (B, eb, NB)):
            if not e:
                continue
            try:
                add_derived(side, name, e)
            except Exception as exc:               # duckdb.Error, or a parse error DuckDB raises as another kind
                for s2 in (A, B):
                    drop_derived(s2, name) if name in s2.derived else None
                raise HTTPException(400, f"{said}: the expression does not read - {exc}") from exc
        ws.data["cmap_seed"] = su.seed_key(A, B)
        sw.put_table(ws, with_added(cmap, A, B, name, ws.data.get("looks_like")), drop=True)
    return sw.setup_view(ws)


@router.delete("/derived/{name}")
def drop_column(name: str, ws: Workspace = Depends(workspace)) -> dict:
    A, B = sw.sides(ws)
    if name not in A.derived and name not in B.derived:
        raise HTTPException(404, f"No added column called {name}.")
    with ws.lock:
        cmap = sw.table(ws)
        for side in (A, B):
            if name in side.derived:
                drop_derived(side, name)
        ws.data["cmap_seed"] = su.seed_key(A, B)
        sw.put_table(ws, without_added(cmap, A, B, name, ws.data.get("looks_like")), drop=True)
    return sw.setup_view(ws)


def _spec(ws: Workspace, canon: str):
    spec = su.spec_of(sw.table(ws), canon)
    if spec is None:
        raise HTTPException(404, f"No paired column called {canon}.")
    return spec


@router.get("/settings")
def get_settings(ws: Workspace = Depends(workspace)) -> dict:
    return sw.settings(ws)


@router.put("/settings")
def put_settings(body: SettingsIn, ws: Workspace = Depends(workspace)) -> dict:
    """Any of the switches - the rest stay as they were."""
    with ws.lock:
        ws.data["settings"] = {**(ws.data.get("settings") or {}), **body.model_dump(exclude_none=True)}
    return sw.settings(ws)


@router.get("/steps")
def steps_meta() -> dict:
    """What a step can be: each op's parameters and their labels, the date spellings, the Types."""
    return {"steps": {op: list(params) for op, (_, params) in STEPS.items()}, "labels": PARAM_LABELS,
            "numeric": sorted(NUMERIC_PARAMS), "presets": FORMAT_PRESETS, "types": TYPES}


@router.get("/functions")
def functions() -> dict:
    """DuckDB's own text, regex and date functions, for the custom expression step."""
    return sw.frame(function_catalog())


@router.post("/steps")
def change_steps(body: StepsIn, ws: Workspace = Depends(workspace)) -> dict:
    """Add, Remove last, Clear, or Copy to the other side - the steps one side of a pair is read with."""
    sw.sides(ws)
    if body.step is not None and body.step.op not in STEPS:
        raise HTTPException(400, f"No step called {body.step.op}.")
    with ws.lock:
        spec = _spec(ws, body.canon)
        try:
            which, steps = su.steps_after(spec, body.which, body.action,
                                          body.step.model_dump() if body.step else None)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        sw.put_table(ws, su.with_steps(sw.table(ws), body.canon, which, steps), drop=True)
    return sw.setup_view(ws)


@router.post("/type")
def change_type(body: TypeIn, ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    with ws.lock:
        _spec(ws, body.canon)
        try:
            new = su.with_type(sw.table(ws), body.canon, body.kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        sw.put_table(ws, new, drop=True)
    return sw.setup_view(ws)


@router.get("/try")
def try_column(canon: str, which: Literal["A", "B"], ws: Workspace = Depends(workspace)) -> dict:
    """The first five rows of one side of a pair: in the file, after the steps, compared as."""
    A, B = sw.sides(ws)
    spec = _spec(ws, canon)
    try:
        df = try_steps(A if which == "A" else B, spec.src(which), spec.steps(which), spec.kind, sw.opts(ws))
    except duckdb.Error as exc:
        return {**sw.frame(None), "error": f"DuckDB says: {exc}"}
    return {**sw.frame(df), "error": ""}


@router.post("/check")
def check_column(body: CanonIn, ws: Workspace = Depends(workspace)) -> dict:
    """Check this column on all rows: the values on each side that do not convert."""
    A, B = sw.sides(ws)
    NA, NB = sw.names(ws)
    spec = _spec(ws, body.canon)
    try:
        df = conversion_report(A, B, [spec], NA, NB, sw.opts(ws))
    except duckdb.Error as exc:
        raise HTTPException(400, f"DuckDB says: {exc}") from exc
    return {**sw.frame(df), "said": "" if len(df) else "Text with no steps - nothing to convert."}


# ---- Rows: the filters ----------------------------------------------------------------------
class FilterRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    apply_to: str = Field("Both", alias="Apply to")
    column: str = Field("", alias="Column")
    operator: str = Field("=", alias="Operator")
    value: str = Field("", alias="Value")
    type: str = Field("auto", alias="Type")


class FiltersIn(BaseModel):
    rows: list[FilterRow]
    rev: str | None = None


def _filters_view(ws: Workspace) -> dict:
    NA, NB = sw.names(ws)
    s = su.setup_of(sw.table(ws))
    rows = sw.filter_rows(ws)
    return {"rows": rows.to_dict("records"), "rev": sw.filters_rev(ws), "columns": s.canon, "apply_to": ["Both", NA, NB], "ops": OPS,
            "types": su.FILTER_TYPES, "error": su.filter_error(rows, NA, NB, s.specs)}


@router.get("/filters")
def get_filters(ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    return _filters_view(ws)


@router.put("/filters")
def put_filters(body: FiltersIn, ws: Workspace = Depends(workspace)) -> dict:
    """The Rows filters as typed - kept even when one cannot be read: the sentence says which."""
    sw.sides(ws)
    for r in body.rows:
        if r.operator not in OPS:
            raise HTTPException(400, f"An operator is one of {', '.join(OPS)}.")
        if r.type not in su.FILTER_TYPES:
            raise HTTPException(400, f"A filter's Type is one of {', '.join(su.FILTER_TYPES)}.")
    with ws.lock:
        sw.check_filters_rev(ws, body.rev)
        rows = pd.DataFrame([r.model_dump(by_alias=True) for r in body.rows] or [BLANK_FILTER],
                            columns=FILTER_COLS)
        sw.put_filters(ws, rows)
    return _filters_view(ws)


# ---- Key ------------------------------------------------------------------------------------
class PicksIn(BaseModel):
    picks: list[int]


def _said(pair: tuple[str, str]) -> dict:
    return {"tone": pair[0], "text": pair[1]}


def _keys_view(ws: Workspace, error: str = "") -> dict:
    """The Key section: the key ticked or the pairing without one, the last suggestions, the last
    check of this key, and what the last format check found."""
    s = su.setup_of(sw.table(ws))
    mode = sw.settings(ws)["nokey_mode"]
    sugg = ws.data.get("key_suggestions")
    held = ws.data.get("key_report")
    fmts = ws.data.get("key_formats")
    formats = []
    if fmts:
        cols, found = fmts
        for i, (tone, text) in enumerate(kg.formats_said(list(cols), found)):
            formats.append({"tone": tone, "text": text,
                            "apply": i if found and not found[i][1] else None})
    return {
        "keys": s.keys, "mode": "key" if s.keys else mode, "nokey_mode": mode, "nokey_modes": kg.NOKEY_MODES,
        "tips": kg.KEY_TIPS, "nokey_tips": kg.NOKEY_TIPS,
        "suggestions": None if sugg is None else {
            "said": _said(kg.suggestions_said(sugg[0], sugg[2])), **sw.frame(sugg[0]),
            "combos": sugg[1], "labels": [" + ".join(c) for c in sugg[1]]},
        "report": None if not (s.keys and held and list(held[0]) == s.keys) else {
            "said": _said(kg.report_said(held[1], s.keys)), **sw.frame(held[1])},
        "formats": formats, "error": error,
    }


def _check_formats(ws: Workspace, cols: list[str]) -> str:
    """The key's columns checked for the two sides writing them differently: simple fixes into
    the table, the rest offered. '' or the sentence when the values could not be read."""
    A, B = sw.sides(ws)
    try:
        new, found = kg.check_formats(A, B, sw.table(ws), cols, sw.opts(ws))
    except duckdb.Error as exc:
        return f"Could not check the key's formats: {exc}"
    ws.data["key_formats"] = (tuple(cols), found)
    if any(done for _, done in found):
        sw.put_table(ws, new, drop=True)
    return ""


@router.get("/keys")
def get_keys(ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    return _keys_view(ws)


@router.post("/keys/suggest")
def suggest(ws: Workspace = Depends(workspace)) -> dict:
    """Suggest keys, as a job: a level at a time, minutes on a wide or big pair."""
    sw.sides(ws)
    sw.table(ws)

    def work(ctx: jobs.JobCtx) -> None:
        A, B = sw.sides(ws)                  # read now, under the lock: a load may have come first
        NA, NB = sw.names(ws)
        specs = su.setup_of(sw.table(ws)).specs
        try:
            found = suggest_keys(A, B, specs, NA, NB, sw.opts(ws), progress=ctx.say,
                                 profile=sw.current_profile(ws))
        except (duckdb.Error, RuntimeError) as exc:
            raise RuntimeError(f"Could not measure the columns: {exc}") from exc
        except Exception as exc:
            raise RuntimeError("Could not measure the columns - load the files again and press it again.") from exc
        ws.data["key_suggestions"] = found
        ctx.label = kg.best_label(found[1])

    return jobs.public(jobs.start(ws, "Key search", "Looking for keys…", work, page="Compare"))


@router.delete("/keys/suggest")
def dismiss_suggestions(ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    with ws.lock:
        ws.data.pop("key_suggestions", None)
    return _keys_view(ws)


@router.post("/keys/use")
def use_as_key(body: PicksIn, ws: Workspace = Depends(workspace)) -> dict:
    """Use as key: the picked suggestions' columns ticked Key - then checked for the two sides
    writing them differently, as a key just picked is."""
    sw.sides(ws)
    with ws.lock:
        sugg = ws.data.get("key_suggestions")
        chosen = kg.chosen_key(sugg[1], body.picks) if sugg else []
        if not chosen:
            raise HTTPException(400, "Pick one or more of the suggestions first.")
        sw.put_table(ws, kg.with_key(sw.table(ws), chosen), drop=True)
        error = _check_formats(ws, chosen)
    return _keys_view(ws, error)


@router.post("/keys/check")
def check_key(ws: Workspace = Depends(workspace)) -> dict:
    """Check key: the key's formats first, then distinct keys counted against rows on each side."""
    sw.sides(ws)
    with ws.lock:
        A, B = sw.sides(ws)
        NA, NB = sw.names(ws)
        keys = su.setup_of(sw.table(ws)).keys
        if not keys:
            raise HTTPException(409, "Tick Key on a column first.")
        error = _check_formats(ws, keys)
        try:
            report = key_uniqueness(A, B, su.setup_of(sw.table(ws)).specs, keys, NA, NB, sw.opts(ws))
        except duckdb.Error as exc:
            return _keys_view(ws, f"Key check failed: {exc}")
        ws.data["key_report"] = (tuple(keys), report)
    return _keys_view(ws, error)


@router.post("/keys/formats/{i}/apply")
def apply_format(i: int, ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    with ws.lock:
        held = ws.data.get("key_formats")
        if not held or not 0 <= i < len(held[1]):
            raise HTTPException(404, "No such format suggestion.")
        fx, _ = held[1][i]
        new = kg.with_fix(sw.table(ws), fx)
        if new is None:
            ws.data.pop("key_formats", None)
            return _keys_view(ws, f"{fx.canon} is no longer paired, so there is nothing to apply.")
        sw.put_table(ws, new, drop=True)
        held[1][i] = (fx, True)
    return _keys_view(ws)


@router.delete("/keys/formats")
def dismiss_formats(ws: Workspace = Depends(workspace)) -> dict:
    sw.sides(ws)
    with ws.lock:
        ws.data.pop("key_formats", None)
    return _keys_view(ws)


# ---- Profile both files -----------------------------------------------------------------------
@router.post("/profile")
def profile_both(ws: Workspace = Depends(workspace)) -> dict:
    """Profile both files, as a job: the key-like columns' formats first, so the profile is
    measured on the key as it will be matched."""
    sw.sides(ws)
    sw.table(ws)

    def work(ctx: jobs.JobCtx) -> None:
        A, B = sw.sides(ws)                  # read now, under the lock: a load may have come first
        o = sw.opts(ws)
        sw.table(ws)
        try:
            s = su.setup_of(ws.data["cmap"])
            cols = kg.key_like(A, B, s.keys, s.specs)
            if cols:
                ctx.say(f"Checking whether {', '.join(cols)} is written differently on the two sides…")
                new, found = kg.check_formats(A, B, ws.data["cmap"], cols, o)
                ws.data["key_formats"] = (tuple(cols), found)
                if any(done for _, done in found):
                    sw.put_table(ws, new, drop=True)
                    ctx.say("Fixed - see the Key section")
            specs = su.setup_of(ws.data["cmap"]).specs
            made = profile_tables(A, B, specs, o, ctx.say)
        except duckdb.Error as exc:
            raise RuntimeError(f"Profile failed: {exc}") from exc
        except Exception as exc:
            raise RuntimeError("Profile failed - load the files again and press it again.") from exc
        ws.data["profile"] = (kg.profile_key_for(A, B, specs, o), made)
        ctx.label = "Profile ready"

    return jobs.public(jobs.start(ws, "Profile", "Profiling…", work, page="Compare"))


@router.get("/profile")
def get_profile(ws: Workspace = Depends(workspace)) -> dict | None:
    """The profile held - with whether it was measured on other settings than the page's now."""
    sw.sides(ws)
    held = ws.data.get("profile")
    if not held:
        return None
    NA, NB = sw.names(ws)
    s = su.setup_of(sw.table(ws))
    prof = held[1]
    have = kg.freq_columns(prof, s.canon)
    return {"stale": sw.current_profile(ws) is None, "names": [NA, NB],
            "stale_said": "This profile is from earlier settings - run it again to refresh.",
            "both": sw.frame(kg.both_table(prof, s.canon, NA, NB)),
            "A": sw.frame(prof["stats"]["A"]), "B": sw.frame(prof["stats"]["B"]),
            "freq_columns": have, "freq_default": [c for c in s.keys if c in have][:2]}


@router.get("/profile/freq")
def get_freq(col: str, ws: Workspace = Depends(workspace)) -> dict:
    """One column's 10 most and 10 least frequent values, on each side."""
    sw.sides(ws)
    held = ws.data.get("profile")
    s = su.setup_of(sw.table(ws))
    if not held or col not in kg.freq_columns(held[1], s.canon):
        raise HTTPException(404, f"The profile has no frequencies for {col}.")
    NA, NB = sw.names(ws)
    f = held[1]["freq"][col]
    return {"title": kg.freq_title(held[1], col, s.keys, NA, NB),
            **{w: {"top": sw.frame(f[w][0]), "bottom": sw.frame(f[w][1])} for w in ("A", "B")}}
