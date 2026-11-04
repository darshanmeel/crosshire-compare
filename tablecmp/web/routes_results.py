# tablecmp/web/routes_results.py
"""The results of the run on the page, one view at a time - Summary (with Profile by bucket),
Columns & values, and the near-match analysis. Every read takes the workspace's lock: the run's
DuckDB connection serves one thread at a time. The wording is results.py's."""
from __future__ import annotations


from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import results as rs
from ..columns import role_tone
from ..column_facts import column_facts
from ..compare import (bucket_rows, cd_occ, cells_table, column_ledger, diffs_by_key_value,
                       differing_rows, join_on, key_value_sql, ledger_counts, near_match, pair_views,
                       paired_where, row_key, side_filter, side_labels, value_pairs)
from ..profile import label
from ..sql import ident, lit, memory_limit_bytes, scratch
from ..values import BYTES_A_CELL, HOLD_SHARE, ColSpec
from . import runs
from . import setupws as sw
from .routes_profiling import HIST_KINDS, _when, histogram
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/results")


def summary_body(run: dict) -> dict:
    NA, NB = run["names"]
    res, mode = run["result"], run["mode"]
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    out: dict = {"mode": mode, "keys": keys, "key_warning": None}
    if mode == "key":
        out["key_line"] = f"Rows are matched on **{' + '.join(keys)}** - **{res.matched_rows:,}** rows matched"
        if res.duplicate_keys_left or res.duplicate_keys_right:
            out["key_warning"] = {
                "head": (f":orange[**Key not unique**] · **{' + '.join(keys)}** repeats on "
                         f"**{res.duplicate_keys_left:,}** rows of {NA} and **{res.duplicate_keys_right:,}** of {NB}"),
                "points": ["repeats were paired in file order, so a difference there may be two rows swapped",
                           "add a column to the key - **Suggest keys** helps"]}
    elif mode == "hash":
        out["key_line"] = f"No key - rows were matched by hashing the {len(cols)} compared columns"
    else:
        out["key_line"] = "No key - rows were paired by position, line 1 against line 1"
    out["counts"] = [
        {"label": f"Rows {NA}", "value": res.rows_left_read}, {"label": f"Rows {NB}", "value": res.rows_right_read},
        {"label": "Matched on key" if mode == "key" else "Identical rows" if mode == "hash" else "Paired by position",
         "value": res.matched_rows},
        {"label": f"Only in {NA}", "value": res.only_left}, {"label": f"Only in {NB}", "value": res.only_right},
        {"label": "Rows that differ", "value": res.diff_rows,
         "help": "Matched rows where at least one compared column differs"}]
    out["filter_note"] = (f"Filter applied - comparing **{res.rows_left:,}** of {res.rows_left_read:,} "
                          f"{NA} rows and **{res.rows_right:,}** of {res.rows_right_read:,} {NB} rows."
                          if res.filter_left or res.filter_right else "")
    out["unmatched"] = ({"lead": (f"Only {res.matched_rows:,} rows matched on {' + '.join(keys)}. If that looks "
                                  "wrong, the key values are spelled differently on the two sides - give the key "
                                  "column a Type or a transform step:"),
                         "lines": [f"{NA}: `{v}`" for v in res.sample_unmatched_left]
                                  + [f"{NB}: `{v}`" for v in res.sample_unmatched_right]}
                        if res.sample_unmatched_left or res.sample_unmatched_right else None)
    ledger = column_ledger(run, NA, NB)
    counts = ledger_counts(ledger, NA, NB)
    out["column_counts"] = [{"label": k.capitalize() if i < 3 else k[0].upper() + k[1:], "value": v}
                            for i, (k, v) in enumerate(counts.items())]
    missing = [k for k, v in counts.items() if k.startswith("only in") and v]
    named = {k: ledger.loc[ledger["Role"] == k, "Column"].tolist() for k in missing}
    out["one_sided"] = ("Columns present on one side only, so not compared: "
                        + " · ".join(f"**{k}**: {', '.join(v[:12])}{' …' if len(v) > 12 else ''}"
                                     for k, v in named.items())) if missing else ""
    if mode == "hash":
        out.update(overall=None, overall_caption="",
                   hash_caption=("Distinct values present on one side only, per compared column - the "
                                 "columns with the most are where the one-sided rows differ."))
    else:
        fully = res.matched_rows - res.diff_rows
        out.update(overall=[{"label": "Overall match %", "value": f"{rs.pct_text(fully, res.matched_rows)}%"},
                            {"label": "Fully matched rows", "value": fully},
                            {"label": "Rows with differences", "value": res.diff_rows}],
                   overall_caption=(f"Match figures are measured on the {res.matched_rows:,} rows that paired. "
                                    "Key columns are identical by construction; one-sided columns have no partner."),
                   hash_caption="")
    out["ledger"] = sw.frame(ledger)
    out["tones"] = [role_tone(r) for r in ledger["Role"]] if len(ledger) else []
    buckets = rs.bucket_list(res, keys, NA, NB)
    out["buckets"] = [{"id": b, "label": label} for b, label in buckets]
    out["default_bucket"] = rs.first_bucket(dict(buckets), None) if buckets else ""
    label_a, label_b = side_labels(NA, NB)
    sided = run.get("one_sided") or {}
    out["sided_tip"] = (f":orange[Only in {label_a}] columns count for {label_a}'s rows, "
                        f":orange[only in {label_b}] for {label_b}'s - both on the paired rows"
                        if sided.get("A") or sided.get("B") else "")
    return out


