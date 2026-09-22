"""Running a comparison and reading it back.

Three ways to pair rows:
  key       the engine (csvdiff) joins on the key columns - the normal case
  position  the engine pairs line 1 with line 1
  hash      no key at all: every row is hashed over the compared columns and the two
            multisets are matched - identical rows pair, the rest are one-sided

Both sides are materialised as DuckDB tables first, under the shared column names
with the canonical values applied, so whatever runs next reads them once.
"""
from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .profile import label
from .sources import Side, work_dir
from .sql import ident, lit, scratch
from .theme import THEME
from .values import FALLBACK_FORMATS, ColSpec, ReadOptions, date_format, fits_held, register

OPS = ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "between", "like", "is null", "is not null"]
OP_MAP = {"=": "eq", "!=": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le",
          "in": "in", "not in": "not_in", "between": "between", "like": "like",
          "is null": "is_null", "is not null": "not_null"}
# how a boolean column spells the value a filter may be typed with
BOOL_WORDS = {"true": "true", "t": "true", "yes": "true", "y": "true", "1": "true",
              "false": "false", "f": "false", "no": "false", "n": "false", "0": "false"}
# settings that change what is shown, not what the answer is
DISPLAY_KEYS = ("name", "notes", "table_formats", "display_rows", "matched_by")
ENGINE_HTML_ROWS = 2000                 # rows per tab in the engine's own diff.html
# A rows sit on the page's bg with its text colour, B rows the other way round - the two sides
# read as black and cream. The differing cells use the theme's four diff tokens.
LEFT_BG, RIGHT_BG = THEME["bg"], THEME["text"]
LEFT_FG, RIGHT_FG = THEME["text"], THEME["bg"]
LEFT_DIFF = f"background-color:{THEME['diff_left_bg']};color:{THEME['diff_left_fg']}"
RIGHT_DIFF = f"background-color:{THEME['diff_right_bg']};color:{THEME['diff_right_fg']}"


@dataclass
class Outcome:
    """What a comparison found, whichever way the rows were paired."""
    mode: str = "key"
    keys: list[str] = field(default_factory=list)
    columns_compared: list[str] = field(default_factory=list)
    rows_left: int = 0
    rows_right: int = 0
    rows_left_read: int = 0
    rows_right_read: int = 0
    matched_rows: int = 0
    only_left: int = 0
    only_right: int = 0
    diff_rows: int = 0
    cell_diffs: int = 0
    diffs_by_column: dict[str, int] = field(default_factory=dict)
    value_gaps: dict[str, tuple[int, int]] = field(default_factory=dict)   # hash mode
    filter_left: str = ""
    filter_right: str = ""
    sample_unmatched_left: list = field(default_factory=list)
    sample_unmatched_right: list = field(default_factory=list)
    duplicate_keys_left: int = 0        # rows that share their key with an earlier row
    duplicate_keys_right: int = 0
    error: str = ""

    @classmethod
    def from_engine(cls, res: Any) -> "Outcome":
        o = cls()
        for k in o.__dataclass_fields__:
            if hasattr(res, k) and k != "value_gaps":
                setattr(o, k, getattr(res, k))
        o.keys = list(o.keys or [])
        o.columns_compared = list(o.columns_compared or [])
        o.diffs_by_column = dict(o.diffs_by_column or {})
        o.error = str(o.error or "")
        return o


# ---- filters -----------------------------------------------------------------
def date_texts(col: str, values: list[str], full: bool, formats: dict[str, str] | None = None
               ) -> list[str]:
    """Each typed value as the ISO text a date column holds - read the way the column is:
    with the format its to date / to timestamp step names (`formats`: side name -> format,
    for the sides the filter applies to), else any of the usual spellings - so the engine
    compares like with like and never sees a ConversionException. `full` keeps the time of
    day (a timestamp column); otherwise a value at midnight is a plain date. A value that is
    not a date, or that the two sides' formats read as different days, raises ValueError."""
    if not values:
        return []
    named = [(side, f) for side, f in (formats or {}).items() if f]
    fl = "[" + ", ".join(lit(f) for f in FALLBACK_FORMATS) + "]"
    reads = ([f"try_strptime(v, {lit(f)})" for _, f in named]
             + [f"coalesce(try_cast(v AS TIMESTAMP), try_strptime(v, {fl}))"])

    def text(ts: str) -> str:
        day = f"CAST({ts} AS DATE)"
        return (f"CAST({ts} AS VARCHAR)" if full
                else f"CASE WHEN {ts} = CAST({day} AS TIMESTAMP) THEN CAST({day} AS VARCHAR) "
                     f"ELSE CAST({ts} AS VARCHAR) END")
    con = scratch()
    try:
        got = con.execute(f"SELECT v, {', '.join(text(ts) for ts in reads)} "
                          f"FROM (SELECT unnest([{', '.join(lit(v) for v in values)}]) AS v)").fetchall()
    except duckdb.Error as exc:
        raise ValueError(f"filter on {col!r}: the column's date format cannot be read - {exc}") from None
    finally:
        con.close()
    out = []
    for v, *own, usual in got:
        seen = [(side, f, t) for (side, f), t in zip(named, own) if t is not None]
        if len({t for _, _, t in seen}) > 1:
            (sa, fa, ta), (sb, fb, tb) = seen[0], seen[-1]
            raise ValueError(f"filter on {col!r}: {v!r} is {ta} to {sa} ({fa}) and {tb} to {sb} ({fb}) "
                             f"- spell it {ta} or {tb}")
        t = seen[0][2] if seen else usual
        if t is None:
            raise ValueError(f"filter on {col!r}: {v!r} is not a date")
        out.append(str(t))
    return out


