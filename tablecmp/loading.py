# tablecmp/loading.py
"""Loading a side, with no page attached. The Streamlit sidebar and the React page's server both
call these, so the two pages load a file, a folder pick or a fetch the same way and say the same
things about it - nothing here imports a UI."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from . import connections as cx
from . import databases as db
from .sources import (FOLDER_LIST_MAX, Side, apply_names, looks_headerless, path_allowed,
                      row_count, short_header, snapshot, work_dir)

DEFAULT_NAMES = {"A": "Left", "B": "Right", "P": "Table"}    # what a side is called until it is named
NAME_HELP = {"side": "What to call this side everywhere - and it names every output file: "
                     "left_compare_right. Defaults: Left and Right. A database side with the "
                     "default name takes its connection's name.",
             "table": "What to call this table - it names the profile file: table__profile.csv. "
                      "Default: Table. A database table with the default name takes its "
                      "connection's name."}
QUICK_OPS = ["=", "!=", ">", ">=", "<", "<=", "contains", "starts with",
             "in (comma separated)", "is null", "is not null"]
UPLOAD_TYPES = ["csv", "txt", "tsv", "dat", "json", "jsonl", "ndjson", "parquet"]
CAP_WARNING = ("A cap without an ORDER BY can give the two sides different rows - "
               "add ORDER BY, or fetch everything.")
CONFIG_PARTLY = ("The settings are in. Load the sides above, then give the same file "
                 "to **Load mapping** under the column table")
FILTER_COLS = ["Apply to", "Column", "Operator", "Value", "Type"]
BLANK_FILTER = {"Apply to": "Both", "Column": "", "Operator": "=", "Value": "", "Type": "auto"}


# ---- names ------------------------------------------------------------------------------
def side_name(tag: str, box: str, side: Side) -> str:
    """What the page calls a side: the Name box wins; left at its default, a database side is
    called after its connection (the name it was loaded with), a file side Left or Right."""
    box = (box or "").strip()
    return box if box and box != DEFAULT_NAMES[tag] else (side.name or DEFAULT_NAMES[tag]).strip()


def load_name(tag: str, box: str, conn: str = "") -> str:
    """The name a Load gives the side: the box - or, left blank or at its default, the
    connection's name for a database side, else the tag."""
    box = (box or "").strip()
    if conn and box in ("", DEFAULT_NAMES[tag]):
        return conn
    return box or tag


def name_hint(tag: str, box: str, side: Side, this: str, other: str) -> str:
    """The word under a loaded A or B about its name: the two sides share one, or a file side is
    still called Left or Right. '' when there is nothing to say."""
    if this == other:                        # two database sides on one connection, typically
        return f":orange[Both sides are called {other}] - name this one to tell them apart"
    if not side.is_database and (box or "").strip() in ("", DEFAULT_NAMES[tag]):
        return "Tip: name this side - it names the output files"
    return ""


# ---- an upload --------------------------------------------------------------------------
def upload_ok(filename: str) -> bool:
    return Path((filename or "").replace("\\", "/")).suffix.lower().lstrip(".") in UPLOAD_TYPES


def upload_path(tag: str, filename: str) -> Path:
    """Where an upload is written: the work folder, under the file's bare name with the side and
    the time in front - the sweep removes it after COMPARE_KEEP_HOURS."""
    bare = Path((filename or "upload.csv").replace("\\", "/")).name or "upload.csv"
    bare = re.sub(r"[^\w.\- ]", "_", bare)             # ':' (a Windows data stream), '<>|?*"' and the like
    return work_dir() / f"cmp_{tag}_{int(time.time() * 1000)}_{bare}"


# ---- a path on disk ---------------------------------------------------------------------
def path_problem(path: str) -> str:
    """'' when a Path on disk can be read, else the sentence the panel says."""
    if not Path(path).is_file():
        return "File not found."
    if not path_allowed(path):
        return "Not under an allowed folder (COMPARE_DATA_DIR)."
    return ""


def picked_in(root: str, chosen: str) -> str:
    """A file the dialog chose, as its name in the folder (with /) - '' when it lies outside it."""
    if not root or not chosen:
        return ""
    try:
        return Path(chosen).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return ""


def folder_note(root: str, files: list[str]) -> tuple[str, str] | None:
    """What the panel says under a folder's file list, as (tone, text) - or None."""
    if not Path(root).is_dir():
        return ("error", f"The folder {root} is not there - fix it under **Connections**.")
    if len(files) >= FOLDER_LIST_MAX:
        return ("caption", f"The first {FOLDER_LIST_MAX:,} files are listed - type a name for any other")
    if not files:
        return ("caption", "No CSV, JSON or Parquet file in it yet - type a name")
    return None


