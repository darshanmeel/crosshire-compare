"""A comparison as a file: everything the page decided, saved after a run, and run again -
on the page, or from the command line for one pair of files or many (python -m tablecmp.run).

The file holds the two sources, the column table (pairs, types, steps, key-format fixes),
the key, the switches, the filters and the outputs. Never a password or a key: a database
side is its connection's name and its SQL, and the password is asked for when it runs.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from .columns import apply_mapping_json, mapping_json, only_in, specs_from, table_compare, table_keys
from .compare import build_filters, column_rules, run_comparison, side_labels, signature
from .outputs import pair_name
from .sources import Side, add_derived, apply_names, file_stamp, kind_of, path_allowed, row_count, snapshot, source_schema, work_dir
from .values import NULL_TOKENS_DEFAULT, ReadOptions

KIND = "crosshire-compare config"
VERSION = 1
# the switches a config carries, as the run's cfg names them
SETTINGS = ("mode", "trim", "empty_as_null", "ignore_case", "tolerance", "null_tokens",
            "display_rows", "table_formats")
DB_FIELDS = ("connection", "database", "query", "cap")


class ConfigError(ValueError):
    """A config that cannot run as it is: not a config, a file missing, a column gone."""


# ---- saving ---------------------------------------------------------------------
def side_block(side: Side, name: str) -> dict:
    """One source as the config holds it. An uploaded file is a temporary copy in the work
    folder - its path is kept, marked, so a rerun says so instead of finding nothing."""
    block = {"name": name, "kind": side.kind, "delimiter": side.delimiter, "header": side.header,
             "where": side.where, "order_by": list(side.order_by), "desc": side.desc,
             "limit": side.limit, "snapshot": bool(side.cache_path)}
    file_cols = [c for c in side.columns if c not in side.derived]
    if file_cols != [c for c in (side.source_columns or side.columns) if c not in side.derived]:   # names typed over the header
        block["column_names"] = file_cols
    if side.derived:
        block["derived"] = dict(side.derived)
    if side.is_database:
        block.update(connection=side.conn, database=side.database, query=side.query, cap=side.cap)
        block.pop("kind")                        # the fetch is always Parquet
    else:
        block["path"] = side.csv_path
        try:
            block["uploaded"] = Path(side.csv_path).resolve().is_relative_to(work_dir().resolve())
        except OSError:
            block["uploaded"] = False
        rel = _in_folder(side.folder, side.csv_path)
        if rel:                                  # picked from a folder connection: kept by its name there
            block.update(folder=side.folder, file=rel)
    return block


def _folder_path(name: str) -> str:
    """Where the folder connection called ``name`` points, or '' when there is none."""
    if not name:
        return ""
    from . import connections as cx
    try:
        c = cx.load_all().get(name)
    except ValueError:
        return ""
    return c.host if c is not None and c.is_folder else ""


def _in_folder(folder: str, path: str) -> str:
    """The path relative to the folder connection (with /), or '' when it is not under it."""
    root = _folder_path(folder)
    if not root or not path:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return ""


def side_path(block: dict) -> str:
    """The file a side reads: in its folder connection when it has one and that folder is known
    here - so the config runs on a machine where the folder lies elsewhere - else its path."""
    root = _folder_path(str(block.get("folder") or ""))
    if root and block.get("file"):
        return str(Path(root) / str(block["file"]))
    return str(block.get("path") or "")


def make_config(cfg: dict, A: Side, B: Side, name_a: str, name_b: str, cmap: pd.DataFrame,
                filter_rows: pd.DataFrame | None = None) -> dict:
    """The config for a run: its cfg (what the engine was told), the column table it came
    from and the Rows filters as they were typed, so loading it fills the page back in."""
    rows = [] if filter_rows is None else [
        {k: ("" if pd.isna(v) else str(v)) for k, v in r.items()}
        for r in filter_rows.to_dict("records") if str(r.get("Column") or "").strip()]
    return {"kind": KIND, "version": VERSION, "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sides": {"A": side_block(A, name_a), "B": side_block(B, name_b)},
            "columns": json.loads(mapping_json(cmap))["columns"],
            "settings": {k: cfg[k] for k in SETTINGS if k in cfg},
            "filters": rows,
            "pairs": []}


def config_json(conf: dict) -> str:
    return json.dumps(conf, indent=2, default=str) + "\n"


# ---- reading ----------------------------------------------------------------------
def read_config(text: str) -> dict:
    """A config from its text, checked for what every run needs."""
    try:
        conf = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"not JSON: {exc}") from None
    if not isinstance(conf, dict) or conf.get("kind") != KIND:
        raise ConfigError("not a config file - save one from the Downloads tab after a run")
    try:
        version = int(conf.get("version") or 0)
    except (TypeError, ValueError):
        raise ConfigError("its version is not a number") from None
    if version > VERSION:
        raise ConfigError(f"made by a newer version (config version {conf['version']}) - update the app")
    sides = conf.get("sides") or {}
    if not all(isinstance(sides.get(w), dict) for w in "AB"):
        raise ConfigError("it needs both sides, A and B")
    if not conf.get("columns"):
        raise ConfigError("it pairs no columns")
    return conf


def options_of(conf: dict) -> ReadOptions:
    """The null and trim rules the run read with."""
    s = conf.get("settings") or {}
    tokens = [t.strip() for t in str(s.get("null_tokens", NULL_TOKENS_DEFAULT)).split(",") if t.strip()]
    if s.get("empty_as_null", True):
        tokens.append("")
    return ReadOptions(tuple(tokens), bool(s.get("trim", True)))


def with_file(block: dict, path: str | None, name: str | None = None) -> dict:
    """A side of the config with another file in it - a rerun on the next pair. The name is
    the one given, else the file's stem: two runs of one pair name are told apart by it."""
    if not path:
        return dict(block, **({"name": name} if name else {}))
    out = {k: v for k, v in block.items() if k not in DB_FIELDS + ("uploaded", "folder", "file")}
    out.update(path=str(path), kind=kind_of(str(path)), name=name or Path(path).stem)
    root = _folder_path(str(block.get("folder") or ""))
    if root and not Path(path).is_absolute() and not Path(path).exists():
        # a bare name, and the side came from a folder: the file of that name in the folder
        out.update(folder=block["folder"], file=Path(path).as_posix(), path=str(Path(root) / path))
    return out


