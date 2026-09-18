"""Per-column statistics and value frequencies, on the same typed values the comparison uses."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .sources import Side
from .sql import ident, lit, scratch
from .values import ColSpec, ReadOptions, register

STATS_COLS = ["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled",
              "Distinct % of rows", "Top value", "Top %", "Min", "Max", "Mean", "Avg length",
              "Min length", "Max length"]          # the stats table, one row per column
LENGTH_COLS = ["Min length", "Max length"]         # whole numbers, blank on a column with nothing filled


def show(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def label(v: Any) -> str:
    return "∅ null" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def stats_table(con, table: str, specs: list[ColSpec]) -> pd.DataFrame:
    """One row per column, every STATS_COLS column. The distinct share is given both ways -
    of the filled rows and of all rows. Top value / Top % are left blank here: measure_on
    fills them from the frequency tables, which already hold the most frequent value."""
    branches = []
    for s in specs:
        c = ident(s.canon)
        num = f"try_cast({c} AS DOUBLE)"
        branches.append(
            f"SELECT {lit(s.canon)} AS col, count(*) AS n, count({c}) AS filled, "
            f"count(DISTINCT {c}) AS uniq, min({c}) AS min_t, max({c}) AS max_t, "
            f"min({num}) AS min_n, max({num}) AS max_n, avg({num}) AS mean_n, "
            f"round(avg(length({c})), 1) AS avg_len, "
            f"min(length({c})) AS min_len, max(length({c})) AS max_len FROM {table}")
    raw = con.execute(" UNION ALL ".join(branches)).fetchdf()
    kinds = {s.canon: s.kind for s in specs}
    out = []
    for _, r in raw.iterrows():
        n, filled, uniq = int(r["n"]), int(r["filled"]), int(r["uniq"])
        numeric = kinds[r["col"]] == "number"
        out.append({
            "Column": r["col"], "Type": kinds[r["col"]], "Rows": n, "Nulls": n - filled,
            "Null %": round((n - filled) / max(n, 1) * 100, 2),
            "Distinct": uniq,
            "Distinct % of filled": round(uniq / filled * 100, 2) if filled else 0.0,
            "Distinct % of rows": round(uniq / n * 100, 2) if n else 0.0,
            "Top value": "", "Top %": 0.0,
            "Min": show(r["min_n"] if numeric else r["min_t"]),
            "Max": show(r["max_n"] if numeric else r["max_t"]),
            "Mean": show(round(r["mean_n"], 4)) if numeric and pd.notna(r["mean_n"]) else "",
            "Avg length": r["avg_len"],
            "Min length": int(r["min_len"]) if pd.notna(r["min_len"]) else None,
            "Max length": int(r["max_len"]) if pd.notna(r["max_len"]) else None})
    df = pd.DataFrame(out, columns=STATS_COLS)
    for c in LENGTH_COLS:                       # whole numbers, blank where nothing is filled
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def freq_tables(con, table: str, col: str, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(most frequent, least frequent) values of one column, with counts and %."""
    c = ident(col)
    df = con.execute(f"""
        WITH c AS (SELECT {c} AS v, count(*) AS n FROM {table} GROUP BY 1),
             r AS (SELECT v, n,
                          row_number() OVER (ORDER BY n DESC, v) AS top_rk,
                          row_number() OVER (ORDER BY n ASC, v) AS bot_rk,
                          sum(n) OVER () AS total FROM c)
        SELECT v, n, top_rk, bot_rk, total FROM r WHERE top_rk <= {n} OR bot_rk <= {n}
    """).fetchdf()
    total = int(df["total"].iloc[0]) if len(df) else 0

    def shape(sub: pd.DataFrame, rk: str) -> pd.DataFrame:
        sub = sub.sort_values(rk)
        return pd.DataFrame({"Value": sub["v"].map(label),
                             "Count": sub["n"].astype(int).values,
                             "%": (sub["n"] / max(total, 1) * 100).round(2).values})
    return shape(df[df["top_rk"] <= n], "top_rk"), shape(df[df["bot_rk"] <= n], "bot_rk")


def measure_on(con, side: Side, which: str, specs: list[ColSpec], say
               ) -> tuple[pd.DataFrame, dict[str, tuple[pd.DataFrame, pd.DataFrame]]]:
    """The statistics and frequencies of a side already registered on `con` as `prof`:
    (the stats table, {column: (most frequent, least frequent)}). The one place the
    measures are taken - measure reads a side for the pair and profile_single for the
    Profiling page, each on its own connection."""
    say(f"{side.name or which}: statistics for {len(specs)} columns…")
    stats = stats_table(con, "prof", specs)
    say(f"{side.name or which}: value frequencies…")
    freq = {s.canon: freq_tables(con, "prof", s.canon) for s in specs}
    # the most frequent value and its share of all rows head the frequency table already -
    # a null counts as a value there, shown as ∅ null; an empty table has no head
    heads = {c: top.iloc[0] for c, (top, _) in freq.items() if len(top)}
    stats["Top value"] = [heads[c]["Value"] if c in heads else "" for c in stats["Column"]]
    stats["Top %"] = [float(heads[c]["%"]) if c in heads else 0.0 for c in stats["Column"]]
    return stats, freq


