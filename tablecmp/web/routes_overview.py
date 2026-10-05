"""The Profile page's overview findings (GET /api/profiling/findings): what is worth knowing about
the whole table, one pill each - text columns that read as another type, placeholder values,
values spelled more than one way, gaps in the key's sequence, the weekend share of dates, the
strongest dependency, and what is clean - plus, per column, the short facts the Columns table
shows under "What stands out", and the strongest dependency pairs across the table.

Every count comes from the column pages' own analysis functions (casts, flag_reads, keycheck,
when_facts, text_values / by_fingerprint / by_other) - nothing is counted twice a different way.
The assembling is plain functions over (con, relation, specs, ...) that return dicts, so the
Compare page can run them on its own rows later; the route only registers the profile, hands
in what the profile already measured and keeps the answer per profile. Read-only."""
from __future__ import annotations

import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from .. import profiling
from ..sql import ident, lit
from ..values import ColSpec
from . import profile_held
from . import routes_col_flag as fl
from . import routes_col_text as tx
from .routes_col_key import keycheck
from .routes_col_when import when_facts
from .routes_profiling import READS_AS, _held, reads_as
from .sides import side
from .workspace import Workspace, workspace

router = APIRouter(prefix="/api/profiling")

PLACEHOLDERS = ("n/a", "na", "#n/a", "null", "none", "nil", "unknown", "tbd", "tba", "-", "--", "?", "??",
                "xx", "xxx", "test", "dummy", "missing", "not set", "not applicable", "undefined", "blank")
NEAR_CAP = 2000                 # a text column with more distinct values is not checked for spellings
SAME_CAP = 50                   # ... nor for values that only occur with one value of another column
DEPEND_TOP = 5                  # dependency pairs listed across the table
STRONG = 30                     # a dependency from here up reads as some dependency (DepMatrix.SHOWN)
DATE_COLS = 5                   # date and timestamp columns counted for their weekend share
TEXT_COLS = 30                  # text columns checked for spellings and placeholders


# ---- the analysis: plain functions --------------------------------------------------------------

def looks_like(casts: list[dict], flags: list[dict]) -> list[dict]:
    """Columns whose values read as another type - from /casts' rows and flag_reads' rows:
    [{column, kind, as, form, n, filled}], `as` one of number, date, timestamp, boolean - a
    column counted when READS_AS of its filled values read so, a boolean when every one does."""
    out: dict[str, dict] = {}
    for r in casts:
        k = reads_as(r)
        if not k and r["kind"] == "text" and "number" in r and r["number"]["any"] >= READS_AS * r["filled"]:
            k = "number"
        if k:
            out[r["column"]] = {"column": r["column"], "kind": r["kind"], "as": k, "form": r[k].get("form", ""),
                                "n": r[k]["any"], "filled": r["filled"]}
    for r in flags:
        out[r["column"]] = {"column": r["column"], "kind": out.get(r["column"], {}).get("kind", "text"), "as": "boolean",
                            "form": "", "n": r["filled"], "filled": r["filled"]}
    return list(out.values())


def placeholder_values(con, rel: str, columns: list[str]) -> list[dict]:
    """Values written as a placeholder word (N/A, unknown, TBD, -, ...) in text columns, one scan:
    [{column, value, n}], the most used spelling per column."""
    if not columns:
        return []
    words = ", ".join(lit(w) for w in PLACEHOLDERS)
    parts = [f"SELECT {lit(c)} AS c, CAST({ident(c)} AS VARCHAR) AS v FROM {ident(rel)} "
             f"WHERE lower(trim(CAST({ident(c)} AS VARCHAR))) IN ({words})" for c in columns]
    rows = con.execute(f"SELECT c, v, count(*) AS n FROM ({' UNION ALL '.join(parts)}) GROUP BY c, v "
                       f"ORDER BY c, n DESC, v").fetchall()
    out: dict[str, dict] = {}
    for c, v, n in rows:
        if c in out:
            out[c]["n"] += int(n)
        else:
            out[c] = {"column": c, "value": v, "n": int(n)}
    return [out[c] for c in columns if c in out]