def number_texts(col: str, values: list[str]) -> list[str]:
    """Each typed value as the number a number column holds - 9, 10.5, -3, 1e+20 - so both the
    engine and filter_sql compare numbers and only ever splice a number into the SQL. A
    value that is not a number (inf and nan included) raises ValueError."""
    out = []
    for v in values:
        try:
            n = float(v)
        except ValueError:
            n = math.nan
        if not math.isfinite(n):
            raise ValueError(f"filter on {col!r}: {v!r} is not a number")
        out.append(repr(n).removesuffix(".0"))
    return out


def side_labels(name_a: str, name_b: str) -> tuple[str, str]:
    """The two names as a widget can offer them: as they are, unless both sides carry the same
    name - two database sides on one connection - when the tag tells them apart (A · SAMPLE)."""
    if name_a != name_b:
        return name_a, name_b
    return f"A · {name_a}", f"B · {name_b}"


def build_filters(rows: pd.DataFrame, name_a: str, name_b: str,
                  specs: list[ColSpec] | None = None) -> tuple[dict, dict, dict]:
    """The Rows filters as the engine's dicts: (both, left, right). With the column specs a
    value is spelled the way its column is: True / yes / 1 on a boolean column is "true",
    a date is ISO text - read with the format the column's own to date / to timestamp step
    names on the side the filter applies to, else in any of the usual spellings - a number
    column compares as numbers (type number, so 10 > 9 whether or not the column is compared
    or a key), and a value that is not a date or a number at all is refused with a sentence
    before the engine ever sees it."""
    by = {s.canon: s for s in specs or []}
    label_a, label_b = side_labels(name_a, name_b)
    both: dict[str, Any] = {}
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    for _, r in rows.iterrows():
        col, op = str(r.get("Column") or "").strip(), str(r.get("Operator") or "").strip()
        if not col or not op:
            continue
        where = str(r.get("Apply to") or "Both")
        side = "A" if where == label_a else "B" if where == label_b else ""     # "": both
        raw = str(r.get("Value") or "").strip()
        spec: dict[str, Any] = {}
        kind = str(r.get("Type") or "auto")
        if kind != "auto":
            spec["type"] = kind
        key = OP_MAP.get(op, op)
        if key in ("is_null", "not_null"):
            spec[key] = True
        elif key in ("in", "not_in"):
            spec[key] = [v.strip() for v in raw.split(",") if v.strip()]
        elif key == "between":
            parts = [p.strip() for p in raw.replace("..", ",").split(",") if p.strip()]
            if len(parts) != 2:
                raise ValueError(f"'between' on {col} needs two values, e.g. 2026-07-20, 2026-07-31")
            spec[key] = parts
        else:
            spec[key] = raw
        if key not in ("like", "is_null", "not_null"):
            s = by.get(col)
            own = s.kind if s else "text"
            values = spec[key] if isinstance(spec[key], list) else [spec[key]]
            if own == "boolean" and kind in ("auto", "string"):
                values = [BOOL_WORDS.get(v.lower(), v) for v in values]
            elif kind == "date" or (kind == "auto" and own in ("date", "timestamp")):
                formats = {name: date_format(s.steps(w)) for w, name in (("A", label_a), ("B", label_b))
                           if s and side in ("", w)}
                values = date_texts(col, values, full=kind == "auto" and own == "timestamp", formats=formats)
            elif kind == "number" or (kind == "auto" and own == "number"):
                values = number_texts(col, values)
                spec["type"] = "number"
            spec[key] = values if isinstance(spec[key], list) else values[0]
        target = left if side == "A" else right if side == "B" else both
        target.setdefault(col, {}).update(spec)
    return both, left, right


