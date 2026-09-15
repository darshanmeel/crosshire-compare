"""Keys: is a combination unique on both sides, and which combinations would be."""
from __future__ import annotations

import re
import time

import pandas as pd

from .sources import Side, work_dir
from .sql import ident, lit, scratch
from .values import ColSpec, ReadOptions, register

DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME")
ID_WORDS = re.compile(r"(^|_)(id|key|code|ref|no|num|nbr|isin|sedol|cusip|symbol|sym|ticker|"
                      r"date|day|time|name|type|line|seq|idx|index|row|account|acct)($|_)", re.I)
MEASURE_WORDS = re.compile(r"(^|_)(qty|quantity|amount|amt|price|px|value|val|total|sum|count|"
                           r"cnt|rate|pct|percent|weight|volume|vol|balance|bal|cost|fee|"
                           r"nav|return|ret|yield)($|_)", re.I)
FLOATY = ("DOUBLE", "FLOAT", "DECIMAL", "REAL")
UCC_SAMPLE = 200_000


def combo(cols: list[str]) -> str:
    inner = ", ".join(f"coalesce({ident(c)}, chr(2))" for c in cols)
    return f"concat_ws(chr(1), {inner})"


def probe(A: Side, B: Side, specs: list[ColSpec], opts: ReadOptions):
    """A connection with both sides as tables under the shared names - one read each."""
    con = scratch()
    register(con, A, "probe_a", specs, "A", opts, materialize=True)
    register(con, B, "probe_b", specs, "B", opts, materialize=True)
    return con


def key_uniqueness(A: Side, B: Side, specs: list[ColSpec], keys: list[str],
                   name_a: str, name_b: str, opts: ReadOptions) -> pd.DataFrame:
    con = probe(A, B, [s for s in specs if s.canon in keys], opts)
    rows = []
    for view, label in (("probe_a", name_a), ("probe_b", name_b)):
        n, d = con.execute(f"SELECT count(*), count(DISTINCT {combo(keys)}) FROM {view}").fetchone()
        rows.append({"Side": label, "Rows": n, "Distinct keys": d,
                     "Duplicate rows": n - d, "Unique": "yes" if n == d else "no"})
    return pd.DataFrame(rows)


def key_affinity(col: str, type_a: str, type_b: str) -> int:
    """How much a column looks like part of a business key rather than a measure."""
    score = 0
    if ID_WORDS.search(col):
        score += 3
    if MEASURE_WORDS.search(col):
        score -= 3
    if any(t in type_a.upper() for t in FLOATY) or any(t in type_b.upper() for t in FLOATY):
        score -= 4
    if any(t in type_a.upper() for t in DATE_TYPES):
        score += 2
    return score


def desbordante_available() -> bool:
    try:
        import desbordante  # noqa: F401
        return True
    except ImportError:
        return False


def ucc_candidates(con, view: str, columns: list[str], error: float = 0.0,
                   max_lhs: int = 4, sample: int = UCC_SAMPLE) -> list[list[str]]:
    """Unique column combinations found by Desbordante on the first `sample` rows."""
    import desbordante
    path = work_dir() / f"ucc_{view}_{int(time.time() * 1000)}.csv"
    picks = ", ".join(ident(c) for c in columns)
    con.execute(f"COPY (SELECT {picks} FROM {view} LIMIT {int(sample)}) "
                f"TO {lit(str(path))} (HEADER, DELIMITER ',')")
    try:
        algo = (desbordante.ucc.algorithms.PyroUCC() if error > 0
                else desbordante.ucc.algorithms.HyUCC())
        algo.load_data(table=(str(path), ",", True))
        opts = {"error": error, "max_lhs": max_lhs} if error > 0 else {}
        allowed = set(getattr(algo, "get_possible_options", lambda: opts.keys())())
        algo.execute(**{k: v for k, v in opts.items() if k in allowed})
        out = [[columns[i] for i in u.indices] for u in algo.get_uccs()]
    finally:
        path.unlink(missing_ok=True)
    return [c for c in out if 0 < len(c) <= max_lhs]