def compared_groups(run: dict, bucket: str, cols: list[str], item) -> list[dict]:
    """The compared columns as the picker offers them: on paired rows those that differ (worst
    first, with their count) apart from those that agree; on one-sided rows one list."""
    if bucket in ("left", "right"):
        return [{"title": "Compared columns", "items": [item(c) for c in cols]}]
    by = run["result"].diffs_by_column
    bad = rs.mismatched(run, cols)
    return [{"title": "Mismatched columns", "items": [{**item(c), "label": f"{item(c)['label']} · {by[c]:,}"} for c in bad]},
            {"title": "Matching columns", "items": [item(c) for c in cols if c not in bad]}]


SUBSETS = {"matched": "matched", "same": "same", "differ": "differ", "left": "only_a", "right": "only_b"}


def bucket_body(run: dict, bucket: str, add: list[str], exact: bool = False) -> dict:
    """One bucket: which columns it counts and how - each column's values come from /values with
    `subset`, on the bucket's rows. The columns are the plan's own (the key, and on the paired
    buckets that differ the worst three) plus `add`, or - with `exact` - `add` alone, so a reader
    can untick a default. `groups` lists every column the bucket can count, as the page offers
    them: the key, the compared columns, the ones not compared."""
    NA, NB = run["names"]
    res = run["result"]
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    if bucket not in dict(rs.bucket_list(res, keys, NA, NB)):
        raise HTTPException(404, "This run has no such bucket of rows.")
    label_a, label_b = side_labels(NA, NB)
    side_name = {"A": label_a, "B": label_b}
    out: dict = {"bucket": bucket, "subset": SUBSETS[bucket], "by_key": None}
    by_val = diffs_by_key_value(run, keys) if bucket == "differ" else {}
    if by_val:
        out["by_key"] = {
            "title": (f"**By key value** - where the :red[{res.diff_rows:,} differing rows] sit, "
                      f"per key column of **{' + '.join(keys)}**"),
            "tables": [{"column": k, "title": f"**{k}** - top {len(t)} values by rows that differ", "table": sw.frame(t)}
                       for k, t in by_val.items()],
            "after": "**Every column across these rows** - its values, counted on each side"}
    own, shown, others = rs.bucket_plan(run, bucket, keys, cols)
    item = lambda c: {"name": c, "label": f"{c} · only in {side_name[own[c]]}" if c in own else c}
    out["shown"] = shown
    out["groups"] = [g for g in (
        {"title": "Key columns", "items": [item(c) for c in keys]},
        *compared_groups(run, bucket, [c for c in cols if c not in keys], item),
        {"title": "Not compared", "tone": "nc", "items": [item(c) for c in own if c not in keys and c not in cols]},
    ) if g["items"]]
    one = {"left": ["a"], "right": ["b"]}.get(bucket)
    out["columns"] = [{"column": col,
                       "title": f"**{col}**" + (" · key" if col in keys else
                                                f" · :orange[only in {side_name[own[col]]}]" if col in own else ""),
                       "sides": one or ([own[col].lower()] if col in own else ["a", "b"])}
                      for col in _counted(keys, shown, others, add, exact)]
    out["empty"] = "" if out["columns"] else "Tick a column to count its values on these rows."
    return out


