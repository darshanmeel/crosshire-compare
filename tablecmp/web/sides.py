"""What each side panel holds on the server - the Side loaded, an upload written, a fetch held -
and the view of it the page gets. Never a password, and a file only by the name the page shows."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..comparing import close_run
from ..loading import loaded_caption, loaded_notes, retire
from ..sources import Side
from .workspace import Workspace

TAGS = ("A", "B", "P")
PAGE = {"A": "Compare", "B": "Compare", "P": "Profiling"}      # whose run disc a side's job lights
# what is worked out from the sides - gone when one is loaded again (state.drop_result / finish)
DROPPED_ON_NEW_SIDE = {"AB": ("result", "cmap", "cmap_seed", "profile", "key_report", "key_suggestions",
                              "data_match", "compare_said"),
                       "P": ("profile_P",)}


@dataclass
class Fetched:
    """A database fetch the panel holds, ready to Load: what it was made from, and its file."""
    key: tuple[str, str, int]
    path: str
    what: str
    at: str
    rows: int
    capped: bool


@dataclass
class Panel:
    side: Side = field(default_factory=Side)
    staged: str = ""                  # the upload, written to the work folder
    staged_label: str = ""            # its own file name
    fetched: Fetched | None = None


def panels(ws: Workspace) -> dict[str, Panel]:
    return ws.data.setdefault("panels", {t: Panel() for t in TAGS})


def panel(ws: Workspace, tag: str) -> Panel:
    return panels(ws)[tag]


def side(ws: Workspace, tag: str) -> Side:
    return panel(ws, tag).side


def unlink_unless_loaded(p: Panel, path: str) -> None:
    """A replaced upload or fetch goes - unless the loaded side still reads it (the sweep gets it later)."""
    if path and p.side.csv_path != path:
        Path(path).unlink(missing_ok=True)


def put_side(ws: Workspace, tag: str, new: Side) -> None:
    """The loaded side takes its place: what the old one read and nothing holds goes, and so
    does everything worked out from it - the run's DuckDB connection closed first."""
    p = panel(ws, tag)
    retire(p.side, new, p.fetched.path if p.fetched else "")
    p.side = new
    if tag != "P":
        close_run(ws.data.get("result"))
    for k in DROPPED_ON_NEW_SIDE["P" if tag == "P" else "AB"]:
        ws.data.pop(k, None)


def fetched_view(f: Fetched | None) -> dict | None:
    return None if f is None else {"at": f.at, "rows": f.rows, "capped": f.capped}


def side_view(ws: Workspace, tag: str) -> dict:
    p = panel(ws, tag)
    s = p.side
    return {"tag": tag, "loaded": s.loaded, "name": s.name, "label": s.label, "origin": s.origin,
            "kind": s.kind, "rows": s.rows, "columns": s.columns, "cut": s.cut,
            "is_database": s.is_database, "conn": s.conn, "fetched_at": s.fetched_at,
            "snapshot": bool(s.cache_path),
            "caption": loaded_caption(s) if s.loaded else "",
            "notes": [{"tone": t, "text": x} for t, x in loaded_notes(s)] if s.loaded else [],
            "staged": p.staged_label if p.staged and Path(p.staged).exists() else "",
            "fetched": fetched_view(p.fetched)}
