"""The side panels' routes: an upload streamed to disk, a path or a folder's file, Browse, the
columns a pick has, Load and the preview, a database fetch as a job, and Run from a config."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from .. import connections as cx
from .. import databases as db
from .. import filepick, loading
from ..connforms import CAP_DEFAULT
from ..sources import (Side, add_derived, file_stamp, folder_files, in_folder, kind_of, path_allowed, preview_rows, quick_clause,
                       source_schema, work_dir)
from .. import setup as su
from . import jobs, runs
from . import setupws as sw
from .sides import PAGE, TAGS, Fetched, fetched_view, panel, put_side, side, side_view, unlink_unless_loaded
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/sources")


def _tag(tag: str) -> str:
    if tag not in TAGS:
        raise HTTPException(404, "A side is A, B or P.")
    return tag


class DbIn(BaseModel):
    connection: str = ""
    mode: Literal["table", "sql"] = "table"
    table: str = ""
    sql: str = ""
    cap: int = Field(CAP_DEFAULT, ge=0, le=1_000_000_000)


class FetchIn(DbIn):
    password: str | None = None       # typed now: held for this session, never saved


class PickIn(BaseModel):
    how: Literal["upload", "path", "database"] = "upload"
    path: str = ""
    folder: str = ""                  # a folder connection's name; "" = Any path
    file: str = ""                    # the file's name in that folder
    delimiter: str = Field(",", max_length=3)
    header: bool = True
    db: DbIn | None = None


class BrowseIn(BaseModel):
    start: str = ""                   # the path typed so far - the dialog opens in its folder
    folder: str = ""


@dataclass
class Picked:
    path: str = ""
    label: str = ""
    folder: str = ""
    db_side: Side | None = None
    error: str = ""


def _held_fetch(ws: Workspace, tag: str, d: DbIn | None) -> Picked:
    """A database pick is the fetch the panel holds - while the boxes still say what it was made from."""
    if d is None or not d.connection:
        return Picked()
    try:
        c = cx.load_all().get(d.connection)
        if c is None:
            return Picked(error=f"No connection called {d.connection}.")
        sql, _ = loading.db_sql(c.kind, d.mode, d.table, d.sql)
    except ValueError as exc:
        return Picked(error=str(exc))
    held = panel(ws, tag).fetched
    if not (held and held.key == loading.fetch_key(loading.conn_key(c), sql, d.cap) and Path(held.path).exists()):
        return Picked()
    return Picked(held.path, f"{c.name}.parquet",
                  db_side=loading.fetched_side(c, sql, held.what, d.cap, held.at, held.capped))


def resolve_pick(ws: Workspace, tag: str, pick: PickIn) -> Picked:
    """The file a panel's boxes point at - nothing yet, a sentence why not, or the file."""
    p = panel(ws, tag)
    if pick.how == "upload":
        return Picked(p.staged, p.staged_label) if p.staged and Path(p.staged).exists() else Picked()
    if pick.how == "database":
        return _held_fetch(ws, tag, pick.db)
    if pick.folder:
        try:
            folders = cx.folders()
        except ValueError as exc:                # a connections file that cannot be read
            return Picked(error=str(exc))
        if pick.folder not in folders:
            return Picked(error=f"No folder connection called {pick.folder} - pick another.")
        if not pick.file.strip():
            return Picked()
        path, folder = in_folder(folders[pick.folder].host, pick.file), pick.folder
    else:
        path, folder = pick.path.strip().strip('"').strip(), ""
        if not path:
            return Picked()
    problem = loading.path_problem(path)
    return Picked(error=problem) if problem else Picked(path, Path(path).name, folder)


@router.get("")
def sources(ws: Workspace = Depends(workspace)) -> dict:
    return {"sides": {t: side_view(ws, t) for t in TAGS}, "defaults": loading.DEFAULT_NAMES,
            "quick_ops": loading.QUICK_OPS, "name_help": loading.NAME_HELP,
            "upload_types": loading.UPLOAD_TYPES, "config": ws.data.get("config_view")}


@router.get("/folders")
def list_folders() -> list[dict]:
    try:
        found = cx.folders()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return [{"name": n, "host": c.host} for n, c in sorted(found.items())]


@router.get("/folders/{name}/files")
def folder_list(name: str) -> dict:
    try:
        found = cx.folders()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if name not in found:
        raise HTTPException(404, f"No folder connection called {name}.")
    root = found[name].host
    files = folder_files(root)
    note = loading.folder_note(root, files)
    return {"root": root, "files": files, "note": None if note is None else {"tone": note[0], "text": note[1]}}