def _counted(keys: list[str], shown: list[str], others: list[str], add: list[str], exact: bool) -> list[str]:
    """The columns a bucket counts: the plan's own plus `add`, or with `exact` `add` alone (in its order)."""
    if exact:
        can = set(keys) | set(shown) | set(others)
        return [c for c in dict.fromkeys(add) if c in can]
    return shown + [c for c in others if c in set(add)]


def facts_body(run: dict, bucket: str, add: list[str], exact: bool = False) -> dict:
    """The extended column profile of one bucket: for each column it counts (the same choice as
    bucket_body), its facts a side each - nulls, distinct, the top value, the range, the length,
    shapes, first and last characters, values spelled two ways. Each column measured once per
    bucket and kept on the run."""
    NA, NB = run["names"]
    res = run["result"]
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    if bucket not in dict(rs.bucket_list(res, keys, NA, NB)):
        raise HTTPException(404, "This run has no such bucket of rows.")
    label_a, label_b = side_labels(NA, NB)
    own, shown, others = rs.bucket_plan(run, bucket, keys, cols)
    wanted = _counted(keys, shown, others, add, exact)
    cache: dict[str, list] = run.setdefault("_facts", {}).setdefault(bucket, {})
    todo = [c for c in wanted if c not in cache]
    if todo:
        where = bucket_rows(run, keys, bucket, todo)
        names = [n for c in todo for _, n in where.get(c, [])]
        got = column_facts(run["con"], "bucket_rows", names)
        for c in todo:
            cache[c] = [{"side": s, "label": label_a if s == "A" else label_b, **got[n]} for s, n in where.get(c, [])]
        run["con"].execute("DROP TABLE IF EXISTS bucket_rows")
    return {"bucket": bucket, "columns": [{"column": c, "sides": cache[c]} for c in wanted if cache.get(c)]}


def key_values_body(run: dict, column: str, search: str, page: int, size: int) -> dict:
    """Every value of one key column the differing rows sit under - matched rows, rows that
    differ, their %, the cells and the columns that differ - most differing first, a page at a
    time. Counted once per key column and held on the run."""
    keys = rs.run_keys(run)
    if column not in keys or not diffs_by_key_value(run, keys):
        raise HTTPException(404, f"No key column called {column} with differing rows.")
    con, held = run["con"], run.setdefault("_key_values", {})
    if column not in held:
        held[column] = f"kv_{len(held)}"
        con.execute(f"CREATE OR REPLACE TABLE {held[column]} AS {key_value_sql(run, keys, column)}")
    hit, params = ("contains(lower(coalesce(CAST(v AS VARCHAR), 'null')), lower(?))", [search]) if search else ("TRUE", [])
    total = con.execute(f"SELECT count(*) FROM {held[column]} WHERE {hit}", params).fetchone()[0]
    got = con.execute(f"SELECT CAST(v AS VARCHAR), coalesce(matched, 0), diff_rows, pct, diff_cells, "
                      f"array_to_string(cols, ', ') FROM {held[column]} WHERE {hit} "
                      f"ORDER BY diff_rows DESC, v NULLS LAST LIMIT ? OFFSET ?", params + [size, (page - 1) * size]).fetchall()
    return {"column": column, "values": int(total), "page": page, "size": size,
            "rows": [{"value": v, "matched": int(m), "differ": int(d), "pct": float(p), "cells": int(n), "columns": cs}
                     for v, m, d, p, n, cs in got]}


