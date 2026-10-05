"""What the Profile page's column views read, worked out once per profile: the table held in one
DuckDB database for as long as the profile is (read and typed once, not again per request), and
each answer kept by its question - the Profile job asks the usual ones before it says done, so a
column's page only draws what is there."""
from __future__ import annotations

import threading
from typing import Any, Callable

from ..sql import scratch
from ..values import ColSpec, hold
from .sides import side
from .workspace import Workspace

DB = "profile_db_P"         # (profile, connection) - the table under the name "prof"
MEMO = "profile_memo_P"     # (profile, {question: answer}, {question: lock})
_guard = threading.Lock()


def drop(ws: Workspace) -> None:
    """The held table goes - a new profile or a new table on the page."""
    got = ws.data.pop(DB, None)
    ws.data.pop(MEMO, None)
    if got:
        got[1].close()


def cursor(ws: Workspace, prof: dict):
    """A connection of its own on the held table "prof" - every column of the profile, in the
    file's order, typed as profiled. Closed by the caller; the table stays."""
    from .routes_profiling import read_options       # local import: routes_profiling imports this
    with _guard:
        got = ws.data.get(DB)
        if not got or got[0] is not prof:
            drop(ws)
            con = scratch(ordered=True)              # the file's own order: a key's sequence reads it
            specs = [ColSpec(**s) for s in prof.get("specs", [])]
            stats = prof["stats"]
            rows = int(stats["Rows"].iloc[0]) if len(stats) else None
            hold(con, side(ws, "P"), "prof", specs, "A", read_options(ws), rows)
            got = (prof, con)
            ws.data[DB] = got
        return got[1].cursor()


def memo(ws: Workspace, prof: dict, question: tuple, work: Callable[[], Any]) -> Any:
    """The answer to `question` for this profile - worked out once; a second asker waits for the first."""
    with _guard:
        got = ws.data.get(MEMO)
        if not got or got[0] is not prof:
            got = (prof, {}, {})
            ws.data[MEMO] = got
        lock = got[2].setdefault(question, threading.Lock())
    with lock:
        if question not in got[1]:
            got[1][question] = work()
        return got[1][question]


def peek(ws: Workspace, prof: dict, question: tuple) -> Any:
    """The answer if it is worked out already, else None - for a page that should not wait on it."""
    got = ws.data.get(MEMO)
    return got[1].get(question) if got and got[0] is prof else None


def held_answer(ws: Workspace, prof: dict, question: tuple, work: Callable[[Any], Any]) -> Any:
    """`work(con)` on the held table, once per profile and question."""
    def run() -> Any:
        con = cursor(ws, prof)
        try:
            return work(con)
        finally:
            con.close()
    return memo(ws, prof, question, run)


def warm(ws: Workspace, prof: dict, say: Callable[[str], None]) -> None:
    """Ask, before the Profile job says done, what each column's page asks for when it opens -
    so the pages only draw. A question that fails here is asked again by its page, which says why."""
    # local imports: the routes import this module
    from .. import profiling
    from . import routes_col_flag as fl, routes_col_key as ky, routes_col_number as nb
    from . import routes_col_text as tx, routes_col_when as wh, routes_overview as ov
    from . import routes_profiling as rp
    stats = prof["stats"].to_dict("records")
    key = profiling.best_key(prof) or []
    casts = {}
    asks: list[tuple[str, Callable[[], Any]]] = [("casts", lambda: rp.cast_counts(ws)), ("overview", lambda: ov.findings(ws))]
    for r in stats:
        c, kind = str(r["Column"]), str(r["Type"])
        if len(key) == 1 and key[0] == c:
            asks.append((c, lambda c=c: ky.key_check(c, ws)))
        if kind == "text":
            asks += [(c, lambda c=c: rp.column_spelling(c, ws)),
                     (c, lambda c=c: tx.column_similar(c, "", tx.NGRAM_MIN, ws))]
        if kind == "number":
            asks += [(c, lambda c=c: rp.hist(c, 10, ws)), (c, lambda c=c: nb.column_numform(c, ws))]
        if kind in ("date", "timestamp"):
            asks += [(c, lambda c=c, k=kind: wh.column_when(c, k, "", ws)), (c, lambda c=c: rp.hist(c, 10, ws))]
        if kind == "boolean":
            asks.append((c, lambda c=c: fl.column_flag(c, "", "", ws)))
        if kind in rp.READ_AS:
            asks.append((c, lambda c=c, k=kind: rp.column_parts(c, 3, casts.get(c, k), ws)))
    say("Working out each column's page…")
    for i, (_, ask) in enumerate(asks):
        if i == 2:          # the casts are in: a text column read as a date opens on its date page
            for row in rp._casts_held(ws, prof)["columns"]:
                got = rp.reads_as(row)
                if got:
                    casts[row["column"]] = got
                    asks.append((row["column"], lambda c=row["column"], k=got: wh.column_when(c, k, "", ws)))
        try:
            ask()
        except Exception:
            pass
