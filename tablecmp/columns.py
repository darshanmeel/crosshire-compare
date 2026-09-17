"""The column table: every column from either file, the column it pairs with on the
other side, the common name, the Type, the Key and Compare ticks, and Case - a text
pair's own say on case ("ignore" or "exact"; blank follows the global switch).

A column may take part in more than one pair; it has a row of its own only when it
is in none. Transform steps ride along in two hidden JSON columns; the transform
screen edits them. The two "looks like" cells hold what sniff.looks_like made of
each side's values - shown as a suggestion, never applied; `looks` is that dict,
{"A": {column: text}, "B": {...}}, and the caller passes it in.
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Iterable

import pandas as pd

from .sources import Side
from .sql import ident, scratch
from .theme import esc, row_tint
from .values import (CASES, DATE_TYPES, NUMERIC_TYPES, TYPES, ColSpec, ReadOptions, final_kind,
                     register_plain, steps_from_json, steps_json)

MAP_COLS = ["A column", "B column", "Common name", "Type", "Key", "Compare", "Case",
            "Matched by", "A detected", "A looks like", "B detected", "B looks like",
            "A steps", "B steps"]
SHOWN_COLS = MAP_COLS[:12]


def norm_key(name: str) -> str:
    """The common name a column gets by default: case-folded, runs of anything that is
    not a letter or digit (in any script) turned into one underscore."""
    return re.sub(r"[\W_]+", "_", str(name).strip().casefold()).strip("_") or "col"


def suggest_pairs(from_cols: list[str], to_cols: list[str]) -> dict[str, tuple[str, bool]]:
    """Pair columns by squashed-name similarity: {from: (to, confident)}."""
    def squash(x: str) -> str:
        return re.sub(r"[\W_]", "", x.casefold())
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


def _look(looks: dict | None, which: str, col: str) -> str:
    """The looks-like cell: what sniff.looks_like said about the column, if anything."""
    return str((looks or {}).get(which, {}).get(col, "") or "") if col else ""


def _case(value) -> str:
    """The Case cell as one of CASES; anything else is blank."""
    v = str(value or "").strip().lower()
    return v if v in CASES else ""


def _row(a: str, b: str, A: Side, B: Side, name: str = "", matched: str = "",
         key: bool = False, compare: bool | None = None, kind: str | None = None,
         case: str = "", a_steps: str = "[]", b_steps: str = "[]",
         looks: dict | None = None) -> dict:
    ta = A.schema.get(a, "") if a else ""
    tb = B.schema.get(b, "") if b else ""
    paired = bool(a and b)
    return {"A column": a, "B column": b,
            "Common name": name or norm_key(a or b),
            "Type": kind or default_kind(ta, tb),
            "Key": bool(key) and paired,
            "Compare": (paired if compare is None else bool(compare)) and paired,
            "Case": _case(case) if paired else "",
            "Matched by": matched if paired else "",
            "A detected": ta, "A looks like": _look(looks, "A", a),
            "B detected": tb, "B looks like": _look(looks, "B", b),
            "A steps": a_steps, "B steps": b_steps}


def _unique_names(rows: list[dict]) -> None:
    seen: dict[str, int] = {}
    for r in rows:
        base = str(r["Common name"]).strip() or norm_key(r["A column"] or r["B column"])
        n = seen.get(base, 0) + 1
        seen[base] = n
        r["Common name"] = base if n == 1 else f"{base}_{n}"


def build_table(A: Side, B: Side, looks: dict | None = None) -> pd.DataFrame:
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
    rows = [_row(a, pairs[a][0], A, B, matched=pairs[a][1], looks=looks) if a in pairs
            else _row(a, "", A, B, looks=looks) for a in A.columns]
    rows += [_row("", b, A, B, looks=looks) for b in B.columns if b not in used]
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def _sort(rows: list[dict], A: Side, B: Side) -> None:
    """Pairs first in A's order, then A-only, then B-only."""
    order_a = {c: i for i, c in enumerate(A.columns)}
    order_b = {c: i for i, c in enumerate(B.columns)}
    rows.sort(key=lambda r: (0 if r["A column"] and r["B column"] else 1 if r["A column"] else 2,
                             order_a.get(r["A column"], 0), order_b.get(r["B column"], 0)))


