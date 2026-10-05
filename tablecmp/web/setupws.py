# tablecmp/web/setupws.py
"""The Compare page's setup in the workspace: the column table and what it was built from, the
names the page shows, the switches, and the views the page gets of them. What st.session_state
held for the Columns, Values, Key and Rows sections, kept in ws.data:

  names          {"A": box, "B": box} - the Name boxes, as the page last sent them
  settings       How values are read and the pairing without a key (setup.SETTINGS_DEFAULT)
  cmap           the column table (a DataFrame, replaced whole on every change - never edited)
  cmap_seed      setup.seed_key of the sides it was built for
  cmap_rev       counts the changes: the page's `rev`
  looks_like     {"A": {...}, "B": {...}} and looks_said, what could not be sampled
  data_match     (DataFrame, {a: b}) from Match by data
  filter_rows    the Rows filters (FILTER_COLS) and filter_for, the (columns, names) they were typed for
  key_formats, key_suggestions, key_report, profile - the Key section and Profile both files

A GET reads these without ws.lock, so the page is never kept waiting by a job that runs for
minutes - only building the table the first time takes the lock. Every write takes it."""
from __future__ import annotations

import json

import pandas as pd
from fastapi import HTTPException

from .. import keying, loading
from .. import setup as su
from ..columns import SHOWN_COLS, build_table, fill_looks, role_tone, roles
from ..compare import side_labels
from ..sources import Side
from ..values import CASES, TYPES, ReadOptions, describe_step
from .sides import side
from .workspace import Workspace

# what goes when the table changes shape - state.forget_results
DERIVED = ("profile", "key_report", "key_suggestions", "data_match")
STALE_TABLE = "The column table changed since - it is shown again as it is now."
STALE_FILTERS = "The filters changed since - they are shown again as they are now."


def frame(df: pd.DataFrame | None) -> dict:
    """A DataFrame as the page's tables take it: column names and rows, JSON-safe."""
    if df is None or not len(df.columns):
        return {"columns": [], "rows": []}
    split = json.loads(df.to_json(orient="split", index=False, date_format="iso", default_handler=str))
    return {"columns": [str(c) for c in split["columns"]], "rows": split["data"]}


def sides(ws: Workspace) -> tuple[Side, Side]:
    """A and B - 409 until both are loaded."""
    A, B = side(ws, "A"), side(ws, "B")
    if not (A.loaded and B.loaded):
        raise HTTPException(409, "Load A and B first.")
    return A, B


def names(ws: Workspace) -> tuple[str, str]:
    """What the page calls the two sides (compare.side_labels: A · X and B · X when they share one)."""
    boxes = ws.data.get("names") or {}
    return side_labels(loading.side_name("A", boxes.get("A", ""), side(ws, "A")),
                       loading.side_name("B", boxes.get("B", ""), side(ws, "B")))


def settings(ws: Workspace) -> dict:
    return su.settings_of(ws.data.get("settings"))


def opts(ws: Workspace) -> ReadOptions:
    return su.read_options(settings(ws))


def forget(ws: Workspace) -> None:
    for k in DERIVED:
        ws.data.pop(k, None)


def table(ws: Workspace) -> pd.DataFrame:
    """The column table - built afresh for a new pair of files, with the looks-like suggestions
    sampled once per pair. Whether it is fresh is decided again once the lock is held: a job
    that had it may have put the table in meanwhile."""
    A, B = sides(ws)
    if not _stale(ws, A, B):
        return ws.data["cmap"]
    with ws.lock:
        A, B = sides(ws)
        key = su.seed_key(A, B)
        fresh = ws.data.get("cmap") is None or ws.data.get("cmap_seed") != key
        if fresh or "looks_like" not in ws.data:
            looks, said = su.sniff_sides(A, B, opts(ws))
            ws.data.update(looks_like=looks, looks_said=said)
            if fresh:
                ws.data.update(cmap=build_table(A, B, looks), cmap_seed=key)
                ws.data["cmap_rev"] = ws.data.get("cmap_rev", 0) + 1
                for k in ("auto_notes", "key_formats"):
                    ws.data.pop(k, None)
                forget(ws)
        return ws.data["cmap"]


def _stale(ws: Workspace, A: Side, B: Side) -> bool:
    return (ws.data.get("cmap") is None or ws.data.get("cmap_seed") != su.seed_key(A, B)
            or "looks_like" not in ws.data)


def rev(ws: Workspace) -> str:
    """The table's version as the page holds it: a count of the changes, which every route that
    puts a table in (a cell, a config, Auto, a rebuild) bumps. No table, no version."""
    return "-" if ws.data.get("cmap") is None else str(ws.data.get("cmap_rev", 0))


