"""What stands out in one table: exact duplicate rows, whether the best key candidate is
unique, which columns determine which, correlated numbers, outliers per number and date
column, the shapes text values take, and one line per column on anything odd - all measured
on the table the profile registered (canonical text per column, read with try_cast the way
the statistics are), plus the raw source for the two checks that need the untrimmed value.

Plain Python, no Streamlit: the page shows the notes as a list and the four tables as
expanders; `profile_single` calls `observe` on the connection it already has.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

import pandas as pd

from .keys import ID_WORDS, MAX_KEY_COLS, combo          # MAX_KEY_COLS: how far the key search grows
from .profile import show
from .sources import Side, source_expr
from .sql import columns_a_statement, ident, lit, memory_limit_bytes
from .values import BYTES_A_CELL, HOLD_SHARE, ColSpec, ReadOptions, fold_nulls, raw_text

OUTLIER_COLS = ["Column", "Type", "P1", "P5", "P25", "Median", "P75", "P95", "P99", "Std dev",
                "Low fence", "High fence", "Outliers", "Outlier %", "Lowest", "Highest",
                "Zeros", "Negatives"]                   # one row per number / date / timestamp column
COUNT_COLS = ["Zeros", "Negatives"]                     # whole numbers, blank on a date row
PATTERN_COLS = ["Column", "Pattern", "Collapsed", "Count", "%", "Example"]
DEP_COLS = ["Determines", "Determined", "Kind", "Distinct"]
CORR_COLS = ["Column A", "Column B", "r"]
QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
Q_COLS = ("P1", "P5", "P25", "Median", "P75", "P95", "P99")     # OUTLIER_COLS[2:9], one per quantile
MAX_DETERMINANTS = 40       # columns tried as a determinant, the fewest values first
SAMPLE_ROWS = 200_000       # rows a dependency is tried on first - one that fails there fails on all
MAX_CORR_COLS = 30          # number columns compared pairwise, the first in table order
MAX_DEP_LINES = 10          # dependency lines in the notes before "… and n more"
MAX_CORR_LINES = 5
MAX_LISTED = 12             # values a category line spells out before "…"
TOP_SHAPES = 3              # shapes kept per text column
MIN_CORR = 0.7              # |r| from which a pair is listed
NEAR_UNIQUE = 99.0          # distinct % of filled from which a column is nearly unique
LETTER = r"\p{L}"           # RE2: a letter in any script
HUGE = 1e150                # a number from here up is left out of the outliers (see measurable)
EPOCH = datetime(1970, 1, 1)


# ---- small helpers ----------------------------------------------------------------------
def n_of(n: int, one: str, many: str | None = None) -> str:
    """'1 outlier', '12 outliers', '1,000 rows'."""
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def num(v) -> str:
    """A number in prose: thousands separators, no trailing .0, two decimals when it has any."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    v = float(v)
    if abs(v) >= 1e15:                       # a 150-digit integer says less than 1.00e+150
        return f"{v:.2e}"
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}" if abs(v) >= 1 else f"{v:.3g}"


def collapse(shape: str) -> str:
    """A shape with its runs folded: AAAA9999 → A+9+, 9999-99-99 → 9+-9+-9+."""
    return re.sub(r"9+", "9+", re.sub(r"A+", "A+", shape))


def shape_sql(v: str) -> str:
    """The shape of a value: every letter (any script) an A, every digit a 9, the rest as is."""
    return f"regexp_replace(regexp_replace({v}, {lit(LETTER)}, 'A', 'g'), '[0-9]', '9', 'g')"


def measurable(s: ColSpec) -> str:
    """The typed value, and whether a quantile, std dev or r can hold it: a number only
    when it is finite and under HUGE (a std dev squares it, and 1e155² is past what a
    double holds), a date or timestamp only when it is finite - `infinity` is a date to
    DuckDB and to a Postgres export. Nulls are neither."""
    c = ident(s.canon)
    if s.kind == "number":
        v = f"try_cast({c} AS DOUBLE)"
        return v, f"isfinite({v}) AND abs({v}) < {HUGE!r}"
    v = f"try_cast({c} AS {s.kind.upper()})"
    return v, f"isfinite({v})"


