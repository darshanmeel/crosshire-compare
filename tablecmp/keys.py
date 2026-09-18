"""Keys: is a combination unique on both sides, and which combinations would be - on a
pair, or on one table on its own (the Profiling page)."""
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
MAX_KEY_COLS = 4            # how many columns a combination may grow to - the page and the notes say it
KEY_COLS = ["Key columns", "Distinct", "Unique", "Duplicate rows", "Null keys",
            "Looks like a key", "Why"]              # a table on its own, one row per candidate


def combo(cols: list[str]) -> str:
    inner = ", ".join(f"coalesce({ident(c)}, chr(2))" for c in cols)
    return f"concat_ws(chr(1), {inner})"


def any_null(cols: list[str]) -> str:
    """The rows where the key is null - any of its columns is."""
    return " OR ".join(f"{ident(c)} IS NULL" for c in cols)


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
    missing = any_null(keys)
    rows = []
    for view, label in (("probe_a", name_a), ("probe_b", name_b)):
        n, d, nulls = con.execute(
            f"SELECT count(*), count(DISTINCT {combo(keys)}) FILTER (WHERE NOT ({missing})), "
            f"count(*) FILTER (WHERE {missing}) FROM {view}").fetchone()
        dup = n - nulls - d
        rows.append({"Side": label, "Rows": n, "Distinct keys": d, "Duplicate rows": dup,
                     "Null keys": nulls, "Unique": "yes" if not dup and not nulls else "no"})
    return pd.DataFrame(rows)


def key_affinity(col: str, type_a: str, type_b: str = "") -> int:
    """How much a column looks like part of a business key rather than a measure - from its
    name and the type detected on each side (a table on its own has only `type_a`)."""
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
                   max_lhs: int = MAX_KEY_COLS, sample: int = UCC_SAMPLE) -> list[list[str]]:
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
HOW_ALONE = "on its own - adding a column told no more rows apart"
HOW_HYUCC = "found with Desbordante HyUCC"
HOW_PYRO = "found with Desbordante PyroUCC as almost unique"


def is_unique(d: dict[str, int], totals: dict[str, int]) -> bool:
    """As many distinct values as rows, on every view."""
    return all(d[v] == totals[v] for v in totals)


def selectivity(d: dict[str, int], totals: dict[str, int]) -> float:
    """Distinct values per row, on the view where it is lowest."""
    return min(d[v] / max(totals[v], 1) for v in totals)