def spellings(con, rel: str, column: str, others: list[str]) -> dict:
    """Values of one text column that are probably one thing spelled twice - by fingerprint (case,
    spaces and punctuation aside), else values that only occur with one value of another column
    (by_other): {column, method, by, groups: [{members, keep, rows, why}]}."""
    vals = tx.text_values(con, rel, column, tx.SIM_CAP)["values"]
    groups = tx.by_fingerprint(vals)
    if groups:
        return {"column": column, "method": "fingerprint", "by": "", "groups": groups}
    by, same = tx.by_other(con, rel, column, others, vals) if others else ("", [])
    return {"column": column, "method": "same" if same else "", "by": by, "groups": same}


def strongest_pairs(matrix: pd.DataFrame, skip: list[str], top: int = DEPEND_TOP) -> list[dict]:
    """The strongest pairs of the dependency matrix - how far X decides Y beyond chance, in % -
    the columns in `skip` (the key, which decides everything) left out: [{x, y, v}]."""
    if matrix is None or matrix.empty:
        return []
    ys = [c for c in matrix.columns if c != "Column"]
    out = []
    for _, r in matrix.iterrows():
        x = str(r["Column"])
        if x in skip:
            continue
        for y in ys:
            v = r[y]
            if y != x and y not in skip and v is not None and pd.notna(v) and float(v) > 0:
                out.append({"x": x, "y": y, "v": round(float(v), 2)})
    return sorted(out, key=lambda p: (-p["v"], p["x"], p["y"]))[:top]


def _n(x: int) -> str:
    return f"{x:,}"


def _pc(part: int, whole: int) -> str:
    return f"{100 * part / whole:.2f}%" if whole else "0.00%"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{_n(n)} {one if n == 1 else (many or one + 's')}"