def fetch_side(block: dict, which: str, passwords: dict[str, str] | None = None, say=print) -> str:
    """A database side's rows, fetched into a Parquet file in the work folder."""
    return _fetch(block, which, passwords, say)[0]


def _fetch(block: dict, which: str, passwords: dict[str, str] | None, say) -> tuple[str, bool]:
    """The fetched file, and whether the fetch stopped at its cap."""
    from . import connections as cx
    from . import databases as db
    c = cx.resolve(block["connection"], passwords)           # PasswordNeeded when none is known
    path = work_dir() / f"fetch_{which}_{int(time.time() * 1000)}.parquet"
    say(f"Fetching {block.get('name') or which} from {c.name}…")
    r = db.fetch_parquet(c, block["query"], str(path), int(block.get("cap") or 0), progress=say)
    return str(path), r.capped


def open_side(block: dict, which: str, passwords: dict[str, str] | None = None, say=print) -> Side:
    """A side read the way the config says: the file (or the fetch), its delimiter and header,
    the names typed over the header, the rows to read, a Parquet snapshot."""
    name = str(block.get("name") or which)
    if block.get("connection"):
        from . import connections as cx
        from . import databases as db
        path, capped = _fetch(block, which, passwords, say)
        conn = cx.load_all()[block["connection"]]
        side = Side(name=name, label=f"{block['connection']}.parquet", csv_path=path, kind="parquet",
                    conn=block["connection"], database=conn.kind, query=block["query"],
                    cap=int(block.get("cap") or 0), capped=capped, fetched_at=time.strftime("%H:%M:%S"),
                    origin=db.origin_of(conn, block["query"]))
    else:
        path = side_path(block)
        if path and not path_allowed(path):          # first, so a config cannot ask what exists outside it
            raise ConfigError(f"{name}: not under an allowed folder (COMPARE_DATA_DIR)")
        if not path or not Path(path).is_file():
            hint = (" - it was an upload, so give the file's own path" if block.get("uploaded") else "")
            raise ConfigError(f"{name}: file not found: {path or '(none)'}{hint}")
        side = Side(name=name, label=Path(path).name, csv_path=path, kind=block.get("kind") or kind_of(path),
                    folder=str(block.get("folder") or "") if _folder_path(str(block.get("folder") or "")) else "")
    side.delimiter = str(block.get("delimiter") or ",")
    side.header = bool(block.get("header", True))
    side.where = str(block.get("where") or "")
    side.order_by = list(block.get("order_by") or [])
    side.desc = bool(block.get("desc"))
    side.limit = int(block.get("limit") or 0)
    schema = source_schema(side.csv_path, side.kind, side.delimiter, side.header, file_stamp(side.csv_path))
    names = list(block.get("column_names") or [])
    side.schema = apply_names(schema, names) if names else dict(schema)
    side.source_columns = list(schema)
    if block.get("snapshot") and not (side.kind == "parquet" and not side.cut):
        snapshot(side, str(work_dir() / f"cmp_{which}_{int(time.time() * 1000)}.parquet"))
    for col, expr in (block.get("derived") or {}).items():
        try:
            add_derived(side, str(col), str(expr))
        except Exception as exc:
            raise ConfigError(f"{name}: the added column {col} does not read - {exc}") from exc
    side.rows = row_count(side)
    return side