def _complete(rows: list[dict], A: Side, B: Side, looks: dict | None = None) -> list[dict]:
    """Pairs as they are, then one one-sided row per column that is in no pair.

    A column may take part in any number of pairs - one full name split into a
    first and a last name, say. A one-sided row for a column that a pair uses, or
    a second one-sided row for the same column, is dropped; a column in no row at
    all gets one. The order of what came in is kept, sorting is the caller's.
    """
    pairs = [r for r in rows if r["A column"] and r["B column"]]
    paired_a = {r["A column"] for r in pairs}
    paired_b = {r["B column"] for r in pairs}
    out = list(pairs)
    for r in rows:
        if r["A column"] and r["B column"]:
            continue
        a, b = r["A column"], r["B column"]
        if (a and a in paired_a) or (b and b in paired_b):
            continue
        out.append(r)
        (paired_a if a else paired_b).add(a or b)
    out += [_row(a, "", A, B, looks=looks) for a in A.columns if a not in paired_a]
    out += [_row("", b, A, B, looks=looks) for b in B.columns if b not in paired_b]
    return out


def normalise(edited: pd.DataFrame, prev: pd.DataFrame, A: Side, B: Side,
              looks: dict | None = None) -> pd.DataFrame:
    """Clean what came back from the editor and keep the table complete and consistent.

    A column may be used in any number of pairs; it has a row of its own only when
    it is in no pair. A row that ends up with nothing on either side disappears; a
    column that ends up in no row gets its own. A row that just changed is marked
    "you", gets Compare ticked and its Type worked out again.
    """
    e = edited.copy()
    for c in ("A column", "B column", "Common name", "Type", "Case", "Matched by",
              "A steps", "B steps"):
        e[c] = e[c].where(e[c].notna(), "").astype(str).str.strip()
    for c in ("Key", "Compare"):
        e[c] = e[c].map(lambda v: bool(v) and not (isinstance(v, float) and pd.isna(v)))
    e["A column"] = e["A column"].where(e["A column"].isin(A.columns), "")
    e["B column"] = e["B column"].where(e["B column"].isin(B.columns), "")
    e["Type"] = e["Type"].where(e["Type"].isin(TYPES), "text")
    e["Case"] = e["Case"].map(_case)

    same_shape = len(e) == len(prev)
    changed_a = {i for i in e.index if same_shape and e.at[i, "A column"] != prev.at[i, "A column"]}
    changed_b = {i for i in e.index if same_shape and e.at[i, "B column"] != prev.at[i, "B column"]}

    rows: list[dict] = []
    for i in e.index:
        a, b = e.at[i, "A column"], e.at[i, "B column"]
        if not a and not b:
            continue
        touched = i in changed_a or i in changed_b
        matched = "you" if touched else e.at[i, "Matched by"]
        kind = None if touched else e.at[i, "Type"]
        rows.append(_row(a, b, A, B, name=e.at[i, "Common name"], matched=matched,
                         key=e.at[i, "Key"], compare=e.at[i, "Compare"] or touched,
                         kind=kind, case=e.at[i, "Case"], a_steps=e.at[i, "A steps"] or "[]",
                         b_steps=e.at[i, "B steps"] or "[]", looks=looks))
    rows = _complete(rows, A, B, looks)
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def shape(cmap: pd.DataFrame) -> list[tuple[str, str]]:
    return list(zip(cmap["A column"], cmap["B column"]))


def specs_from(cmap: pd.DataFrame) -> list[ColSpec]:
    return [ColSpec(canon=str(r["Common name"]), a_src=str(r["A column"]),
                    b_src=str(r["B column"]), kind=str(r["Type"]),
                    a_steps=steps_from_json(r["A steps"]), b_steps=steps_from_json(r["B steps"]),
                    case=_case(r["Case"]))
            for _, r in cmap.iterrows() if r["A column"] and r["B column"]]


