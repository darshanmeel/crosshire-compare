"""Per-column statistics and value frequencies, on the same typed values the comparison uses."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .sources import Side
from .sql import ident, lit, scratch
from .values import ColSpec, ReadOptions, register

STATS_COLS = ["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct %", "Min", "Max",
              "Mean", "Avg length"]                # the stats table, one row per column


def show(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def label(v: Any) -> str:
    return "∅ null" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def stats_table(con, table: str, specs: list[ColSpec]) -> pd.DataFrame:
    branches = []
    for s in specs:
        c = ident(s.canon)
        num = f"try_cast({c} AS DOUBLE)"
        branches.append(
            f"SELECT {lit(s.canon)} AS col, count(*) AS n, count({c}) AS filled, "
            f"count(DISTINCT {c}) AS uniq, min({c}) AS min_t, max({c}) AS max_t, "
            f"min({num}) AS min_n, max({num}) AS max_n, avg({num}) AS mean_n, "
            f"round(avg(length({c})), 1) AS avg_len FROM {table}")
    raw = con.execute(" UNION ALL ".join(branches)).fetchdf()
    kinds = {s.canon: s.kind for s in specs}
    out = []
    for _, r in raw.iterrows():
        n, filled = int(r["n"]), int(r["filled"])
        numeric = kinds[r["col"]] == "number"
        out.append({
            "Column": r["col"], "Type": kinds[r["col"]], "Rows": n, "Nulls": n - filled,
            "Null %": round((n - filled) / max(n, 1) * 100, 2),
            "Distinct": int(r["uniq"]),
            "Distinct %": round(int(r["uniq"]) / max(filled, 1) * 100, 2) if filled else 0.0,
            "Min": show(r["min_n"] if numeric else r["min_t"]),
            "Max": show(r["max_n"] if numeric else r["max_t"]),
            "Mean": show(round(r["mean_n"], 4)) if numeric and pd.notna(r["mean_n"]) else "",
            "Avg length": r["avg_len"]})
    return pd.DataFrame(out, columns=STATS_COLS)


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


def measure(side: Side, which: str, specs: list[ColSpec], opts: ReadOptions, say
            ) -> tuple[pd.DataFrame, dict[str, tuple[pd.DataFrame, pd.DataFrame]]]:
    """One side read once under the shared names: (the stats table, {column: (most
    frequent, least frequent)})."""
    say(f"Reading {side.name or which}…")
    con = scratch()
    register(con, side, "prof", specs, which, opts, materialize=True)
    say(f"{side.name or which}: statistics for {len(specs)} columns…")
    stats = stats_table(con, "prof", specs)
    say(f"{side.name or which}: value frequencies…")
    return stats, {s.canon: freq_tables(con, "prof", s.canon) for s in specs}


def profile_single(side: Side, specs: list[ColSpec], opts: ReadOptions, progress=None) -> dict:
    """A table on its own - the Profiling page. The specs name the table's own columns on
    both sides (columns.single_specs), so it is read as side A of each."""
    stats, freq = measure(side, "A", specs, opts, progress or (lambda _m: None))
    return {"stats": stats, "freq": freq, "specs": [asdict(s) for s in specs]}


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