# ---- Load -------------------------------------------------------------------------------
@dataclass
class ReadAsked:
    """What the Load button reads: one panel's boxes, past the file pick."""
    name: str = ""
    label: str = ""
    path: str = ""
    kind: str = "csv"
    origin: str = ""
    folder: str = ""
    delimiter: str = ","
    header: bool = True
    where: str = ""
    order_by: list[str] = field(default_factory=list)
    desc: bool = False
    limit: int = 0
    names_text: str = ""
    snapshot: bool = True


def names_warning(names_text: str, schema: dict[str, str]) -> str:
    names = names_text.split(",") if names_text.strip() else []
    if names and len(names) != len(schema):
        return (f"You gave {len(names)} names but the file has {len(schema)} "
                "columns - the surplus was ignored / the shortfall kept its original name.")
    return ""


def build_side(tag: str, ask: ReadAsked, schema: dict[str, str], db_side: Side | None = None) -> Side:
    """The Side a Load makes: named, cut, snapshotted when asked, its rows counted. duckdb.Error
    when the rows cannot be read."""
    side = Side(name=ask.name.strip() or tag, label=ask.label, csv_path=ask.path, kind=ask.kind,
                origin=ask.origin, delimiter=ask.delimiter, header=ask.header, where=ask.where,
                order_by=list(ask.order_by), desc=bool(ask.desc), limit=int(ask.limit), folder=ask.folder,
                **({"conn": db_side.conn, "database": db_side.database, "query": db_side.query,
                    "fetched_at": db_side.fetched_at, "cap": db_side.cap, "capped": db_side.capped}
                   if db_side else {}))
    names = ask.names_text.split(",") if ask.names_text.strip() else []
    side.schema = apply_names(schema, names) if names else dict(schema)
    side.source_columns = list(schema)
    # a Parquet source with no cut is already what a snapshot would be - no second copy
    already = ask.kind == "parquet" and not (ask.where.strip() or ask.order_by or ask.limit)
    if ask.snapshot and not already:
        snapshot(side, str(work_dir() / f"cmp_{tag}_{int(time.time() * 1000)}.parquet"))
    else:
        side.cache_path = ""
    side.rows = row_count(side)
    return side


def loaded_caption(side: Side) -> str:
    return (f":green[**✓ {side.name}**] · {side.origin or side.label} · {side.rows or 0:,} rows × "
            f"{len(side.schema)} columns"
            + (f"  ·  {side.cut}" if side.cut else "")
            + (f"  ·  fetched {side.fetched_at}" if side.fetched_at else "")
            + (f"  ·  capped at {side.cap:,}" if side.capped else "")
            + ("  ·  Parquet snapshot" if side.cache_path else ""))


def loaded_notes(side: Side) -> list[tuple[str, str]]:
    """The warnings and errors under a loaded side, as (tone, text)."""
    out: list[tuple[str, str]] = []
    if side.rows == 0:
        out.append(("warning", "The filter left no rows." if side.cut else
                    "The fetch returned no rows." if side.is_database else "The file has no rows."))
    if side.kind == "csv" and side.header and looks_headerless(side.schema):
        out.append(("error", "These column names look like a data row. Untick **First row is a "
                             "header** and load again."))
    # an empty CSV gets one auto-named column from DuckDB - there is no data row to name
    missing = short_header(side.schema) if side.kind == "csv" and side.rows else 0
    if missing:
        named = len(side.schema) - missing
        out.append(("error", f"The header row names only **{named}** columns but the data has "
                             f"**{len(side.schema)}** fields, so the last {missing} were auto-named. "
                             "Paste the full comma-separated list into **Advanced → Column names** "
                             "and load again."))
    return out


def retire(old: Side, new: Side, held_fetch: str = "") -> None:
    """What the old side read and the new one does not goes: its snapshot, and a database fetch
    nothing holds any more (held_fetch is the fetch the panel still offers)."""
    if old.cache_path and old.cache_path != new.cache_path:
        Path(old.cache_path).unlink(missing_ok=True)
    if old.is_database and old.csv_path and old.csv_path != new.csv_path and old.csv_path != held_fetch:
        Path(old.csv_path).unlink(missing_ok=True)


# ---- a database side ----------------------------------------------------------------------
def db_sql(kind: str, mode: str, table: str, sql: str) -> tuple[str, str]:
    """(the SQL to fetch, what it reads) from the Table or the SQL query box. ValueError for a
    table name that names nothing."""
    if mode == "table":
        what = (table or "").strip()
        return (db.table_sql(kind, what) if what else ""), what
    return (sql or "").strip(), "query"


_SECRET_EXTRAS = ("token", "private_key_pwd")


def conn_key(c: cx.Connection) -> str:
    """A connection's name with what it points at - an edited connection no longer matches a fetch
    made from the old server. Never holds the password, a token or a passphrase."""
    extra = sorted((k, v) for k, v in c.extra.items() if k not in _SECRET_EXTRAS)
    where = (c.kind, c.host, c.port, c.database, c.schema, c.user, extra)
    return f"{c.name}#{hashlib.sha1(repr(where).encode('utf-8')).hexdigest()[:10]}"