def missing_columns(conf: dict, A: Side, B: Side) -> list[str]:
    """Each paired column the config names that a side does not have - said, never guessed."""
    out = []
    for r in conf["columns"]:
        for col, side in ((r.get("a", ""), A), (r.get("b", ""), B)):
            if col and col not in side.columns:
                out.append(f"{col} (not in {side.name})")
    return list(dict.fromkeys(out))


def column_table(conf: dict, A: Side, B: Side) -> pd.DataFrame:
    """The page's column table from the config's pairs - and a row for every column no pair uses."""
    return apply_mapping_json(json.dumps({"columns": conf["columns"]}), A, B)


def build_cfg(conf: dict, A: Side, B: Side, name_a: str, name_b: str, cmap: pd.DataFrame | None = None) -> dict:
    """What the engine is told, worked out from the config against these two sides - the same
    dict the Compare button builds."""
    gone = missing_columns(conf, A, B)
    if gone:
        raise ConfigError("columns the config pairs are missing: " + ", ".join(gone))
    cmap = column_table(conf, A, B) if cmap is None else cmap
    specs = specs_from(cmap)
    keys, compare = table_keys(cmap), table_compare(cmap)
    s = dict(conf.get("settings") or {})
    mode = "key" if keys else (s.get("mode") if s.get("mode") in ("hash", "position") else "hash")
    if not compare:
        raise ConfigError("no column is ticked Compare")
    rows = pd.DataFrame(conf.get("filters") or [],
                        columns=["Apply to", "Column", "Operator", "Value", "Type"])
    both, left, right = build_filters(rows, name_a, name_b, specs)      # ValueError on a bad value
    return {"name": pair_name(name_a, name_b), "notes": [],
            "table_formats": list(s.get("table_formats") or ["csv"]),
            "matched_by": {sp.canon: "config" for sp in specs},
            "mode": mode, "keys": keys if mode == "key" else [], "specs": [sp.__dict__ for sp in specs],
            "compare_columns": compare, "only_a": only_in(cmap, "A"), "only_b": only_in(cmap, "B"),
            "trim": bool(s.get("trim", True)), "empty_as_null": bool(s.get("empty_as_null", True)),
            "ignore_case": bool(s.get("ignore_case", False)), "tolerance": float(s.get("tolerance") or 0.0),
            "null_tokens": str(s.get("null_tokens", NULL_TOKENS_DEFAULT)),
            "column_rules": column_rules(specs, compare),
            "filters": both, "left_filters": left, "right_filters": right,
            "display_rows": int(s.get("display_rows") or 1000)}


