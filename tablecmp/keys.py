"""Keys: is a combination unique on both sides, and which combinations would be - on a
pair, or on one table on its own (the Profiling page)."""
from __future__ import annotations

import re
import time
from itertools import combinations

import pandas as pd

from .profile import profile_singles
from .sources import Side, work_dir
from .sql import columns_a_statement, ident, in_batches, lit, scratch
from .values import ColSpec, ReadOptions, hold, register

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
KEY_SAMPLE = 5_000          # rows of the random sample a level is counted on first - a duplicate there is one on every row
POOL_COLS = 24              # columns that take part in combinations: the most key-like, in table order
POOL_MEASURES = 8           # measures added to them when the key-like columns found no key
MAX_TRIED = 300             # combinations counted a level, the tightest first
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
HOW_LEVEL = {2: "unique as a pair - no single column is",
             3: "unique as three - no single column or pair is",
             4: "unique as four - nothing shorter is"}
HOW_CLOSEST = "the closest - no combination up to {n} columns is unique"
HOW_ALONE = "on its own - adding a column told no more rows apart"
HOW_ONLY = "on its own - no other column to add"
HOW_NULL = "on its own - with a null it can complete no key"
HOW_NO_COMBO = "on its own - no combination with it is unique"
HOW_HYUCC = "found with Desbordante HyUCC"
HOW_PYRO = "found with Desbordante PyroUCC as almost unique"


def is_unique(d: dict[str, int], totals: dict[str, int]) -> bool:
    """As many distinct values as rows, on every view."""
    return all(d[v] == totals[v] for v in totals)


def selectivity(d: dict[str, int], totals: dict[str, int]) -> float:
    """Distinct values per row, on the view where it is lowest."""
    return min(d[v] / max(totals[v], 1) for v in totals)


def count_sql(cols, nulls_apart: bool = False) -> str:
    """The distinct count of one combination - with `nulls_apart` the rows where any of its
    columns is null are left out, the way key_uniqueness counts them."""
    sql = f"count(DISTINCT {combo(list(cols))})"
    if nulls_apart:
        sql += f" FILTER (WHERE NOT ({any_null(list(cols))}))"
    return sql


def count_combos(con, table: str, combos: list[tuple], rows: int,
                 nulls_apart: bool = False) -> list[int]:
    """The distinct count of each combination on `table`, a few a statement - each count
    holds a hash table of its own (sql.columns_a_statement), and hundreds at once is what
    runs DuckDB out of memory."""
    def run(batch: list[tuple]) -> list[int]:
        picks = ", ".join(count_sql(cols, nulls_apart) for cols in batch)
        return [int(n) for n in con.execute(f"SELECT {picks} FROM {table}").fetchone()]
    return in_batches(combos, run, columns_a_statement(rows))


def single_figures(con, views, cols: list[str], totals: dict[str, int] | None = None
                   ) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Each column on its own: distinct count per view, and nulls over every view - a few
    columns a statement per view (sql.columns_a_statement: a count(DISTINCT) per column
    holds a hash table each, and hundreds at once run DuckDB out of memory)."""
    singles: dict[str, dict[str, int]] = {c: {} for c in cols}
    nulls: dict[str, int] = {}
    for v in views:
        def run(part: list[str], v=v) -> list:
            picks = ", ".join(f"count(DISTINCT {ident(c)}), count(*) - count({ident(c)})" for c in part)
            row = con.execute(f"SELECT {picks} FROM {v}").fetchone()
            for j, c in enumerate(part):
                singles[c][v] = row[2 * j]
                nulls[c] = nulls.get(c, 0) + row[2 * j + 1]
            return list(part)
        in_batches(cols, run, columns_a_statement((totals or {}).get(v, 0)))
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
    first_name + last_name, however key-like a name and a date read; then how close it comes -
    distinct values per row, the same for every key - the share of values the other side has
    when there is one, then fewer columns, then how key-like the names are on average.

    How close it comes before the names, and the names averaged rather than summed: a sum
    grows with every column added, so four key-like names outscored the two that are the key
    whenever nothing was unique on both sides - the list then held four-column coincidences
    and not the pair the reader wanted."""
    def key(f):
        cols, d, _ = f
        return (not is_unique(d, totals), any(u < set(cols) for u in unique_sets),
                overlap is not None and not overlap[tuple(cols)],
                not all(affinity[c] >= 0 for c in cols),
                not any(ID_WORDS.search(c) for c in cols),
                -selectivity(d, totals),
                -round(overlap[tuple(cols)]) if overlap is not None else 0,
                len(cols),
                -sum(affinity[c] for c in cols) / len(cols))
    found.sort(key=key)