def columns_body(run: dict, limit: int, pick: list[str]) -> dict:
    NA, NB = run["names"]
    res, mode = run["result"], run["mode"]
    if mode == "hash":
        return {"hash_caption": "With hashing there are no matched-but-different rows: a row is either "
                                "identical on the other side or one-sided. The one-sided rows are below."}
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    specs = {d["canon"]: ColSpec(**d) for d in run["cfg"]["specs"]}
    differing, shown, rest = rs.card_order(res, cols)
    pairs = value_pairs(run, 10)                 # one DuckDB pass over cd, every column at once
    out: dict = {"hash_caption": "", "rows": None,
                 "tips": [f"Each compared column on the **{res.matched_rows:,}** rows paired"
                          f"{' on ' + ' + '.join(keys) if keys else ' by position'} - :red[differing first], worst first",
                          f"{len(shown)} of {len(shown) + len(rest)} open; the rest under *Other columns*" if rest else "",
                          "What a set of rows holds: *Profile by bucket* on the Summary"],
                 "differ_error": ((f"**{len(differing)} column(s) differ**: "
                                   + ", ".join(f"{c} ({res.diffs_by_column[c]:,})" for c in differing[:10])
                                   + (" …" if len(differing) > 10 else "")) if differing else "")}
    if keys and res.diff_rows:
        df, marks = differing_rows(run, keys, cols, limit)
        out["rows"] = {"title": (f"Rows that differ - {NA} above {NB}, differing cells marked · "
                                 f"first {min(limit, res.diff_rows):,} of {res.diff_rows:,}"),
                       "table": sw.frame(df) if len(df) else None,
                       "marks": {str(i): sorted(cs) for i, cs in marks.items()}}
    out["rest"], out["rest_title"] = rest, f"Other columns - {len(rest)} not open"
    asked = set(pick)
    cards = []
    for col in shown + [c for c in rest if c in asked]:
        n = res.diffs_by_column.get(col, 0)
        pct = rs.pct_text(n, res.matched_rows)
        read_as = specs[col].describe() if col in specs else "text"
        head = (f"**{col}** · {read_as} - all {res.matched_rows:,} matched rows agree" if not n
                else f":red[**{col}** · {read_as} - {n:,} {'mismatch' if n == 1 else 'mismatches'} ({pct}%)]")
        warning = ("Every matched row differs on this column - usually two different fields paired by mistake, "
                   "or a value that converts on one side only. Check the column in the transform section."
                   if n and res.matched_rows and n >= 0.99 * res.matched_rows else "")
        table = None
        pair = pairs.get(col) if n else None
        if pair is not None and len(pair):
            pair = pair[["a", "b", "n", "pct"]].copy()
            pair.columns = [f"{NA} · {col}", f"{NB} · {col}", "Count", "%"]
            pair["%"] = pair["%"].astype(float).round(2)
            table = sw.frame(pair)
        cards.append({"column": col, "head": head, "warning": warning, "pairs": table})
    out["cards"] = cards
    out["near_match"] = bool(run["files"].get(f"{run['pair']}__cell_diffs.csv"))
    return out


