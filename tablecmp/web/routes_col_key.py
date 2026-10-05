"""The key column's page.

GET /api/profiling/keycheck - what makes one column safe to match rows on (unique, nulls, blanks,
case and space variants, width) and how its ids are built (shapes, a letters prefix, the number
part, its runs and gaps, the ids past the largest gap-free run, the order in the file, the next id).

GET /api/profiling/keycompare - the same column in the comparison on the page: what it pairs
with, how many ids the two sides share and the ids only one side has (count, lowest, highest).

The analysis is plain functions that take a DuckDB connection and the name of a relation holding
the column (keycheck, key_runs, beyond, id_span), so the Compare page can run them over its own
rows later; the routes only register the relation and call them. Read-only."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import results as rs
from ..sql import ident, lit, scratch
from ..values import ColSpec
from .profile_held import held_answer
from . import runs
from .routes_profiling import _held, _spec
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

SHAPES = 3
GAPS = 20                          # the largest gaps drawn; smaller ones stay inside their run
SHARED = 3                         # columns said to hold one value on every id past the gap
ID = "^([A-Za-z]*)([0-9]+)$"       # letters then digits, or digits alone: a number part to read


def _text(col: str, kind: str = "text") -> str:
    """The column as text - a whole number read as a number loses its '.0'."""
    c = ident(col)
    return (f"regexp_replace(CAST({c} AS VARCHAR), '[.]0$', '')" if kind == "number"
            else f"CAST({c} AS VARCHAR)")


def _numbered(rel: str, col: str, kind: str = "text") -> str:
    """Every filled value with its row number in the relation's order, its prefix, its digits and
    the number they make (NULL when the value is not letters then digits)."""
    return f"""
        SELECT rn, v, m.pre AS pre, m.dig AS dig, try_cast(nullif(m.dig, '') AS HUGEINT) AS x
        FROM (SELECT rn, v, regexp_extract(v, '{ID}', ['pre', 'dig']) AS m
              FROM (SELECT row_number() OVER () AS rn, {_text(col, kind)} AS v FROM {ident(rel)})
              WHERE v IS NOT NULL AND v <> '')"""


def keycheck(con, rel: str, spec: ColSpec) -> dict:
    """One column checked as a key. `rel` holds the column under spec.canon, in the file's order
    (a connection made with scratch(ordered=True)) - "order in the file" reads it."""
    v = _text(spec.canon, spec.kind)
    shape = "regexp_replace(regexp_replace(v, '[A-Za-z]', 'A', 'g'), '[0-9]', '9', 'g')"
    # f is read once (materialized); every count and the order comes from one aggregate over it,
    # the shapes and the prefix from one GROUP BY each. regexp_extract gives '' when the value is
    # not letters then digits, so dig <> '' says the number part is there.
    sql = f"""
    WITH f AS MATERIALIZED ({_numbered(rel, spec.canon, spec.kind)}),
    o AS (SELECT *, lag(x) OVER (ORDER BY rn) AS px, lag(v) OVER (ORDER BY rn) AS pv FROM f),
    c AS (SELECT *, CASE WHEN pv IS NULL THEN NULL WHEN x IS NOT NULL AND px IS NOT NULL THEN sign(x - px)
                         WHEN v > pv THEN 1 WHEN v < pv THEN -1 ELSE 0 END AS cmp FROM o),
    s AS (SELECT {shape} AS k, count(*) AS m, min(v) AS eg FROM f GROUP BY k ORDER BY m DESC, k LIMIT {SHAPES}),
    p AS (SELECT regexp_extract(v, '^[A-Za-z]+') AS k, count(*) AS m FROM f
          WHERE regexp_matches(v, '^[A-Za-z]') GROUP BY k ORDER BY m DESC, k LIMIT 1),
    a AS (SELECT count(*) AS filled, count(DISTINCT v) AS d, count(DISTINCT lower(v)) AS folded,
                 count(*) FILTER (WHERE v <> trim(v) OR v LIKE '% %') AS spaces,
                 min(length(v)) AS wmin, max(length(v)) AS wmax,
                 count(x) AS numbered, min(x) AS lo, max(x) AS hi, count(DISTINCT x) AS nd,
                 count(*) FILTER (WHERE dig LIKE '0%' AND length(dig) > 1) AS zeros,
                 arg_max(pre, x) AS pre, arg_max(length(dig), x) AS digits,
                 count(*) FILTER (WHERE cmp > 0) AS up, count(*) FILTER (WHERE cmp < 0) AS down FROM c)
    SELECT (SELECT count(*) FROM {ident(rel)}), (SELECT count(*) FILTER (WHERE {v} IS NULL) FROM {ident(rel)}),
           (SELECT count(*) FILTER (WHERE {v} = '') FROM {ident(rel)}),
           a.filled, a.d, a.folded, a.spaces, a.wmin, a.wmax, a.numbered, a.lo, a.hi, a.nd, a.zeros,
           a.pre, a.digits, a.up, a.down,
           (SELECT list({{'shape': k, 'n': m, 'example': eg}} ORDER BY m DESC, k) FROM s),
           (SELECT first(k) FROM p), (SELECT first(m) FROM p)
    FROM a
    """
    (rows, nulls, blanks, filled, distinct, folded, spaces, wmin, wmax, numbered, lo, hi, nd,
     zeros, pre, digits, up, down, shapes, ptext, pn) = con.execute(sql).fetchone()
    shapes = [{"shape": s["shape"], "n": int(s["n"]), "example": s["example"]} for s in (shapes or [])]
    prefix = {"text": ptext, "n": int(pn)} if ptext else None
    number = None
    next_id = ""
    seq = {"runs": [], "gaps": {"count": 0, "ids": 0, "shown": 0}, "beyond": None}
    if filled and numbered == filled:          # every filled value is letters then digits
        lo, hi, nd = int(lo), int(hi), int(nd)
        number = {"min": lo, "max": hi, "distinct": nd, "gaps": hi - lo + 1 - nd, "leading_zeros": int(zeros)}
        next_id = f"{pre or ''}{str(hi + 1).zfill(int(digits or 0))}"
        # ids are written back as the values are: the one prefix and the one width, when they hold
        same = len(shapes) == 1 and (prefix is None or prefix["n"] == filled)
        width = len(shapes[0]["shape"]) - len(prefix["text"] if prefix else "") if same else 0
        name = (lambda x: f"{prefix['text'] if prefix else ''}{str(x).zfill(width)}") if same else str
        seq = key_runs(con, rel, spec, number, name)
    order = ("ascending" if up and not down else "descending" if down and not up else "neither")
    return {"rows": int(rows), "filled": int(filled), "nulls": int(nulls), "blanks": int(blanks),
            "distinct": int(distinct), "duplicates": int(filled - distinct),
            "case_variants": int(distinct - folded), "spaces": int(spaces),
            "width": {"min": int(wmin or 0), "max": int(wmax or 0)},
            "shapes": shapes, "prefix": prefix, "number": number, "order": order, "next_id": next_id, **seq}


def key_runs(con, rel: str, spec: ColSpec, number: dict, name=str, top: int = 0) -> dict:
    """The number part in order: the `top` largest gaps between the lowest and the highest number
    and the runs between them, each {from, to, kind: 'run' | 'gap', n, id_from, id_to} - a run's
    n is how many distinct ids it holds and `holes` the numbers inside it that smaller gaps miss.
    gaps: {count, ids, shown} over every gap; beyond: the ids past the largest run (see beyond())."""
    lo, hi = number["min"], number["max"]
    if number["gaps"] == 0:
        whole = {"from": lo, "to": hi, "kind": "run", "n": number["distinct"], "holes": 0,
                 "id_from": name(lo), "id_to": name(hi)}
        return {"runs": [whole], "gaps": {"count": 0, "ids": 0, "shown": 0}, "beyond": None}
    d = f"(SELECT DISTINCT x FROM ({_numbered(rel, spec.canon, spec.kind)}) WHERE x IS NOT NULL)"
    got = con.execute(f"""
        WITH i AS (SELECT min(x) AS lo, max(x) AS hi FROM (SELECT x, x - row_number() OVER (ORDER BY x) AS g FROM {d})
                   GROUP BY g),
        h AS (SELECT lag(hi) OVER (ORDER BY lo) + 1 AS a, lo - 1 AS b FROM i)
        SELECT a, b, b - a + 1 AS n, count(*) OVER () AS total FROM h WHERE a IS NOT NULL
        ORDER BY n DESC, a LIMIT {int(top or GAPS)}""").fetchall()
    gaps = sorted((int(a), int(b)) for a, b, _, _ in got)
    total = int(got[0][3]) if got else 0
    spans, at = [], lo
    for a, b in gaps:
        spans.append((at, a - 1))
        at = b + 1
    spans.append((at, hi))
    counts = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE x BETWEEN {a} AND {b})" for a, b in spans)
                         + f" FROM {d}").fetchone()
    out: list[dict] = []
    for i, (a, b) in enumerate(spans):
        n = int(counts[i])
        out.append({"from": a, "to": b, "kind": "run", "n": n, "holes": b - a + 1 - n,
                    "id_from": name(a), "id_to": name(b)})
        if i < len(gaps):
            ga, gb = gaps[i]
            out.append({"from": ga, "to": gb, "kind": "gap", "n": gb - ga + 1, "holes": 0,
                        "id_from": name(ga), "id_to": name(gb)})
    return {"runs": out, "gaps": {"count": total, "ids": number["gaps"], "shown": len(gaps)},
            "beyond": beyond(con, rel, spec, out)}


def beyond(con, rel: str, spec: ColSpec, spans: list[dict]) -> dict | None:
    """The ids past the largest gap-free run, when there are any: {from, to, n, id_from, id_to,
    rows, shared} - shared is up to SHARED other columns that hold one value on every one of those
    rows and on no other row ({column, value}). None when the largest run comes last."""
    clean = [s for s in spans if s["kind"] == "run"]
    if len(clean) < 2:
        return None
    big = max(clean, key=lambda s: (s["n"], -s["from"]))
    after = [s for s in clean if s["from"] > big["to"]]
    if not after:
        return None
    t = big["to"]
    others = [r[0] for r in con.execute(f"DESCRIBE {ident(rel)}").fetchall() if r[0] != spec.canon]
    x = f"try_cast(nullif(regexp_extract({_text(spec.canon, spec.kind)}, '{ID}', 2), '') AS HUGEINT)"
    # the number part is read once per row, not once per aggregate: with many columns the
    # FILTERs below would otherwise run the regex a few hundred times a row
    flag = "__key_past__"
    src = f"(SELECT *, ({x} > {t}) IS TRUE AS {flag} FROM {ident(rel)})"
    q = [f"count(*) FILTER (WHERE {flag})"]
    for c in others:
        tv = f"CAST({ident(c)} AS VARCHAR)"
        q += [f"count(DISTINCT {tv}) FILTER (WHERE {flag}) = 1 AND count({tv}) FILTER (WHERE {flag}) "
              f"= count(*) FILTER (WHERE {flag})", f"any_value({tv}) FILTER (WHERE {flag})"]
    got = con.execute(f"SELECT {', '.join(q)} FROM {src}").fetchone()
    rows = int(got[0])
    one = [(c, got[2 + 2 * i]) for i, c in enumerate(others) if got[1 + 2 * i]] if rows >= 2 else []
    shared: list[dict] = []
    if one:
        tv = lambda c: f"CAST({ident(c)} AS VARCHAR)"    # noqa: E731
        elsewhere = con.execute("SELECT " + ", ".join(
            f"count(*) FILTER (WHERE NOT {flag} AND {tv(c)} = {lit(str(v))})" for c, v in one)
            + f" FROM {src}").fetchone()
        shared = [{"column": c, "value": str(v)} for (c, v), e in zip(one, elsewhere) if not e][:SHARED]
    return {"from": after[0]["from"], "to": after[-1]["to"], "n": sum(s["n"] for s in after),
            "id_from": after[0]["id_from"], "id_to": after[-1]["id_to"], "rows": rows, "shared": shared}


def id_span(con, rel: str, col: str) -> dict:
    """How many rows a relation holds and its lowest and highest id, ordered by the number part
    when there is one - for the ids only one side of a comparison has."""
    n, lo, hi = con.execute(f"""
        SELECT count(*), coalesce(arg_min(v, x), min(v)), coalesce(arg_max(v, x), max(v))
        FROM ({_numbered(rel, col)})""").fetchone()
    total = con.execute(f"SELECT count(*) FROM {ident(rel)}").fetchone()[0]
    return {"n": int(total), "filled": int(n), "min": lo or "", "max": hi or ""}


@router.get("/keycheck")
def key_check(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """One column checked as a key: unique, nulls and blanks, case and space variants, width,
    its shapes, prefix and number part with its runs and gaps, the order in the file, the next id."""
    _, prof, _ = _held(ws)
    spec = _spec(prof, column)
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    # the held table keeps the file's own order: "order in the file" reads it
    return held_answer(ws, prof, ("keycheck", column), lambda con: {"column": column, **keycheck(con, "prof", spec)})


def _one_sided(run: dict, tag: str) -> Path | None:
    stem = f"{run['pair']}__{tag}_only"
    files = run["files"]
    return next((Path(files[n]) for n in (f"{stem}.csv", f"{stem}.parquet")
                 if n in files and Path(files[n]).is_file()), None)


def compare_body(run: dict, column: str, fallback: tuple[str, str], stale: bool) -> dict:
    """The column as the run on the page used it - None in `key` when it was not the run's one key."""
    NA, NB = run.get("names") or fallback
    res = run["result"]
    keys = rs.run_keys(run)
    out: dict = {"run": run["run_id"], "names": [NA, NB], "stale": stale, "key": None}
    specs = {d["canon"]: d for d in run["cfg"]["specs"]}
    if len(keys) != 1:
        return out
    k = keys[0]
    d = specs.get(k, {})
    own = [d.get("a_src") or k, d.get("b_src") or k]
    on = [s for s, name in (("A", own[0]), ("B", own[1])) if column in (name, k)]
    if not on:
        return out
    only = []
    for which, tag, i in (("A", "left", 0), ("B", "right", 1)):
        p = _one_sided(run, tag)
        span = {"n": 0, "filled": 0, "min": "", "max": ""}
        if p is not None:
            src = (f"read_parquet({lit(str(p))})" if p.suffix == ".parquet"
                   else f"read_csv({lit(str(p))}, all_varchar=true)")
            con = scratch(ordered=True)
            try:
                con.execute(f"CREATE VIEW one AS SELECT * FROM {src}")
                cols = [r[0] for r in con.execute("DESCRIBE one").fetchall()]
                col = k if k in cols else own[i] if own[i] in cols else None
                span = id_span(con, "one", col) if col else {**span, "n": con.execute("SELECT count(*) FROM one").fetchone()[0]}
            finally:
                con.close()
        only.append({"side": which, **span})
    out["key"] = {"canon": k, "columns": own, "side": on[0], "matched": int(res.matched_rows),
                  "rows": [int(res.rows_left_read), int(res.rows_right_read)], "only": only}
    return out


@router.get("/keycompare")
def key_compare(column: str = Query(..., max_length=1000), ws: Workspace = Depends(workspace)) -> dict:
    """The key column in the comparison on the page: the columns it pairs, the ids in common and
    the ids only one side has - {run: None} before a run, {key: None} when it is not the run's key."""
    with ws.lock:
        p = runs.plan(ws)
        run = runs.current(ws) if p.gate == "" else None
        if run is None:
            return {"run": None, "key": None}
        if run["mode"] != "key":
            return {"run": run["run_id"], "names": list(run.get("names") or (p.NA, p.NB)), "stale": False, "key": None}
        with runs.guard(run, "Key"):
            return compare_body(run, column, (p.NA, p.NB), run.get("signature") != p.sig)