def single_figures(con, views, cols: list[str]) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Each column on its own: distinct count per view, and nulls over every view - one
    query per view."""
    singles: dict[str, dict[str, int]] = {c: {} for c in cols}
    nulls: dict[str, int] = {}
    if cols:
        for v in views:
            picks = ", ".join(f"count(DISTINCT {ident(c)}), count(*) - count({ident(c)})" for c in cols)
            row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
            for i, c in enumerate(cols):
                singles[c][v] = row[2 * i]
                nulls[c] = nulls.get(c, 0) + row[2 * i + 1]
    return singles, nulls


def rank(found: list[tuple[list[str], dict[str, int], str]], totals: dict[str, int],
         affinity: dict[str, int], unique_sets: list[frozenset],
         overlap: dict[tuple, float] | None = None) -> None:
    """Sort the candidates in place: unique first; a combination that only adds columns to a
    key that is already unique adds nothing, whatever the affinity of the extra columns says,
    so it goes below; then affinity sum, the share of values the other side has when there
    is one, fewer columns, selectivity."""
    def key(f):
        cols, d, _ = f
        return (not is_unique(d, totals), any(u < set(cols) for u in unique_sets),
                -sum(affinity[c] for c in cols),
                -round(overlap[tuple(cols)]) if overlap is not None else 0,
                len(cols), -selectivity(d, totals))
    found.sort(key=key)


def search_keys(con, views, totals: dict[str, int], candidates: list[str],
                singles: dict[str, dict[str, int]], nulls: dict[str, int],
                affinity: dict[str, int], max_cols: int, want: int, say,
                nulls_apart: bool = False
                ) -> tuple[list[tuple[list[str], dict[str, int], str]], list[frozenset], str]:
    """The candidate search, over any number of side views on one connection - a pair, or a
    table on its own: every column unique by itself, then combinations grown from the most
    selective columns (affinity-ranked, up to `max_cols`), or Desbordante's HyUCC / PyroUCC
    on the first UCC_SAMPLE rows when it is installed, verified on every row. Returns each
    candidate as (columns, distinct per view, how it was found), ranked; the column sets
    that are unique, so a superset can say it adds nothing; and the note on how they were
    found. A column with one value (or none) on every view can never tell rows apart, so it
    is never a candidate. With `nulls_apart` a combination's distinct count leaves out the
    rows where any of its columns is null, as key_uniqueness does - they identify nothing -
    so it is unique only with no null keys and no duplicates, the way the one-table
    candidate table reads Unique; a single column's count leaves them out either way. A
    pair counts null as a value, as it always has."""
    candidates = [c for c in candidates if not all(singles[c][v] <= 1 for v in views)]
    order = {c: i for i, c in enumerate(candidates)}
    ranked = sorted(candidates, key=lambda c: (-affinity[c], nulls.get(c, 0) > 0,
                                               -selectivity(singles[c], totals)))

    def distinct(cols: list[str]) -> dict[str, int]:
        if len(cols) == 1:
            return singles[cols[0]]
        count = f"count(DISTINCT {combo(cols)})"
        if nulls_apart:
            count += f" FILTER (WHERE NOT ({any_null(cols)}))"
        return {v: con.execute(f"SELECT {count} FROM {v}").fetchone()[0] for v in views}

    found: list[tuple[list[str], dict[str, int], str]] = []
    seen: set[frozenset] = set()

    def offer(cols, d, how):
        if cols and frozenset(cols) not in seen:
            seen.add(frozenset(cols))
            found.append((cols, d, how))

    def grow(seed_cols, d, how=HOW_GROWN):
        cols = list(seed_cols)
        pool = [c for c in ranked if c not in cols]
        while not is_unique(d, totals) and len(cols) < max_cols and pool:
            best, best_d, best_score = None, None, -1.0
            for col in pool[:12]:
                cand = distinct(cols + [col])
                sc = selectivity(cand, totals)
                if sc > best_score:
                    best, best_d, best_score = col, cand, sc
            if best is None:
                break
            # with nulls apart a null-key row is never told apart, so a column that raises
            # the count by nothing is not carried - the seed stands on its own; a pair keeps
            # growing, as it always has
            if nulls_apart and best_score <= selectivity(d, totals):
                break
            cols, d = cols + [best], best_d
            pool.remove(best)
        offer(cols, d, HOW_ALONE if nulls_apart and cols == list(seed_cols) and how == HOW_GROWN else how)

    pair = len(views) > 1
    if desbordante_available():
        n = min(UCC_SAMPLE, max(totals.values()))
        note = (f"Found with Desbordante HyUCC on the first {n:,} rows"
                + (" of each side and verified on every row of both" if pair
                   else " and verified on every row"))
        say("Desbordante: minimal unique column combinations" + (" on each side…" if pair else "…"))
        cands: set[frozenset] = set()
        for v in views:
            cands.update(frozenset(c) for c in ucc_candidates(con, v, candidates, max_lhs=max_cols))
        say(f"Verifying {len(cands)} candidate(s) on every row…")
        for c in sorted(cands, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:30]:
            cols = sorted(c, key=order.get)
            offer(cols, distinct(cols), HOW_HYUCC)
        if not any(is_unique(d, totals) for _, d, _ in found):
            say("Nothing exactly unique - PyroUCC, almost-unique combinations…")
            note += "; nothing was exactly unique, so PyroUCC's almost-unique combinations " \
                    "(≤1% of rows in the way) were added and grown"
            approx: set[frozenset] = set()
            for v in views:
                approx.update(frozenset(c) for c in ucc_candidates(con, v, candidates, error=0.01,
                                                                   max_lhs=max_cols))
            for c in sorted(approx, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:12]:
                cols = sorted(c, key=order.get)
                d = distinct(cols)
                offer(cols, d, HOW_PYRO)
                if not is_unique(d, totals):
                    grow(cols, d, HOW_GROWN + " on top of a PyroUCC combination")
    else:
        note = ("Found by measuring every column and growing the most selective ones - "
                "`pip install desbordante` for exact key discovery (HyUCC / PyroUCC)")
        say("Growing the most selective columns…")
        for col in ranked:
            if is_unique(singles[col], totals):
                offer([col], singles[col], HOW_SINGLE)
        for seed in ranked[:4]:
            if len(found) >= want:
                break
            grow([seed], singles[seed])

    unique_sets = [frozenset(cols) for cols, d, _ in found if is_unique(d, totals)]
    rank(found, totals, affinity, unique_sets)
    return found, unique_sets, note


def cut_said(note: str, want: int, n: int) -> str:
    """Every cut is said: when more than `want` candidates were found, the note tells how
    many there were."""
    return note + (f" - the best {want} of {n:,} candidates are listed" if n > want else "")


def key_reasons(cols: list[str], d: dict[str, int], totals: dict[str, int], affinity: dict[str, int],
                nulls: dict[str, int], overlap: float | None, unique_sets: list[frozenset], how: str,
                name_a: str, name_b: str | None = None, single_ov: dict[str, float] | None = None,
                null_keys: int = 0) -> str:
    """Why a candidate ranks where it does, as one line of plain reasons. `d` and `totals`
    are keyed by side view - two for a pair, one for a table on its own: then `name_b` is
    None, the figures name no side and there is no overlap to speak of. `single_ov` is the
    overlap of each column on its own - read only when the combination shares nothing, to
    name the column that is the reason. `null_keys` is the one-table count of rows where
    any of the columns is null: they identify nothing, so they are not among the rows that
    share a key - the pair does not pass it, and reads rows less distinct as it always has."""
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
    # the figures per side, the side named on a pair: "3,000 distinct of 3,000 in hr, 2,985
    # of 2,985 in payroll" - a table on its own reads "3,000 distinct of 3,000"
    sides = ([("probe_a", name_a), ("probe_b", name_b)] if name_b is not None
             else [(next(iter(totals)), "")])
    bits.append(", ".join(f"{d[v]:,} {'distinct ' if not i else ''}of {totals[v]:,}"
                          + (f" in {nm}" if nm else "") for i, (v, nm) in enumerate(sides)))
    shares = [(totals[v] - null_keys - d[v], nm) for v, nm in sides]
    if any(n for n, _ in shares):
        bits.append(" and ".join(f"{n:,} rows" + (f" in {nm}" if nm else "") + " share it"
                                 for n, nm in shares if n))
    if name_b is not None:
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
                 opts: ReadOptions, progress=None, max_cols: int = MAX_KEY_COLS, want: int = 8,
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
    singles, nulls = single_figures(con, views, measure)
    for c, p in from_profile.items():
        if p is not None:
            singles[c] = {"probe_a": p["probe_a"], "probe_b": p["probe_b"]}
            nulls[c] = p["nulls_a"] + p["nulls_b"]
    affinity = {s.canon: key_affinity(s.canon, A.schema.get(s.a_src, ""),
                                      B.schema.get(s.b_src, "")) for s in specs}
    found, unique_sets, note = search_keys(con, views, totals, candidates, singles, nulls,
                                           affinity, max_cols, want, say)
    if used_profile:
        note += " - single-column figures from the profile"

    def overlap(cols: list[str]) -> float:
        """Share of A's distinct key values also present in B."""
        k = combo(cols)
        n, m = con.execute(f"SELECT count(DISTINCT {k}), count(DISTINCT {k}) FILTER "
                           f"(WHERE {k} IN (SELECT {k} FROM probe_b)) FROM probe_a").fetchone()
        return m / n * 100 if n else 0.0

    n_found = len(found)
    found = found[:want * 2]                       # the overlap is measured on the best of them
    say(f"Overlap between the sides for {len(found)} candidate(s)…")
    ov = {tuple(cols): overlap(cols) for cols, _, _ in found}
    rank(found, totals, affinity, unique_sets, ov)
    found = found[:want]
    note = cut_said(note, want, n_found)
    # a combination that shares nothing: which of its columns is the reason
    single_ov = {c: overlap([c]) for cols, _, _ in found if len(cols) > 1 and ov[tuple(cols)] == 0
                 for c in cols}
    table = pd.DataFrame([{
        "Key columns": " + ".join(cols),
        f"Distinct in {name_a}": d["probe_a"],
        f"Distinct in {name_b}": d["probe_b"],
        "Unique on both": "yes" if is_unique(d, totals) else "no",
        "Duplicate rows": (totals["probe_a"] - d["probe_a"]) + (totals["probe_b"] - d["probe_b"]),
        "Overlap %": round(ov[tuple(cols)], 1),
        "Looks like a key": "yes" if all(affinity[c] >= 0 for c in cols) else "measure columns",
        "Why": key_reasons(cols, d, totals, affinity, nulls, ov[tuple(cols)], unique_sets, how,
                           name_a, name_b, single_ov),
    } for cols, d, how in found])
    return table, [cols for cols, _, _ in found], note