def typed(s: ColSpec) -> str:
    """The column read as its type, the way the statistics read it, with what cannot be
    measured read as null: NaN, ±inf and astronomically large numbers, infinite dates. They
    are values to the reader, so `outliers` counts them apart and the notes say so."""
    v, ok = measurable(s)
    return f"CASE WHEN {ok} THEN {v} END"


def facts_of(stats: pd.DataFrame) -> dict[str, dict]:
    """Per column, what the notes need from the statistics table - derived from Rows, Nulls
    and Distinct so nothing else in the table is relied on."""
    out = {}
    for _, r in stats.iterrows():
        rows, nulls, distinct = int(r["Rows"]), int(r["Nulls"]), int(r["Distinct"])
        filled = rows - nulls
        out[r["Column"]] = {
            "rows": rows, "nulls": nulls, "filled": filled, "distinct": distinct,
            "shared": max(filled - distinct, 0),                 # rows whose value another row has too
            "share_filled": distinct / filled * 100 if filled else 0.0,
            "share_rows": distinct / rows * 100 if rows else 0.0,
            "unique": rows > 0 and nulls == 0 and distinct == rows,
            "empty": rows > 0 and nulls == rows,
            "constant": distinct == 1,
            "min": r["Min"]}
    return out


# ---- the measures -------------------------------------------------------------------------
def duplicate_rows(con, table: str, cols: list[str]) -> int:
    """Rows that repeat another one in every column, nulls equal. The rows are told apart
    by the MD5 of the row's values joined (keys.combo), 16 bytes a row, not by the values
    themselves: two hundred text columns of a million rows are no hash table to hold."""
    if not cols:
        return 0
    n, d = con.execute(f"SELECT count(*), count(DISTINCT md5_number({combo(cols)})) "
                       f"FROM {table}").fetchone()
    return int(n - d)


def key_line(con, table: str, cols: list[str], rows: int, keys) -> tuple[str, str]:
    """(the note, the headline part) for the best candidate the key search found: unique on
    every row, or the closest with its distinct count. Measured here on the same table, so
    it holds whatever the search's own table says."""
    if keys is None or rows == 0:
        return "", ""
    best = [c for c in (keys[1][0] if keys[1] else []) if c in cols]
    if not best:
        return (f"no single column or combination up to {MAX_KEY_COLS} is unique",
                f"no key up to {MAX_KEY_COLS} columns")
    missing = " OR ".join(f"{ident(k)} IS NULL" for k in best)
    d, nulls = con.execute(
        f"SELECT count(DISTINCT {combo(best)}) FILTER (WHERE NOT ({missing})), "
        f"count(*) FILTER (WHERE {missing}) FROM {table}").fetchone()
    name = " + ".join(best)
    if not nulls and rows - d == 0:
        return f"key: {name} - unique on every row", f"key: {name}"
    return (f"no single column or combination up to {MAX_KEY_COLS} is unique - "
            f"closest: {name} ({d:,} distinct of {rows:,})",
            f"no key up to {MAX_KEY_COLS} columns")


def determined(con, table: str, x: str, ys: list[str], groups: int) -> list[str]:
    """The columns among `ys` that `x` determines on `table`: within every group of x the
    column holds one value (null one value). One pass grouped by x, the min, max and
    count of each y - no hash table per column, as count(DISTINCT) would keep - a few
    columns at a time when x has many groups."""
    out = []
    per = columns_a_statement(groups)
    for i in range(0, len(ys), per):
        part = ys[i:i + per]
        inner = ", ".join(f"min({ident(y)}) AS __mn{j}, max({ident(y)}) AS __mx{j}, "
                          f"count({ident(y)}) AS __c{j}" for j, y in enumerate(part))
        outer = ", ".join(f"bool_and(__mn{j} IS NOT DISTINCT FROM __mx{j} AND (__c{j} = 0 OR __c{j} = __n))"
                          for j in range(len(part)))
        found = con.execute(f"SELECT {outer} FROM (SELECT {ident(x)}, count(*) AS __n, {inner} "
                            f"FROM {table} GROUP BY 1)").fetchone()
        out += [y for y, ok in zip(part, found) if ok]
    return out