@router.post("/browse")
def browse(body: BrowseIn) -> dict:
    """The system's file dialog, on this machine. A plain (threadpool) route: it may stay open
    for up to filepick.WAIT seconds, and nothing else waits on it."""
    if not filepick.available():
        raise HTTPException(409, "There is no screen here to open a file dialog on - type the path.")
    root = ""
    if body.folder:
        try:
            found = cx.folders()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        root = found[body.folder].host if body.folder in found else ""
    start = root or (str(Path(body.start.strip().strip('"')).parent) if body.start.strip() else "")
    try:
        chosen = filepick.pick_file(start)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    rel = loading.picked_in(root, chosen) if chosen else ""
    return {"path": "" if rel else chosen, "file": rel}


@router.post("/{tag}/upload")
async def upload(tag: str, request: Request, filename: str = Query(..., max_length=255),
                 ws: Workspace = Depends(workspace)) -> dict:
    """The file's bytes as the body, written as they arrive: nothing holds the whole file, and
    there is no size cap. Never takes ws.lock - a running job must not stall the server."""
    _tag(tag)
    if not loading.upload_ok(filename):
        raise HTTPException(400, "Upload a CSV, JSON or Parquet file: "
                                 + ", ".join("." + t for t in loading.UPLOAD_TYPES) + ".")
    dest = loading.upload_path(tag, filename)
    try:
        with open(dest, "wb") as out:
            async for chunk in request.stream():
                if chunk:
                    await run_in_threadpool(out.write, chunk)
    except (ClientDisconnect, OSError) as exc:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise HTTPException(400, f"The upload did not finish: {exc}") from exc
    p = panel(ws, tag)
    old = p.staged
    p.staged, p.staged_label = str(dest), Path(filename.replace("\\", "/")).name
    if old and old != p.staged:
        unlink_unless_loaded(p, old)
    return side_view(ws, tag)


@router.post("/{tag}/schema")
def schema(tag: str, pick: PickIn, ws: Workspace = Depends(workspace)) -> dict:
    """The columns the picked file has - what the panel lists, and what Load is offered."""
    _tag(tag)
    got = resolve_pick(ws, tag, pick)
    kind = kind_of(got.path) if got.path else "csv"
    out = {"label": got.label, "kind": kind, "columns": [], "error": got.error}
    if got.path:
        delim, header = (pick.delimiter or ",", pick.header) if kind == "csv" else (",", True)
        try:
            found = source_schema(got.path, kind, delim, header, file_stamp(got.path))
        except duckdb.Error as exc:
            out["error"] = f"Could not read the {kind} file: {exc}"
        else:
            out["columns"] = [{"name": n, "type": t} for n, t in found.items()]
    return out


class LoadIn(PickIn):
    name: str = ""
    where: str = ""
    order_by: list[str] = Field(default_factory=list)
    desc: bool = False
    limit: int = Field(0, ge=0, le=500_000_000)
    column_names: str = ""
    snapshot: bool = True


class ClauseIn(BaseModel):
    column: str
    op: str
    value: str = ""
    where: str = ""


@router.post("/quick-clause")
def add_clause(body: ClauseIn) -> dict:
    """One condition from Column / Condition / Value, ANDed onto the filter typed so far - built
    here, where the SQL quoting lives."""
    if body.op not in loading.QUICK_OPS:
        raise HTTPException(400, "Pick a condition from the list.")
    clause = quick_clause(body.column, body.op, body.value)
    cur = body.where.strip()
    return {"where": f"{cur}\nAND {clause}" if cur else clause}


