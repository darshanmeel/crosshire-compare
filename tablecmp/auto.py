"""Two files in, the rest worked out. Brute force: several passes over both files."""
from __future__ import annotations

import re

import pandas as pd

from .columns import build_table, match_columns_by_data, pair_rows, set_steps, specs_from
from .keys import probe, suggest_keys
from .sources import Side
from .sql import ident, lit, scratch
from .values import DATE_TYPES, FALLBACK_FORMATS, ColSpec, ReadOptions, fold_nulls, raw_text
from .sources import source_expr

DATEY = re.compile(r"date|day|time|stamp|_dt$|_at$|^dt_|period|month|year", re.I)
PROBE_ROWS = 50_000


def probe_types(side: Side, specs: list[ColSpec], which: str, opts: ReadOptions
                ) -> dict[str, dict[str, int]]:
    """One pass over the first PROBE_ROWS rows: how many values of each column read as
    a number, a number once commas go, an ISO date, d/m/y, m/d/y, any known date
    spelling, a date with a time of day, or a boolean."""
    fl = "[" + ", ".join(lit(f) for f in FALLBACK_FORMATS) + "]"
    aggs, names = [], []
    for sp in specs:
        t = f"trim({fold_nulls(raw_text(side, sp.src(which)), opts.tokens)})"
        ts = f"coalesce(try_cast({t} AS TIMESTAMP), try_strptime({t}, {fl}))"
        aggs += [f"count({t})",
                 f"count(try_cast({t} AS DOUBLE))",
                 f"count(try_cast(replace({t}, ',', '') AS DOUBLE))",
                 f"count(try_cast({t} AS TIMESTAMP))",
                 f"count(try_strptime({t}, '%d/%m/%Y'))",
                 f"count(try_strptime({t}, '%m/%d/%Y'))",
                 f"count({ts})",
                 f"count(*) FILTER (WHERE CAST({ts} AS TIME) <> TIME '00:00:00')",
                 f"count(try_cast({t} AS BOOLEAN))"]
        names.append(sp.canon)
    row = scratch().execute(f"SELECT {', '.join(aggs)} FROM (SELECT * FROM {source_expr(side)} "
                            f"LIMIT {PROBE_ROWS})").fetchone()
    keys = ("n", "num", "num_nc", "iso", "dmy", "mdy", "anydate", "has_time", "bool")
    return {c: dict(zip(keys, (int(v) for v in row[9 * i: 9 * i + 9])))
            for i, c in enumerate(names)}


def decide_type(sp: ColSpec, pa: dict[str, int], pb: dict[str, int],
                det_a: str, det_b: str) -> tuple[str, list, list, str]:
    """(kind, steps for A, steps for B, why) from what the two sides hold."""
    def ok(p, k):
        return p["n"] > 0 and p[k] / p["n"] >= 0.98

    if pa["n"] == 0 or pb["n"] == 0:
        return "text", [], [], f"{sp.canon}: empty on {'both sides' if not (pa['n'] or pb['n']) else 'one side'} - left as text"
    datey = bool(DATEY.search(sp.canon)) or any(
        d in det for det in (det_a.upper(), det_b.upper()) for d in DATE_TYPES)
    num_ok = ok(pa, "num") and ok(pb, "num")
    num_nc_ok = ok(pa, "num_nc") and ok(pb, "num_nc")
    date_ok = ok(pa, "anydate") and ok(pb, "anydate")
    if ok(pa, "bool") and ok(pb, "bool") and not num_ok:
        return "boolean", [], [], f"{sp.canon}: boolean"
    if date_ok and (datey or not (num_ok or num_nc_ok)):
        kind = "timestamp" if (pa["has_time"] + pb["has_time"]) else "date"
        steps, why = {}, []
        for w, p in (("A", pa), ("B", pb)):
            if ok(p, "iso"):
                steps[w] = []
            elif ok(p, "dmy") and not ok(p, "mdy"):
                steps[w] = [{"op": f"to {kind}", "params": {"fmt": "%d/%m/%Y"}}]
            elif ok(p, "mdy") and not ok(p, "dmy"):
                steps[w] = [{"op": f"to {kind}", "params": {"fmt": "%m/%d/%Y"}}]
            elif ok(p, "dmy") and ok(p, "mdy"):
                steps[w] = [{"op": f"to {kind}", "params": {"fmt": "%d/%m/%Y"}}]
                why.append(f"{w}: day/month order ambiguous, assumed day first")
            else:
                steps[w] = []                   # the built-in list of spellings reads it
        note = f"{sp.canon}: {kind}" + "".join(
            f" ({w}: {s[0]['params']['fmt']})" for w, s in steps.items() if s)
        return kind, steps["A"], steps["B"], note + ("; " + "; ".join(why) if why else "")
    if num_ok:
        return "number", [], [], f"{sp.canon}: number"
    if num_nc_ok:
        steps = {w: ([] if ok(p, "num") else [{"op": "remove thousands separators", "params": {}}])
                 for w, p in (("A", pa), ("B", pb))}
        return ("number", steps["A"], steps["B"],
                f"{sp.canon}: number, thousands separators removed on "
                + " and ".join(w for w, s in steps.items() if s))
    partial = [k for k, p in (("A", pa), ("B", pb)) if ok(p, "num") or ok(p, "anydate")]
    return "text", [], [], (f"{sp.canon}: text" + (f" - only {partial[0]} converts, so compared as text"
                                                   if len(partial) == 1 else ""))