@router.get("/{run_id}/summary")
def summary(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    with runs.reading(ws, run_id, "Summary") as run:
        return summary_body(run)


@router.get("/{run_id}/buckets/{bucket}")
def bucket(run_id: str, bucket: str, add: list[str] = Query(default=[]), exact: bool = False,
           ws: Workspace = Depends(workspace)) -> dict:
    with runs.reading(ws, run_id, "Summary") as run:
        return bucket_body(run, bucket, add, exact)


@router.get("/{run_id}/buckets/{bucket}/facts")
def bucket_facts(run_id: str, bucket: str, add: list[str] = Query(default=[]), exact: bool = False,
                 ws: Workspace = Depends(workspace)) -> dict:
    """The extended column profile of a bucket - asked for when the page shows it, read-only."""
    with runs.reading(ws, run_id, "Summary") as run:
        return facts_body(run, bucket, add, exact)


@router.get("/{run_id}/columns")
def columns(run_id: str, pick: list[str] = Query(default=[], alias="open"),
            ws: Workspace = Depends(workspace)) -> dict:
    with runs.reading(ws, run_id, "Columns & values") as run:
        return columns_body(run, int(runs.settings(ws)["display_rows"]), pick)


@router.get("/{run_id}/near-match")
def near(run_id: str, ws: Workspace = Depends(workspace)) -> dict:
    """How close the differing values are - asked for on its button, since it reads every cell."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        path = run["files"].get(f"{run['pair']}__cell_diffs.csv")
        if not path:
            raise HTTPException(404, "This run has no cell differences to measure.")
        with runs.guard(run, "Columns & values"):
            return sw.frame(near_match(str(path)))


def pairs_body(run: dict, column: str, limit: int) -> dict:
    """The most frequent (A value, B value) pairs behind one column's mismatches - with how many
    mismatches there are and how many distinct pairs they make, so the page can tell a few
    systematic renames from values that are all different."""
    if column not in rs.run_columns(run):
        raise HTTPException(404, f"This run did not compare a column called {column}.")
    out: dict = {"column": column, "mismatches": 0, "distinct": 0, "pairs": []}
    if not cells_table(run):
        return out
    # one pass: the windows count every pair before LIMIT keeps the top ones
    rows = run["con"].execute(
        "SELECT left_value, right_value, count(*) AS n, sum(count(*)) OVER () AS total, count(*) OVER () AS pairs "
        "FROM cd WHERE column_name = ? GROUP BY 1, 2 ORDER BY n DESC, 1, 2 LIMIT ?", [column, int(limit)]).fetchall()
    if rows:
        out.update(mismatches=int(rows[0][3]), distinct=int(rows[0][4]),
                   pairs=[{"a": label(a), "b": label(b), "n": int(n)} for a, b, n, *_ in rows])
    return out


def one_sided_body(run: dict, which: str, offset: int, limit: int) -> dict:
    """A page of the rows only one side has, read from the run's left_only / right_only file, with
    the side's own key column names and the columns that hold one value on every row (a pattern
    the page may point out)."""
    tag = {"A": "left", "B": "right"}[which]
    got = runs.one_sided_source(run, tag)
    specs = {d["canon"]: d for d in run["cfg"]["specs"]}
    own = "a_src" if which == "A" else "b_src"
    out: dict = {"side": which, "file": "", "keys": [], "total": 0, "offset": offset,
                 "columns": [], "rows": [], "constant": []}
    if got is None:
        return out
    name, src = got
    con = scratch(ordered=True)
    try:
        con.execute(f"CREATE TABLE one AS SELECT * FROM {src}")
        total = con.execute("SELECT count(*) FROM one").fetchone()[0]
        cols = [r[0] for r in con.execute("DESCRIBE one").fetchall()]
        keys = [k if k in cols else specs.get(k, {}).get(own, k) for k in rs.run_keys(run)]   # canon or own name
        order = " ORDER BY " + ", ".join(ident(k) for k in keys if k in cols) if any(k in cols for k in keys) else ""
        page = con.execute(f"SELECT * FROM one{order} LIMIT {int(limit)} OFFSET {int(offset)}").fetchdf()
        constant = []
        if total >= 2 and cols:
            q = ", ".join(f"count(DISTINCT {ident(c)}) = 1 AND count({ident(c)}) = count(*), "
                          f"any_value({ident(c)})" for c in cols)
            got = con.execute(f"SELECT {q} FROM one").fetchone()
            constant = [{"column": c, "value": str(got[2 * i + 1])} for i, c in enumerate(cols)
                        if got[2 * i] and c not in keys]
    finally:
        con.close()
    compared = set(rs.run_columns(run))
    groups = [{"title": t, "items": i, **({"tone": "nc"} if t == "Not compared" else {})} for t, i in (
        ("Key columns", [c for c in cols if c in keys]),
        ("Compared columns", [c for c in cols if c not in keys and c in compared]),
        ("Not compared", [c for c in cols if c not in keys and c not in compared])) if i]
    rest = [c for c in cols if c not in keys and c in compared]        # a column only this side has waits to be ticked
    out.update(file=name, keys=keys, total=int(total), columns=cols, rows=sw.frame(page)["rows"], constant=constant,
               groups=groups, shown=[c for c in cols if c in keys] + rest[:rs.BUCKET_SHOWN])
    return out


@router.get("/{run_id}/pairs/{column}")
def pairs(run_id: str, column: str, limit: int = Query(5, ge=1, le=100), ws: Workspace = Depends(workspace)) -> dict:
    """Why a column differs: its most frequent value pairs, for the Summary's side panel."""
    with runs.reading(ws, run_id, "Summary") as run:
        return pairs_body(run, column, limit)


@router.get("/{run_id}/one-sided/{which}")
def one_sided(run_id: str, which: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=10_000),
              ws: Workspace = Depends(workspace)) -> dict:
    """The rows only A (or only B) has, a page at a time, for the One-sided rows tab."""
    if which not in ("A", "B"):
        raise HTTPException(404, "A side is A or B.")
    with runs.reading(ws, run_id, "One-sided rows") as run:
        return one_sided_body(run, which, offset, limit)