def filter_sql(filters: dict) -> str:
    """The same filter dicts as SQL, for the paths that do not go through the engine."""
    parts = []
    for col, spec in filters.items():
        c = ident(col)
        if spec.get("type") == "number":
            c = f"try_cast({c} AS DOUBLE)"
            q = lambda v: v          # noqa: E731
        else:
            q = lit
        for k, v in spec.items():
            if k == "type":
                continue
            if k in ("eq", "ne", "gt", "ge", "lt", "le"):
                op = {"eq": "=", "ne": "<>", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}[k]
                parts.append(f"{c} {op} {q(v)}")
            elif k == "in":
                parts.append(f"{c} IN ({', '.join(q(x) for x in v) or lit('')})")
            elif k == "not_in":
                parts.append(f"{c} NOT IN ({', '.join(q(x) for x in v) or lit('')})")
            elif k == "between":
                parts.append(f"{c} BETWEEN {q(v[0])} AND {q(v[1])}")
            elif k == "like":
                parts.append(f"{ident(col)} LIKE {lit(v)}")
            elif k == "is_null":
                parts.append(f"{ident(col)} IS NULL")
            elif k == "not_null":
                parts.append(f"{ident(col)} IS NOT NULL")
    return " AND ".join(parts)


def signature(a: Side, b: Side, cfg: dict) -> str:
    """Everything that changes the answer. Used to spot a stale result. The name, the notes,
    the table formats, the rows shown on screen and how the pairs were matched do not."""
    payload = {"a": [a.label, a.rows, a.read_key, list(a.schema)],
               "b": [b.label, b.rows, b.read_key, list(b.schema)],
               "cfg": {k: v for k, v in cfg.items() if k not in DISPLAY_KEYS}}
    return json.dumps(payload, sort_keys=True, default=str)