def case_probe(A: Side, B: Side, specs: list[ColSpec], opts: ReadOptions,
               sample: int = 5000) -> list[str]:
    """Text pairs whose two sides only agree once case is ignored."""
    text = [sp for sp in specs if sp.kind == "text" and not sp.a_steps and not sp.b_steps]
    if not text:
        return []
    con = probe(A, B, text, opts)
    out = []
    for sp in text:
        c = ident(sp.canon)
        raw, upper = [], []
        for v in ("probe_a", "probe_b"):
            df = con.execute(f"SELECT {c} AS v FROM {v} WHERE {c} IS NOT NULL LIMIT {int(sample)}").fetchdf()
            vals = {str(x) for x in df["v"]}
            raw.append(vals)
            upper.append({x.upper() for x in vals})
        if min(len(raw[0]), len(raw[1])) < 5:
            continue
        share_raw = len(raw[0] & raw[1]) / min(len(raw[0]), len(raw[1]))
        share_up = len(upper[0] & upper[1]) / min(len(upper[0]), len(upper[1]))
        if share_up >= 0.8 and share_up - share_raw >= 0.3:
            out.append(sp.canon)
    return out


def auto_configure(A: Side, B: Side, name_a: str, name_b: str, opts: ReadOptions, say
                   ) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Pair, type, key, compare - from the data. Returns the column table, the notes, the key."""
    notes: list[str] = []
    say("Pairing columns by name…")
    cmap = build_table(A, B)
    spare_a = [r["A column"] for _, r in cmap.iterrows() if r["A column"] and not r["B column"]]
    spare_b = [r["B column"] for _, r in cmap.iterrows() if r["B column"] and not r["A column"]]
    if spare_a and spare_b:
        say(f"Pairing {len(spare_a)} × {len(spare_b)} leftover columns by their values…")
        _, found = match_columns_by_data(A, B, spare_a, spare_b, name_a, name_b, opts)
        cmap = pair_rows(cmap, found, A, B)
        notes += [f"paired {a} with {b} by their values" for a, b in found.items()]
    paired = cmap[(cmap["A column"] != "") & (cmap["B column"] != "")]
    notes.insert(0, f"{len(paired)} columns paired ({int((paired['Matched by'] == 'name').sum())} by "
                    f"name, {int(paired['Matched by'].str.contains('similar|guess').sum())} by similar "
                    f"name, {int((paired['Matched by'] == 'data').sum())} by data); unpaired: "
                    f"{', '.join(r['A column'] for _, r in cmap.iterrows() if r['A column'] and not r['B column']) or 'none'} in {name_a}, "
                    f"{', '.join(r['B column'] for _, r in cmap.iterrows() if r['B column'] and not r['A column']) or 'none'} in {name_b}")
    specs = specs_from(cmap)
    if not specs:
        return cmap, notes + ["nothing could be paired - stop here"], []

    say(f"Analysing {len(specs)} columns on both sides for number, date, timestamp, boolean "
        f"and the date spelling each side uses (first {PROBE_ROWS:,} rows)…")
    pa, pb = probe_types(A, specs, "A", opts), probe_types(B, specs, "B", opts)
    for sp in specs:
        kind, sa, sb, why = decide_type(sp, pa[sp.canon], pb[sp.canon],
                                        A.schema.get(sp.a_src, ""), B.schema.get(sp.b_src, ""))
        cmap.loc[cmap["Common name"] == sp.canon, "Type"] = kind
        set_steps(cmap, sp.canon, "A", sa)
        set_steps(cmap, sp.canon, "B", sb)
        notes.append(why)
    specs = specs_from(cmap)

    say("Checking whether text columns differ only by case…")
    for canon in case_probe(A, B, specs, opts):
        set_steps(cmap, canon, "A", [{"op": "upper", "params": {}}])
        set_steps(cmap, canon, "B", [{"op": "upper", "params": {}}])
        notes.append(f"{canon}: the two files spell the same values in different case - compared upper-cased")
    specs = specs_from(cmap)

    say("Finding the key - unique column combinations on both sides…")
    table, combos, how = suggest_keys(A, B, specs, name_a, name_b, opts, progress=say)
    cmap["Key"] = False
    chosen: list[str] = []
    if combos:
        good = [c for c, u in zip(combos, table["Unique on both"]) if u == "yes"]
        chosen = good[0] if good else combos[0]
        cmap.loc[cmap["Common name"].isin(chosen), "Key"] = True
        notes.append(f"key: {' + '.join(chosen)}"
                     + ("" if good else " - NOT unique on both sides; the closest found. "
                                         "Rows sharing it are paired in file order")
                     + f". {how}")
        say(f"Key: {' + '.join(chosen)}" + ("" if good else " (not unique - closest found)"))
    else:
        notes.append("key: none found - rows will be matched by hashing the compared columns")
        say("No key found - rows will be matched by hashing the compared columns")
    paired_mask = (cmap["A column"] != "") & (cmap["B column"] != "")
    cmap.loc[paired_mask & ~cmap["Key"], "Compare"] = True
    notes.append(f"comparing all {int((paired_mask & ~cmap['Key']).sum())} paired non-key columns")
    return cmap, notes, chosen
