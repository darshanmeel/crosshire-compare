"""Quoting and connections. Our own quoting, so column names come back exactly as written."""
from __future__ import annotations

import os

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
    mem = os.environ.get("COMPARE_DUCKDB_MEMORY", "").strip()
    if mem:
        con.execute(f"SET memory_limit = {lit(mem)}")
    return con