def dependencies(con, table: str, cols: list[str], facts: dict[str, dict], rows: int = 0
                 ) -> tuple[pd.DataFrame, list[str]]:
    """Functional dependencies X → Y among the columns: X determines Y when every group of
    X holds one value of Y (null one value). Determinants are the columns that are neither
    unique nor constant nor nearly unique - those determine anything and say nothing - the
    fewest values first, at most MAX_DETERMINANTS; one pass per determinant, grouped by it,
    over every other live column. On a table over SAMPLE_ROWS rows the pass runs first on
    a sample - the first SAMPLE_ROWS rows, fewer when that many would not fit in memory,
    held as a table of their own so the forty passes read it and not the file: a
    dependency that fails there fails on the whole table, so only the ones that hold on
    the sample are tried on every row. A pair that holds both ways is one-to-one and
    listed once, the column first in table order first. Returns the table and the
    determinants the cap left out."""
    order = {c: i for i, c in enumerate(cols)}
    live = [c for c in cols if facts[c]["distinct"] > 1]         # neither constant nor empty
    cands = sorted((c for c in live
                    if not facts[c]["unique"] and facts[c]["share_filled"] < NEAR_UNIQUE),
                   key=lambda c: (facts[c]["distinct"], order[c]))
    cut, cands = cands[MAX_DETERMINANTS:], cands[:MAX_DETERMINANTS]
    sample, n_sample = None, 0
    if rows > SAMPLE_ROWS and cands:
        fits = int(memory_limit_bytes(con) * HOLD_SHARE / BYTES_A_CELL) // max(len(live), 1)
        n_sample = max(1000, min(SAMPLE_ROWS, fits))
        con.execute(f"CREATE OR REPLACE TEMP TABLE __sample AS SELECT "
                    f"{', '.join(ident(c) for c in live)} FROM {table} LIMIT {n_sample}")
        sample = "__sample"

    def holds(x: str, ys: list[str]) -> list[str]:
        if sample and ys:
            ys = determined(con, sample, x, ys, min(facts[x]["distinct"], n_sample))
        return determined(con, table, x, ys, facts[x]["distinct"]) if ys else []

    held = {x: holds(x, [y for y in live if y != x]) for x in cands}     # x -> the ys it determines
    # the other way round, for the pairs that hold: Y -> X makes a pair one-to-one
    back = {y: set(holds(y, [x for x, ys in held.items() if y in ys]))
            for y in {y for ys in held.values() for y in ys}}
    if sample:
        con.execute("DROP TABLE __sample")
    out, seen = [], set()
    for x, ys in held.items():
        for y in ys:
            both = x in back.get(y, ())
            a, b = sorted((x, y), key=order.get) if both else (x, y)
            if both and (a, b) in seen:
                continue
            seen.add((a, b))
            out.append({"Determines": a, "Determined": b,
                        "Kind": "one-to-one" if both else "many-to-one",
                        "Distinct": facts[a]["distinct"]})
    return pd.DataFrame(out, columns=DEP_COLS), cut


def correlations(con, table: str, specs: list[ColSpec]) -> tuple[pd.DataFrame, list[str]]:
    """Pearson's r for every pair of number columns (the first MAX_CORR_COLS in table order),
    one query; pairs with |r| ≥ MIN_CORR, the strongest first. Returns the table and the
    number columns the cap left out."""
    nums = [s for s in specs if s.kind == "number"]
    cut, nums = [s.canon for s in nums[MAX_CORR_COLS:]], nums[:MAX_CORR_COLS]
    pairs = [(a, b) for i, a in enumerate(nums) for b in nums[i + 1:]]
    if not pairs:
        return pd.DataFrame(columns=CORR_COLS), cut
    picks = ", ".join(f"corr({typed(a)}, {typed(b)})" for a, b in pairs)
    found = con.execute(f"SELECT {picks} FROM {table}").fetchone()
    rows = [{"Column A": a.canon, "Column B": b.canon, "r": round(float(r), 3)}
            for (a, b), r in zip(pairs, found)
            if r is not None and math.isfinite(r) and abs(r) >= MIN_CORR]
    rows.sort(key=lambda r: -abs(r["r"]))
    return pd.DataFrame(rows, columns=CORR_COLS), cut


