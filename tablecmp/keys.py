"""Keys: is a combination unique on both sides, and which combinations would be."""
from __future__ import annotations

import re
import time

import pandas as pd

from .profile import profile_singles
from .sources import Side, work_dir
from .sql import ident, lit, scratch
from .values import ColSpec, ReadOptions, register

DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME")
ID_WORDS = re.compile(r"(^|_)(id|key|code|ref|no|num|nbr|isin|sedol|cusip|symbol|sym|ticker|"
                      r"type|line|seq|idx|index|row|account|acct)($|_)", re.I)
# names and dates often take part in a key, so they rank like an identifier - but are not one
KEY_WORDS = re.compile(r"(^|_)(name|date|day|time)($|_)", re.I)
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
    """Per side: rows, distinct keys and duplicate rows among the rows that have a key, and
    the rows where any key column is null - those identify nothing, so they are neither
    distinct nor duplicates, and a key with any is not unique."""
    con = probe(A, B, [s for s in specs if s.canon in keys], opts)
    missing = " OR ".join(f"{ident(k)} IS NULL" for k in keys)
    rows = []
    for view, label in (("probe_a", name_a), ("probe_b", name_b)):
        n, d, nulls = con.execute(
            f"SELECT count(*), count(DISTINCT {combo(keys)}) FILTER (WHERE NOT ({missing})), "
            f"count(*) FILTER (WHERE {missing}) FROM {view}").fetchone()
        dup = n - nulls - d
        rows.append({"Side": label, "Rows": n, "Distinct keys": d, "Duplicate rows": dup,
                     "Null keys": nulls, "Unique": "yes" if not dup and not nulls else "no"})
    return pd.DataFrame(rows)


def key_affinity(col: str, type_a: str, type_b: str) -> int:
    """How much a column looks like part of a business key rather than a measure."""
    score = 0
    if ID_WORDS.search(col) or KEY_WORDS.search(col):
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


HOW_SINGLE = "unique by itself"
HOW_GROWN = "grown from the most selective column"
HOW_HYUCC = "found with Desbordante HyUCC"
HOW_PYRO = "found with Desbordante PyroUCC as almost unique"


def key_reasons(cols: list[str], d: dict[str, int], totals: dict[str, int], affinity: dict[str, int],
                nulls: dict[str, int], overlap: float, unique_sets: list[frozenset], how: str,
                name_a: str, name_b: str, single_ov: dict[str, float] | None = None) -> str:
    """Why a candidate ranks where it does, as one line of plain reasons. `single_ov` is the
    overlap of each column on its own - read only when the combination shares nothing, to
    name the column that is the reason."""
    bits = []
    idish = [c for c in cols if ID_WORDS.search(c)]
    measures = [c for c in cols if MEASURE_WORDS.search(c) or affinity[c] <= -4]
    if measures:
        bits.append(f"{', '.join(measures)}: a measure"
                    + (", decimal" if any(affinity[c] <= -4 for c in measures) else "") + " - never a key")
    elif idish:
        bits.append("name says identifier" if len(cols) == 1
                    else f"{idish[0]} says identifier" if len(idish) == 1
                    else f"{', '.join(idish)} say identifier")
    else:
        bits.append("a name, not an identifier" if any(re.search(r"name", c, re.I) for c in cols)
                    else "a date, not an identifier" if any(KEY_WORDS.search(c) for c in cols)
                    else "no identifier in the name")
    n_null = sum(nulls.get(c, 0) for c in cols)
    bits.append("no nulls" if not n_null else f"{n_null:,} nulls")
    bits.append(f"{d['probe_a']:,} distinct of {totals['probe_a']:,} in {name_a}, "
                f"{d['probe_b']:,} of {totals['probe_b']:,} in {name_b}")
    dup_a, dup_b = totals["probe_a"] - d["probe_a"], totals["probe_b"] - d["probe_b"]
    if dup_a or dup_b:
        bits.append(" and ".join(f"{n:,} rows in {nm} share it"
                                 for n, nm in ((dup_a, name_a), (dup_b, name_b)) if n))
    if overlap:
        bits.append(f"{overlap:.1f}% of {name_a}'s values found in {name_b}")
    else:
        alone = {c: (single_ov or {}).get(c) for c in cols} if len(cols) > 1 else {}
        dead = [c for c, o in alone.items() if o == 0]
        bits.append("no values in common"
                    + (f" - none of {name_a}'s {' or '.join(dead)} values found in {name_b}" if dead
                       else ", though every column alone shares some" if alone and all(alone.values())
                       else ""))
    for u in unique_sets:
        if u < set(cols):
            bits.append(f"adds nothing - {' + '.join(sorted(u))} is already unique")
            break
    return " · ".join(bits) + f" · {how}"


