"""A text column's page (GET /api/profiling/similar): its values most to least frequent, its
shortest and longest value, and the values that are probably the same thing spelled twice -
found four ways: a fingerprint (case, spaces, punctuation and word order set aside), character
3-grams alike, one value starting another, or two values that only ever occur with the same
value of another column this one otherwise decides. Read-only, counted in DuckDB on the loaded
table with its steps applied.

The analysis is plain functions over (con, relation, column, ...) that return dicts, so the
Compare page can run them on any relation; the route only registers the profile and calls them."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query

from ..sql import ident
from .profile_held import held_answer
from .routes_profiling import _held, _spec
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

METHODS = ("fingerprint", "ngram", "prefix", "same")
VALUES_TOP = 100          # values listed on the page, the most frequent first
SIM_CAP = 2000            # values the similarity looks at, the most frequent first
NGRAM_CAP = 1000          # values the 3-gram comparison looks at - it compares pairs
NGRAM_MIN = 0.5           # Jaccard of the 3-grams from which two values read as alike
NGRAM_LEN = 60            # values longer than this are free text and left out of the 3-gram comparison
PREFIX_MIN = 3            # characters a value needs to count as the start of another
OTHERS_TOP = 12           # other columns tried for "same"


# ---- the analysis: plain functions over a relation ------------------------------------------

def text_values(con, rel: str, column: str, cap: int = SIM_CAP) -> dict:
    """A column's values as text, most to least frequent (up to `cap`), how many distinct and
    filled there are, and the shortest and the longest value."""
    v = f"CAST({ident(column)} AS VARCHAR)"
    distinct, filled, short, long_ = con.execute(
        f"SELECT count(DISTINCT {v}), count({v}), arg_min({v}, length({v})), arg_max({v}, length({v})) "
        f"FROM {ident(rel)}").fetchone()
    rows = con.execute(f"SELECT {v} AS v, count(*) AS n FROM {ident(rel)} WHERE {v} IS NOT NULL "
                       f"GROUP BY v ORDER BY n DESC, v LIMIT {int(cap)}").fetchall()
    return {"distinct": int(distinct), "filled": int(filled),
            "values": [{"value": str(x), "n": int(n)} for x, n in rows],
            "shortest": short, "longest": long_}


def _tokens(v: str) -> list[str]:
    return re.findall(r"[^\W_]+", v.lower())


def fingerprint(v: str) -> str:
    """Lower case, punctuation and spaces dropped, the words sorted: 'Sales-EMEA ' and 'emea sales' agree."""
    return " ".join(sorted(_tokens(v)))


def _fp_why(members: list[str]) -> str:
    def same(f):
        return len({f(m) for m in members}) == 1
    if same(str.strip):
        return "differ only in outer spaces"
    if same(lambda m: m.strip().lower()):
        return "differ only in case" if same(lambda m: m.lower()) else "differ only in case and outer spaces"
    if same(lambda m: " ".join(m.lower().split())):
        return "differ only in case and spacing"
    if same(lambda m: " ".join(_tokens(m))):
        return "differ only in punctuation, case or spacing"
    return "the same words in another order"


def _group(members: list[dict], why: str, **extra) -> dict:
    ms = sorted(members, key=lambda m: (-m["n"], m["value"]))
    return {"members": ms, "keep": ms[0]["value"], "rows": sum(m["n"] for m in ms), "why": why, **extra}


def _ordered(groups: list[dict]) -> list[dict]:
    return sorted(groups, key=lambda g: (-g["rows"], g["keep"]))


def by_fingerprint(values: list[dict]) -> list[dict]:
    keyed: dict[str, list[dict]] = {}
    for m in values:
        k = fingerprint(m["value"])
        if k:
            keyed.setdefault(k, []).append(m)
    return _ordered([_group(ms, _fp_why([m["value"] for m in ms])) for ms in keyed.values() if len(ms) > 1])


def grams(v: str) -> set[str]:
    s = " ".join(v.lower().split())
    return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else ({s} if s else set())


def by_ngram(values: list[dict], threshold: float = NGRAM_MIN, cap: int = NGRAM_CAP,
             longest: int = NGRAM_LEN) -> list[dict]:
    """Values whose character 3-grams overlap with a more frequent value's by `threshold`
    (Jaccard) or more. The most frequent value not yet taken heads a group and takes the values
    alike to it - alike to the head, not to one another, so groups do not chain. Values longer
    than `longest` characters (free text, where 3-grams say little and cost much) are left out."""
    vs = [m for m in values if len(m["value"]) <= longest][:cap]
    gs = [grams(m["value"]) for m in vs]
    index: dict[str, list[int]] = {}
    for i, g in enumerate(gs):
        for x in g:
            index.setdefault(x, []).append(i)
    taken: set[int] = set()
    groups = []
    for i, g in enumerate(gs):
        if i in taken or not g:
            continue
        shared: dict[int, int] = {}             # later value -> 3-grams it shares with this one
        for x in g:
            for j in index[x]:
                if j > i:
                    shared[j] = shared.get(j, 0) + 1
        alike = []
        for j in sorted(shared):
            if j in taken:
                continue
            c = shared[j]
            sim = c / (len(g) + len(gs[j]) - c)
            if sim >= threshold:
                alike.append((j, sim))
        if alike:
            taken.update(j for j, _ in alike)
            low = min(s for _, s in alike)
            groups.append(_group([vs[i]] + [vs[j] for j, _ in alike], f"{round(100 * low)}% of their 3-letter pieces alike",
                                 alike=round(100 * low, 2)))
    return _ordered(groups)


def by_prefix(values: list[dict], least: int = PREFIX_MIN) -> list[dict]:
    """A value that starts another (case and outer spaces aside, `least` characters or more):
    each value joins the shortest value it starts with."""
    norm: dict[str, list[dict]] = {}
    for m in values:
        norm.setdefault(m["value"].strip().lower(), []).append(m)
    roots: dict[str, list[dict]] = {}
    for k, ms in norm.items():
        r = next((k[:i] for i in range(least, len(k)) if k[:i] in norm), None)
        if r is not None:
            roots.setdefault(r, []).extend(ms)
    groups = []
    for r, ms in roots.items():
        head = norm[r]
        groups.append(_group(head + ms, f'all begin "{head[0]["value"].strip()}"', prefix=head[0]["value"].strip()))
    return _ordered(groups)


def by_other(con, rel: str, column: str, others: list[str], values: list[dict]) -> tuple[str, list[dict]]:
    """Two or more values of `column` that only ever occur with one value of another column -
    a column `column` decides on every row and that otherwise names one value of `column`
    each (at least half of its values). The other column whose values are most often one to
    one wins. Returns (that column, its groups)."""
    n = {m["value"]: m["n"] for m in values}
    x = f"CAST({ident(column)} AS VARCHAR)"
    best: tuple[float, int, str, list[dict]] | None = None
    for other in others:
        y = f"CAST({ident(other)} AS VARCHAR)"
        # one row per value of `column` (never more than it has values): does it go with one `other`?
        pairs = con.execute(f"SELECT {x} AS a, min({y}), min({y}) = max({y}) FROM {ident(rel)} "
                            f"WHERE {x} IS NOT NULL AND {y} IS NOT NULL GROUP BY a").fetchall()
        if not pairs or not all(one for _, _, one in pairs):
            continue
        to_y: dict[str, str] = {a: b for a, b, _ in pairs}
        by_y: dict[str, list[str]] = {}
        for a, b in to_y.items():
            by_y.setdefault(b, []).append(a)
        many = {b: xs for b, xs in by_y.items() if len(xs) > 1}
        single = len(by_y) - len(many)
        if not many or single * 2 < len(by_y):
            continue
        groups = []
        for b, xs in many.items():
            if any(a not in n for a in xs):
                continue
            word = "both" if len(xs) == 2 else f"all {len(xs)}"
            groups.append(_group([{"value": a, "n": n[a]} for a in xs], f"{word} only in {other} {b}",
                                 on={"column": other, "value": b}))
        if not groups:
            continue
        score = (single / len(by_y), -len(groups))
        if best is None or score > best[:2]:
            best = (score[0], score[1], other, _ordered(groups))
    return (best[2], best[3]) if best else ("", [])


def similar(con, rel: str, column: str, others: list[str] | None = None, threshold: float = NGRAM_MIN,
            cap: int = SIM_CAP) -> dict:
    """Everything the text page shows of one column of `rel`: its values, and the groups each
    method finds among its `cap` most frequent values - {distinct, filled, values, shortest,
    longest, scanned, methods: {name: {groups, by?}}}."""
    vals = text_values(con, rel, column, cap)
    vs = vals["values"]
    by, same = by_other(con, rel, column, others or [], vs) if others else ("", [])
    vals["scanned"] = len(vs)
    vals["methods"] = {"fingerprint": {"groups": by_fingerprint(vs)},
                       "ngram": {"groups": by_ngram(vs, threshold)},
                       "prefix": {"groups": by_prefix(vs)},
                       "same": {"groups": same, "by": by}}
    return vals


def first_method(methods: dict) -> str:
    """The method the page opens on: fingerprint or same, the two that are facts rather than
    likenesses, whichever finds anything - n-gram and prefix only when picked."""
    return next((m for m in ("fingerprint", "same") if methods[m]["groups"]), "fingerprint")


# ---- the route ------------------------------------------------------------------------------

def _others(prof: dict, column: str, distinct: int) -> list[str]:
    """Columns that could be decided by `column`: fewer distinct values than it, more than one,
    the closest in count first."""
    st = prof["stats"]
    found = [(int(r["Distinct"]), str(r["Column"])) for _, r in st.iterrows()
             if str(r["Column"]) != column and 1 < int(r["Distinct"]) < distinct]
    return [c for _, c in sorted(found, reverse=True)][:OTHERS_TOP]


@router.get("/similar")
def column_similar(column: str = Query(..., max_length=1000), method: str = Query("", max_length=20),
                   threshold: float = Query(NGRAM_MIN, ge=0.2, le=0.95),
                   ws: Workspace = Depends(workspace)) -> dict:
    """One text column's values and the values probably the same thing spelled twice, by
    `method` (fingerprint, ngram, prefix, same; empty: fingerprint, or same when only it finds a group) -
    groups [{members: [{value, n}], keep, rows, why}], the most frequent spelling kept."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    if method and method not in METHODS:
        raise HTTPException(400, f"Method is one of {', '.join(METHODS)}.")
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    key = (column, round(threshold, 2))
    st = prof["stats"]
    row = st[st["Column"] == column]
    distinct = int(row["Distinct"].iloc[0]) if len(row) else 0
    others = _others(prof, column, distinct) if spec.kind == "text" and distinct <= SIM_CAP else []
    got = held_answer(ws, prof, ("similar",) + key, lambda con: similar(con, "prof", column, others, threshold)
                      if spec.kind == "text" else
                      {**text_values(con, "prof", column), "scanned": 0,
                       "methods": {m: {"groups": [], **({"by": ""} if m == "same" else {})} for m in METHODS}})
    chosen = method or first_method(got["methods"])
    pick = got["methods"][chosen]
    return {"column": column, "kind": spec.kind, "method": chosen,
            "counts": {m: len(got["methods"][m]["groups"]) for m in METHODS},
            "groups": pick["groups"], "by": pick.get("by", ""), "threshold": key[1],
            "distinct": got["distinct"], "filled": got["filled"], "scanned": got["scanned"],
            "capped": got["distinct"] > got["scanned"],
            "values": got["values"][:VALUES_TOP], "more": max(0, got["distinct"] - min(VALUES_TOP, len(got["values"]))),
            "shortest": got["shortest"], "longest": got["longest"]}
