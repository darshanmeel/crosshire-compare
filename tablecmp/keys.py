"""Keys: is a combination unique on both sides, and which combinations would be - on a
pair, or on one table on its own (the Profiling page)."""
from __future__ import annotations

import re
import time

import pandas as pd

from .profile import profile_singles
from .sources import Side, work_dir
from .sql import columns_a_statement, ident, lit, scratch
from .values import ColSpec, ReadOptions, hold

DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME")
ID_WORDS = re.compile(r"(^|_)(id|key|code|ref|no|num|nbr|isin|sedol|cusip|symbol|sym|ticker|"
                      r"type|line|seq|idx|index|row|account|acct)($|_)", re.I)
# names and dates often take part in a key, so they rank like an identifier - but are not one
KEY_WORDS = re.compile(r"(^|_)(name|date|day|time)($|_)", re.I)
MEASURE_WORDS = re.compile(r"(^|_)(qty|quantity|amount|amt|price|px|value|val|total|sum|count|"
                           r"cnt|rate|pct|percent|weight|volume|vol|balance|bal|cost|fee|"
                           r"nav|return|ret|yield)($|_)", re.I)
# a checksum of the row is unique by construction and says nothing about which row it is
HASH_WORDS = re.compile(r"(^|_)(hash|hsh|hk|hashkey|hashdiff|checksum|chksum|cksum|md5|sha|sha1|"
                        r"sha2|sha256|sha512|crc|crc32|digest|fingerprint|etag)($|_)", re.I)
HASH_SHAPE = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64}|[0-9a-f]{128})$", re.I)
HASH_SAMPLE = 200           # filled values looked at to say a column's values are digests
HASH_LENGTHS = (32, 40, 64, 128)     # hex digits in an MD5, SHA-1, SHA-256, SHA-512
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
    """A connection with both sides under the shared names - a table each when it fits in
    memory, else a view over the file (values.hold)."""
    con = scratch()
    hold(con, A, "probe_a", specs, "A", opts)
    hold(con, B, "probe_b", specs, "B", opts)
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


def looks_like(cols: list[str], affinity: dict[str, int], hashed: set[str] | frozenset[str]) -> str:
    """The Looks like a key cell: yes, or what among the columns says otherwise."""
    if any(HASH_WORDS.search(c) or c in hashed for c in cols):
        return "checksum"
    return "yes" if all(affinity[c] >= 0 for c in cols) else "measure columns"


def could_be_hashed(specs: list[ColSpec], stats: list[pd.DataFrame]) -> list[str]:
    """The text columns worth a look for digests: with a statistics table of the columns,
    only the ones whose every filled value has one digest length; without, every text
    column - a look is one small read of the column (looks_hashed)."""
    keep = {s.canon for s in specs if s.kind == "text"}
    for table in stats:
        if "Min length" not in table.columns:          # (Column, Distinct, Nulls) says nothing here
            continue
        lens = {r["Column"]: (r["Min length"], r["Max length"]) for _, r in table.iterrows()}
        keep = {c for c in keep if c not in lens
                or (pd.notna(lens[c][0]) and lens[c][0] == lens[c][1] and int(lens[c][0]) in HASH_LENGTHS)}
    return [s.canon for s in specs if s.canon in keep]


def looks_hashed(con, view: str, col: str) -> bool:
    """Whether the column's values are digests: the first HASH_SAMPLE filled values are all
    hex of one digest length - 32 (MD5), 40 (SHA-1), 64 (SHA-256) or 128 (SHA-512) - and
    not all of them digits, which a long number would be."""
    vals = [str(v) for (v,) in con.execute(
        f"SELECT {ident(col)} FROM {view} WHERE {ident(col)} IS NOT NULL LIMIT {HASH_SAMPLE}").fetchall()]
    return (bool(vals) and all(HASH_SHAPE.match(v) for v in vals)
            and any(re.search(r"[a-f]", v, re.I) for v in vals))