# ---- running ---------------------------------------------------------------
def run_comparison(A: Side, B: Side, cfg: dict, opts: ReadOptions, sig: str = "",
                   previous: dict | None = None, progress=None) -> dict:
    """One run: <work_dir>/<pair>__<run_id>/ holding every file the engine and we write,
    flat, each named <pair>__<what>. The run dict carries the result, the folder, the files,
    the open connection and the verdict."""
    from .outputs import run_id, verdict_of
    say = progress or (lambda _m: None)
    mode = cfg["mode"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys = list(cfg["keys"]) if mode == "key" else []
    con = scratch(ordered=True)   # file order is what pairs duplicate keys (1st with 1st) - keep it
    started = datetime.now().astimezone()
    rid = run_id(started)
    out = work_dir() / f"{cfg['name']}__{rid}"
    while out.exists():                                  # two runs in one second
        rid += "a"
        out = work_dir() / f"{cfg['name']}__{rid}"
    folder = out / cfg["name"]                           # the engine writes under <out>/<name>
    folder.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    say(f"Reading {A.name or 'A'} - {len(specs)} columns, canonical values…")
    register(con, A, "src_a", specs, "A", opts, materialize=True)
    n_a = con.execute("SELECT count(*) FROM src_a").fetchone()[0]
    say(f"{A.name or 'A'}: {n_a:,} rows. Reading {B.name or 'B'}…")
    register(con, B, "src_b", specs, "B", opts, materialize=True)
    n_b = con.execute("SELECT count(*) FROM src_b").fetchone()[0]
    say(f"{B.name or 'B'}: {n_b:,} rows.")

    if mode == "hash":
        res = hash_compare(con, cfg, folder, say)
    else:
        res = engine_compare(con, cfg, folder, out, keys, say)
    res.rows_left_read = res.rows_left_read or n_a
    res.rows_right_read = res.rows_right_read or n_b
    elapsed = time.perf_counter() - t0
    for p in folder.iterdir():                           # flatten: <out>/<name>/x -> <out>/x
        p.rename(out / p.name)
    folder.rmdir()
    run = {"result": res, "folder": out, "files": {p.name: p for p in out.glob("*")}, "seconds": elapsed,
           "con": con, "left": "src_a", "right": "src_b", "cfg": cfg, "signature": sig,
           "at": started.strftime("%H:%M:%S"), "mode": mode, "run_id": rid, "pair": cfg["name"],
           "started_at": started.isoformat(timespec="seconds"), "verdict": verdict_of(res, mode)}
    return run              # the paired rows are written when they are asked for: see paired_path


def engine_compare(con, cfg: dict, folder: Path, out: Path, keys: list[str], say) -> Outcome:
    import csvdiff                                   # the engine, next to the app
    options = csvdiff.Options().merged({
        "keys": keys,
        "only_columns": cfg["compare_columns"],
        "trim": cfg["trim"],
        "treat_empty_as_null": cfg["empty_as_null"],
        "ignore_case_values": cfg["ignore_case"],
        "tolerance": cfg["tolerance"],
        "column_rules": cfg["column_rules"],
        "filters": cfg["filters"],
        "left_filters": cfg["left_filters"],
        "right_filters": cfg["right_filters"],
        "html_limit": ENGINE_HTML_ROWS,      # the rows shown on screen are display-only
        "html_all_limit": ENGINE_HTML_ROWS,
        "write_empty": True,                 # the fixed file set: empty tables keep their header
        "mode": "key" if keys else "row_number",
        "case_insensitive_columns": False,   # our views already carry the exact canonical names
    })
    spec = csvdiff.PairSpec(cfg["name"], csvdiff.SRC + "src_a", csvdiff.SRC + "src_b", options)
    say(("Matching on " + " + ".join(keys) if keys else "Pairing rows by position")
        + f" and comparing {len(cfg['compare_columns'])} columns…")
    res = Outcome.from_engine(csvdiff.CsvDiff(con).compare(spec, out))
    res.mode = "key" if keys else "position"
    return res


def hash_compare(con, cfg: dict, folder: Path, say) -> Outcome:
    """No key: hash every row over the compared columns and match the two multisets."""
    cols = list(cfg["compare_columns"])
    res = Outcome(mode="hash", keys=[], columns_compared=cols)
    for side, filt in (("src_a", {**cfg["filters"], **cfg["left_filters"]}),
                       ("src_b", {**cfg["filters"], **cfg["right_filters"]})):
        where = filter_sql(filt)
        if where:
            con.execute(f"CREATE OR REPLACE TABLE {side} AS SELECT * FROM {side} WHERE {where}")
            setattr(res, "filter_left" if side == "src_a" else "filter_right", where)
    h = "hash(concat_ws(chr(1), " + ", ".join(f"coalesce({ident(c)}, chr(2))" for c in cols) + "))"
    say(f"Hashing every row over {len(cols)} columns on both sides…")
    for side in ("src_a", "src_b"):                  # every column, so one-sided rows come out whole
        con.execute(f"CREATE OR REPLACE TABLE h_{side[-1]} AS "
                    f"SELECT {h} AS __h, row_number() OVER (PARTITION BY {h}) AS __k, * FROM {side}")
    res.rows_left = con.execute("SELECT count(*) FROM h_a").fetchone()[0]     # after the filter; the rows
    res.rows_right = con.execute("SELECT count(*) FROM h_b").fetchone()[0]    # read are counted by the caller
    say("Matching identical rows…")
    res.matched_rows = con.execute(
        "SELECT count(*) FROM h_a a JOIN h_b b ON a.__h = b.__h AND a.__k = b.__k").fetchone()[0]
    for tag, mine, other, fname in (("left", "h_a", "h_b", "left_only"),
                                    ("right", "h_b", "h_a", "right_only")):
        path = folder / f"{cfg['name']}__{fname}.csv"
        con.execute(f"COPY (SELECT * EXCLUDE (__h, __k) FROM {mine} m WHERE NOT EXISTS (SELECT 1 FROM {other} o "
                    f"WHERE o.__h = m.__h AND o.__k = m.__k)) TO {lit(str(path))} (HEADER)")
        setattr(res, f"only_{tag}", con.execute(
            f"SELECT count(*) FROM {mine} m WHERE NOT EXISTS (SELECT 1 FROM {other} o "
            f"WHERE o.__h = m.__h AND o.__k = m.__k)").fetchone()[0])
    if res.only_left or res.only_right:
        say("Which columns carry the difference…")
        for c in cols:
            q = ident(c)
            ga = con.execute(f"SELECT count(DISTINCT {q}) FROM h_a WHERE {q} IS NOT NULL AND "
                             f"{q} NOT IN (SELECT {q} FROM h_b WHERE {q} IS NOT NULL)").fetchone()[0]
            gb = con.execute(f"SELECT count(DISTINCT {q}) FROM h_b WHERE {q} IS NOT NULL AND "
                             f"{q} NOT IN (SELECT {q} FROM h_a WHERE {q} IS NOT NULL)").fetchone()[0]
            res.value_gaps[c] = (int(ga), int(gb))
            res.diffs_by_column[c] = int(ga) + int(gb)
    return res


# ---- reading results back ------------------------------------------------------
def ordered_view(con, table: str, name: str, keys: list[str] | None = None) -> None:
    """Row number in file order plus, when there is a key, the occurrence index within that
    key - the same numbering the engine uses to pair duplicate keys (1st with 1st, 2nd with
    2nd), so every follow-up query pairs exactly the rows the engine paired."""
    occ = ""
    if keys:
        part = ", ".join(ident(k) for k in keys)
        occ = f", row_number() OVER (PARTITION BY {part} ORDER BY __rn) AS __occ"
    con.execute(f"CREATE OR REPLACE VIEW {ident(name)} AS "
                f"SELECT *{occ} FROM (SELECT row_number() OVER () AS __rn, * FROM {ident(table)})")


def pair_views(run: dict, keys: list[str]) -> None:
    """cmp_l / cmp_r with row number and occurrence index - held as tables once per run so
    every follow-up table (by key value, profiles, differing rows) is a plain join. A side
    too big to hold a second copy of stays a view over the one already read: the numbering
    is worked out per query instead of once, which is slower and costs no memory."""
    con = run["con"]
    if run.get("_pair_keys") == tuple(keys):
        return
    cols = len(run["cfg"].get("specs") or [])
    for side, name in (("left", "cmp_l"), ("right", "cmp_r")):
        ordered_view(con, run[side], f"{name}_v", keys)
        rows = int(con.execute(f"SELECT count(*) FROM {ident(run[side])}").fetchone()[0])
        what = "TABLE" if fits_held(con, rows, cols + 2) else "VIEW"
        con.execute(f"CREATE OR REPLACE {what} {ident(name)} AS SELECT * FROM {ident(name + '_v')}")
    run["_pair_keys"] = tuple(keys)


def discard_run(run: dict | None) -> None:
    """Remove a run's folder and its zip - only ever called once a newer run has replaced it.
    The folder sits directly in the work folder next to fetches and snapshots, so only the
    folder itself goes, never its parent."""
    if run and run.get("folder"):
        shutil.rmtree(Path(run["folder"]), ignore_errors=True)
        z = run.get("zip")
        if z:
            Path(z).unlink(missing_ok=True)


def join_on(keys: list[str]) -> str:
    if not keys:
        return "l.__rn = r.__rn"
    return (" AND ".join(f"l.{ident(k)} IS NOT DISTINCT FROM r.{ident(k)}" for k in keys)
            + " AND l.__occ = r.__occ")


def row_key(keys: list[str], prefix: str = "", occ: str | None = "__occ") -> str:
    """One text per paired row: the key values plus the occurrence index when the engine
    wrote one (it only does when a key repeats)."""
    parts = [f"coalesce({prefix}{ident(k)}, chr(2))" for k in keys]
    if occ:
        parts.append(f"coalesce({prefix}{ident(occ)}::VARCHAR, '1')")
    return "concat_ws(chr(1), " + ", ".join(parts) + ")"


def cd_occ(run: dict) -> str | None:
    """Name of the occurrence column in the engine's cell_diffs, if it wrote one."""
    return "occurrence" if "occurrence" in cd_columns(run) else None


def cells_table(run: dict) -> bool:
    """Load the engine's cell differences into the connection as `cd`; False if none."""
    con, cfg = run["con"], run["cfg"]
    if run.get("_cd_loaded"):
        return True
    path = run["files"].get(f"{cfg['name']}__cell_diffs.csv")
    if not path:
        return False
    con.execute(f"CREATE OR REPLACE TABLE cd AS SELECT * FROM "
                f"read_csv({lit(str(path))}, all_varchar=true)")
    run["_cd_loaded"] = True
    return True


def cd_columns(run: dict) -> set[str]:
    return {r[0] for r in run["con"].execute("DESCRIBE cd").fetchall()}


@lru_cache(maxsize=32)
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def column_ledger(run: dict, name_a: str, name_b: str) -> pd.DataFrame:
    """Every column from either file on one sheet: what it is called on each side, its role
    in this comparison, how it was read and - for compared columns - how it did."""
    res: Outcome = run["result"]
    cfg = run["cfg"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys, compared = set(cfg.get("keys") or []), set(cfg.get("compare_columns") or [])
    matched = res.matched_rows
    rows = []
    for s in specs:
        role = ("key" if s.canon in keys else "compared" if s.canon in compared
                else "paired, not compared")
        rec = {"Column": s.canon, name_a: s.a_src, name_b: s.b_src, "Role": role,
               "Read as": s.describe(), "Matched": None, "Mismatched": None, "Match %": None}
        if role == "compared" and run["mode"] != "hash":
            bad = res.diffs_by_column.get(s.canon, 0)
            rec.update(Matched=matched - bad, Mismatched=bad,
                       **{"Match %": round((matched - bad) / matched * 100, 2) if matched else 0.0})
        elif role == "compared":
            gaps = res.value_gaps.get(s.canon, (0, 0))
            rec.update({f"Values only in {name_a}": gaps[0], f"Values only in {name_b}": gaps[1]})
        rows.append(rec)
    for c in cfg.get("only_a") or []:
        rows.append({"Column": c, name_a: c, name_b: None, "Role": f"only in {name_a}",
                     "Read as": "not compared"})
    for c in cfg.get("only_b") or []:
        rows.append({"Column": c, name_a: None, name_b: c, "Role": f"only in {name_b}",
                     "Read as": "not compared"})
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    order = {"key": 0, "compared": 1, "paired, not compared": 2}
    df["_o"] = df["Role"].map(lambda r: order.get(r, 3))
    df["_bad"] = -(df["Mismatched"].fillna(-1) if "Mismatched" in df else 0)
    df = df.sort_values(["_o", "_bad", "Column"]).drop(columns=["_o", "_bad"])
    if run["mode"] == "hash":
        df = df.drop(columns=["Matched", "Mismatched", "Match %"], errors="ignore")
    for c in ("Matched", "Mismatched", "Match %", f"Values only in {name_a}", f"Values only in {name_b}"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")      # NaN shows as blank, not "None"
    df[name_a] = df[name_a].fillna("—")
    df[name_b] = df[name_b].fillna("—")
    return df.reset_index(drop=True)


def ledger_counts(df: pd.DataFrame, name_a: str, name_b: str) -> dict[str, int]:
    roles = df["Role"].tolist() if len(df) else []
    return {"key": roles.count("key"), "compared": roles.count("compared"),
            "not compared": roles.count("paired, not compared"),
            f"only in {name_a}": roles.count(f"only in {name_a}"),
            f"only in {name_b}": roles.count(f"only in {name_b}")}


def diffs_by_key_value(run: dict, keys: list[str], n: int = 10) -> dict[str, pd.DataFrame]:
    """For each key column: the values the differing rows sit under."""
    con = run["con"]
    if "_by_key" in run:
        return run["_by_key"]
    if not keys or not cells_table(run):
        return {}
    have = cd_columns(run)
    if not all(k in have for k in keys):
        return {}
    pair_views(run, keys)
    rowkey = row_key(keys, "", cd_occ(run))
    out = {}
    for k in keys:
        kq = ident(k)
        df = con.execute(f"""
            WITH d AS (SELECT {kq} AS v, count(DISTINCT {rowkey}) AS diff_rows,
                              count(*) AS diff_cells,
                              list_slice(list_distinct(list(column_name)), 1, 6) AS cols
                       FROM cd GROUP BY 1),
                 m AS (SELECT l.{kq} AS v, count(*) AS matched
                       FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} GROUP BY 1)
            SELECT d.v, m.matched, d.diff_rows,
                   round(100.0 * d.diff_rows / greatest(m.matched, 1), 2) AS pct,
                   d.diff_cells, array_to_string(d.cols, ', ') AS cols
            FROM d LEFT JOIN m ON d.v IS NOT DISTINCT FROM m.v
            ORDER BY d.diff_rows DESC, d.v LIMIT {int(n)}""").fetchdf()
        df.columns = [k, "Matched rows", "Rows that differ", "% of those rows",
                      "Cells that differ", "Columns that differ"]
        df[k] = df[k].map(label)
        out[k] = df
    run["_by_key"] = out
    return out


def differing_rows(run: dict, keys: list[str], cols: list[str], limit: int
                   ) -> tuple[pd.DataFrame, dict[int, set[str]]]:
    """Rows that paired on the key but differ: A above B, with the differing cells marked."""
    con = run["con"]
    cache = run.setdefault("_differing", {})
    if (tuple(cols), limit) in cache:
        return cache[(tuple(cols), limit)]
    if not keys or not cells_table(run):
        return pd.DataFrame(), {}
    pair_views(run, keys)
    occ = cd_occ(run)
    sel = ", ".join([f"l.{ident(k)} AS {ident('k_' + k)}" for k in keys]
                    + [f"{row_key(keys, 'l.', '__occ' if occ else None)} AS __rk"]
                    + [f"l.{ident(c)} AS {ident('l_' + c)}" for c in cols]
                    + [f"r.{ident(c)} AS {ident('r_' + c)}" for c in cols])
    df = con.execute(
        f"SELECT {sel} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} "
        f"WHERE {row_key(keys, 'l.', '__occ' if occ else None)} IN (SELECT {row_key(keys, '', occ)} FROM cd) "
        f"ORDER BY l.__rn LIMIT {int(limit)}").fetchdf()
    marks_raw = con.execute(
        f"SELECT {row_key(keys, '', occ)} AS rk, list_distinct(list(column_name)) AS cols FROM cd GROUP BY 1"
    ).fetchall()
    changed = {rk: set(cs) for rk, cs in marks_raw}
    rows, marks = [], {}
    for _, row in df.iterrows():
        rk = row["__rk"]
        for side, prefix in (("A", "l_"), ("B", "r_")):
            rec = {"Side": side}
            for k in keys:
                rec[k] = row[f"k_{k}"]
            for c in cols:
                rec[c] = row[f"{prefix}{c}"]
            rows.append(rec)
        marks[len(rows) - 2] = changed.get(rk, set())
    result = (pd.DataFrame(rows, columns=["Side"] + keys + cols) if rows else pd.DataFrame(), marks)
    cache[(tuple(cols), limit)] = result
    return result


def write_paired(run: dict, keys: list[str], cols: list[str]) -> Path:
    """Every paired row side by side - keys, then a_<col>, b_<col> - straight from DuckDB.
    In hash mode nothing pairs by key, so the file is a header only."""
    con = run["con"]
    path = Path(run["folder"]) / f"{run['cfg']['name']}__paired.csv"
    if run["mode"] == "hash":
        pd.DataFrame(columns=cols).to_csv(path, index=False, lineterminator="\n")
        run["files"][path.name] = path
        return path
    pair_views(run, keys)
    sel = ", ".join([f"l.{ident(k)} AS {ident(k)}" for k in keys]
                    + [f"l.{ident(c)} AS {ident('a_' + c)}" for c in cols]
                    + [f"r.{ident(c)} AS {ident('b_' + c)}" for c in cols])
    con.execute(f"COPY (SELECT {sel or 'l.__rn'} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} ORDER BY l.__rn) "
                f"TO {lit(str(path))} (HEADER)")
    run["files"][path.name] = path
    return path


def have_paired(run: dict) -> bool:
    """Whether the run's paired-rows file is on disk - it is written when it is asked for, and
    a folder can be swept under a session that is still open."""
    p = run["files"].get(f"{run['cfg']['name']}__paired.csv")
    return bool(p and p.exists())


def paired_path(run: dict) -> Path | None:
    """The run's paired-rows file, written the first time something asks for it - the button on
    Downloads, the zip, a save of everything, the Parquet copies - and kept after that.

    Every other file of a run falls out of the comparison itself. This one is a second pass
    over both sides joined and written out whole: on a 100,000-row, 200-column pair it was 19
    of the run's 80 seconds, and most runs are read on the page and never downloaded. So it is
    written on request, like the zip; once written it is in the folder, the file list and the
    summary's listing like any other file - with its Parquet copy when the run keeps those,
    since the copies were made before this file existed. None when the run failed - nothing
    paired.
    """
    res, cfg = run["result"], run["cfg"]
    if res.error:
        return None
    if have_paired(run):
        return run["files"][f"{cfg['name']}__paired.csv"]
    keys = list(res.keys or cfg["keys"]) if run["mode"] == "key" else []
    path = write_paired(run, keys, list(res.columns_compared or cfg["compare_columns"]))
    from .outputs import drop_zip, has_parquet, parquet_copy, refresh_listing
    if has_parquet(run):
        parquet_copy(run, "paired")
    refresh_listing(run)
    drop_zip(run)                     # a zip built before this file does not hold it
    return path


def value_pairs(run: dict, n: int = 5) -> dict[str, pd.DataFrame]:
    """Per differing column: the n most frequent (left value, right value) pairs with count and %."""
    if not cells_table(run):
        return {}
    con = run["con"]
    df = con.execute(f"""
        SELECT column_name AS col, coalesce(left_value, {lit(label(None))}) AS a,
               coalesce(right_value, {lit(label(None))}) AS b,
               count(*) AS n, count(*) * 100.0 / sum(count(*)) OVER (PARTITION BY column_name) AS pct
        FROM cd GROUP BY 1, 2, 3
        QUALIFY row_number() OVER (PARTITION BY column_name ORDER BY count(*) DESC, a, b) <= {int(n)}
        ORDER BY col, n DESC, a, b""").fetchdf()
    return {col: sub.drop(columns=["col"]).reset_index(drop=True) for col, sub in df.groupby("col", sort=False)}


def bucket_profile(run: dict, keys: list[str], cols: list[str], bucket: str,
                   n: int = 10, only: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Top values per column for one bucket of rows: 'matched' (paired on the key),
    'differ' (paired but not equal), 'left' (only in A) or 'right' (only in B). Key columns
    first. For paired buckets each value is counted on both sides, since a non-key column
    can differ. `only` names the columns to profile - nothing else is measured, which is
    what keeps a wide pair from counting hundreds of columns nobody asked to see; without
    it every column is. Each column is measured once per bucket and kept on the run."""
    con, cfg = run["con"], run["cfg"]
    every = list(keys) + [c for c in cols if c not in keys]
    wanted = every if only is None else [c for c in every if c in set(only)]
    cache: dict[str, pd.DataFrame] = run.setdefault("_profiles", {}).setdefault(bucket, {})
    todo = [c for c in wanted if c not in cache]
    if todo:
        if bucket in ("left", "right"):
            _one_side_profile(run, bucket, todo, cache, n)
        elif keys:
            _paired_profile(run, keys, bucket, todo, cache, n)
    return {c: cache[c] for c in wanted if c in cache}


def _counts_frame(df: pd.DataFrame, total: int, names: list[str]) -> pd.DataFrame:
    """A (value, count) frame as the page shows it: the label, the count, and the share of
    the bucket's rows - a frame counted on both sides (v, na, nb) has no single share."""
    df["v"] = df["v"].map(label)
    if "n" in df.columns:
        df["%"] = (df["n"] / max(total, 1) * 100).round(2)
    df.columns = names
    return df


def _one_side_profile(run: dict, bucket: str, todo: list[str], cache: dict, n: int) -> None:
    """The one-sided rows - read from the run's left_only / right_only file, once."""
    con, cfg = run["con"], run["cfg"]
    f = run["files"].get(f"{cfg['name']}__{bucket}_only.csv")
    if not f:
        return
    if run.get("_one_side") != bucket:
        con.execute(f"CREATE OR REPLACE TABLE one_side AS SELECT * FROM "
                    f"read_csv({lit(str(f))}, all_varchar=true)")
        run["_one_side"] = bucket
    have = {r[0] for r in con.execute("DESCRIBE one_side").fetchall()}
    total = con.execute("SELECT count(*) FROM one_side").fetchone()[0]
    for c in todo:
        if c not in have:
            continue
        df = con.execute(f"SELECT {ident(c)} AS v, count(*) AS n FROM one_side "
                         f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(n)}").fetchdf()
        cache[c] = _counts_frame(df, total, ["Value", "Rows", "%"])


def _paired_profile(run: dict, keys: list[str], bucket: str, todo: list[str],
                    cache: dict, n: int) -> None:
    """The paired rows - matched on the key, or matched but not equal. The rows are held
    once per bucket with the key and the columns asked for, a side each."""
    con = run["con"]
    pair_views(run, keys)
    picks = ", ".join([f"l.{ident(k)} AS {ident(k)}" for k in keys]
                      + [f"l.{ident(c)} AS {ident('a_' + c)}, r.{ident(c)} AS {ident('b_' + c)}"
                         for c in todo if c not in keys])
    if bucket == "matched":                       # every row that paired on the key
        con.execute(f"CREATE OR REPLACE TABLE differ AS SELECT {picks} "
                    f"FROM cmp_l l JOIN cmp_r r ON {join_on(keys)}")
    else:                                         # paired on the key, but not equal
        if not cells_table(run):
            return
        occ = cd_occ(run)
        con.execute(f"CREATE OR REPLACE TABLE differ AS SELECT {picks} "
                    f"FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} "
                    f"WHERE {row_key(keys, 'l.', '__occ' if occ else None)} IN (SELECT {row_key(keys, '', occ)} FROM cd)")
    total = con.execute("SELECT count(*) FROM differ").fetchone()[0]
    for c in todo:
        if c in keys:
            df = con.execute(f"SELECT {ident(c)} AS v, count(*) AS n FROM differ "
                             f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(n)}").fetchdf()
            cache[c] = _counts_frame(df, total, ["Value", "Rows", "%"])
        else:
            a, b = ident("a_" + c), ident("b_" + c)
            df = con.execute(f"""
                WITH ca AS (SELECT {a} AS v, count(*) AS na FROM differ GROUP BY 1),
                     cb AS (SELECT {b} AS v, count(*) AS nb FROM differ GROUP BY 1)
                SELECT coalesce(ca.v, cb.v) AS v, coalesce(na, 0) AS na, coalesce(nb, 0) AS nb
                FROM ca FULL OUTER JOIN cb ON ca.v IS NOT DISTINCT FROM cb.v
                ORDER BY greatest(coalesce(na, 0), coalesce(nb, 0)) DESC, 1 LIMIT {int(n)}""").fetchdf()
            cache[c] = _counts_frame(df, total, ["Value", "Rows A", "Rows B"])


def near_match(cells_path: str) -> pd.DataFrame:
    """How close the differing values are - high similarity means formatting, not data."""
    con = scratch()
    l, r = "coalesce(left_value, '')", "coalesce(right_value, '')"
    dist = f"levenshtein({l}, {r})"
    span = f"greatest(length({l}), length({r}), 1)"
    sql = (f'SELECT column_name AS "Column", count(*) AS "Mismatches", '
           f'round(avg({dist}), 2) AS "Avg edit distance", '
           f'round(100 * avg(1 - least(1.0, {dist}::DOUBLE / {span})), 1) AS "Similarity %" '
           f"FROM read_csv({lit(cells_path)}, all_varchar=true) "
           f'GROUP BY 1 ORDER BY "Similarity %" DESC')
    return con.execute(sql).fetchdf()


def style_pairs(df: pd.DataFrame, marks: dict[int, set[str]]):
    """A rows black on ink, B rows ink on cream; differing cells in the trouble colour.
    Built as arrays rather than cell by cell - a few thousand rows style in milliseconds."""
    import numpy as np

    def paint(frame: pd.DataFrame) -> pd.DataFrame:
        is_a = (frame["Side"].to_numpy() == "A")
        base = np.where(is_a, f"background-color:{LEFT_BG};color:{LEFT_FG}",
                        f"background-color:{RIGHT_BG};color:{RIGHT_FG}")
        css = np.repeat(base[:, None], len(frame.columns), axis=1).astype(object)
        col_pos = {c: j for j, c in enumerate(frame.columns)}
        for i, cols in marks.items():                 # i = position of the A row of a pair
            for c in cols:
                j = col_pos.get(c)
                if j is None:
                    continue
                for k, style in ((i, LEFT_DIFF), (i + 1, RIGHT_DIFF)):
                    if k < len(frame):
                        css[k, j] = style + ";font-weight:600"
        return pd.DataFrame(css, index=frame.index, columns=frame.columns)
    return df.style.apply(paint, axis=None)