def _seconds(v) -> float | None:
    """A date or timestamp as seconds since 1970, for the fences on dates; None for a value
    DuckDB could not hand over as one (a year beyond 9999 arrives as text)."""
    if isinstance(v, datetime):
        return (v - EPOCH).total_seconds()
    if isinstance(v, date):
        return (datetime(v.year, v.month, v.day) - EPOCH).total_seconds()
    return None


def _whole_second(v):
    """An interpolated timestamp to the nearest second - a quartile between two values
    carries fractions of a second that say nothing."""
    if not isinstance(v, datetime) or not v.microsecond:
        return v
    try:
        return (v + timedelta(microseconds=500_000)).replace(microsecond=0)
    except OverflowError:                       # the last second of 9999
        return v.replace(microsecond=0)


def _as_shown(v, kind: str):
    """A quantile or fence the way the row shows it: numbers rounded like the Mean, a date
    column's timestamps (quantile_cont interpolates) as dates."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if kind == "number":
        return show(round(float(v), 4))
    if kind == "date" and isinstance(v, datetime):
        return show(v.date())
    if kind == "date" and isinstance(v, str):       # beyond year 9999 DuckDB hands over text
        return v.split(" ")[0]
    return show(v)


def _from_seconds(sec: float | None, kind: str):
    """A fence back on the calendar: a date, or a timestamp to the second; None when it lies
    outside the years a date can hold - a quartile on 9999-12-31 or 0001-01-01 does that,
    and the fence is then blank while the counts each side of it still stand."""
    if sec is None:
        return None
    try:
        v = EPOCH + timedelta(seconds=round(sec))
    except (OverflowError, ValueError):
        return None
    return v.date() if kind == "date" else v


def outliers(con, table: str, specs: list[ColSpec]) -> tuple[pd.DataFrame, dict[str, dict]]:
    """One row per number / date / timestamp column: quantiles, Tukey's fences (1.5 × IQR),
    the values outside them, the extremes, zeros and negatives. Dates take the same quantiles
    on the typed value with the fences worked out on epoch seconds and shown as dates; their
    Std dev, Zeros and Negatives are blank. A value that cannot be measured - NaN, infinite,
    astronomically large (see `measurable`) - is left out and counted apart. Alongside the
    table, per column, what the notes need: the counts each side of the fences, the values
    left out, dates after today and before 1900."""
    rows, facts = [], {}
    qs = "[" + ", ".join(str(q) for q in QUANTILES) + "]"
    for s in specs:
        if s.kind not in ("number", "date", "timestamp"):
            continue
        numeric = s.kind == "number"
        c = ident(s.canon)
        raw, ok = measurable(s)
        # the three counts after the std dev: zeros and negatives for a number, values after
        # today and before 1900 for a date; then what could not be measured (see measurable)
        extra = ("stddev_samp(x), count(*) FILTER (WHERE x = 0), count(*) FILTER (WHERE x < 0)"
                 if numeric else
                 "NULL, count(*) FILTER (WHERE x > current_date), "
                 "count(*) FILTER (WHERE x < DATE '1900-01-01')")
        q, lo, hi, n, sd, first, second, bad = con.execute(
            f"SELECT quantile_cont(x, {qs}), min(x), max(x), count(x), {extra}, "
            f"count(*) FILTER (WHERE NOT ({ok})) "
            f"FROM (SELECT {typed(s)} AS x, {c} FROM {table})").fetchone()
        zeros, negs = (int(first), int(second)) if numeric else (0, 0)
        future, old = (0, 0) if numeric else (int(first), int(second))
        q = list(q) if q is not None else [None] * len(QUANTILES)
        p25, p75, x = (q[2], q[4], "x") if numeric else (_seconds(q[2]), _seconds(q[4]), "epoch(x)")
        if s.kind == "timestamp":              # shown to the second, the fences from the exact values
            q = [_whole_second(v) for v in q]
        below = above = 0
        fence_lo = fence_hi = None
        # a float goes into SQL only when it is finite: the quartiles are, or there are no fences
        if p25 is not None and p75 is not None and math.isfinite(p25) and math.isfinite(p75):
            iqr = p75 - p25
            fence_lo, fence_hi = p25 - 1.5 * iqr, p75 + 1.5 * iqr
            below, above = con.execute(
                f"SELECT count(*) FILTER (WHERE {x} < {fence_lo!r}), "
                f"count(*) FILTER (WHERE {x} > {fence_hi!r}) "
                f"FROM (SELECT {typed(s)} AS x FROM {table})").fetchone()
        if not numeric:                       # shown as dates again - blank when off the calendar
            fence_lo, fence_hi = (_from_seconds(f, s.kind) for f in (fence_lo, fence_hi))
        out = int(below + above)
        rows.append({
            "Column": s.canon, "Type": s.kind,
            **{k: _as_shown(v, s.kind) for k, v in zip(Q_COLS, q)},
            "Std dev": _as_shown(sd, "number") if numeric else "",
            "Low fence": _as_shown(fence_lo, s.kind), "High fence": _as_shown(fence_hi, s.kind),
            "Outliers": out, "Outlier %": round(out / n * 100, 2) if n else 0.0,
            "Lowest": _as_shown(lo, s.kind), "Highest": _as_shown(hi, s.kind),
            "Zeros": zeros if numeric else None, "Negatives": negs if numeric else None})
        prose = num if numeric else (lambda v: _as_shown(v, s.kind))   # for the notes
        facts[s.canon] = {
            "outliers": out, "below": int(below), "above": int(above),
            "lo": prose(fence_lo), "hi": prose(fence_hi), "lowest": prose(lo), "highest": prose(hi),
            "zeros": zeros, "negatives": negs, "non_finite": int(bad),
            "future": future, "before_1900": old}
    df = pd.DataFrame(rows, columns=OUTLIER_COLS)
    for k in COUNT_COLS:                          # whole numbers, blank on a date row
        df[k] = pd.to_numeric(df[k], errors="coerce").astype("Int64")
    df["Outliers"] = df["Outliers"].astype("int64")
    df["Outlier %"] = df["Outlier %"].astype("float64")
    return df, facts


def patterns(con, table: str, specs: list[ColSpec]) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Per text column the TOP_SHAPES most common shapes of its non-null values, each with
    its count, share and the smallest value of that shape. Alongside, per column, how many
    shapes there are and - when one shape covers nearly every value - up to three of the
    values that do not fit it."""
    rows, facts = [], {}
    for s in specs:
        if s.kind != "text":
            continue
        c = ident(s.canon)
        df = con.execute(f"""
            WITH s AS (SELECT {c} AS v, {shape_sql(c)} AS shape FROM {table}
                       WHERE {c} IS NOT NULL),
                 g AS (SELECT shape, count(*) AS n, min(v) AS example FROM s GROUP BY shape)
            SELECT shape, n, example, count(*) OVER () AS shapes, sum(n) OVER () AS total
            FROM g ORDER BY n DESC, shape LIMIT {TOP_SHAPES}""").fetchdf()
        if not len(df):
            continue
        total, shapes = int(df["total"].iloc[0]), int(df["shapes"].iloc[0])
        top, top_n = str(df["shape"].iloc[0]), int(df["n"].iloc[0])
        for _, r in df.iterrows():
            rows.append({"Column": s.canon, "Pattern": r["shape"], "Collapsed": collapse(str(r["shape"])),
                         "Count": int(r["n"]), "%": round(int(r["n"]) / total * 100, 2),
                         "Example": str(r["example"])})
        share = top_n / total * 100
        odd = []                    # three distinct values of another shape, a fourth says there are more
        if 90 <= share < 100:
            odd = [str(v) for (v,) in con.execute(
                f"SELECT DISTINCT {c} AS v FROM {table} "
                f"WHERE {c} IS NOT NULL AND {shape_sql(c)} <> {lit(top)} "
                f"ORDER BY v LIMIT 4").fetchall()]
        facts[s.canon] = {"shapes": shapes, "top": top, "share": share, "others": total - top_n,
                          "examples": odd[:3], "more": len(odd) > 3}
    return pd.DataFrame(rows, columns=PATTERN_COLS), facts