# ---- value counts: how often each value occurs, on a side and a set of rows ----------------
HELD_VALUES = 50_000          # more distinct values than this (an id) are counted per call, not held
HELD_TABLES = 32              # counts held on a run at once, together within HOLD_SHARE of DuckDB's memory
PAIRED = ("matched", "same", "differ")     # the subsets of paired rows - every other is a side's rows


def _value_rows(run: dict, subset: str, side: str, column: str, differs: str, need: bool = True) -> str | None:
    """The SQL of the rows counted - the column as `v` (and B's as `b` for side "pair"): every row
    of a side after the run's filters, a bucket of paired rows - every one (matched), those with no
    difference (same) or with one (differ; only those where `differs` differs, when given) - or one
    side's one-sided rows. None, or 404 with `need`, when the side lacks the column."""
    con, cfg, c = run["con"], run["cfg"], ident(column)
    if subset in PAIRED:
        keys = rs.run_keys(run)
        pair_views(run, keys)
        rel = {"a": ("cmp_l", "l"), "b": ("cmp_r", "r")}
        picked = ("a", "b") if side == "pair" else (side,)
        src = [f"SELECT * FROM {rel[s][0]}" for s in picked]
        sel = ", ".join(f"{rel[s][1]}.{c} AS {name}" for s, name in zip(picked, ("v", "b")))
        where = paired_where(run, keys, subset)
        if differs:
            occ = cd_occ(run)
            where += (f" AND {row_key(keys, 'l.', '__occ' if occ else None)} IN (SELECT {row_key(keys, '', occ)} "
                      f"FROM cd WHERE column_name = {lit(differs)})")
        sql = f"SELECT {sel} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)}{where}"
    elif subset == "all":
        table = run["left"] if side == "a" else run["right"]
        src = [f"SELECT * FROM {ident(table)}"]
        where = side_filter(cfg, "left" if side == "a" else "right")
        sql = f"SELECT {c} AS v FROM {ident(table)}" + (f" WHERE {where}" if where else "")
    else:
        got = runs.one_sided_source(run, "left" if subset == "only_a" else "right")
        if got is None:
            raise HTTPException(404, "This run wrote no one-sided rows for this side.")
        src = [f"SELECT * FROM {got[1]}"]
        sql = f"SELECT {c} AS v FROM {got[1]}"
    if all(column in {r[0] for r in con.execute(f"DESCRIBE {q}").fetchall()} for q in src):
        return sql
    if need:
        raise HTTPException(404, f"No column called {column} on this side.")
    return None


def _counted_table(run: dict, subset: str, side: str, column: str, differs: str) -> str:
    """The grouped counts (v, n) - (v, b, n) for a pair, (v, na, nb) for both - as a table held on
    the run's connection: counted once, every page and search after that ranks the small table.
    A count too big to hold (an id, long text) stays a view, so memory does not grow; both sides is
    a view over the two. Only the HELD_TABLES used last are kept - the oldest is dropped."""
    cache = run.setdefault("_values", {})
    k = (subset, side, column, differs)
    if k in cache:                # used last - both sides with the two it is built on
        for t in [(subset, s, column, differs) for s in "ab" if side == "both"] + [k]:
            if t in cache:
                cache[t] = cache.pop(t)
        return cache[k]
    con = run["con"]
    if side == "both":            # from the two sides' own tables - a side without the column counts nothing
        x, y = (_counted_table(run, subset, s, column, differs)
                if _value_rows(run, subset, s, column, differs, need=False) else None for s in "ab")
        if not (x or y):
            raise HTTPException(404, f"No column called {column} on either side.")
        x, y = x or f"(SELECT * FROM {y} WHERE false)", y or f"(SELECT * FROM {x} WHERE false)"
        sql = (f"SELECT coalesce(x.v, y.v) AS v, coalesce(x.n, 0) AS na, coalesce(y.n, 0) AS nb "
               f"FROM {x} x FULL JOIN {y} y ON x.v IS NOT DISTINCT FROM y.v")
        held = False
    else:
        rows = _value_rows(run, subset, side, column, differs)
        sql = f"SELECT *, count(*) AS n FROM ({rows}) GROUP BY ALL"
        parts = ["v", "b"] if side == "pair" else ["v"]
        chars = " + ".join(f"coalesce(avg(strlen(CAST({p} AS VARCHAR))), 0)" for p in parts)
        d, chars = con.execute(f"SELECT approx_count_distinct(({', '.join(parts)})), {chars} FROM ({rows})").fetchone()
        held = d <= HELD_VALUES and d * (chars + BYTES_A_CELL) <= memory_limit_bytes(con) * HOLD_SHARE / HELD_TABLES
    run["_values_made"] = n = run.get("_values_made", -1) + 1
    name = f"{'vc' if held else 'vv'}_{n}"
    con.execute(f"CREATE OR REPLACE {'TABLE' if held else 'VIEW'} {name} AS {sql}")
    cache[k] = name
    while len(cache) > HELD_TABLES:
        _drop_counted(run, next(iter(cache)))
    return name