def suggest_keys(A: Side, B: Side, specs: list[ColSpec], name_a: str, name_b: str,
                 opts: ReadOptions, progress=None, max_cols: int = 4, want: int = 8,
                 profile: dict | None = None
                 ) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Candidate keys, best first - each with how much of A's values B shares and the
    reasons for its place - plus a note on how they were found. A profile of the same
    columns supplies the single-column figures, so they are not measured twice."""
    say = progress or (lambda _msg: None)
    candidates = [s.canon for s in specs]
    say(f"Reading both sides ({len(candidates)} columns)…")
    con = probe(A, B, specs, opts)
    views = ("probe_a", "probe_b")
    totals = {v: con.execute(f"SELECT count(*) FROM {v}").fetchone()[0] for v in views}

    from_profile = {c: profile_singles(profile, c) for c in candidates}
    measure = [c for c in candidates if from_profile[c] is None]
    used_profile = len(measure) < len(candidates)
    say("Reading the profile…" if used_profile else "Measuring every column…")
    singles: dict[str, dict[str, int]] = {c: {} for c in candidates}
    nulls: dict[str, int] = {}
    if measure:
        for v in views:
            picks = ", ".join(f"count(DISTINCT {ident(c)}), count(*) - count({ident(c)})" for c in measure)
            row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
            for i, c in enumerate(measure):
                singles[c][v] = row[2 * i]
                nulls[c] = nulls.get(c, 0) + row[2 * i + 1]
    for c, p in from_profile.items():
        if p is not None:
            singles[c] = {"probe_a": p["probe_a"], "probe_b": p["probe_b"]}
            nulls[c] = p["nulls_a"] + p["nulls_b"]
    # one value (or none) on each side can never tell rows apart
    candidates = [c for c in candidates if not all(singles[c][v] <= 1 for v in views)]

    def distinct(cols: list[str]) -> dict[str, int]:
        if len(cols) == 1:
            return singles[cols[0]]
        return {v: con.execute(f"SELECT count(DISTINCT {combo(cols)}) FROM {v}").fetchone()[0]
                for v in views}

    def unique(d): return all(d[v] == totals[v] for v in views)
    def selectivity(d): return min(d[v] / max(totals[v], 1) for v in views)

    def overlap(cols: list[str]) -> float:
        """Share of A's distinct key values also present in B."""
        k = combo(cols)
        n, m = con.execute(f"SELECT count(DISTINCT {k}), count(DISTINCT {k}) FILTER "
                           f"(WHERE {k} IN (SELECT {k} FROM probe_b)) FROM probe_a").fetchone()
        return m / n * 100 if n else 0.0

    found: list[tuple[list[str], dict[str, int], str]] = []
    seen: set[frozenset] = set()

    def offer(cols, d, how):
        if cols and frozenset(cols) not in seen:
            seen.add(frozenset(cols))
            found.append((cols, d, how))

    affinity = {s.canon: key_affinity(s.canon, A.schema.get(s.a_src, ""),
                                      B.schema.get(s.b_src, "")) for s in specs}
    order = {c: i for i, c in enumerate(candidates)}
    ranked = sorted(candidates, key=lambda c: (-affinity[c], nulls.get(c, 0) > 0, -selectivity(singles[c])))

    def grow(seed_cols, d, how=HOW_GROWN):
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
        offer(cols, d, how)

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
            offer(cols, distinct(cols), HOW_HYUCC)
        if not any(unique(d) for _, d, _ in found):
            say("Nothing exactly unique - PyroUCC, almost-unique combinations…")
            note += "; nothing was exactly unique, so PyroUCC's almost-unique combinations " \
                    "(≤1% of rows in the way) were added and grown"
            approx: set[frozenset] = set()
            for v in views:
                approx.update(frozenset(c) for c in ucc_candidates(con, v, candidates, error=0.01))
            for c in sorted(approx, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:12]:
                cols = sorted(c, key=order.get)
                d = distinct(cols)
                offer(cols, d, HOW_PYRO)
                if not unique(d):
                    grow(cols, d, HOW_GROWN + " on top of a PyroUCC combination")
    else:
        note = ("Found by measuring every column and growing the most selective ones - "
                "`pip install desbordante` for exact key discovery (HyUCC / PyroUCC)")
        say("Growing the most selective columns…")
        for col in ranked:
            if unique(singles[col]):
                offer([col], singles[col], HOW_SINGLE)
        for seed in ranked[:4]:
            if len(found) >= want:
                break
            grow([seed], singles[seed])
    if used_profile:
        note += " - single-column figures from the profile"

    # a combination that only adds columns to a key that is already unique adds nothing,
    # whatever the affinity of the extra columns says
    unique_sets = [frozenset(cols) for cols, d, _ in found if unique(d)]
    def redundant(cols): return any(u < set(cols) for u in unique_sets)

    found.sort(key=lambda f: (not unique(f[1]), redundant(f[0]), -sum(affinity[c] for c in f[0]),
                              len(f[0]), -selectivity(f[1])))
    found = found[:want * 2]
    say(f"Overlap between the sides for {len(found)} candidate(s)…")
    ov = {tuple(cols): overlap(cols) for cols, _, _ in found}
    found.sort(key=lambda f: (not unique(f[1]), redundant(f[0]), -sum(affinity[c] for c in f[0]),
                              -round(ov[tuple(f[0])]), len(f[0]), -selectivity(f[1])))
    found = found[:want]
    # a combination that shares nothing: which of its columns is the reason
    single_ov = {c: overlap([c]) for cols, _, _ in found if len(cols) > 1 and ov[tuple(cols)] == 0
                 for c in cols}
    table = pd.DataFrame([{
        "Key columns": " + ".join(cols),
        f"Distinct in {name_a}": d["probe_a"],
        f"Distinct in {name_b}": d["probe_b"],
        "Unique on both": "yes" if unique(d) else "no",
        "Duplicate rows": (totals["probe_a"] - d["probe_a"]) + (totals["probe_b"] - d["probe_b"]),
        "Overlap %": round(ov[tuple(cols)], 1),
        "Looks like a key": "yes" if all(affinity[c] >= 0 for c in cols) else "measure columns",
        "Why": key_reasons(cols, d, totals, affinity, nulls, ov[tuple(cols)], unique_sets, how,
                           name_a, name_b, single_ov),
    } for cols, d, how in found])
    return table, [cols for cols, _, _ in found], note