def put_table(ws: Workspace, new: pd.DataFrame, drop: bool = False) -> None:
    """A changed table takes the old one's place; with drop, what was worked out from it goes."""
    ws.data["cmap"] = new
    ws.data["cmap_rev"] = ws.data.get("cmap_rev", 0) + 1
    if drop:
        forget(ws)


def check_rev(ws: Workspace, sent: str) -> None:
    if sent != rev(ws):
        raise HTTPException(409, STALE_TABLE)


def setup_view(ws: Workspace) -> dict:
    """Everything the Columns section draws, and what the Values, Key and Rows sections read."""
    NA, NB = names(ws)
    A, B = side(ws, "A"), side(ws, "B")
    if not (A.loaded and B.loaded):
        return {"ready": False, "names": [NA, NB]}
    cmap = table(ws)
    s = su.setup_of(cmap)
    shown = fill_looks(cmap, ws.data.get("looks_like"))
    rows = []
    for (_, r), role in zip(shown.iterrows(), roles(shown, NA, NB)):
        rows.append({**{c: (bool(r[c]) if c in ("Key", "Compare") else str(r[c])) for c in SHOWN_COLS},
                     "Role": role, "tone": role_tone(role)})
    dm = ws.data.get("data_match")
    return {
        "ready": True, "names": [NA, NB], "rev": rev(ws),
        "columns": {"A": A.columns, "B": B.columns}, "types": TYPES, "cases": CASES,
        "rows": rows, "pairs": len(s.specs),
        "chips": [{"text": t, "cls": c} for t, c in su.chip_items(cmap, NA, NB)],
        "duplicates": su.duplicate_names(cmap),
        "card": [{"label": k, "html": v} for k, v in su.card_rows(s, NA, NB)],
        "specs": [{"canon": sp.canon, "kind": sp.kind, "a_src": sp.a_src, "b_src": sp.b_src,
                   "a_steps": sp.a_steps, "b_steps": sp.b_steps, "case": sp.case, "describe": sp.describe(),
                   "a_said": [describe_step(x) for x in sp.a_steps], "b_said": [describe_step(x) for x in sp.b_steps]}
                  for sp in s.specs],
        "keys": s.keys, "compare": s.compare, "only_a": s.only_a, "only_b": s.only_b,
        "can_match": bool(s.only_a and s.only_b),
        "data_match": None if dm is None else {**frame(dm[0]), "pairs": len(dm[1])},
        "said": [{"tone": "warning", "text": t} for t in ws.data.get("looks_said", [])],
        "settings": settings(ws), "looks_help": su.LOOKS_HELP,
        "derived": [{"name": n, "a": A.derived.get(n, ""), "b": B.derived.get(n, ""),
                     "a_type": A.schema.get(n, "") if n in A.derived else "", "b_type": B.schema.get(n, "") if n in B.derived else ""}
                    for n in dict.fromkeys([*A.derived, *B.derived])],
    }


def filter_rows(ws: Workspace) -> pd.DataFrame:
    """The Rows filters - kept while the paired columns and the names are the ones they were typed
    for, else one blank row. Rows a config put in (no filter_for yet) are taken for the table now."""
    held = ws.data.get("filter_rows")
    now = (tuple(sp.canon for sp in su.setup_of(table(ws)).specs), tuple(names(ws)))
    made = ws.data.get("filter_for")
    if held is not None and made in (None, now):
        ws.data["filter_for"] = now
        return held
    return pd.DataFrame([loading.BLANK_FILTER], columns=loading.FILTER_COLS)


def filters_rev(ws: Workspace) -> str:
    return str(ws.data.get("filters_rev", 0))


def check_filters_rev(ws: Workspace, sent: str | None) -> None:
    """A page that sends the version it holds is refused when the filters changed since."""
    if sent is not None and sent != filters_rev(ws):
        raise HTTPException(409, STALE_FILTERS)


def put_filters(ws: Workspace, rows: pd.DataFrame) -> None:
    ws.data["filters_rev"] = ws.data.get("filters_rev", 0) + 1
    ws.data["filter_rows"] = rows
    ws.data["filter_for"] = (tuple(sp.canon for sp in su.setup_of(table(ws)).specs), tuple(names(ws)))


def current_profile(ws: Workspace) -> dict | None:
    """The profile held, when it was measured on the sides, columns and switches as they are now
    (compare_app.current_profile) - what Suggest keys and Compare take; else None."""
    held = ws.data.get("profile")
    if not held or ws.data.get("cmap") is None:
        return None
    A, B = side(ws, "A"), side(ws, "B")
    key = keying.profile_key_for(A, B, su.setup_of(ws.data["cmap"]).specs, opts(ws))
    return held[1] if held[0] == key else None