def suggest_keys(A: Side, B: Side, specs: list[ColSpec], name_a: str, name_b: str,
                 opts: ReadOptions, progress=None, max_cols: int = 4, want: int = 8
                 ) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Candidate keys, best first, plus a note on how they were found."""
    say = progress or (lambda _msg: None)
    candidates = [s.canon for s in specs]
    say(f"Reading both sides ({len(candidates)} columns)…")
    con = probe(A, B, specs, opts)
    views = ("probe_a", "probe_b")
    totals = {v: con.execute(f"SELECT count(*) FROM {v}").fetchone()[0] for v in views}

    say("Measuring every column…")
    singles: dict[str, dict[str, int]] = {c: {} for c in candidates}
    for v in views:
        picks = ", ".join(f"count(DISTINCT {ident(c)})" for c in candidates)
        row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
        for c, d in zip(candidates, row):
            singles[c][v] = d

    def distinct(cols: list[str]) -> dict[str, int]:
        if len(cols) == 1:
            return singles[cols[0]]
        return {v: con.execute(f"SELECT count(DISTINCT {combo(cols)}) FROM {v}").fetchone()[0]
                for v in views}

    def unique(d): return all(d[v] == totals[v] for v in views)
    def selectivity(d): return min(d[v] / max(totals[v], 1) for v in views)

    found: list[tuple[list[str], dict[str, int]]] = []
    seen: set[frozenset] = set()

    def offer(cols, d):
        if cols and frozenset(cols) not in seen:
            seen.add(frozenset(cols))
            found.append((cols, d))

    affinity = {s.canon: key_affinity(s.canon, A.schema.get(s.a_src, ""),
                                      B.schema.get(s.b_src, "")) for s in specs}
    order = {c: i for i, c in enumerate(candidates)}
    ranked = sorted(candidates, key=lambda c: (-affinity[c], -selectivity(singles[c])))

    def grow(seed_cols, d):
        cols = list(seed_cols)
        pool = [c for c in ranked if c not in cols]
        while not unique(d) and len(cols) < max_cols and pool:
            best, best_d, best_score = None, None, -1.0
            for col in pool[:12]:
                cand = distinct(cols + [col])
                sc = selectivity(cand)
                if sc > best_score:
                    best, best_d, best_score = col, cand, sc
            if best is None:
                break
            cols, d = cols + [best], best_d
            pool.remove(best)
        offer(cols, d)

    if desbordante_available():
        n = min(UCC_SAMPLE, max(totals.values()))
        note = (f"Found with Desbordante HyUCC on the first {n:,} rows of each side and "
                "verified on every row of both")
        say("Desbordante: minimal unique column combinations on each side…")
        cands: set[frozenset] = set()
        for v in views:
            cands.update(frozenset(c) for c in ucc_candidates(con, v, candidates))
        say(f"Verifying {len(cands)} candidate(s) on every row…")
        for c in sorted(cands, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:30]:
            cols = sorted(c, key=order.get)
            offer(cols, distinct(cols))
        if not any(unique(d) for _, d in found):
            say("Nothing exactly unique - PyroUCC, almost-unique combinations…")
            note += "; nothing was exactly unique, so PyroUCC's almost-unique combinations " \
                    "(≤1% of rows in the way) were added and grown"
            approx: set[frozenset] = set()
            for v in views:
                approx.update(frozenset(c) for c in ucc_candidates(con, v, candidates, error=0.01))
            for c in sorted(approx, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:12]:
                cols = sorted(c, key=order.get)
                d = distinct(cols)
                offer(cols, d)
                if not unique(d):
                    grow(cols, d)
    else:
        note = ("Found by measuring every column and growing the most selective ones - "
                "`pip install desbordante` for exact key discovery (HyUCC / PyroUCC)")
        say("Growing the most selective columns…")
        for col in ranked:
            if unique(singles[col]):
                offer([col], singles[col])
        for seed in ranked[:4]:
            if len(found) >= want:
                break
            grow([seed], singles[seed])

    found.sort(key=lambda f: (not unique(f[1]), -sum(affinity[c] for c in f[0]),
                              len(f[0]), -selectivity(f[1])))
    found = found[:want]
    table = pd.DataFrame([{
        "Key columns": " + ".join(cols),
        f"Distinct in {name_a}": d["probe_a"],
        f"Distinct in {name_b}": d["probe_b"],
        "Unique on both": "yes" if unique(d) else "no",
        "Duplicate rows": (totals["probe_a"] - d["probe_a"]) + (totals["probe_b"] - d["probe_b"]),
        "Looks like a key": "yes" if all(affinity[c] >= 0 for c in cols) else "measure columns",
    } for cols, d in found])
    return table, [cols for cols, _ in found], note
