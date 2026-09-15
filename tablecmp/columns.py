"""The column table: every column from either file, the column it pairs with on the
other side, the common name, the Type, the Key and Compare ticks.

Transform steps ride along in two hidden JSON columns; the transform screen edits them.
"""
from __future__ import annotations

import difflib
import json
import re

import pandas as pd

from .sources import Side
from .sql import ident, scratch
from .values import (DATE_TYPES, NUMERIC_TYPES, TYPES, ColSpec, ReadOptions, register_plain,
                     steps_from_json, steps_json)

MAP_COLS = ["A column", "B column", "Common name", "Type", "Key", "Compare",
            "Matched by", "A detected", "B detected", "A steps", "B steps"]
SHOWN_COLS = MAP_COLS[:9]


def norm_key(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_") or "col"


def suggest_pairs(from_cols: list[str], to_cols: list[str]) -> dict[str, tuple[str, bool]]:
    """Pair columns by squashed-name similarity: {from: (to, confident)}."""
    def squash(x: str) -> str:
        return re.sub(r"[^0-9a-z]", "", x.lower())
    pool = {c: squash(c) for c in to_cols}
    out: dict[str, tuple[str, bool]] = {}
    used: set[str] = set()
    for f in sorted(from_cols, key=lambda x: -len(x)):
        key = squash(f)
        free = {c: sq for c, sq in pool.items() if c not in used}
        if not free:
            break
        exact = [c for c, sq in free.items() if sq == key]
        if exact:
            out[f] = (exact[0], True)
            used.add(exact[0])
            continue
        score, best = max((difflib.SequenceMatcher(None, key, sq).ratio(), c)
                          for c, sq in free.items())
        if score >= 0.6:
            out[f] = (best, score >= 0.82)
            used.add(best)
    return out


def default_kind(type_a: str, type_b: str) -> str:
    """The type to read a pair as, from what DuckDB sniffed in the two files."""
    ta, tb = type_a.upper(), type_b.upper()

    def isnum(t): return any(x in t for x in NUMERIC_TYPES)
    def isdate(t): return any(x in t for x in DATE_TYPES)
    def isbool(t): return "BOOL" in t
    if isdate(ta) or isdate(tb):
        return "timestamp" if any("TIME" in t for t in (ta, tb)) else "date"
    if isbool(ta) and isbool(tb):
        return "boolean"
    if isnum(ta) or isnum(tb):
        return "number"
    return "text"


def _row(a: str, b: str, A: Side, B: Side, name: str = "", matched: str = "",
         key: bool = False, compare: bool | None = None, kind: str | None = None,
         a_steps: str = "[]", b_steps: str = "[]") -> dict:
    ta = A.schema.get(a, "") if a else ""
    tb = B.schema.get(b, "") if b else ""
    paired = bool(a and b)
    return {"A column": a, "B column": b,
            "Common name": name or norm_key(a or b),
            "Type": kind or default_kind(ta, tb),
            "Key": bool(key) and paired,
            "Compare": (paired if compare is None else bool(compare)) and paired,
            "Matched by": matched if paired else "",
            "A detected": ta, "B detected": tb,
            "A steps": a_steps, "B steps": b_steps}


def _unique_names(rows: list[dict]) -> None:
    seen: dict[str, int] = {}
    for r in rows:
        base = str(r["Common name"]).strip() or norm_key(r["A column"] or r["B column"])
        n = seen.get(base, 0) + 1
        seen[base] = n
        r["Common name"] = base if n == 1 else f"{base}_{n}"


def build_table(A: Side, B: Side) -> pd.DataFrame:
    """Every A column paired by name where possible, then every B column left over."""
    b_by_norm: dict[str, str] = {}
    for c in B.columns:
        b_by_norm.setdefault(norm_key(c), c)
    used: set[str] = set()
    pairs: dict[str, tuple[str, str]] = {}
    for a in A.columns:
        b = b_by_norm.get(norm_key(a), "")
        if b in used:
            b = ""
        if b:
            used.add(b)
            pairs[a] = (b, "name")
    spare_a = [a for a in A.columns if a not in pairs]
    spare_b = [c for c in B.columns if c not in used]
    for a, (b, confident) in suggest_pairs(spare_a, spare_b).items():
        pairs[a] = (b, "similar name" if confident else "guess - check")
        used.add(b)
    rows = [_row(a, pairs[a][0], A, B, matched=pairs[a][1]) if a in pairs
            else _row(a, "", A, B) for a in A.columns]
    rows += [_row("", b, A, B) for b in B.columns if b not in used]
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def _sort(rows: list[dict], A: Side, B: Side) -> None:
    """Pairs first in A's order, then A-only, then B-only."""
    order_a = {c: i for i, c in enumerate(A.columns)}
    order_b = {c: i for i, c in enumerate(B.columns)}
    rows.sort(key=lambda r: (0 if r["A column"] and r["B column"] else 1 if r["A column"] else 2,
                             order_a.get(r["A column"], 0), order_b.get(r["B column"], 0)))


def normalise(edited: pd.DataFrame, prev: pd.DataFrame, A: Side, B: Side) -> pd.DataFrame:
    """Clean what came back from the editor and keep the table complete and consistent.

    Every column of A and of B appears in exactly one row. When the same column is
    picked in two rows, the row that just changed wins. A row that ends up with
    nothing on either side disappears; a column that ends up in no row gets its own.
    """
    e = edited.copy()
    for c in ("A column", "B column", "Common name", "Type", "Matched by",
              "A steps", "B steps"):
        e[c] = e[c].where(e[c].notna(), "").astype(str).str.strip()
    for c in ("Key", "Compare"):
        e[c] = e[c].map(lambda v: bool(v) and not (isinstance(v, float) and pd.isna(v)))
    e["A column"] = e["A column"].where(e["A column"].isin(A.columns), "")
    e["B column"] = e["B column"].where(e["B column"].isin(B.columns), "")
    e["Type"] = e["Type"].where(e["Type"].isin(TYPES), "text")

    same_shape = len(e) == len(prev)
    changed_a = {i for i in e.index if same_shape and e.at[i, "A column"] != prev.at[i, "A column"]}
    changed_b = {i for i in e.index if same_shape and e.at[i, "B column"] != prev.at[i, "B column"]}

    def winners(col: str, changed: set) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in e.index:
            v = e.at[i, col]
            if not v:
                continue
            if v not in out or (i in changed and out[v] not in changed):
                out[v] = i
        return out

    keep_a, keep_b = winners("A column", changed_a), winners("B column", changed_b)
    rows: list[dict] = []
    for i in e.index:
        a = e.at[i, "A column"] if keep_a.get(e.at[i, "A column"]) == i else ""
        b = e.at[i, "B column"] if keep_b.get(e.at[i, "B column"]) == i else ""
        if not a and not b:
            continue
        touched = i in changed_a or i in changed_b
        matched = "you" if touched else e.at[i, "Matched by"]
        kind = None if touched else e.at[i, "Type"]
        rows.append(_row(a, b, A, B, name=e.at[i, "Common name"], matched=matched,
                         key=e.at[i, "Key"], compare=e.at[i, "Compare"] or touched,
                         kind=kind, a_steps=e.at[i, "A steps"] or "[]",
                         b_steps=e.at[i, "B steps"] or "[]"))
    have_a = {r["A column"] for r in rows if r["A column"]}
    have_b = {r["B column"] for r in rows if r["B column"]}
    rows += [_row(a, "", A, B) for a in A.columns if a not in have_a]
    rows += [_row("", b, A, B) for b in B.columns if b not in have_b]
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def shape(cmap: pd.DataFrame) -> list[tuple[str, str]]:
    return list(zip(cmap["A column"], cmap["B column"]))


def specs_from(cmap: pd.DataFrame) -> list[ColSpec]:
    return [ColSpec(canon=str(r["Common name"]), a_src=str(r["A column"]),
                    b_src=str(r["B column"]), kind=str(r["Type"]),
                    a_steps=steps_from_json(r["A steps"]), b_steps=steps_from_json(r["B steps"]))
            for _, r in cmap.iterrows() if r["A column"] and r["B column"]]


def table_keys(cmap: pd.DataFrame) -> list[str]:
    return [str(r["Common name"]) for _, r in cmap.iterrows()
            if r["A column"] and r["B column"] and r["Key"]]


def table_compare(cmap: pd.DataFrame) -> list[str]:
    return [str(r["Common name"]) for _, r in cmap.iterrows()
            if r["A column"] and r["B column"] and r["Compare"] and not r["Key"]]


def only_in(cmap: pd.DataFrame, which: str) -> list[str]:
    own, other = ("A column", "B column") if which == "A" else ("B column", "A column")
    return [str(r[own]) for _, r in cmap.iterrows() if r[own] and not r[other]]


def set_steps(cmap: pd.DataFrame, canon: str, which: str, steps: list) -> None:
    cmap.loc[cmap["Common name"] == canon, f"{which} steps"] = steps_json(steps)


def mapping_json(cmap: pd.DataFrame) -> str:
    cols = [{"a": r["A column"], "b": r["B column"], "name": r["Common name"],
             "type": r["Type"], "key": bool(r["Key"]), "compare": bool(r["Compare"]),
             "a_steps": steps_from_json(r["A steps"]), "b_steps": steps_from_json(r["B steps"])}
            for _, r in cmap.iterrows() if r["A column"] and r["B column"]]
    return json.dumps({"columns": cols}, indent=2)


def apply_mapping_json(text: str, A: Side, B: Side) -> pd.DataFrame:
    data = json.loads(text)
    rows = []
    used_a: set[str] = set()
    used_b: set[str] = set()
    for r in data.get("columns", []):
        a, b = r.get("a", ""), r.get("b", "")
        if a in A.columns and b in B.columns and a not in used_a and b not in used_b:
            used_a.add(a)
            used_b.add(b)
            rows.append(_row(a, b, A, B, name=str(r.get("name") or ""), matched="file",
                             key=bool(r.get("key")), compare=r.get("compare", True),
                             kind=r.get("type") if r.get("type") in TYPES else None,
                             a_steps=steps_json(r.get("a_steps") or []),
                             b_steps=steps_json(r.get("b_steps") or [])))
    rows += [_row(a, "", A, B) for a in A.columns if a not in used_a]
    rows += [_row("", b, A, B) for b in B.columns if b not in used_b]
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def _value_set(series: pd.Series, cap: int = 20000) -> set[str]:
    vals = {str(v).strip().lower() for v in series.dropna().unique()}
    vals.discard("")
    return set(list(vals)[:cap])


def match_columns_by_data(A: Side, B: Side, spare_a: list[str], spare_b: list[str],
                          name_a: str, name_b: str, opts: ReadOptions, sample: int = 5000
                          ) -> tuple[pd.DataFrame, dict[str, str]]:
    """Pair leftover columns by what is in them, whatever they are called."""
    if not spare_a or not spare_b:
        return pd.DataFrame(), {}
    con = scratch()
    register_plain(con, A, "probe_a", spare_a, opts)
    register_plain(con, B, "probe_b", spare_b, opts)

    def sample_of(view: str, cols: list[str]) -> pd.DataFrame:
        picks = ", ".join(ident(c) for c in cols)
        return con.execute(f"SELECT {picks} FROM {view} LIMIT {int(sample)}").fetchdf()

    sa, sb = sample_of("probe_a", spare_a), sample_of("probe_b", spare_b)
    sets_a = {c: _value_set(sa[c]) for c in spare_a}
    sets_b = {c: _value_set(sb[c]) for c in spare_b}
    scored = []
    for ca, va in sets_a.items():
        for cb, vb in sets_b.items():
            if len(va) < 2 or len(vb) < 2:
                continue
            shared = va & vb
            if len(shared) < 2:
                continue
            containment = len(shared) / min(len(va), len(vb))
            jaccard = len(shared) / len(va | vb)
            name_bonus = difflib.SequenceMatcher(
                None, re.sub(r"[^a-z0-9]", "", ca.lower()),
                re.sub(r"[^a-z0-9]", "", cb.lower())).ratio()
            scored.append((containment + 0.15 * jaccard + 0.1 * name_bonus,
                           containment, jaccard, name_bonus, ca, cb, shared))
    scored.sort(reverse=True, key=lambda r: r[0])
    used_a: set[str] = set()
    used_b: set[str] = set()
    rows, mapping = [], {}
    for _, cont, jac, nb, ca, cb, shared in scored:
        if ca in used_a or cb in used_b or cont < 0.6:
            continue
        used_a.add(ca)
        used_b.add(cb)
        mapping[ca] = cb
        rows.append({f"{name_a} column": ca, f"{name_b} column": cb,
                     "Values in common": f"{cont * 100:.0f}%",
                     "Overall overlap": f"{jac * 100:.0f}%",
                     "Name similarity": f"{nb * 100:.0f}%",
                     "Examples": ", ".join(sorted(shared)[:3])})
    return pd.DataFrame(rows), mapping


def pair_rows(cmap: pd.DataFrame, found: dict[str, str], A: Side, B: Side,
              matched: str = "data") -> pd.DataFrame:
    """Put the pairs found by data or by Auto into the table."""
    rows = cmap.to_dict("records")
    for a, b in found.items():
        ra = next((r for r in rows if r["A column"] == a), None)
        rb = next((r for r in rows if r["B column"] == b), None)
        if ra is None or rb is None:
            continue
        if ra is rb:
            continue
        if rb["A column"]:                      # b already paired elsewhere: leave it
            continue
        rows.remove(rb)
        ra.update(_row(a, b, A, B, name=ra["Common name"], matched=matched,
                       key=ra["Key"], compare=True, a_steps=ra["A steps"], b_steps="[]"))
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)