def overview(con, rel: str, specs: list[ColSpec], stats: list[dict], *, key: list[str], notes: list[str],
             duplicates: int | None, matrix: pd.DataFrame, today=None) -> dict:
    """The overview's findings over `rel` (every spec registered on `con`, in the file's order for
    the key's sequence): {items: [{tone, label, detail, columns}], columns: {name: [fact]},
    pairs: [{x, y, v}], gaps, clean}. `stats` are the profile's statistics rows. What the columns
    look like is added by with_looks(), as the casts take longest and come on their own."""
    by_name = {s.canon: s for s in specs}
    st = {str(r["Column"]): r for r in stats}
    rows = int(stats[0]["Rows"]) if stats else 0
    facts: dict[str, list[str]] = {s.canon: [] for s in specs}
    items: list[dict] = []

    # placeholder words, and dates set to a placeholder day
    texts = [s.canon for s in specs if s.kind == "text" and s.canon not in key][:TEXT_COLS]
    held = placeholder_values(con, rel, texts)
    for h in held:
        facts.setdefault(h["column"], []).append(f"placeholder {h['value']} ×{_n(h['n'])}")

    # the key: its sequence, and the ids past its largest run
    gaps = None
    if len(key) == 1 and key[0] in by_name:
        k = keycheck(con, rel, by_name[key[0]])
        g = k.get("gaps") or {}
        f = facts[key[0]]
        f.append("unique" if k["duplicates"] == 0 and k["nulls"] == 0 else " · ".join(
            x for x in (_plural(k["duplicates"], "duplicate") if k["duplicates"] else "",
                        _plural(k["nulls"], "null") if k["nulls"] else "") if x))
        if k["order"] != "neither":
            f.append(f"{k['order']} in the file")
        if g.get("count"):
            big = max((r for r in k["runs"] if r["kind"] == "gap"), key=lambda r: r["n"])
            gaps = {"column": key[0], "count": g["count"], "ids": g["ids"],
                    "largest": {"from": big["id_from"], "to": big["id_to"], "n": big["n"]}}
            f.append(f"{_plural(g['count'], 'gap')} · {_plural(g['ids'], 'id')} missing"
                     + (f" ({big['id_from']} - {big['id_to']})" if g["count"] == 1 else ""))
            items.append({"tone": "warn", "label": "Sequence gap" if g["count"] == 1 else "Sequence gaps",
                          "detail": f"{key[0]} · {_plural(g['ids'], 'id')} missing"
                                    + (f" · {big['id_from']} - {big['id_to']}" if g["count"] == 1 else ""),
                          "columns": [key[0]]})
        b = k.get("beyond")
        if b:
            f.append(f"{_plural(b['rows'], 'id')} past the largest run ({b['id_from']} - {b['id_to']})")
            for s in b["shared"]:
                facts.setdefault(s["column"], []).append(f"{s['value']} on every id past the gap ×{_n(b['rows'])}")
            if b["shared"]:
                items.append({"tone": "warn", "label": f"One value on every id past the gap ×{_n(b['rows'])}",
                              "detail": " · ".join(f"{s['column']} {s['value']}" for s in b["shared"][:2]),
                              "columns": [s["column"] for s in b["shared"]]})
    if held:
        items.append({"tone": "warn", "label": "Placeholder value" if len(held) == 1 else "Placeholder values",
                      "detail": " · ".join(f"{h['column']} · {h['value']} ×{_n(h['n'])}" for h in held[:3]),
                      "columns": [h["column"] for h in held]})

    # values spelled more than one way
    near = []
    for c in texts:
        d = int(st.get(c, {}).get("Distinct") or 0)
        if d < 2 or d > NEAR_CAP:
            continue
        others = tx._others({"stats": pd.DataFrame(stats)}, c, d) if d <= SAME_CAP else []
        got = spellings(con, rel, c, others)
        if got["groups"]:
            near.append(got)
            gs = got["groups"]
            names = " · ".join(" / ".join(m["value"] for m in g["members"]) for g in gs[:3])
            why = (f" - each only with one {got['by']}" if got["method"] == "same"
                   else f" - {gs[0]['why']}" if len(gs) == 1 else " - case, spaces or punctuation aside")
            facts.setdefault(c, []).append(f"{_plural(len(gs), 'near-duplicate group')}: {names}{' · …' if len(gs) > 3 else ''}{why}")
    if near:
        total = sum(len(x["groups"]) for x in near)
        first = near[0]["groups"][0]
        items.append({"tone": "warn", "label": _plural(total, "near-duplicate group"),
                      "detail": f"{near[0]['column']} · {' / '.join(m['value'] for m in first['members'])}"
                                + (" …" if total > 1 else ""),
                      "columns": [x["column"] for x in near]})

    # dates: the weekend share and placeholder days, from the date page's own count
    weekend = []
    for s in [s for s in specs if s.kind in ("date", "timestamp")][:DATE_COLS]:
        kind = s.kind
        w = when_facts(con, ident(rel), s, kind=kind, today=today)
        if not w["filled"]:
            continue
        facts.setdefault(s.canon, []).append(f"weekend {_pc(w['weekend'], w['filled'])}")
        if w["weekend"]:
            weekend.append((s.canon, w["weekend"], w["filled"], kind))
        for p in w["placeholders"]:
            facts[s.canon].append(f"placeholder {p['value']} ×{_n(p['n'])}")
        if w["future"]:
            facts[s.canon].append(f"{_plural(w['future'], 'value')} after {w['today']}")
        if w["repeated"] and w["repeated"][0]["n"] > 1:
            r0 = w["repeated"][0]
            facts[s.canon].append(f"most often {r0['value']} ×{_n(r0['n'])}")
    if weekend:
        c, n, of, kind = weekend[0]
        items.append({"tone": "info", "label": f"Weekend {'dates' if kind == 'date' else 'times'} {_pc(n, of)}",
                      "detail": c + (f" · {len(weekend) - 1} more" if len(weekend) > 1 else ""),
                      "columns": [w[0] for w in weekend]})

    # the strongest dependency, the key left out
    pairs = strongest_pairs(matrix, key)
    near_full = [p for p in pairs if STRONG <= p["v"] < 100]
    pick = near_full[0] if near_full else (pairs[0] if pairs and pairs[0]["v"] >= STRONG else None)
    if pick:
        items.append({"tone": "info", "label": f"{pick['x']} decides {pick['y']}",
                      "detail": "on every row" if pick["v"] >= 100 else f"{pick['v']:.2f}% beyond chance",
                      "columns": [pick["x"], pick["y"]]})
    for p in pairs:
        if p["v"] >= STRONG:
            facts.setdefault(p["x"], []).append(f"decides {p['y']}" + (" on every row" if p["v"] >= 100 else f" - {p['v']:.2f}%"))

    # what is clean
    nulls = sum(int(r.get("Nulls") or 0) for r in stats)
    variants = any(re.search(r" differ only in case|leading or trailing", n) for n in notes) or \
        any(x["method"] == "fingerprint" for x in near)
    clean = [w for w, ok in (("no nulls", nulls == 0), ("no duplicate rows", duplicates == 0),
                             ("no whitespace or case variants", not variants)) if ok]
    if clean:
        items.append({"tone": "pos", "label": " · ".join(clean).capitalize(), "detail": "", "columns": []})

    return {"rows": rows, "nulls": nulls, "duplicates": duplicates, "items": items,
            "columns": {c: f for c, f in facts.items() if f}, "looks": [], "pairs": pairs, "gaps": gaps,
            "clean": clean}