def _drop_counted(run: dict, k: tuple) -> None:
    """Drops one count, and the both sides view built on it."""
    name = run["_values"].pop(k, None)
    if name is None:
        return
    run["con"].execute(f"DROP {'TABLE' if name.startswith('vc_') else 'VIEW'} IF EXISTS {name}")
    if k[1] in ("a", "b"):
        _drop_counted(run, (k[0], "both", *k[2:]))


def _value_hist(run: dict, subset: str, side: str, column: str, differs: str, kind: str, bins: int) -> list[dict]:
    """Equal-width bins and the median a side, for a number, date or timestamp column - held on the run."""
    if not bins or kind not in HIST_KINDS or side == "pair":
        return []
    cache = run.setdefault("_values_hist", {})
    k = (subset, side, column, differs, bins)
    if k not in cache:
        con, out = run["con"], []
        x = "try_cast(v AS DOUBLE)" if kind == "number" else "epoch(try_cast(v AS TIMESTAMP))"
        q = "quantile_cont" if kind == "number" else "quantile_disc"
        for s in ("a", "b") if side == "both" else (side,):
            rows = _value_rows(run, subset, s, column, differs, need=False)
            if rows is None:
                continue
            got = histogram(con, f"({rows})", ColSpec("v", "v", "v", kind), bins)
            m = con.execute(f"SELECT {q}({x}, 0.5) FROM ({rows}) WHERE isfinite({x})").fetchone()[0]
            median = None if m is None else round(float(m), 6) if kind == "number" else _when(float(m), kind)
            out.append({"side": s, "bins": got, "median": median})
        cache[k] = out
    return cache[k]