def key_affinity(col: str, type_a: str, type_b: str = "", hashed: bool = False) -> int:
    """How much a column looks like part of a business key rather than a measure - from its
    name and the type detected on each side (a table on its own has only `type_a`), and
    whether its values are digests (looks_hashed): a checksum of the row is unique by
    construction and no key, so it ranks under one however key-like its name reads."""
    score = 0
    if ID_WORDS.search(col) or KEY_WORDS.search(col):
        score += 3
    if MEASURE_WORDS.search(col):
        score -= 3
    if HASH_WORDS.search(col) or hashed:
        score -= 5
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
HOW_ONLY = "on its own - no other column to add"
HOW_HYUCC = "found with Desbordante HyUCC"
HOW_PYRO = "found with Desbordante PyroUCC as almost unique"


def is_unique(d: dict[str, int], totals: dict[str, int]) -> bool:
    """As many distinct values as rows, on every view."""
    return all(d[v] == totals[v] for v in totals)


def selectivity(d: dict[str, int], totals: dict[str, int]) -> float:
    """Distinct values per row, on the view where it is lowest."""
    return min(d[v] / max(totals[v], 1) for v in totals)


def single_figures(con, views, cols: list[str], totals: dict[str, int] | None = None
                   ) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Each column on its own: distinct count per view, and nulls over every view - a few
    columns a statement per view (sql.columns_a_statement: a count(DISTINCT) per column
    holds a hash table each, and hundreds at once run DuckDB out of memory)."""
    singles: dict[str, dict[str, int]] = {c: {} for c in cols}
    nulls: dict[str, int] = {}
    for v in views:
        per = columns_a_statement((totals or {}).get(v, 0))
        for i in range(0, len(cols), per):
            part = cols[i:i + per]
            picks = ", ".join(f"count(DISTINCT {ident(c)}), count(*) - count({ident(c)})" for c in part)
            row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
            for j, c in enumerate(part):
                singles[c][v] = row[2 * j]
                nulls[c] = nulls.get(c, 0) + row[2 * j + 1]
    return singles, nulls


def rank(found: list[tuple[list[str], dict[str, int], str]], totals: dict[str, int],
         affinity: dict[str, int], unique_sets: list[frozenset],
         overlap: dict[tuple, float] | None = None) -> None:
    """Sort the candidates in place: unique first; a combination that only adds columns to a
    key that is already unique adds nothing, whatever the affinity of the extra columns says,
    so it goes below; on a pair, one with no values in common pairs no rows, so it goes
    below every one that pairs some - a row number each side counts for itself under a
    name and a date shared by both; then the ones that look like a key (no measure among
    them); then the ones with an identifier in the name - emp_id above hire_date +
    first_name + last_name, however key-like a name and a date read; then affinity sum,
    the share of values the other side has when there is one, fewer columns, selectivity."""
    def key(f):
        cols, d, _ = f
        return (not is_unique(d, totals), any(u < set(cols) for u in unique_sets),
                overlap is not None and not overlap[tuple(cols)],
                not all(affinity[c] >= 0 for c in cols),
                not any(ID_WORDS.search(c) for c in cols),
                -sum(affinity[c] for c in cols),
                -round(overlap[tuple(cols)]) if overlap is not None else 0,
                len(cols), -selectivity(d, totals))
    found.sort(key=key)


def search_keys(con, views, totals: dict[str, int], candidates: list[str],
                singles: dict[str, dict[str, int]], nulls: dict[str, int],
                affinity: dict[str, int], max_cols: int, want: int, say,
                nulls_apart: bool = False, pairs=None
                ) -> tuple[list[tuple[list[str], dict[str, int], str]], list[frozenset], str]:
    """The candidate search, over any number of side views on one connection - a pair, or a
    table on its own: every column unique by itself, then combinations grown from the most
    selective columns (affinity-ranked, up to `max_cols`), or Desbordante's HyUCC / PyroUCC
    on the first UCC_SAMPLE rows when it is installed, verified on every row. Every
    combination grown is minimal: nothing is grown onto a key that works already, and one
    that is grown is cut back to the fewest columns that tell as many rows apart. The
    columns that look like a key are tried before a measure, and a measure is tried only
    while no key has been found at all - as a seed, as a column added, and in a second
    growth with every column competing on selectivity alone when the key-like columns fill
    a combination without making it unique: a key with an amount in it beats no key, and is
    a coincidence beside one. `want` keys end the search. On a pair `pairs(cols)` says
    whether a unique combination has any value in common with the other side: one with
    none is unique but no key - it pairs no rows - so it neither ends the search nor keeps
    a measure or a lone seed from being offered, though a superset of it still adds
    nothing. Returns each candidate as (columns, distinct per view, how it was found),
    ranked; the column sets that are unique, so a superset can say it adds nothing; and the
    note on how they were found. A column with one value (or none) on every view can never
    tell rows apart, so it is never a candidate. With `nulls_apart` a combination's distinct
    count leaves out the rows where any of its columns is null, as key_uniqueness does -
    they identify nothing - so it is unique only with no null keys and no duplicates, the
    way the one-table candidate table reads Unique, and a column with a null can never
    complete a key; a single column's count leaves them out either way. A pair counts null
    as a value, as it always has."""
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
    uniques: list[frozenset] = []          # the column sets found unique, as they are found
    keys: list[frozenset] = []             # the ones that pair rows - all of them on one table

    def offer(cols, d, how):
        if cols and frozenset(cols) not in seen:
            seen.add(frozenset(cols))
            found.append((cols, d, how))
            if is_unique(d, totals):
                uniques.append(frozenset(cols))
                if pairs is None or pairs(cols):
                    keys.append(frozenset(cols))

    def adds_nothing(cols: list[str]) -> bool:
        """Holds more than a set that is unique already - columns added to a key that works.
        The set itself is not that: reached again it is offered again, and dropped as seen."""
        return any(u < set(cols) for u in uniques)

    def shrink(cols, d):
        """A combination cut back to a minimal one: a column that can go without the rest
        telling fewer rows apart goes, the least key-like first, until none can - a key
        stays a key, and the closest stays as close with fewer columns."""
        while len(cols) > 1:
            for col in sorted(cols, key=lambda c: affinity[c]):
                rest = [c for c in cols if c != col]
                rd = distinct(rest)
                if all(rd[v] >= d[v] for v in totals):
                    cols, d = rest, rd
                    break
            else:
                break
        return cols, d

    def tier(c: str) -> tuple[bool, bool]:
        """The order columns are tried in: the ones that look like a key before a measure,
        and with nulls apart the ones without a null first - a null-key row is never told
        apart, so a column with a null can never complete a key."""
        return affinity[c] < 0, nulls_apart and nulls.get(c, 0) > 0

    def climb(seed_cols, seed_d, tiered: bool):
        """Columns added to the seed one at a time, the one that tells most rows apart each
        time, until the combination is unique or full. Tiered, the columns of a better tier
        are tried first and a worse tier only when none of them tells more rows apart;
        untiered, every column competes on selectivity alone."""
        cols, d = list(seed_cols), seed_d
        # a column that would only be added to a key that works already is never carried -
        # the combination would add nothing - and a measure is never added beside a key
        pool = [c for c in ranked if c not in cols and not adds_nothing(cols + [c])
                and not (keys and affinity[c] < 0)]
        if not tiered and nulls_apart:
            # this growth is after a key, and a column with a null can never complete one
            pool = [c for c in pool if not nulls.get(c)]
        while not is_unique(d, totals) and len(cols) < max_cols and pool:
            best, best_d, best_score = None, None, -1.0
            tiers = ([[c for c in pool if tier(c) == t] for t in sorted({tier(c) for c in pool})]
                     if tiered else [pool])
            for cands in tiers:
                for col in cands[:12]:
                    cand = distinct(cols + [col])
                    sc = selectivity(cand, totals)
                    if sc > best_score:
                        best, best_d, best_score = col, cand, sc
                if best is not None and best_score > selectivity(d, totals):
                    break
            if best is None:
                break
            # with nulls apart a null-key row is never told apart, so a column that raises
            # the count by nothing is not carried - the seed stands on its own; a pair keeps
            # growing, as it always has
            if nulls_apart and best_score <= selectivity(d, totals):
                break
            cols, d = cols + [best], best_d
            pool = [c for c in pool if c != best and not adds_nothing(cols + [c])]
        return cols, d

    def grow(seed_cols, seed_d, how=HOW_GROWN):
        others = [c for c in ranked if c not in seed_cols and not adds_nothing(list(seed_cols) + [c])]
        cols, d = climb(seed_cols, seed_d, tiered=True)
        # the columns that look like a key can fill the combination without making it
        # unique while a measure would have - then, while no key has been found at all,
        # the measure is taken, every column competing on selectivity alone: a key with an
        # amount in it beats no key, and is a coincidence beside one
        if not is_unique(d, totals) and not keys and any(affinity[c] < 0 for c in others):
            alt, alt_d = climb(seed_cols, seed_d, tiered=False)
            if is_unique(alt_d, totals):
                cols, d = alt, alt_d
        # a combination is cut back to the fewest columns that tell as many rows apart, so
        # every key offered is minimal - and the closest is not a key that is not, padded
        if len(cols) > 1:
            cols, d = shrink(cols, d)
        if len(cols) == 1 and how == HOW_GROWN:
            if keys and not nulls_apart:
                return      # a pair's column that nothing could be added to says nothing beside a key
            how = HOW_ONLY if not others else HOW_ALONE
        offer(cols, d, how)

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
        # the seeds are the best four columns that are not keys on their own - one that is
        # has been offered, and nothing grown from it could add anything; with nulls apart
        # a column with a null can only stand on its own, so it is grown without using up
        # one of the four that could grow a key; a measure is no seed beside a key
        taken = {False: 0, True: 0}
        for seed in [c for c in ranked if not is_unique(singles[c], totals)]:
            if len(keys) >= want:
                break       # only keys count towards the cut - the closest never end the search
            null_seed = nulls_apart and nulls.get(seed, 0) > 0
            if taken[null_seed] >= 4 or (affinity[seed] < 0 and keys):
                continue
            taken[null_seed] += 1
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
                null_keys: int = 0, hashed: frozenset[str] | set[str] = frozenset()) -> str:
    """Why a candidate ranks where it does, as one line of plain reasons. `d` and `totals`
    are keyed by side view - two for a pair, one for a table on its own: then `name_b` is
    None, the figures name no side and there is no overlap to speak of. `single_ov` is the
    overlap of each column on its own - read only when the combination shares nothing, to
    name the column that is the reason. `null_keys` is the one-table count of rows where
    any of the columns is null: they identify nothing, so they are not among the rows that
    share a key - the pair does not pass it, and reads rows less distinct as it always has."""
    bits = []
    idish = [c for c in cols if ID_WORDS.search(c)]
    hashes = [c for c in cols if HASH_WORDS.search(c) or c in hashed]
    measures = [c for c in cols if c not in hashes and (MEASURE_WORDS.search(c) or affinity[c] <= -4)]
    if hashes:
        bits.append(f"{', '.join(hashes)}: a checksum - unique by construction, not a key")
    if measures:
        bits.append(f"{', '.join(measures)}: a measure"
                    + (", decimal" if any(affinity[c] <= -4 for c in measures) else "") + " - never a key")
    if not hashes and not measures:
        if idish:
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
    singles, nulls = single_figures(con, views, measure, totals)
    for c, p in from_profile.items():
        if p is not None:
            singles[c] = {"probe_a": p["probe_a"], "probe_b": p["probe_b"]}
            nulls[c] = p["nulls_a"] + p["nulls_b"]
    stats = [profile["stats"][w] for w in ("A", "B")
             if profile and isinstance(profile.get("stats"), dict) and w in profile["stats"]]
    hashed = {c for c in could_be_hashed(specs, stats) if any(looks_hashed(con, v, c) for v in views)}
    affinity = {s.canon: key_affinity(s.canon, A.schema.get(s.a_src, ""),
                                      B.schema.get(s.b_src, ""), s.canon in hashed) for s in specs}
    ov: dict[tuple, float] = {}

    def overlap(cols: list[str]) -> float:
        """Share of A's distinct key values also present in B - measured once per combination."""
        if tuple(cols) not in ov:
            k = combo(cols)
            n, m = con.execute(f"SELECT count(DISTINCT {k}), count(DISTINCT {k}) FILTER "
                               f"(WHERE {k} IN (SELECT {k} FROM probe_b)) FROM probe_a").fetchone()
            ov[tuple(cols)] = m / n * 100 if n else 0.0
        return ov[tuple(cols)]

    # a key with no values in common pairs no rows, so it is no key to the search
    found, unique_sets, note = search_keys(con, views, totals, candidates, singles, nulls,
                                           affinity, max_cols, want, say,
                                           pairs=lambda cols: overlap(cols) > 0)
    if used_profile:
        note += " - single-column figures from the profile"

    n_found = len(found)
    found = found[:want * 2]                       # the overlap is measured on the best of them
    say(f"Overlap between the sides for {len(found)} candidate(s)…")
    for cols, _, _ in found:
        overlap(cols)
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
        "Looks like a key": looks_like(cols, affinity, hashed),
        "Why": key_reasons(cols, d, totals, affinity, nulls, ov[tuple(cols)], unique_sets, how,
                           name_a, name_b, single_ov, hashed=hashed),
    } for cols, d, how in found])
    return table, [cols for cols, _, _ in found], note


