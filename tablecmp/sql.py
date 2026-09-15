"""Quoting and connections. Our own quoting, so column names come back exactly as written."""
from __future__ import annotations

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
    return con