def search_keys(con, views, totals: dict[str, int], candidates: list[str],
                singles: dict[str, dict[str, int]], nulls: dict[str, int],
                affinity: dict[str, int], max_cols: int, want: int, say,
                nulls_apart: bool = False, pairs=None, sampler=None
                ) -> tuple[list[tuple[list[str], dict[str, int], str]], list[frozenset], str]:
    """The candidate search, over any number of side views on one connection - a pair, or a
    table on its own - a level at a time: every column on its own first; when none is
    unique, every pair; when no pair is, combinations of three; then of four (`max_cols`).
    A level that finds a key ends the search, so nothing is ever combined with a column
    or a pair that is a key already, no key found holds a shorter one, and every key is
    minimal by construction. Or Desbordante's HyUCC / PyroUCC on the first UCC_SAMPLE
    rows when it is installed, verified on every row, the shortest first, and the same
    level rule on what it found.

    The columns that take part in a combination are the pool: the POOL_COLS most key-like
    columns in table order - the ones with an identifier, a name or a date in the name
    first, then the rest, a measure only in a second pass when the key-like ones found no
    key at all (a key with an amount in it beats no key, and is a coincidence beside one)
    - never a column unique by itself or constant, and with `nulls_apart` never one with
    a null, which can complete no key. A combination whose columns' distinct counts
    multiply to fewer than the rows cannot be unique and is not counted; the rest are
    counted in order of that product, the tightest first - a designed key partitions the
    rows about once, a coincidence of high-cardinality columns many times over - every
    pair, and the MAX_TRIED tightest combinations of three and of four, a few a
    statement. Over KEY_SAMPLE rows a level is counted on a random sample of KEY_SAMPLE
    rows first (reservoir, the same rows each run; `sampler(view, name, cols, n)` makes
    it as a table `name`, drawn from the file before the values are typed - without one
    it is drawn from the view, which types every row first) - a duplicate there is a
    duplicate on every row, and a count there is a couple of milliseconds - and only the combinations
    unique on the sample are verified on every row, the tightest first, a statement's
    worth at a time; a statement that verified a key ends the level, so the tightest key
    is verified in one and the coincidences behind it are never counted on every row.
    On a pair only one side is counted here and `pairs(cols)` verifies what was found on
    the other: a combination unique on the side counted is a key only when it holds there
    too - one that does not is listed but does not end the level, so the search goes on,
    though a superset of it still adds nothing. Nothing unique at all, and the closest are listed: the most
    selective combinations counted, each cut back to the fewest columns that tell as many
    rows apart, and the most selective single columns. Returns each candidate as
    (columns, distinct per view, how it was found), ranked; the column sets that are
    unique, so a superset can say it adds nothing; and the note on how they were found.
    With `nulls_apart` a combination's distinct count leaves out the rows where any of
    its columns is null, as key_uniqueness does - they identify nothing - so it is unique
    only with no null keys and no duplicates, the way the one-table candidate table reads
    Unique; a single column's count leaves them out either way. A pair counts null as a
    value, as it always has."""
    order = {c: i for i, c in enumerate(candidates)}
    live = [c for c in candidates if not all(singles[c][v] <= 1 for v in views)]

    def alone_count(c: str) -> dict[str, int]:
        """A column's distinct count as a key counts it. A combination counts a null as a
        value unless nulls are apart, and rows with a null key do pair - the join matches
        null with null - so a column unique but for one null is counted unique here too.
        Counting it one way alone and the other in a pair is what made a pair read `unique
        as a pair - no single column is` when the single column was just as unique."""
        n = singles[c]
        if nulls_apart or not nulls.get(c, 0):
            return n
        return {v: n[v] + 1 for v in views}
    found: list[tuple[list[str], dict[str, int], str]] = []
    seen: set[frozenset] = set()
    uniques: list[frozenset] = []          # the column sets found unique, as they are found
    keys: list[frozenset] = []             # the ones that pair rows - all of them on one table

    def verify(combos: list[tuple]) -> set[frozenset]:
        """Which of these hold on the other side too - all of them when there is no other side.

        The tightest is asked about on its own and the rest only when it did not hold: a
        designed key is verified in one small statement, as it was when each candidate was
        asked about in turn, and a table where nothing holds asks about the rest a few a
        statement rather than one statement per candidate."""
        if pairs is None:
            return {frozenset(c) for c in combos}
        if not combos:
            return set()
        held = pairs([list(combos[0])])
        if not held and len(combos) > 1:
            held = pairs([list(c) for c in combos[1:]])
        return held

    def offer(cols, d, how, held: set[frozenset] | None = None):
        """One candidate, with `held` when the caller has already asked the other side about
        a batch this one is in - without it a unique candidate is asked about on its own."""
        if cols and frozenset(cols) not in seen:
            seen.add(frozenset(cols))
            found.append((list(cols), d, how))
            if is_unique(d, totals):
                uniques.append(frozenset(cols))
                if frozenset(cols) in (verify([tuple(cols)]) if held is None else held):
                    keys.append(frozenset(cols))

    def adds_nothing(cols) -> bool:
        """Holds more than a set that is unique already - columns added to a key that works."""
        return any(u < set(cols) for u in uniques)

    def count_many(table: str, combos: list[tuple], rows: int) -> list[int]:
        return count_combos(con, table, combos, rows, nulls_apart)

    def distinct(cols) -> dict[str, int]:
        if len(cols) == 1:
            return alone_count(cols[0])
        return {v: count_many(v, [tuple(cols)], totals[v])[0] for v in views}

    def shrink(cols, d):
        """A combination cut back to a minimal one: a column that can go without the rest
        telling fewer rows apart goes, the least key-like first, until none can - the
        closest stays as close with fewer columns."""
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

    # ---- level 1: every column on its own
    alone = [(c,) for c in live if is_unique(alone_count(c), totals)]
    held = verify(alone) if alone else set()
    for (c,) in alone:
        offer([c], alone_count(c), HOW_SINGLE, held)
    pair = len(views) > 1
    hint = "`pip install desbordante` for exact key discovery (HyUCC / PyroUCC)"

    if desbordante_available():
        n = min(UCC_SAMPLE, max(totals.values()))
        note = (f"Found with Desbordante HyUCC on the first {n:,} rows"
                + (" of each side and verified on every row of both" if pair
                   else " and verified on every row")
                + " - the shortest combinations first, and a length that holds a key ends the search")
        if keys:
            note = "Found by measuring every column - a column unique by itself is the key, so no combination was tried"
        else:
            say("Desbordante: minimal unique column combinations" + (" on each side…" if pair else "…"))
            cands: set[frozenset] = set()
            for v in views:
                cands.update(frozenset(c) for c in ucc_candidates(con, v, live, max_lhs=max_cols))
            ordered = sorted(cands, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:30]
            say(f"Verifying {len(ordered)} candidate(s) on every row…")
            for size in range(2, max_cols + 1):
                for c in [c for c in ordered if len(c) == size]:
                    cols = sorted(c, key=order.get)
                    if not adds_nothing(cols):
                        offer(cols, distinct(cols), HOW_HYUCC)
                if keys:
                    break
            if not any(is_unique(d, totals) for _, d, _ in found):
                say("Nothing exactly unique - PyroUCC, almost-unique combinations…")
                note += "; nothing was exactly unique, so PyroUCC's almost-unique combinations " \
                        "(≤1% of rows in the way) were added"
                approx: set[frozenset] = set()
                for v in views:
                    approx.update(frozenset(c) for c in ucc_candidates(con, v, live, error=0.01,
                                                                       max_lhs=max_cols))
                for c in sorted(approx, key=lambda c: (len(c), -sum(affinity[x] for x in c)))[:12]:
                    cols = sorted(c, key=order.get)
                    d = distinct(cols)
                    offer(*shrink(cols, d), HOW_PYRO)
        unique_sets = [frozenset(cols) for cols, d, _ in found if is_unique(d, totals)]
        rank(found, totals, affinity, unique_sets)
        return found, unique_sets, note

    if keys:
        unique_sets = [frozenset(cols) for cols, d, _ in found if is_unique(d, totals)]
        rank(found, totals, affinity, unique_sets)
        return found, unique_sets, ("Found by measuring every column - a column unique by itself "
                                    "is the key, so no combination was tried - " + hint)

    # ---- the pool: the most key-like columns in table order, a measure only in the second pass
    able = [c for c in live if not is_unique(alone_count(c), totals)
            and not (nulls_apart and nulls.get(c, 0))]
    pool = sorted([c for c in able if affinity[c] >= 0],
                  key=lambda c: (affinity[c] < 3, order[c]))[:POOL_COLS]
    measures = [c for c in able if affinity[c] < 0][:POOL_MEASURES]
    pool.sort(key=order.get)

    def values(c: str, v: str) -> int:
        """Distinct values of the column as a combination counts them - see counted()."""
        return alone_count(c)[v]

    def product(cols, v: str) -> int:
        out = 1
        for c in cols:
            out *= values(c, v)
        return out

    def fits(cols) -> bool:
        """Could be unique: the distinct counts multiply to at least the rows, on every view."""
        return all(product(cols, v) >= totals[v] for v in views)

    def level_combos(cols_pool: list[str], size: int, must: set[str] | None) -> list[tuple]:
        """The combinations of `size` pool columns worth counting, the tightest first -
        with `must`, only the ones holding one of those columns (the measures pass). Past
        MAX_TRIED the rest are dropped; `could` keeps how many there were, so the note can
        say the cut rather than let the reader read a count as the whole of it."""
        out = []
        for cols in combinations(cols_pool, size):
            if must is not None and not any(c in must for c in cols):
                continue
            if adds_nothing(cols) or not fits(cols):
                continue
            out.append(cols)
        first = views[0]
        out.sort(key=lambda cols: (product(cols, first), tuple(order[c] for c in cols)))
        could[size] = max(could[size], len(out))
        return out[:MAX_TRIED]

    # the random sample of each view over KEY_SAMPLE rows, made when a level needs it, dropped at the end
    sample: dict[str, tuple[str, int]] = {}
    sampled = False

    def ensure_samples():
        nonlocal sampled
        if sampled:
            return
        sampled = True
        picks = ", ".join(ident(c) for c in pool + measures)
        for i, v in enumerate(views):
            if totals[v] > KEY_SAMPLE:
                name = f"__keys_{i}"
                if sampler is not None:
                    sampler(v, name, pool + measures, KEY_SAMPLE)
                else:
                    con.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT {picks} FROM {v} "
                                f"USING SAMPLE reservoir({KEY_SAMPLE} ROWS) REPEATABLE (1)")
                sample[v] = (name, int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]))

    counted: dict[tuple, dict[str, int]] = {}      # every combination counted: distinct per view,
    on_sample: set[tuple] = set()                   # on the sample where it was cut there

    def try_level(combos: list[tuple]) -> None:
        """Count the combinations on the samples first, then verify the ones unique there on
        every row of every view, the tightest first, a statement's worth at a time - a
        full count each - and offer the unique ones; a statement that verified a key ends
        the level, so a designed key is verified in one and a wide table's coincidences
        are not verified at all."""
        ensure_samples()
        alive = list(combos)
        for v in views:
            if v in sample and alive:
                name, n = sample[v]
                for cols, d in zip(alive, count_many(name, alive, n)):
                    counted.setdefault(cols, {})[v] = d
                    on_sample.add(cols)
                alive = [cols for cols in alive if counted[cols][v] == n]
        if sample and alive:
            say(f"Verifying {len(alive)} on every row…")
        per = min(columns_a_statement(totals[v]) for v in views)
        for i in range(0, len(alive), per):
            batch = alive[i:i + per]
            for v in views:
                for cols, d in zip(batch, count_many(v, batch, totals[v])):
                    counted.setdefault(cols, {})[v] = d
            unique_here = [cols for cols in batch if is_unique(counted[cols], totals)]
            held = verify(unique_here) if unique_here else set()
            for cols in batch:
                on_sample.discard(cols)
                if is_unique(counted[cols], totals):
                    offer(list(cols), counted[cols], HOW_LEVEL.get(len(cols), HOW_LEVEL[4]), held)
            if keys:
                break

    # the biggest level of each width, not the sum of the two passes: the note says what one
    # level tried, and a reader adding up two passes read "600 tightest" for two lots of 300
    tried = {size: 0 for size in range(2, max_cols + 1)}
    could = {size: 0 for size in range(2, max_cols + 1)}    # before the MAX_TRIED cut
    with_measures = False
    for must in (None, set(measures)):
        if must is not None:
            if not measures:
                break
            with_measures = True
            say("No key among the key-like columns - the measures too…")
        cols_pool = pool if must is None else sorted(pool + measures, key=order.get)
        for size in range(2, max_cols + 1):
            combos = level_combos(cols_pool, size, must)
            if not combos:
                continue
            tried[size] = max(tried[size], len(combos))
            say(f"{'Pairs' if size == 2 else f'Combinations of {size}'}: {len(combos):,}…")
            try_level(combos)
            if keys:
                break
        if keys:
            break

    if not keys:
        # the closest: the most selective combinations counted - the ones cut on the sample
        # counted on every row first - cut back to minimal, and the most selective columns
        def closeness(cols) -> float:
            """Distinct per row on the rows it was counted on, the lowest view."""
            return min(d / max(sample[v][1] if v in sample and cols in on_sample else totals[v], 1)
                       for v, d in counted[cols].items())
        best = sorted(counted, key=lambda cols: -closeness(cols))[:want]
        for cols in best:
            d = distinct(list(cols)) if cols in on_sample else counted[cols]
            cols, d = shrink(list(cols), d)
            offer(cols, d, HOW_ALONE if len(cols) == 1 else HOW_CLOSEST.format(n=max_cols))
        others = [c for c in live if not is_unique(alone_count(c), totals)]
        for c in sorted(others, key=lambda c: -selectivity(alone_count(c), totals))[:want]:
            how = (HOW_NULL if nulls_apart and nulls.get(c, 0)
                   else HOW_ONLY if len(pool + measures) <= 1 else HOW_NO_COMBO)
            offer([c], alone_count(c), how)
    for name, _ in sample.values():
        con.execute(f"DROP TABLE IF EXISTS {name}")

    said_pool = (f"the {len(pool)} most key-like columns"
                 + (f" and the {len(measures)} measures" if with_measures else ""))
    steps = [f"every pair of {said_pool}" if tried[2] else
             f"the pairs of {said_pool} - none could be unique, so none was counted"]
    for size in range(3, max_cols + 1):
        if tried[size]:
            steps.append(f"the {tried[size]:,} tightest of {could[size]:,} combinations of {size}"
                         if could[size] > tried[size] else
                         f"the {tried[size]:,} tightest combinations of {size}")
    where = (f" - on a random sample of {KEY_SAMPLE:,} rows first, the ones unique there verified on every row"
             if sample else "")
    if keys:
        note = (f"Found by measuring every column, then {', then '.join(steps)}"
                + where + " - the tightest first, a key ending the level"
                + (" - a measure only once the key-like columns had no key" if with_measures else ""))
    else:
        note = (f"Nothing up to {max_cols} columns is unique - every column, {', '.join(steps)}"
                + where)
    note += " - " + hint
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
    # on a pair the nulls are A's: the side the search counts (suggest_keys)
    said_in = f" in {name_a}" if name_b is not None else ""
    bits.append(("no nulls" if not n_null else f"{n_null:,} nulls") + said_in)
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
    reasons for its place - plus a note on how they were found. The search itself counts
    one side, A: every column, then the combinations, each level on a random sample first
    (see search_keys). What is unique there is verified on B - unique there too, and
    sharing values - and only then is it a key that ends the search; one that fails on B
    is listed but the search goes on. A profile of the same columns supplies the
    single-column figures, so they are not measured twice."""
    say = progress or (lambda _msg: None)
    candidates = [s.canon for s in specs]
    say(f"Reading both sides ({len(candidates)} columns)…")
    con = probe(A, B, specs, opts)
    views = ("probe_a", "probe_b")
    totals = {v: con.execute(f"SELECT count(*) FROM {v}").fetchone()[0] for v in views}
    lead = {"probe_a": totals["probe_a"]}          # the side the search counts; B verifies

    from_profile = {c: profile_singles(profile, c) for c in candidates}
    measure = [c for c in candidates if from_profile[c] is None]
    used_profile = len(measure) < len(candidates)
    say("Reading the profile…" if used_profile else f"Measuring every column of {name_a}…")
    singles, nulls = single_figures(con, ("probe_a",), measure, lead)
    for c, p in from_profile.items():
        if p is not None:
            singles[c] = {"probe_a": p["probe_a"], "probe_b": p["probe_b"]}
            nulls[c] = p["nulls_a"]
    stats = [profile["stats"][w] for w in ("A", "B")
             if profile and isinstance(profile.get("stats"), dict) and w in profile["stats"]]
    hashed = {c for c in could_be_hashed(specs, stats) if looks_hashed(con, "probe_a", c)}
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

    sides = {"probe_a": (A, "A"), "probe_b": (B, "B")}

    def sampler(v: str, name: str, cols: list[str], n: int) -> None:
        """A random n-row sample of a side as a table `name`: the rows drawn from the file,
        the steps and types on those alone."""
        side, which = sides[v]
        register(con, side, name, [s for s in specs if s.canon in cols], which, opts,
                 materialize=True, sample=n)

    b_count: dict[tuple, int] = {}

    def on_b(combos: list[tuple]) -> None:
        """The distinct count on B of combinations the search on A turned up - measured
        once each, a few a statement."""
        todo = [c for c in combos if c not in b_count]
        if todo:
            for cols, n in zip(todo, count_combos(con, "probe_b", todo, totals["probe_b"])):
                b_count[cols] = n

    def verified(combos: list[list[str]]) -> set[frozenset]:
        """Which combinations unique on A end the search: the ones unique on B as well and
        sharing values with it - a key with none pairs no rows. One that is neither is listed
        all the same, but the search goes on to the next level. A whole batch at a time, so B
        is counted a few combinations a statement and not once per candidate."""
        on_b([tuple(c) for c in combos])
        return {frozenset(c) for c in combos
                if b_count[tuple(c)] == totals["probe_b"] and overlap(c) > 0}

    # the levels are counted on A alone - every column, then the combinations - and what is
    # unique there is verified on B: half the counting of measuring both sides at every level
    found, unique_sets, note = search_keys(con, ("probe_a",), lead, candidates, singles, nulls,
                                           affinity, max_cols, want, say,
                                           pairs=verified, sampler=sampler)
    note += f" - counted on {name_a} alone, every candidate verified on {name_b}"
    if used_profile:
        note += " - single-column figures from the profile"

    n_found = len(found)
    found = found[:want * 2]                       # B and the overlap are measured on the best of them
    say(f"Verifying {len(found)} candidate(s) on {name_b}…")
    on_b([tuple(cols) for cols, _, _ in found])
    found = [(cols, {**d, "probe_b": b_count[tuple(cols)]}, how) for cols, d, how in found]
    unique_sets = [frozenset(cols) for cols, d, _ in found if is_unique(d, totals)]
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
    def sampler(v: str, name: str, cols: list[str], n: int) -> None:
        """A random n-row sample of the table as `name`: the rows drawn from the file, the
        steps and types on those alone."""
        register(con, P, name, [s for s in specs if s.canon in cols], "A", opts,
                 materialize=True, sample=n)

    found, unique_sets, note = search_keys(con, views, totals, candidates, singles, nulls,
                                           affinity, max_cols, want, say, nulls_apart=True,
                                           sampler=sampler)
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