def suggest_keys_single(P: Side, specs: list[ColSpec], name: str, opts: ReadOptions,
                        progress=None, max_cols: int = MAX_KEY_COLS, want: int = 3,
                        con=None, view: str | None = None, stats: pd.DataFrame | None = None
                        ) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Candidate keys of a table on its own, best first - the Profiling page - each with the
    reasons for its place, plus a note on how they were found. The best `want` are listed:
    when anything is unique, only the keys - each minimal, no two the same - and when
    nothing is, the closest. `con` and `view` are a
    connection where the table is already registered (the profile's), so it is not read
    again; without them it is read here. `stats` is the profile's statistics table
    (Column, Distinct, Nulls) of the same columns: when given, the single-column figures
    come from it, so they are not measured twice."""
    say = progress or (lambda _msg: None)
    candidates = [s.canon for s in specs]
    if con is None:
        say(f"Reading {name} ({len(candidates)} columns)…")
        con, view = scratch(), "probe"
        hold(con, P, view, specs, "A", opts)
    views = (view,)
    totals = {view: con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]}

    known = {} if stats is None else {r["Column"]: (int(r["Distinct"]), int(r["Nulls"]))
                                      for _, r in stats.iterrows()}
    measure = [c for c in candidates if c not in known]
    used_profile = len(measure) < len(candidates)
    say("Reading the profile…" if used_profile else "Measuring every column…")
    singles, nulls = single_figures(con, views, measure, totals)
    for c in candidates:
        if c in known:
            singles[c], nulls[c] = {view: known[c][0]}, known[c][1]
    hashed = {c for c in could_be_hashed(specs, [stats] if stats is not None else [])
              if looks_hashed(con, view, c)}
    affinity = {s.canon: key_affinity(s.canon, P.schema.get(s.a_src, ""), hashed=s.canon in hashed)
                for s in specs}
    # the search keeps the rows with a null key apart, as key_uniqueness does: they identify
    # nothing, so they are neither distinct nor duplicates, and a combination is unique only
    # with none - the way the table reads Unique, so the rank, the unique sets and the
    # 'adds nothing' agree with it
    found, unique_sets, note = search_keys(con, views, totals, candidates, singles, nulls,
                                           affinity, max_cols, want, say, nulls_apart=True)
    if used_profile:
        note += " - single-column figures from the profile"
    # beside a key only keys are listed; a combination that is not unique is the closest
    # there is only when nothing is
    keys = [f for f in found if is_unique(f[1], totals)]
    found = keys or found
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
            "Looks like a key": looks_like(cols, affinity, hashed),
            "Why": key_reasons(cols, d, totals, affinity, nulls, None, unique_sets, how, name,
                               null_keys=nk, hashed=hashed),
        })
    return pd.DataFrame(table, columns=KEY_COLS), [cols for cols, _, _ in found], note