def with_looks(answer: dict, looks: list[dict], casts: bool = True) -> dict:
    """The overview with what its columns look like (looks_like's rows) added: a fact per column
    and, for text columns, one pill first - a new dict, `answer` left as it was. `casts` says
    whether the casts were in when it was made."""
    facts = {c: list(f) for c, f in answer["columns"].items()}
    items = list(answer["items"])
    for x in looks:
        form = x["form"] if x["form"] not in ("", "plain", "ISO") else ""
        facts.setdefault(x["column"], []).insert(
            0, f"reads as {x['as']}" + (f" · {form}" if form else "") + f" - {_n(x['n'])} of {_n(x['filled'])}")
    text = [x for x in looks if x["kind"] == "text"]
    if text:
        kinds = " · ".join(k for k in ("number", "date", "timestamp", "boolean") if any(x["as"] == k for x in text))
        items.insert(0, {"tone": "warn", "label": f"{_plural(len(text), 'text column')} {'looks' if len(text) == 1 else 'look'} like {kinds}",
                         "detail": ", ".join(f"{x['column']} → {x['as']}" for x in text),
                         "columns": [x["column"] for x in text]})
    return {**answer, "items": items, "columns": facts, "looks": looks, "casts": casts}


# ---- the route ----------------------------------------------------------------------------------

def _flags(ws: Workspace) -> list[dict]:
    """The boolean check, held once per profile by the flag page's own route."""
    return fl.column_flags(ws)["columns"]


@router.get("/findings")
def findings(ws: Workspace = Depends(workspace)) -> dict:
    """What stands out across the whole table, one pill each, with per-column facts and the
    strongest dependency pairs - worked out once per profile. What the columns look like as
    another type comes from the casts once /casts has counted them (`casts` says whether it
    had): asking here does not wait on them, the page asks again when they are in."""
    _, prof, _ = _held(ws)
    base = profile_held.memo(ws, prof, ("findings",), lambda: _base(ws, prof))
    got = profile_held.peek(ws, prof, ("casts",))
    casts = got["columns"] if got else None
    return with_looks(base, looks_like(casts or [], _flags(ws)), casts is not None)


def _base(ws: Workspace, prof: dict) -> dict:
    P = side(ws, "P")
    if not P.loaded:
        raise HTTPException(409, "Load a table first.")
    specs = [ColSpec(**s) for s in prof.get("specs", [])]
    con = profile_held.cursor(ws, prof)
    try:
        stats = prof["stats"].to_dict("records")
        answer = overview(con, "prof", specs, stats,
                          key=profiling.best_key(prof) or [], notes=list(prof["notes"]),
                          duplicates=prof.get("duplicates"), matrix=prof.get("matrix"))
    finally:
        con.close()
    return answer