def measure(side: Side, which: str, specs: list[ColSpec], opts: ReadOptions, say
            ) -> tuple[pd.DataFrame, dict[str, tuple[pd.DataFrame, pd.DataFrame]]]:
    """One side read once under the shared names, on a scratch connection of its own:
    (the stats table, {column: (most frequent, least frequent)})."""
    say(f"Reading {side.name or which}…")
    con = scratch()
    register(con, side, "prof", specs, which, opts, materialize=True)
    return measure_on(con, side, which, specs, say)


def profile_single(side: Side, specs: list[ColSpec], opts: ReadOptions, progress=None,
                   name: str = "", looks: dict[str, str] | None = None) -> dict:
    """A table on its own - the Profiling page: the statistics and frequencies as `measure`
    takes them, then the candidate keys and what stands out (duplicates, dependencies,
    correlations, outliers, patterns, the raw-text checks), all on one read of the table.
    The specs name the table's own columns on both sides (columns.single_specs), so it is
    read as side A of each; `looks` is what the values looked like (sniff.looks_like), for
    the notes to say what was read as what. Nothing returned holds the connection - the
    dict lives in session state, so it is DataFrames, lists, strings and ints only."""
    from .keys import MAX_KEY_COLS, suggest_keys_single    # local: keys and observe import profile
    from .observe import observe
    say = progress or (lambda _m: None)
    who = side.name or "A"
    say(f"Reading {who}…")
    con = scratch()
    register(con, side, "prof", specs, "A", opts, materialize=True)
    stats, freq = measure_on(con, side, "A", specs, say)
    say("Looking for keys…")
    keys = suggest_keys_single(side, specs, name or who, opts, say, con=con, view="prof", stats=stats,
                               max_cols=MAX_KEY_COLS)
    say("What stands out…")
    out = {"stats": stats, "freq": freq, "specs": [asdict(s) for s in specs], "keys": keys}
    out.update(observe(con, "prof", side, specs, stats, freq, opts, looks or {}, keys, say))
    con.close()
    return out


def profile_tables(A: Side, B: Side, specs: list[ColSpec], opts: ReadOptions,
                   progress=None) -> dict:
    say = progress or (lambda _m: None)
    out: dict[str, Any] = {"stats": {}, "freq": {s.canon: {} for s in specs},
                           "specs": [asdict(s) for s in specs]}      # what it was measured on
    for side, which in ((A, "A"), (B, "B")):
        out["stats"][which], freq = measure(side, which, specs, opts, say)
        for canon, tables in freq.items():
            out["freq"][canon][which] = tables
    ia, ib = out["stats"]["A"].set_index("Column"), out["stats"]["B"].set_index("Column")
    both, notes = [], []
    for s in specs:
        c = s.canon
        if c not in ia.index or c not in ib.index:
            continue
        rec = {"Column": c, "Type": s.kind,
               "Nulls A": int(ia.at[c, "Nulls"]), "Nulls B": int(ib.at[c, "Nulls"]),
               "Distinct A": int(ia.at[c, "Distinct"]), "Distinct B": int(ib.at[c, "Distinct"]),
               "Rows A": int(ia.at[c, "Rows"]), "Rows B": int(ib.at[c, "Rows"]),
               "Min A": ia.at[c, "Min"], "Min B": ib.at[c, "Min"],
               "Max A": ia.at[c, "Max"], "Max B": ib.at[c, "Max"]}
        rec["constant"] = rec["Distinct A"] <= 1 and rec["Distinct B"] <= 1
        rec["empty"] = rec["Nulls A"] == rec["Rows A"] and rec["Nulls B"] == rec["Rows B"]
        if rec["empty"]:
            notes.append(f"{c}: empty on both sides")
        elif rec["constant"]:
            notes.append(f"{c}: constant - one value on each side, never a key")
        elif max(rec["Distinct A"], rec["Distinct B"]) > 2 * max(1, min(rec["Distinct A"], rec["Distinct B"])):
            notes.append(f"{c}: {rec['Distinct A']:,} distinct values on {A.name or 'A'} against "
                         f"{rec['Distinct B']:,} on {B.name or 'B'} - spelled differently, or a different field")
        both.append(rec)
    out["both"] = pd.DataFrame(both)
    out["notes"] = notes
    return out


def profile_singles(profile: dict | None, canon: str) -> dict | None:
    """What the key search needs for one column, from a profile that already measured it:
    distinct count and nulls per side (keyed like the key probe's views), and whether the
    column is constant or empty on both sides."""
    if not profile or "both" not in profile or not len(profile["both"]):
        return None
    hit = profile["both"][profile["both"]["Column"] == canon]
    if not len(hit):
        return None
    r = hit.iloc[0]
    return {"probe_a": int(r["Distinct A"]), "probe_b": int(r["Distinct B"]),
            "nulls_a": int(r["Nulls A"]), "nulls_b": int(r["Nulls B"]),
            "constant": bool(r["constant"]) or bool(r["empty"])}