def raw_checks(con, side: Side, specs: list[ColSpec], opts: ReadOptions, rows: int = 0
               ) -> dict[str, dict]:
    """The two checks that need the value as the file has it, plus leading zeros, read from
    the source a few columns a statement: per text column the values with leading or
    trailing spaces and whether any differ only in case; per number column the values that
    start with a zero.
    The null tokens are folded first, as the reader folds them, so 'null', ' NULL ' and a
    cell of spaces are not spellings or padded values. A column with case variants is read
    once more for how many spellings are involved and the group with the most of them."""
    text = [s for s in specs if s.kind == "text"]
    nums = [s for s in specs if s.kind == "number"]
    if not text and not nums:
        return {}

    def raw(s: ColSpec) -> str:
        return fold_nulls(raw_text(side, s.a_src), opts.tokens)

    aggs = []
    for s in text:
        v = raw(s)
        aggs += [f"count(*) FILTER (WHERE {v} <> trim({v}))",
                 f"count(DISTINCT {v}) - count(DISTINCT lower({v}))"]
    for s in nums:
        aggs.append(f"count(*) FILTER (WHERE regexp_matches({raw(s)}, '^0[0-9]'))")
    per = 2 * columns_a_statement(rows)                # a text column is two of them
    found = tuple(v for i in range(0, len(aggs), per) for v in con.execute(
        f"SELECT {', '.join(aggs[i:i + per])} FROM {source_expr(side)}").fetchone())
    out: dict[str, dict] = {}
    for i, s in enumerate(text):
        spaces, variants = found[2 * i], found[2 * i + 1]
        rec = {"spaces": int(spaces), "case": None}
        if variants:
            v = raw(s)
            hit = con.execute(f"""
                WITH v AS (SELECT {v} AS v, count(*) AS n FROM {source_expr(side)}
                           WHERE {v} IS NOT NULL GROUP BY 1),
                     g AS (SELECT count(*) AS k, sum(n) AS rows_, list(v ORDER BY n DESC, v) AS spellings
                           FROM v GROUP BY lower(v) HAVING count(*) > 1)
                SELECT (SELECT sum(k) FROM g), spellings FROM g ORDER BY k DESC, rows_ DESC LIMIT 1
            """).fetchone()
            if hit:
                rec["case"] = (int(hit[0]), [str(x) for x in hit[1]][:3])
        out[s.canon] = rec
    for j, s in enumerate(nums):
        out[s.canon] = {"leading_zeros": int(found[2 * len(text) + j])}
    return out