def suggest_keys_single(P: Side, specs: list[ColSpec], name: str, opts: ReadOptions,
                        progress=None, max_cols: int = MAX_KEY_COLS, want: int = 8,
                        con=None, view: str | None = None, stats: pd.DataFrame | None = None
                        ) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Candidate keys of a table on its own, best first - the Profiling page - each with the
    reasons for its place, plus a note on how they were found. `con` and `view` are a
    connection where the table is already registered (the profile's), so it is not read
    again; without them it is read here. `stats` is the profile's statistics table
    (Column, Distinct, Nulls) of the same columns: when given, the single-column figures
    come from it, so they are not measured twice."""
    say = progress or (lambda _msg: None)
    candidates = [s.canon for s in specs]
    if con is None:
        say(f"Reading {name} ({len(candidates)} columns)…")
        con, view = scratch(), "probe"
        register(con, P, view, specs, "A", opts, materialize=True)
    views = (view,)
    totals = {view: con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]}

    known = {} if stats is None else {r["Column"]: (int(r["Distinct"]), int(r["Nulls"]))
                                      for _, r in stats.iterrows()}
    measure = [c for c in candidates if c not in known]
    used_profile = len(measure) < len(candidates)
    say("Reading the profile…" if used_profile else "Measuring every column…")
    singles, nulls = single_figures(con, views, measure)
    for c in candidates:
        if c in known:
            singles[c], nulls[c] = {view: known[c][0]}, known[c][1]
    affinity = {s.canon: key_affinity(s.canon, P.schema.get(s.a_src, "")) for s in specs}
    # the search keeps the rows with a null key apart, as key_uniqueness does: they identify
    # nothing, so they are neither distinct nor duplicates, and a combination is unique only
    # with none - the way the table reads Unique, so the rank, the unique sets and the
    # 'adds nothing' agree with it
    found, unique_sets, note = search_keys(con, views, totals, candidates, singles, nulls,
                                           affinity, max_cols, want, say, nulls_apart=True)
    if used_profile:
        note += " - single-column figures from the profile"
    note = cut_said(note, want, len(found))
    found = found[:want]

    # what is left to count is how many rows each combination has with a null key, all in
    # one query - a single column has them measured already
    multi = [cols for cols, _, _ in found if len(cols) > 1]
    null_keys: dict[tuple, int] = {}
    if multi:
        picks = ", ".join(f"count(*) FILTER (WHERE {any_null(cols)})" for cols in multi)
        row = con.execute(f"SELECT {picks} FROM {view}").fetchone()
        null_keys = {tuple(cols): n for cols, n in zip(multi, row)}
    rows = totals[view]
    table = []
    for cols, d, how in found:
        dist, nk = d[view], null_keys.get(tuple(cols), nulls.get(cols[0], 0))
        dup = rows - nk - dist
        table.append({
            "Key columns": " + ".join(cols),
            "Distinct": dist,
            "Unique": "yes" if not dup and not nk else "no",
            "Duplicate rows": dup,
            "Null keys": nk,
            "Looks like a key": "yes" if all(affinity[c] >= 0 for c in cols) else "measure columns",
            "Why": key_reasons(cols, d, totals, affinity, nulls, None, unique_sets, how, name,
                               null_keys=nk),
        })
    return pd.DataFrame(table, columns=KEY_COLS), [cols for cols, _, _ in found], note