# ---- running ------------------------------------------------------------------------
@dataclass
class PairOutcome:
    """One pair of a config run, as the command line lists it."""
    name: str
    status: str = ""
    folder: str = ""
    error: str = ""
    counts: dict = field(default_factory=dict)


def write_outputs(run: dict, cfg: dict, A: Side, B: Side, name_a: str, name_b: str) -> None:
    """The report, the summary sheets and the Parquet copies - what a page run writes, through the
    page's own function; a failure raises here, where the page would warn."""
    from .comparing import write_outputs as write_all
    write_all(run, cfg, A, B, name_a, name_b, strict=True)


def run_pair(conf: dict, left: str | None = None, right: str | None = None,
             names: tuple[str | None, str | None] = (None, None), out: str | None = None,
             passwords: dict[str, str] | None = None, say=print) -> PairOutcome:
    """One pair: the config's own sides, or its settings on other files. The run folder is
    copied under `out` when it is given. Any failure is the pair's own outcome - the next
    pair of a batch still runs."""
    a_block = with_file(conf["sides"]["A"], left, names[0])
    b_block = with_file(conf["sides"]["B"], right, names[1])
    label = f"{a_block.get('name') or 'A'} against {b_block.get('name') or 'B'}"
    try:
        opts = options_of(conf)
        A = open_side(a_block, "A", passwords, say)
        B = open_side(b_block, "B", passwords, say)
        NA, NB = side_labels(A.name, B.name)
        cfg = build_cfg(conf, A, B, NA, NB)
        run = run_comparison(A, B, cfg, opts, signature(A, B, cfg), progress=say, names=(NA, NB))
    except Exception as exc:                     # noqa: BLE001 - reported per pair, the batch goes on
        return PairOutcome(label, "Error", error=_said(exc))
    res = run["result"]
    try:
        if res.error:
            return PairOutcome(label, "Error", str(run["folder"]), res.error)
        write_outputs(run, cfg, A, B, NA, NB)
        folder = Path(run["folder"])
        if out:
            dest = Path(out).expanduser() / folder.name
            shutil.copytree(folder, dest, dirs_exist_ok=True)
            folder = dest
        return PairOutcome(label, run["verdict"].word, str(folder), counts={
            "matched": res.matched_rows, "differ": res.diff_rows, "cells": res.cell_diffs,
            "only_left": res.only_left, "only_right": res.only_right})
    finally:
        run["con"].close()


def _said(exc: Exception) -> str:
    from .connections import PasswordNeeded, redact
    if isinstance(exc, PasswordNeeded):
        return (f"connection {exc.name} needs a password - set COMPARE_PASSWORD_{env_name(exc.name)} "
                f"or run from a terminal to be asked")
    return redact(f"{type(exc).__name__}: {exc}" if not isinstance(exc, ConfigError) else exc)


def env_name(conn: str) -> str:
    """A connection's name as the end of an environment variable: COMPARE_PASSWORD_<NAME>."""
    return "".join(ch if ch.isalnum() else "_" for ch in conn).upper()


def pairs_of(conf: dict, left: str | None = None, right: str | None = None) -> list[dict]:
    """The pairs a run takes: the files given on the command line, else the config's `pairs`
    list, else the config's own two sides."""
    if left or right:
        return [{"left": left, "right": right}]
    return [p for p in conf.get("pairs") or [] if isinstance(p, dict)] or [{}]