def top_values(con, table: str, col: str, n: int = MAX_LISTED) -> list[str]:
    """The column's non-null values, the most frequent first."""
    c = ident(col)
    return [str(v) for (v,) in con.execute(
        f"SELECT {c} FROM {table} WHERE {c} IS NOT NULL GROUP BY 1 "
        f"ORDER BY count(*) DESC, 1 LIMIT {int(n)}").fetchall()]


# ---- the notes ----------------------------------------------------------------------------
def column_notes(con, table: str, s: ColSpec, f: dict, top: pd.DataFrame, look: str,
                 raw: dict, out: dict | None, pat: dict | None, opts: ReadOptions) -> list[str]:
    """The lines for one column, in the order the spec lists them - each only when it applies."""
    c, notes = s.canon, []
    rows, nulls, distinct = f["rows"], f["nulls"], f["distinct"]
    if f["empty"]:
        return [f"{c}: empty - null on every row"]
    if f["constant"]:
        notes.append(f"{c}: constant - one value on every {'filled ' if nulls else ''}row ({f['min']})")
    null_pct = nulls / rows * 100 if rows else 0.0
    if null_pct >= 5 or (nulls and ID_WORDS.search(c)):
        notes.append(f"{c}: null on {null_pct:.1f}% of rows" if null_pct >= 0.1
                     else f"{c}: null on {n_of(nulls, 'row')} of {rows:,}")
    if f["share_filled"] >= NEAR_UNIQUE and f["shared"]:
        notes.append(f"{c}: nearly unique - {n_of(f['shared'], 'row')} "
                     f"{'shares' if f['shared'] == 1 else 'share'} a value with another")
    elif ID_WORDS.search(c) and not f["unique"] and f["shared"]:
        notes.append(f"{c}: says identifier but {n_of(f['shared'], 'row')} "
                     f"{'shares' if f['shared'] == 1 else 'share'} a value")
    if 2 <= distinct <= 20 and f["share_rows"] <= 50:
        listed = top_values(con, table, c)
        notes.append(f"{c}: {distinct} values - "
                     + ", ".join(listed + (["…"] if distinct > len(listed) else [])))
    if len(top) and distinct > 1:
        head = top.iloc[0]
        pct = int(head["Count"]) / rows * 100 if rows else 0.0
        if pct >= 95 and head["Value"] != "∅ null":
            notes.append(f"{c}: {head['Value']} on {pct:.1f}% of rows")
    if look:                        # the suggestion in its own words - taken, or not
        head, _, detail = look.partition(" · ")
        said = f"{c}: {'read as' if head == s.kind else 'looks like'} a {head}"
        if detail:
            said += f" - {detail}"
        notes.append(said if head == s.kind else f"{said} - read as {s.kind}")
    if raw.get("leading_zeros"):
        n = raw["leading_zeros"]
        notes.append(f"{c}: reads as a number but {n_of(n, 'value')} "
                     f"{'has' if n == 1 else 'have'} leading zeros - keep it as text")
    if raw.get("case"):
        k, spellings = raw["case"]
        notes.append(f"{c}: {n_of(k, 'value')} differ only in case - {' / '.join(spellings)}")
    if raw.get("spaces"):
        n = raw["spaces"]
        notes.append(f"{c}: {n_of(n, 'value')} {'has' if n == 1 else 'have'} leading or trailing "
                     "spaces" + (" - trimmed before measuring" if opts.trim else ""))
    if out and out["outliers"]:     # one side only when the other fence is not crossed; a
        sides, ends = [], ""        # fence off the calendar is not named, the extreme is
        if out["below"]:
            sides += [f"below {out['lo']}"] if out["lo"] else []
            ends += f" · lowest {out['lowest']}"
        if out["above"]:
            sides += [f"above {out['hi']}"] if out["hi"] else []
            ends += f" · highest {out['highest']}"
        where = f" - {' or '.join(sides)}" if sides else ""
        notes.append(f"{c}: {n_of(out['outliers'], 'outlier')}{where} (1.5 × IQR){ends}")
    if out and out.get("non_finite"):
        n = out["non_finite"]
        what = (f"NaN, infinite or beyond {HUGE:g}".replace("e+", "e") if s.kind == "number"
                else "infinite")
        notes.append(f"{c}: {n_of(n, 'value')} {'is' if n == 1 else 'are'} {what} - "
                     "left out of the outliers")
    if out and s.kind == "number" and (out["negatives"] or out["zeros"]):
        bits = ([n_of(out["negatives"], "negative value")] if out["negatives"] else []) \
            + ([n_of(out["zeros"], "zero")] if out["zeros"] else [])
        notes.append(f"{c}: {' · '.join(bits)}")
    if out and s.kind != "number" and (out["future"] or out["before_1900"]):
        bits = ([f"{n_of(out['future'], 'date')} after today"] if out["future"] else []) \
            + ([f"{n_of(out['before_1900'], 'date')} before 1900"] if out["before_1900"] else [])
        notes.append(f"{c}: {' · '.join(bits)}")
    if pat and 90 <= pat["share"] < 100:
        ex = pat["examples"] + (["…"] if pat["more"] else [])
        notes.append(f"{c}: {pat['share']:.1f}% of values are {pat['top']} - "
                     f"{pat['others']:,} {'is' if pat['others'] == 1 else 'are'} not ({', '.join(ex)})")
    return notes