def suggested_steps(kind: str, detail: str) -> list[dict]:
    """The step that takes a looks-like suggestion: the thousands separators a number
    carries, the spelling a date or timestamp is in - none for ISO, a boolean or plain text."""
    if kind == "number" and "thousands separators" in detail:
        return [{"op": "remove thousands separators", "params": {}}]
    fmt = detail.rpartition(" → ")[2] if kind in ("date", "timestamp") else ""
    return [{"op": f"to {kind}", "params": {"fmt": fmt}}] if fmt.startswith("%") else []


def single_specs(side: Side, looks: dict[str, str] | None = None) -> list[ColSpec]:
    """One spec per column of a table on its own - the Profiling page: the column is the
    common name and both sources, its Type the detected one. There is no table to take a
    looks-like suggestion in, so one is taken here: its type, and the step that reads it."""
    out = []
    for col, det in side.schema.items():
        kind, steps = default_kind(det, det), []
        head, _, detail = str((looks or {}).get(col, "") or "").partition(" · ")
        if head in TYPES:
            kind, steps = head, suggested_steps(head, detail)
        out.append(ColSpec(canon=col, a_src=col, b_src=col, kind=kind,
                           a_steps=steps, b_steps=list(steps)))
    return out


def table_keys(cmap: pd.DataFrame) -> list[str]:
    return [str(r["Common name"]) for _, r in cmap.iterrows()
            if r["A column"] and r["B column"] and r["Key"]]


def table_compare(cmap: pd.DataFrame) -> list[str]:
    return [str(r["Common name"]) for _, r in cmap.iterrows()
            if r["A column"] and r["B column"] and r["Compare"] and not r["Key"]]


def only_in(cmap: pd.DataFrame, which: str) -> list[str]:
    own, other = ("A column", "B column") if which == "A" else ("B column", "A column")
    return [str(r[own]) for _, r in cmap.iterrows() if r[own] and not r[other]]


def roles(cmap: pd.DataFrame, name_a: str, name_b: str) -> pd.Series:
    """What each row is, in a word or two: "key", "compared", "not compared", or "only in
    HR" for a column with no counterpart - aligned to the table's index."""
    def role(r) -> str:
        if r["A column"] and r["B column"]:
            return "key" if r["Key"] else "compared" if r["Compare"] else "not compared"
        return f"only in {name_a if r['A column'] else name_b}"
    return pd.Series([role(r) for _, r in cmap.iterrows()], index=cmap.index, dtype=object)


def role_tone(role: str) -> str:
    """The colour a role is drawn in: "pos" (green) for a key, "neg" (red) for a row that
    takes no part in the comparison, "" for a compared column."""
    return "pos" if role == "key" else "" if role == "compared" else "neg"


def row_css(row: pd.Series) -> list[str]:
    """The Styler's say on one row of a table with a Role column - the column table, the
    Summary tab's ledger: the role's tint in every cell."""
    return [row_tint(role_tone(row["Role"]))] * len(row)


def chip(text: str, cls: str = "") -> str:
    """One chip of a strip: plain, "key" (green) or "off" (red)."""
    return f'<span class="chip{" " + cls if cls else ""}">{esc(text)}</span>'


def chip_strip(chips: Iterable[str]) -> str:
    return f'<div class="chips">{"".join(chips)}</div>'


def chips_html(cmap: pd.DataFrame, name_a: str, name_b: str) -> str:
    """The strip under the table: one chip per row - green for a key, plain for a compared
    column, red with the reason for a column that is not compared or only in one file."""
    chips = []
    for (_, r), role in zip(cmap.iterrows(), roles(cmap, name_a, name_b)):
        paired = bool(r["A column"] and r["B column"])
        name = r["Common name"] if paired else (r["A column"] or r["B column"])
        cls = {"pos": "key", "neg": "off"}.get(role_tone(role), "")
        chips.append(chip(f"{name} · {role}" if cls == "off" else name, cls))
    return chip_strip(chips)


def key_chips_html(keys: list[str]) -> str:
    """The key columns as a strip of green chips - the Key block at the top of the Summary tab."""
    return chip_strip(chip(k, "key") for k in keys)


