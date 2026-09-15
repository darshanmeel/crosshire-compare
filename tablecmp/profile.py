"""Per-column statistics and value frequencies, on the same typed values the comparison uses."""
from __future__ import annotations

from typing import Any

import pandas as pd

from .sources import Side
from .sql import ident, lit, scratch
from .values import ColSpec, ReadOptions, register


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
    return pd.DataFrame(out)


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


def profile_tables(A: Side, B: Side, specs: list[ColSpec], opts: ReadOptions,
                   progress=None) -> dict:
    say = progress or (lambda _m: None)
    out: dict[str, Any] = {"stats": {}, "freq": {s.canon: {} for s in specs}}
    for side, which in ((A, "A"), (B, "B")):
        say(f"Reading {side.name or which}…")
        con = scratch()
        register(con, side, "prof", specs, which, opts, materialize=True)
        say(f"{side.name or which}: statistics for {len(specs)} columns…")
        out["stats"][which] = stats_table(con, "prof", specs)
        say(f"{side.name or which}: value frequencies…")
        for s in specs:
            out["freq"][s.canon][which] = freq_tables(con, "prof", s.canon)
    return out
