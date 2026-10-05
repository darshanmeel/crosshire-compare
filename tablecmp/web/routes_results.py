# tablecmp/web/routes_results.py
"""The results of the run on the page, one view at a time - Summary (with Profile by bucket),
Columns & values, and the near-match analysis. Every read takes the workspace's lock: the run's
DuckDB connection serves one thread at a time. The wording is results.py's."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import results as rs
from ..columns import role_tone
from ..column_facts import column_facts
from ..compare import (bucket_profile, bucket_rows, cells_table, column_ledger, diffs_by_key_value, differing_rows,
                       ledger_counts, near_match, side_labels, value_pairs)
from ..profile import label
from ..sql import ident, lit, scratch
from ..values import ColSpec
from . import runs
from . import setupws as sw
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


def bucket_body(run: dict, bucket: str, add: list[str], exact: bool = False) -> dict:
    """One bucket's profile. The columns counted are the plan's own plus `add`, or - with `exact` -
    `add` alone, so a reader can untick one the plan counts. `groups` lists every column the bucket
    can count, as the page offers them: the key, the compared columns, the ones not compared."""
    NA, NB = run["names"]
    res = run["result"]
    keys, cols = rs.run_keys(run), rs.run_columns(run)
    if bucket not in dict(rs.bucket_list(res, keys, NA, NB)):
        raise HTTPException(404, "This run has no such bucket of rows.")
    label_a, label_b = side_labels(NA, NB)
    side_name = {"A": label_a, "B": label_b}
    out: dict = {"bucket": bucket, "by_key": None}
    if bucket == "differ":
        by_val = diffs_by_key_value(run, keys)
        out["by_key"] = {
            "title": (f"**By key value** - where the :red[{res.diff_rows:,} differing rows] sit, "
                      f"per key column of **{' + '.join(keys)}**"),
            "tables": [{"title": f"**{k}** - top {len(t)} values by rows that differ", "table": sw.frame(t)}
                       for k, t in by_val.items()],
            "after": "**Every column across these rows** - top values, counted on each side"}
    apart = bool(out["by_key"] and out["by_key"]["tables"])
    own, shown, others = rs.bucket_plan(run, bucket, keys, cols, keys_apart=apart)
    item = lambda c: {"name": c, "label": f"{c} · only in {side_name[own[c]]}" if c in own else c}
    out["others"] = [item(c) for c in others]
    out["others_title"] = f"Other columns - {len(others)} to add"
    out["shown"] = shown
    out["groups"] = [g for g in (
        {"title": "Key columns", "items": [] if apart else [item(c) for c in keys]},
        *compared_groups(run, bucket, [c for c in cols if c not in keys], item),
        {"title": "Not compared", "tone": "nc", "items": [item(c) for c in own if c not in keys and c not in cols]},
    ) if g["items"]]
    prof = bucket_profile(run, keys, cols, bucket, only=_counted(keys, shown, others, apart, add, exact))
    out["profiles"] = [{"column": col,
                        "title": f"**{col}**" + (" · key" if col in keys else
                                                 f" · :orange[only in {side_name[own[col]]}]" if col in own else ""),
                        "table": sw.frame(df)} for col, df in prof.items()]
    out["empty"] = "" if prof else "Nothing to profile for this bucket."
    return out


def _counted(keys: list[str], shown: list[str], others: list[str], apart: bool, add: list[str], exact: bool) -> list[str]:
    """The columns a bucket counts: the plan's own plus `add`, or with `exact` `add` alone."""
    asked = set(add)
    can = set(shown) | set(others) | (set() if apart else set(keys))
    return [c for c in can if c in asked] if exact else shown + [c for c in others if c in asked]


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
    apart = bucket == "differ" and bool(diffs_by_key_value(run, keys))
    own, shown, others = rs.bucket_plan(run, bucket, keys, cols, keys_apart=apart)
    wanted = _counted(keys, shown, others, apart, add, exact)
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
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Summary"):
            return summary_body(run)


@router.get("/{run_id}/buckets/{bucket}")
def bucket(run_id: str, bucket: str, add: list[str] = Query(default=[]), exact: bool = False,
           ws: Workspace = Depends(workspace)) -> dict:
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Summary"):
            return bucket_body(run, bucket, add, exact)


@router.get("/{run_id}/buckets/{bucket}/facts")
def bucket_facts(run_id: str, bucket: str, add: list[str] = Query(default=[]), exact: bool = False,
                 ws: Workspace = Depends(workspace)) -> dict:
    """The extended column profile of a bucket - asked for when the page shows it, read-only."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Summary"):
            return facts_body(run, bucket, add, exact)


@router.get("/{run_id}/columns")
def columns(run_id: str, pick: list[str] = Query(default=[], alias="open"),
            ws: Workspace = Depends(workspace)) -> dict:
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Columns & values"):
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
    con = run["con"]
    total, distinct = con.execute(
        "SELECT count(*), count(DISTINCT (coalesce(left_value, chr(2)), coalesce(right_value, chr(2)))) "
        "FROM cd WHERE column_name = ?", [column]).fetchone()
    rows = con.execute(
        "SELECT left_value, right_value, count(*) AS n FROM cd WHERE column_name = ? "
        "GROUP BY 1, 2 ORDER BY n DESC, 1, 2 LIMIT ?", [column, int(limit)]).fetchall()
    out.update(mismatches=int(total), distinct=int(distinct),
               pairs=[{"a": label(a), "b": label(b), "n": int(n)} for a, b, n in rows])
    return out


def one_sided_body(run: dict, which: str, offset: int, limit: int) -> dict:
    """A page of the rows only one side has, read from the run's left_only / right_only file, with
    the side's own key column names and the columns that hold one value on every row (a pattern
    the page may point out)."""
    tag = {"A": "left", "B": "right"}[which]
    files = run["files"]
    stem = f"{run['pair']}__{tag}_only"
    path = next((files[n] for n in (f"{stem}.csv", f"{stem}.parquet") if n in files and Path(files[n]).is_file()),
                None)
    specs = {d["canon"]: d for d in run["cfg"]["specs"]}
    own = "a_src" if which == "A" else "b_src"
    out: dict = {"side": which, "file": "", "keys": [], "total": 0, "offset": offset,
                 "columns": [], "rows": [], "constant": []}
    if path is None:
        return out
    p = Path(path)
    src = f"read_parquet({lit(str(p))})" if p.suffix == ".parquet" else f"read_csv({lit(str(p))}, all_varchar=true)"
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
    out.update(file=p.name, keys=keys, total=int(total), columns=cols, rows=sw.frame(page)["rows"], constant=constant,
               groups=groups, shown=[c for c in cols if c in keys] + rest[:rs.BUCKET_SHOWN])
    return out


@router.get("/{run_id}/pairs/{column}")
def pairs(run_id: str, column: str, limit: int = Query(5, ge=1, le=100), ws: Workspace = Depends(workspace)) -> dict:
    """Why a column differs: its most frequent value pairs, for the Summary's side panel."""
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "Summary"):
            return pairs_body(run, column, limit)


@router.get("/{run_id}/one-sided/{which}")
def one_sided(run_id: str, which: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=10_000),
              ws: Workspace = Depends(workspace)) -> dict:
    """The rows only A (or only B) has, a page at a time, for the One-sided rows tab."""
    if which not in ("A", "B"):
        raise HTTPException(404, "A side is A or B.")
    with ws.lock:
        run = runs.run_of(ws, run_id)
        with runs.guard(run, "One-sided rows"):
            return one_sided_body(run, which, offset, limit)