def table_notes(duplicates: int, key: str, deps: pd.DataFrame, cut_deps: list[str],
                corr: pd.DataFrame, cut_corr: list[str], pat: dict[str, dict]) -> list[str]:
    """The table-level lines: duplicates, the key, dependencies, correlations - and where a
    cap cut a list, a line that says so."""
    notes = []
    if duplicates:
        notes.append(f"{n_of(duplicates, 'exact duplicate row')} - the same values in every column")
    if key:
        notes.append(key)
    lines = [f"{x} ↔ {y}: one-to-one" if kind == "one-to-one" else f"{x} → {y}: every {x} has one {y}"
             for x, y, kind in zip(deps["Determines"], deps["Determined"], deps["Kind"])]
    notes += lines[:MAX_DEP_LINES]
    if len(lines) > MAX_DEP_LINES:
        notes.append(f"… and {len(lines) - MAX_DEP_LINES} more in Dependencies")
    if cut_deps:
        notes.append(f"dependencies: only the {MAX_DETERMINANTS} columns with the fewest values "
                     f"were tried as determinants - {len(cut_deps)} more were not")
    lines = [f"{a} ~ {b}: correlated, r = {r:.2f}"
             for a, b, r in zip(corr["Column A"], corr["Column B"], corr["r"])]
    notes += lines[:MAX_CORR_LINES]
    if len(lines) > MAX_CORR_LINES:
        notes.append(f"… and {len(lines) - MAX_CORR_LINES} more")
    if cut_corr:
        notes.append(f"correlations: only the first {MAX_CORR_COLS} number columns were compared - "
                     f"{len(cut_corr)} more were not")
    more = [(c, p["shapes"]) for c, p in pat.items() if p["shapes"] > TOP_SHAPES]
    if more:
        notes.append(f"patterns: the {TOP_SHAPES} most common shapes per column are listed - "
                     "more exist in " + ", ".join(f"{c} ({n:,} shapes)" for c, n in more[:8])
                     + (f", … and {len(more) - 8} more columns" if len(more) > 8 else ""))
    return notes


