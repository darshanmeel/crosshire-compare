"""Quoting and connections. Our own quoting, so column names come back exactly as written."""
from __future__ import annotations

import os
import re

import duckdb

SRC = "src:"            # prefix the engine expects in front of a view name


def lit(s: object) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ident(s: object) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def scratch(ordered: bool = False) -> duckdb.DuckDBPyConnection:
    """A fresh in-memory connection. Order is only preserved when asked, which lets
    DuckDB use every core for everything else."""
    con = duckdb.connect()
    con.execute(f"SET preserve_insertion_order = {'true' if ordered else 'false'}")
    con.execute("SET TimeZone = 'UTC'")
    from .sources import work_dir       # local import: sources imports sql
    con.execute(f"SET temp_directory = {lit(str(work_dir() / 'duckdb'))}")
    lim = engine_limits()
    con.execute(f"SET memory_limit = {lit(lim['memory'])}")
    con.execute(f"SET max_temp_directory_size = {lit(lim['disk'])}")
    return con


# DuckDB's own defaults are 80% of the machine's memory and 90% of the free disk for spilling -
# enough to starve the server and the browser, or fill the disk. These are the app's instead;
# the Run settings card changes them (saved in the work folder), COMPARE_DUCKDB_MEMORY and
# COMPARE_DUCKDB_DISK fix them for every user of a shared machine. Memory past the limit
# spills to temp_directory up to the disk limit; a count(DISTINCT) or a quantile cannot spill
# and fails instead, which in_batches answers by halving the batch.
DEFAULT_MEMORY = "2GB"
DEFAULT_DISK = "20GB"
MIN_MEMORY = 256 * 2 ** 20
MIN_DISK = 2 ** 30
_saved: dict[str, tuple[float, dict]] = {}       # settings file -> (mtime, what it held)


def _settings_file():
    from .sources import work_dir       # local import: sources imports sql
    return work_dir() / "engine.json"


def _read_saved() -> dict:
    f = _settings_file()
    try:
        m = f.stat().st_mtime
    except OSError:
        return {}
    hit = _saved.get(str(f))
    if hit and hit[0] == m:
        return hit[1]
    import json
    try:
        got = json.loads(f.read_text(encoding="utf-8"))
        got = {k: str(got[k]) for k in ("memory", "disk") if isinstance(got, dict) and got.get(k)}
    except (OSError, ValueError):
        got = {}
    for k in list(got):                 # a hand-edited value DuckDB would refuse falls back to the default
        try:
            got[k] = _size_text(got[k])
        except ValueError:
            del got[k]
    _saved[str(f)] = (m, got)
    return got


def _size_text(text: str) -> str:
    """A size as it is kept and given to DuckDB: '1.5 GiB' -> '1.5GiB'. DuckDB reads a space between
    the number and the unit but not one inside the number, so '1 000MB' is refused here."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?) ?([A-Za-z]+)", str(text).strip())
    if not m or m[2].upper() not in UNITS:
        raise ValueError(f"{text!r} is not a size - write it as 2GB, 512MB or 1.5GiB")
    return m[1] + m[2]


def size_bytes(text: str) -> int:
    """'2GB', '1.5 GiB', '512MB', '4G' -> bytes; ValueError for anything else."""
    t = _size_text(text)
    unit = t.lstrip("0123456789.")
    return int(float(t[: len(t) - len(unit)]) * UNITS[unit.upper()])


def engine_limits() -> dict:
    """DuckDB's memory and spill-to-disk limits for every connection the app opens, and where
    each comes from: 'env' (fixed by the machine's owner), 'saved' (set on the page) or 'default'."""
    saved = _read_saved()
    out: dict = {}
    for k, env, dflt in (("memory", "COMPARE_DUCKDB_MEMORY", DEFAULT_MEMORY), ("disk", "COMPARE_DUCKDB_DISK", DEFAULT_DISK)):
        given = os.environ.get(env, "").strip()
        out[k], out[k + "_from"] = (given, "env") if given else (saved[k], "saved") if saved.get(k) else (dflt, "default")
    return out


def save_engine_limits(memory: str, disk: str) -> dict:
    """Check and keep the page's limits - each a size DuckDB reads, memory at least 256MB and at
    most the machine's, disk at least 1GiB. They apply to every connection opened after this.
    A limit fixed by its environment variable is neither checked nor kept: what the page sends
    for it is only the variable's value read back."""
    import json
    now = engine_limits()
    keep = {k: v for k, v in _read_saved().items() if now[k + "_from"] != "env"}
    if now["memory_from"] != "env":
        mem = size_bytes(memory)
        if mem < MIN_MEMORY:
            raise ValueError("Memory must be at least 256MB")
        total = machine_memory_bytes()
        if total and mem > total:
            raise ValueError(f"Memory must be at most this machine's {total / 2 ** 30:.1f} GiB")
        keep["memory"] = _size_text(memory)
    if now["disk_from"] != "env":
        if size_bytes(disk) < MIN_DISK:
            raise ValueError("Disk must be at least 1GB")
        keep["disk"] = _size_text(disk)
    f = _settings_file()
    f.write_text(json.dumps(keep), encoding="utf-8")
    _saved.pop(str(f), None)
    return engine_limits()


def machine_memory_bytes() -> int:
    """The machine's memory, as DuckDB sees it: its default limit is 80% of it."""
    return int(memory_limit_bytes(duckdb.connect()) / 0.8)


UNITS = {"B": 1, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
         "KIB": 2 ** 10, "MIB": 2 ** 20, "GIB": 2 ** 30, "TIB": 2 ** 40}
CELLS_A_STATEMENT = 4_000_000       # values one measuring statement may hold at once
COLUMNS_A_STATEMENT = 32            # and the most columns, however few the rows


def memory_limit_bytes(con: duckdb.DuckDBPyConnection) -> int:
    """DuckDB's memory_limit on this connection, in bytes - '12.5 GiB' as it prints it."""
    text = str(con.execute("SELECT current_setting('memory_limit')").fetchone()[0]).strip()
    num, _, unit = text.partition(" ")
    try:
        return int(float(num) * UNITS.get(unit.upper() or "B", 1))
    except ValueError:
        return 0


def columns_a_statement(rows: int) -> int:
    """How many columns one statement measures at once - count(DISTINCT) holds a hash
    table per column, so the columns of a big table go a few at a time and a small
    table's go COLUMNS_A_STATEMENT at a time: hundreds at once is what runs DuckDB out
    of memory on a wide table, whatever the row count.

    A count of cells is only a guess at the memory: a million rows of 2 KB notes is a
    hundred times the hash table of a million short codes. in_batches is what makes a
    wrong guess cost a retry rather than the run."""
    return max(1, min(COLUMNS_A_STATEMENT, CELLS_A_STATEMENT // max(rows, 1)))


def in_batches(items: list, run, per: int) -> list:
    """`run(batch)` over the items, `per` at a time, every result in order - the batch halved
    and tried again when DuckDB runs out of memory, and smaller from then on.

    A count(DISTINCT), a quantile or a list() holds its hash table in memory and raises rather
    than spilling, and how much it needs depends on how wide the values are, which the cell
    count behind `per` cannot know. One item that still will not fit raises: there is nothing
    left to halve, and a measurement nobody can take is worth saying out loud."""
    out: list = []
    i = 0
    while i < len(items):
        batch = items[i:i + per]
        try:
            out += run(batch)
        except duckdb.OutOfMemoryException:
            if len(batch) == 1:
                raise
            per = max(1, per // 2)
            continue
        i += len(batch)
    return out