@router.post("/{tag}/load")
def load(tag: str, body: LoadIn, ws: Workspace = Depends(workspace)) -> dict:
    """The side read with its cut, counted (and snapshotted), in place of the old one."""
    _tag(tag)
    got = resolve_pick(ws, tag, body)
    if got.error:
        raise HTTPException(400, got.error)
    if not got.path:
        raise HTTPException(400, "Nothing to load - pick a file, or fetch a table, first.")
    kind = kind_of(got.path)
    delim, header = (body.delimiter or ",", body.header) if kind == "csv" else (",", True)
    try:
        found = source_schema(got.path, kind, delim, header, file_stamp(got.path))
    except duckdb.Error as exc:
        raise HTTPException(400, f"Could not read the {kind} file: {exc}") from exc
    if not found:
        raise HTTPException(400, "Nothing to load - pick a file, or fetch a table, first.")
    dbs = got.db_side
    ask = loading.ReadAsked(name=loading.load_name(tag, body.name, dbs.conn if dbs else ""), label=got.label,
                            path=got.path, kind=kind, origin=dbs.origin if dbs else "", folder=got.folder,
                            delimiter=delim, header=header, where=body.where,
                            order_by=[c for c in body.order_by if c in found], desc=body.desc,
                            limit=body.limit, names_text=body.column_names, snapshot=body.snapshot)
    warn = loading.names_warning(body.column_names, found)
    with ws.lock:
        try:
            new = loading.build_side(tag, ask, found, dbs)
        except duckdb.Error as exc:
            raise HTTPException(400, f"Could not read the rows: {exc}") from exc
        for col, expr in panel(ws, tag).side.derived.items():      # the columns added to the old one come along
            if col in new.schema:
                warn = (warn + " " if warn else "") + f"The added column {col} was dropped - the file has its own {col}."
                continue
            try:
                add_derived(new, col, expr)
            except Exception as exc:
                warn = (warn + " " if warn else "") + f"The added column {col} was dropped - it does not read on these rows: {exc}"
        put_side(ws, tag, new)
    return {"side": side_view(ws, tag), "warnings": [warn] if warn else []}


@router.get("/{tag}/preview")
def preview(tag: str, n: int = Query(10, ge=1, le=100), ws: Workspace = Depends(workspace)) -> dict:
    """The first rows as the file has them, under the names the page shows."""
    s = panel(ws, _tag(tag)).side
    if not s.loaded:
        raise HTTPException(409, "Load this side first.")
    try:
        df = preview_rows(s, n)
    except duckdb.Error as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"columns": [str(c) for c in df.columns],
            "rows": json.loads(df.to_json(orient="values", date_format="iso", default_handler=str))}


def _connection(name: str) -> cx.Connection:
    try:
        conns = cx.load_all()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    c = conns.get(name)
    if c is None or c.is_folder:
        raise HTTPException(400, f"No database connection called {name} - pick one.")
    return c


@router.post("/{tag}/db")
def db_plan(tag: str, body: DbIn, ws: Workspace = Depends(workspace)) -> dict:
    """What the Database box shows for its boxes as they stand: the SQL, the cap warning, the
    fetch held for them, and whether a password must be typed."""
    _tag(tag)
    c = _connection(body.connection)
    needs = c.password is None and not cx.needs_no_password(c)
    out = {"sql": "", "error": "", "warning": "", "held": None,
           "password": "none" if not needs else "held" if c.name in ws.passwords else "asked"}
    try:
        sql, _ = loading.db_sql(c.kind, body.mode, body.table, body.sql)
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    out["sql"] = sql
    if body.cap and sql and not db.has_order_by(sql):
        out["warning"] = loading.CAP_WARNING
    held = panel(ws, tag).fetched
    if held and held.key == loading.fetch_key(loading.conn_key(c), sql, body.cap) and Path(held.path).exists():
        out["held"] = fetched_view(held)
    return out


@router.post("/{tag}/fetch")
def fetch(tag: str, body: FetchIn, ws: Workspace = Depends(workspace)) -> dict:
    """The rows fetched into a Parquet file in the work folder, as a job the Log follows."""
    _tag(tag)
    c0 = _connection(body.connection)
    if body.password:
        ws.passwords[c0.name] = body.password
    try:
        sql, what = loading.db_sql(c0.kind, body.mode, body.table, body.sql)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not sql:
        raise HTTPException(400, "Give a table, or write the SQL, first.")
    try:
        db.check_read_only(sql)
    except db.NotReadOnly as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        c = cx.resolve(c0.name, ws.passwords)
    except cx.PasswordNeeded as exc:
        raise HTTPException(400, "Type the password above first.") from exc
    key = loading.fetch_key(loading.conn_key(c0), sql, body.cap)     # the stored record, as Load builds it
    path = work_dir() / f"fetch_{tag}_{int(time.time() * 1000)}.parquet"
    p = panel(ws, tag)

    def work(ctx: jobs.JobCtx) -> dict:
        try:
            r = db.fetch_parquet(c, sql, str(path), body.cap, progress=ctx.say)
        except db.DriverMissing as exc:
            raise RuntimeError(str(exc)) from None
        except Exception as exc:                         # a driver's own error, redacted
            secrets = cx.known_secrets([c.password or "", *c.extra.values(), *ws.passwords.values()])
            raise RuntimeError("The fetch failed - " + cx.redact(str(exc), secrets)) from None
        ctx.label = f"Fetched {r.rows:,} rows in {r.seconds:.1f}s"
        if p.fetched:
            unlink_unless_loaded(p, p.fetched.path)
        p.fetched = Fetched(key, str(path), what, time.strftime("%H:%M:%S"), r.rows, r.capped)
        return {"rows": r.rows, "capped": r.capped}

    return jobs.public(jobs.start(ws, "Fetch", f"Fetching from {c.name}…", work, page=PAGE[tag], slot=tag))