def headline(rows: int, cols: int, key: str, duplicates: int, facts: dict[str, dict],
             out: dict[str, dict]) -> str:
    """`3,000 rows × 7 columns · key: emp_id · 0 duplicate rows · 1 empty column · …` - the
    zero parts dropped, except the duplicate rows, which are always said."""
    empties = sum(1 for f in facts.values() if f["empty"])
    constants = sum(1 for f in facts.values() if f["constant"] and not f["empty"])
    wild = sum(1 for o in out.values() if o["outliers"])
    bits = [f"{n_of(rows, 'row')} × {n_of(cols, 'column')}"]
    if key:
        bits.append(key)
    bits.append(n_of(duplicates, "duplicate row"))
    if empties:
        bits.append(n_of(empties, "empty column"))
    if constants:
        bits.append(n_of(constants, "constant column"))
    if wild:
        bits.append(n_of(wild, "column with outliers", "columns with outliers"))
    return " · ".join(bits)


def observe(con, table: str, side: Side, specs: list[ColSpec], stats: pd.DataFrame,
            freq: dict[str, tuple[pd.DataFrame, pd.DataFrame]], opts: ReadOptions,
            looks: dict[str, str], keys: tuple[pd.DataFrame, list[list[str]], str] | None,
            say=None) -> dict:
    """Everything that stands out in the table registered on `con`, given its statistics and
    frequency tables: {"notes", "duplicates", "outliers", "patterns", "deps", "corr",
    "headline"} - the notes table-level first, then per column in table order. `keys` is the
    key search's (table, combos, note), or None when there was none; `say` narrates."""
    say = say or (lambda _m: None)
    who = side.name or "A"
    facts = facts_of(stats)
    specs = [s for s in specs if s.canon in facts]
    cols = [s.canon for s in specs]
    rows = facts[cols[0]]["rows"] if cols else 0

    say(f"{who}: duplicate rows and the key…")
    duplicates = duplicate_rows(con, table, cols)
    key, key_part = key_line(con, table, cols, rows, keys)
    say(f"{who}: dependencies…")
    deps, cut_deps = dependencies(con, table, cols, facts, rows)
    say(f"{who}: correlations…")
    corr, cut_corr = correlations(con, table, specs)
    say(f"{who}: outliers…")
    out, out_facts = outliers(con, table, specs)
    say(f"{who}: patterns…")
    pat, pat_facts = patterns(con, table, specs)
    say(f"{who}: leading spaces, case variants, leading zeros…")
    raw = raw_checks(con, side, specs, opts, rows) if rows else {}

    notes = table_notes(duplicates, key, deps, cut_deps, corr, cut_corr, pat_facts)
    for s in specs:
        top = freq.get(s.canon, (pd.DataFrame(), None))[0]
        look = str((looks or {}).get(s.canon, "") or "")
        notes += column_notes(con, table, s, facts[s.canon], top, look, raw.get(s.canon, {}),
                              out_facts.get(s.canon), pat_facts.get(s.canon), opts)
    return {"notes": notes, "duplicates": duplicates, "outliers": out, "patterns": pat,
            "deps": deps, "corr": corr,
            "headline": headline(rows, len(cols), key_part, duplicates, facts, out_facts)}
