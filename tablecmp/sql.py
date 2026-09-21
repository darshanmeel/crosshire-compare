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


UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
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
    of memory on a wide table, whatever the row count."""
    return max(1, min(COLUMNS_A_STATEMENT, CELLS_A_STATEMENT // max(rows, 1)))
