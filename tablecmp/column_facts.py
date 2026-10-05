"""A short profile of some columns of any set of rows - the facts the Compare page's extended
column profile shows for a bucket (the rows that differ, the rows only one side has): nulls,
distinct values, the top value, the range of a number or a date, the length of text, its
shapes, its common first and last characters and the values spelled two ways. A plain function
over a DuckDB relation and its column names - no run, no workspace - so any page can ask it of
any rows. No n-grams and no parts: the rows a bucket holds are few, the facts should be quick."""
from __future__ import annotations

from .sql import ident
from .web.routes_col_text import by_fingerprint

TOP = 3                 # shapes, first and last characters listed
ENDS = 3                # characters a value's start and end are read on
CATEGORY = 20           # distinct values up to which a column is a category - no starts or ends
SPELL_CAP = 2000        # most frequent values the spellings are looked for among


def _pct(n: int, of: int) -> float:
    return round(n * 100.0 / of, 2) if of else 0.0


def _tops(con, rel: str, expr: str, total: int, where: str = "") -> list[dict]:
    rows = con.execute(f"SELECT {expr} AS k, count(*) AS n FROM {rel} WHERE v IS NOT NULL {where} "
                       f"GROUP BY k ORDER BY n DESC, k LIMIT {TOP}").fetchall()
    return [{"value": str(k), "n": int(n), "pct": _pct(int(n), total)} for k, n in rows]


def column_facts(con, rel: str, columns: list[str]) -> dict[str, dict]:
    """{column: {rows, nulls, null_pct, distinct, top, length, number, date, shapes, prefixes,
    suffixes, spellings}} for each column of `rel` - one pass for the counts of every column,
    then a few small group-bys per column. A blank value counts as null; values are read as
    text, a number or a date only when every filled one reads as one."""
    if not columns:
        return {}
    r = ident(rel)
    aggs = []
    for c in columns:
        v = f"nullif(trim(CAST({ident(c)} AS VARCHAR)), '')"
        aggs += [f"count({v})", f"count(DISTINCT {v})", f"min(length({v}))", f"max(length({v}))",
                 f"count(try_cast({v} AS DOUBLE))", f"min(try_cast({v} AS DOUBLE))",
                 f"max(try_cast({v} AS DOUBLE))", f"avg(try_cast({v} AS DOUBLE))",
                 f"count(try_cast({v} AS TIMESTAMP))", f"min(try_cast({v} AS TIMESTAMP))",
                 f"max(try_cast({v} AS TIMESTAMP))"]
    got = con.execute(f"SELECT count(*), {', '.join(aggs)} FROM {r}").fetchone()
    rows, out = int(got[0]), {}
    for i, c in enumerate(columns):
        (filled, distinct, lmin, lmax, nnum, nlo, nhi, nmean, nts, tlo, thi) = got[1 + 11 * i: 12 + 11 * i]
        filled, distinct = int(filled), int(distinct)
        f = {"rows": rows, "nulls": rows - filled, "null_pct": _pct(rows - filled, rows), "distinct": distinct,
             "top": None, "length": None, "number": None, "date": None,
             "shapes": [], "prefixes": [], "suffixes": [], "spellings": []}
        out[c] = f
        if not filled:
            continue
        number = int(nnum) == filled
        date = not number and int(nts) == filled
        if number:
            f["number"] = {"min": float(nlo), "max": float(nhi), "mean": round(float(nmean), 4)}
        elif date:
            f["date"] = {"min": str(tlo), "max": str(thi)}
        else:
            f["length"] = {"min": int(lmin), "max": int(lmax)}
        con.execute(f"CREATE OR REPLACE TEMP VIEW __cf AS SELECT nullif(trim(CAST({ident(c)} AS VARCHAR)), '') AS v FROM {r}")
        values = con.execute(f"SELECT v, count(*) AS n FROM __cf WHERE v IS NOT NULL GROUP BY v "
                             f"ORDER BY n DESC, v LIMIT {SPELL_CAP}").fetchall()
        f["top"] = {"value": str(values[0][0]), "n": int(values[0][1]), "pct": _pct(int(values[0][1]), rows)}
        if number or date:
            continue
        shape = "regexp_replace(regexp_replace(v, '[A-Za-z]', 'A', 'g'), '[0-9]', '9', 'g')"
        f["shapes"] = [{"shape": t["value"], "n": t["n"], "pct": t["pct"]} for t in _tops(con, "__cf", shape, filled)]
        if distinct > CATEGORY:
            f["prefixes"] = _tops(con, "__cf", f"left(v, {ENDS})", filled, f"AND length(v) > {ENDS}")
            f["suffixes"] = _tops(con, "__cf", f"right(v, {ENDS})", filled, f"AND length(v) > {ENDS}")
        f["spellings"] = [{"members": [m["value"] for m in g["members"]], "rows": g["rows"], "why": g["why"]}
                          for g in by_fingerprint([{"value": str(x), "n": int(n)} for x, n in values])]
    con.execute("DROP VIEW IF EXISTS __cf")
    return out