@router.delete("/{tag}/fetch")
def drop_fetch(tag: str, ws: Workspace = Depends(workspace)) -> dict:
    """Fetch again: the held fetch goes (its file too, unless the loaded side reads it)."""
    p = panel(ws, _tag(tag))
    if p.fetched:
        unlink_unless_loaded(p, p.fetched.path)
        p.fetched = None
    return side_view(ws, tag)


class ConfigIn(BaseModel):
    text: str | None = None           # the file's text - the page reads an uploaded config itself
    path: str = ""


@router.post("/config")
def run_config(body: ConfigIn, ws: Workspace = Depends(workspace)) -> dict:
    """A saved config: both sides opened (a database side fetched), the column table, the Rows
    filters and the switches kept - as a job, since a fetch may take minutes. Then it compares, as a job of its own."""
    from ..runconfig import ConfigError, read_config
    text = body.text
    if text is None:
        where = body.path.strip().strip('"')
        if not where:
            raise HTTPException(400, "Give the config file, or its path.")
        if not path_allowed(where):
            raise HTTPException(400, "Not under an allowed folder (COMPARE_DATA_DIR).")
        try:
            text = Path(where).read_text(encoding="utf-8-sig")
        except (OSError, ValueError) as exc:             # a missing file, or one that is not UTF-8 text
            raise HTTPException(400, f"Could not read it: {exc}") from exc
    try:
        conf = read_config(text)
    except ConfigError as exc:
        raise HTTPException(400, f"Not loaded: {exc}") from exc
    try:
        boxes = loading.config_boxes(conf, loading.folder_names())
    except (ValueError, TypeError, AttributeError) as exc:     # "limit": "ten" and the like
        raise HTTPException(400, f"Not loaded: a value in the config is not usable ({exc}).") from exc

    def work(ctx: jobs.JobCtx) -> int:
        sides, said = loading.open_config_sides(conf, ws.passwords, say=ctx.say)
        for tag, s in sides.items():
            if s.is_database:                    # the panel holds the fetch, ready to Load again
                p = panel(ws, tag)
                if p.fetched and p.fetched.path != s.csv_path:
                    unlink_unless_loaded(p, p.fetched.path)
                key = loading.fetch_key(loading.conn_key(cx.load_all()[s.conn]), s.query, s.cap)
                p.fetched = Fetched(key, s.csv_path, "query", s.fetched_at, s.rows or 0, s.capped)
            put_side(ws, tag, s)
        ws.data["settings"] = {**(ws.data.get("settings") or {}), **boxes["settings"]}
        A, B = side(ws, "A"), side(ws, "B")
        if said or not (A.loaded and B.loaded):
            said = said + [("info", loading.CONFIG_PARTLY)]
        else:
            cmap, rows, said = loading.config_columns(conf, A, B)
            if cmap is not None:
                ws.data.update(cmap=cmap, cmap_seed=(A.label, tuple(A.columns), B.label, tuple(B.columns)),
                               filter_rows=rows, names={"A": boxes["A"]["name"], "B": boxes["B"]["name"]})
                ws.data["cmap_rev"] = ws.data.get("cmap_rev", 0) + 1           # a new table is a new version
                ws.data["filters_rev"] = ws.data.get("filters_rev", 0) + 1
                for k in ("auto_notes", "key_formats", "data_match", "filter_for", "looks_like", "looks_said"):
                    ws.data.pop(k, None)                  # load_config pops these too; the old pair's sample goes
                looks, looks_said = su.sniff_sides(A, B, sw.opts(ws))     # sampled now, so the setup page need not wait for the Compare
                ws.data.update(looks_like=looks, looks_said=looks_said)
                runs.start_compare(ws)
        n = (ws.data.get("config_view") or {}).get("n", 0) + 1
        ws.data["config_view"] = {"n": n, "said": [{"tone": t, "text": x} for t, x in said], "boxes": boxes}
        return n

    return runs.start_guarded(ws, lambda: jobs.public(jobs.start(ws, "Config", "Loading the config…", work, page="Compare")))