def reused(specs: list[ColSpec], name_a: str, name_b: str) -> list[str]:
    """Each source column in more than one pair: 'name used 2 times on the Right'."""
    out = []
    for which, name in (("A", name_a), ("B", name_b)):
        counts: dict[str, int] = {}
        for s in specs:
            counts[s.src(which)] = counts.get(s.src(which), 0) + 1
        out += [f"{c} used {n} times on the {name}" for c, n in counts.items() if n > 1]
    return out


def set_steps(cmap: pd.DataFrame, canon: str, which: str, steps: list) -> None:
    cmap.loc[cmap["Common name"] == canon, f"{which} steps"] = steps_json(steps)


def mapping_json(cmap: pd.DataFrame) -> str:
    cols = [{"a": r["A column"], "b": r["B column"], "name": r["Common name"],
             "type": r["Type"], "key": bool(r["Key"]), "compare": bool(r["Compare"]),
             "case": _case(r["Case"]),
             "a_steps": steps_from_json(r["A steps"]), "b_steps": steps_from_json(r["B steps"])}
            for _, r in cmap.iterrows() if r["A column"] and r["B column"]]
    return json.dumps({"columns": cols}, indent=2)


def apply_mapping_json(text: str, A: Side, B: Side, looks: dict | None = None) -> pd.DataFrame:
    """Every pair in the file whose columns both exist - a column may appear in several -
    then a row of its own for each column no pair uses."""
    data = json.loads(text)
    rows = []
    seen: set[tuple] = set()
    for r in data.get("columns", []):
        a, b = r.get("a", ""), r.get("b", "")
        same = (a, b, steps_json(r.get("a_steps") or []), steps_json(r.get("b_steps") or []))
        if a in A.columns and b in B.columns and same not in seen:     # the same pair twice adds nothing
            seen.add(same)
            rows.append(_row(a, b, A, B, name=str(r.get("name") or ""), matched="file",
                             key=bool(r.get("key")), compare=r.get("compare", True),
                             kind=r.get("type") if r.get("type") in TYPES else None,
                             case=r.get("case", ""), a_steps=steps_json(r.get("a_steps") or []),
                             b_steps=steps_json(r.get("b_steps") or []), looks=looks))
    rows = _complete(rows, A, B, looks)
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)


def fill_looks(cmap: pd.DataFrame, looks: dict | None) -> pd.DataFrame:
    """The two looks-like columns from the dict - for a table built without it, Auto's say."""
    out = cmap.copy()
    for which in ("A", "B"):
        out[f"{which} looks like"] = [_look(looks, which, c) for c in out[f"{which} column"]]
    return out


def untaken(cmap: pd.DataFrame, name_a: str, name_b: str) -> list[tuple[str, str]]:
    """Each suggestion on a pair whose Type is something else and whose side has no
    conversion step: (common name, 'Right looks like date (06-Nov-2019 → %d-%b-%Y) - read as text')."""
    out = []
    for _, r in cmap.iterrows():
        if not (r["A column"] and r["B column"]):
            continue
        for which, name in (("A", name_a), ("B", name_b)):
            kind, _, detail = str(r[f"{which} looks like"] or "").partition(" · ")
            if not kind or kind == r["Type"] or final_kind(steps_from_json(r[f"{which} steps"])):
                continue
            out.append((str(r["Common name"]), f"{name} looks like {kind}"
                        + (f" ({detail})" if detail else "") + f" - read as {r['Type']}"))
    return out


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
                None, re.sub(r"[\W_]", "", ca.casefold()),
                re.sub(r"[\W_]", "", cb.casefold())).ratio()
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
              matched: str = "data", looks: dict | None = None) -> pd.DataFrame:
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
        ra.update(_row(a, b, A, B, name=ra["Common name"], matched=matched, key=ra["Key"],
                       compare=True, case=ra["Case"], a_steps=ra["A steps"], b_steps="[]",
                       looks=looks))
    _sort(rows, A, B)
    _unique_names(rows)
    return pd.DataFrame(rows, columns=MAP_COLS)