def fetch_key(conn: str, sql: str, cap: int) -> tuple[str, str, int]:
    """What a held fetch was made from - a fetch is offered again only while this is unchanged."""
    return (conn, " ".join((sql or "").split()), int(cap))


def fetched_side(c: cx.Connection, sql: str, what: str, cap: int, fetched_at: str, capped: bool) -> Side:
    """The database half of a Side that Load reads from a held fetch."""
    return Side(conn=c.name, database=c.kind, query=sql, fetched_at=fetched_at, cap=int(cap), capped=capped,
                origin=db.origin_of(c, what if what != "query" else sql))


# ---- a saved config -----------------------------------------------------------------------
def folder_names() -> set[str]:
    try:
        return set(cx.folders())
    except ValueError:                   # a connections file that cannot be read: paths then
        return set()


def config_boxes(conf: dict, folders: set[str]) -> dict:
    """What a saved config puts in the page: the switches, and each side's boxes in the page's
    own names (the React form's keys)."""
    s = conf.get("settings") or {}
    settings: dict = {"trim": bool(s.get("trim", True)), "empty_as_null": bool(s.get("empty_as_null", True)),
                      "ignore_case": bool(s.get("ignore_case", False)), "tolerance": float(s.get("tolerance") or 0.0)}
    if s.get("display_rows"):               # the page's own switches stay as they are unless the config sets them
        settings["display_rows"] = int(s["display_rows"])
    if "null_tokens" in s:
        settings["null_tokens"] = str(s["null_tokens"])
    fmts = set(s.get("table_formats") or [])
    if fmts:
        settings["out_fmt"] = "both" if {"csv", "parquet"} <= fmts else "parquet" if "parquet" in fmts else "csv"
    if s.get("mode") in ("hash", "position"):
        settings["nokey_mode"] = s["mode"]
    out: dict = {"settings": settings}
    for tag in "AB":
        b = conf["sides"][tag]
        box = {"name": str(b.get("name") or DEFAULT_NAMES[tag]), "delimiter": str(b.get("delimiter") or ","),
               "header": bool(b.get("header", True)), "where": str(b.get("where") or ""),
               "order_by": list(b.get("order_by") or []), "desc": bool(b.get("desc")),
               "limit": int(b.get("limit") or 0), "column_names": ", ".join(b.get("column_names") or []),
               "snapshot": bool(b.get("snapshot"))}
        if b.get("connection"):
            box.update(how="database", connection=str(b["connection"]), db_mode="sql",
                       sql=str(b.get("query") or ""), cap=int(b.get("cap") or 0))
        else:
            known = bool(b.get("folder") and b.get("file") and b["folder"] in folders)
            box.update(how="path", path=str(b.get("path") or ""),
                       folder=str(b["folder"]) if known else "", file=str(b["file"]) if known else "")
        out[tag] = box
    return out


def open_config_sides(conf: dict, passwords: dict[str, str] | None,
                      say: Callable[[str], None] = lambda _m: None) -> tuple[dict[str, Side], list[tuple[str, str]]]:
    """Each side opened the way the config says (a database side is fetched); what could not be
    opened is said, one line a side."""
    from .runconfig import ConfigError, open_side
    sides: dict[str, Side] = {}
    said: list[tuple[str, str]] = []
    for tag in "AB":
        b = conf["sides"][tag]
        try:
            sides[tag] = open_side(b, tag, passwords, say=say)
        except cx.PasswordNeeded:
            said.append(("warning", f"{tag}: type the password for **{b['connection']}**, then Fetch and Load"))
        except ConfigError as exc:
            said.append(("error", f"{tag}: {exc}"))
        except Exception as exc:                 # noqa: BLE001 - a file or driver error, said in a line
            said.append(("error", f"{tag}: could not be read - {cx.redact(str(exc), cx.known_secrets((passwords or {}).values()))}"))
    return sides, said


def config_columns(conf: dict, A: Side, B: Side, comparing: bool = True
                   ) -> tuple[pd.DataFrame | None, pd.DataFrame | None, list[tuple[str, str]]]:
    """With both sides in: the column table and the Rows filters the config holds - or the
    columns it pairs that a side does not have, said."""
    from .runconfig import column_table, missing_columns
    gone = missing_columns(conf, A, B)
    if gone:
        return None, None, [("error", "Both files are loaded, but the config pairs columns they do not have: "
                                      + ", ".join(gone))]
    cmap = column_table(conf, A, B)
    pairs = sum(1 for _, r in cmap.iterrows() if r["A column"] and r["B column"])
    rows = pd.DataFrame(conf.get("filters") or [BLANK_FILTER], columns=FILTER_COLS).fillna("")
    return cmap, rows, [("success", f"Loaded - {A.name} against {B.name}, {pairs} pairs"
                                    + ("; comparing" if comparing else ""))]