def values_body(run: dict, column: str, subset: str, side: str, differs: str, basis: str, search: str,
                page: int, size: int, bins: int) -> dict:
    """One column's values counted over a set of rows, most frequent first, a page at a time:
    per side the rows, nulls, distinct values and the largest count, then each value with its
    count and running total per side - ranked on the whole set, so a search keeps the ranks."""
    if subset == "only_a" and side != "a" or subset == "only_b" and side != "b":
        raise HTTPException(400, f"The rows {subset} holds are counted on side {subset[-1]} only.")
    if side == "pair" and subset != "differ":
        raise HTTPException(400, "A to B pairs are counted on the differing rows only.")
    if side == "both" and subset in ("only_a", "only_b"):
        raise HTTPException(400, "Both sides are counted on all rows or the paired rows only.")
    if differs and subset != "differ":
        raise HTTPException(400, "differs narrows the differing rows only.")
    if subset in PAIRED and (run["mode"] != "key" or not rs.run_keys(run)):
        raise HTTPException(404, "This run paired no rows on a key.")
    if subset == "differ" and not cells_table(run):
        raise HTTPException(404, "This run has no differing rows to group.")
    if differs and differs not in rs.run_columns(run):
        raise HTTPException(404, f"This run did not compare a column called {differs}.")
    con = run["con"]
    kind = {d["canon"]: d for d in run["cfg"]["specs"]}.get(column, {}).get("kind", "text")
    table = _counted_table(run, subset, side, column, differs)
    ns = ["na", "nb"] if side == "both" else ["n"]
    names = ["a", "b"] if side == "both" else [side]
    null = "v IS NULL AND b IS NULL" if side == "pair" else "v IS NULL"
    keep = f"NOT ({null})" if basis == "nonnull" else "TRUE"
    order = f"{' + '.join(ns)} DESC, v NULLS LAST" + (", b NULLS LAST" if side == "pair" else "")
    stats = ", ".join(f"coalesce(sum({n}), 0)::BIGINT, coalesce(sum({n}) FILTER (WHERE {null}), 0)::BIGINT, "
                      f"count(*) FILTER (WHERE NOT ({null}) AND {n} > 0), coalesce(max({n}) FILTER (WHERE {keep}), 0)"
                      for n in ns)
    got = con.execute(f"SELECT {stats} FROM {table}").fetchone()
    sides = [{"side": s, "rows": int(got[4 * i]), "nulls": int(got[4 * i + 1]), "distinct": int(got[4 * i + 2]),
              "top": int(got[4 * i + 3])} for i, s in enumerate(names)]
    hit, params = "TRUE", []
    if search:
        parts = ["v", "b"] if side == "pair" else ["v"]
        # matched as the page shows it: a null reads "null", an empty text "empty"
        hit = " OR ".join(f"contains(CASE WHEN {p} IS NULL THEN 'null' WHEN CAST({p} AS VARCHAR) = '' THEN 'empty' "
                          f"ELSE lower(CAST({p} AS VARCHAR)) END, lower(?))" for p in parts)
        params = [search] * len(parts)
    cums = ", ".join(f"sum({n}) OVER (ORDER BY {order} ROWS UNBOUNDED PRECEDING)::BIGINT AS c_{n}" for n in ns)
    ranked = f"SELECT *, row_number() OVER (ORDER BY {order}) AS __rank, {cums} FROM {table} WHERE {keep}"
    total = con.execute(f"SELECT count(*) FROM {table} WHERE {keep} AND ({hit})", params).fetchone()[0]
    f = sw.frame(con.execute(f"SELECT * FROM ({ranked}) WHERE {hit} ORDER BY __rank LIMIT ? OFFSET ?",
                             params + [size, (page - 1) * size]).fetchdf())
    ix = {c: i for i, c in enumerate(f["columns"])}
    rows = [{"rank": r[ix["__rank"]], "value": r[ix["v"]], **({"b": r[ix["b"]]} if side == "pair" else {}),
             "n": [r[ix[n]] for n in ns], "cum": [r[ix["c_" + n]] for n in ns]} for r in f["rows"]]
    return {"column": column, "subset": subset, "side": side, "differs": differs, "basis": basis, "kind": kind,
            "sides": [{**sides[0], "side": "pair"}] if side == "pair" else sides,
            "values": int(total), "page": page, "size": size, "rows": rows,
            "hist": _value_hist(run, subset, side, column, differs, kind, bins)}


@router.get("/{run_id}/values")
def values(run_id: str, column: str = Query(..., max_length=1000),
           subset: Literal["all", "matched", "same", "differ", "only_a", "only_b"] = "all",
           side: Literal["a", "b", "both", "pair"] = "a", differs: str = Query("", max_length=1000),
           basis: Literal["all", "nonnull"] = "all", search: str = Query("", max_length=200),
           page: int = Query(1, ge=1, le=1_000_000), size: int = Query(25, ge=1, le=500), bins: int = Query(0, ge=0, le=50),
           ws: Workspace = Depends(workspace)) -> dict:
    """One column's value counts on a side and a set of rows - for the top values on the Summary,
    the buckets of Profile by bucket and the distinct values on the Differing and One-sided rows
    tabs. Read-only."""
    with runs.reading(ws, run_id, "Values") as run:
        return values_body(run, column, subset, side, differs, basis, search, page, size, bins)


@router.get("/{run_id}/key-values")
def key_values(run_id: str, column: str = Query(..., max_length=1000), search: str = Query("", max_length=200),
               page: int = Query(1, ge=1, le=1_000_000), size: int = Query(25, ge=1, le=500),
               ws: Workspace = Depends(workspace)) -> dict:
    """Every value of a key column the differing rows sit under, a page at a time - read-only."""
    with runs.reading(ws, run_id, "Key values") as run:
        return key_values_body(run, column, search, page, size)
