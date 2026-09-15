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
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .profile import label
from .sources import Side
from .sql import ident, lit, scratch
from .theme import THEME
from .values import ColSpec, ReadOptions, register

OPS = ["=", "!=", ">", ">=", "<", "<=", "in", "not in", "between", "like", "is null", "is not null"]
OP_MAP = {"=": "eq", "!=": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le",
          "in": "in", "not in": "not_in", "between": "between", "like": "like",
          "is null": "is_null", "is not null": "not_null"}
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
def build_filters(rows: pd.DataFrame, name_a: str, name_b: str) -> tuple[dict, dict, dict]:
    both: dict[str, Any] = {}
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    for _, r in rows.iterrows():
        col, op = str(r.get("Column") or "").strip(), str(r.get("Operator") or "").strip()
        if not col or not op:
            continue
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
        where = str(r.get("Apply to") or "Both")
        target = both if where == "Both" else left if where == name_a else \
            right if where == name_b else both
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
    """Everything that changes the answer. Used to spot a stale result."""
    payload = {"a": [a.label, a.rows, a.read_key, list(a.schema)],
               "b": [b.label, b.rows, b.read_key, list(b.schema)],
               "cfg": {k: v for k, v in cfg.items() if k != "name"}}
    return json.dumps(payload, sort_keys=True, default=str)


# ---- running ---------------------------------------------------------------
def run_comparison(A: Side, B: Side, cfg: dict, opts: ReadOptions, sig: str = "",
                   previous: dict | None = None, progress=None) -> dict:
    say = progress or (lambda _m: None)
    mode = cfg["mode"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys = list(cfg["keys"]) if mode == "key" else []
    con = scratch(ordered=True)   # file order is what pairs duplicate keys (1st with 1st) - keep it
    out = Path(tempfile.mkdtemp(prefix="cmp_"))
    folder = out / cfg["name"]
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
    say(f"Done in {elapsed:.1f}s - writing the summary…")
    record = asdict(res)
    (folder / f"{cfg['name']}__summary.json").write_text(
        json.dumps({"settings": {k: v for k, v in cfg.items() if k != "display_rows"},
                    "result": record}, indent=2, default=str), encoding="utf-8")
    pd.DataFrame([{k: (", ".join(map(str, v)) if isinstance(v, (list, dict)) else v)
                   for k, v in record.items()}]).to_csv(
        folder / f"{cfg['name']}__summary.csv", index=False)
    files = {p.name: p for p in folder.glob("*")}
    return {"result": res, "folder": folder, "files": files, "seconds": elapsed,
            "con": con, "left": "src_a", "right": "src_b", "cfg": cfg, "signature": sig,
            "at": time.strftime("%H:%M:%S"), "mode": mode}


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
        "html_limit": cfg["display_rows"],
        "html_all_limit": cfg["display_rows"],
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
    picks = ", ".join(ident(c) for c in cols)
    h = "hash(concat_ws(chr(1), " + ", ".join(f"coalesce({ident(c)}, chr(2))" for c in cols) + "))"
    say(f"Hashing every row over {len(cols)} columns on both sides…")
    for side in ("src_a", "src_b"):
        con.execute(f"CREATE OR REPLACE TABLE h_{side[-1]} AS "
                    f"SELECT {h} AS __h, row_number() OVER (PARTITION BY {h}) AS __k, {picks} "
                    f"FROM {side}")
    res.rows_left = res.rows_left_read = con.execute("SELECT count(*) FROM h_a").fetchone()[0]
    res.rows_right = res.rows_right_read = con.execute("SELECT count(*) FROM h_b").fetchone()[0]
    say("Matching identical rows…")
    res.matched_rows = con.execute(
        "SELECT count(*) FROM h_a a JOIN h_b b ON a.__h = b.__h AND a.__k = b.__k").fetchone()[0]
    for tag, mine, other, fname in (("left", "h_a", "h_b", "left_only"),
                                    ("right", "h_b", "h_a", "right_only")):
        path = folder / f"{cfg['name']}__{fname}.csv"
        con.execute(f"COPY (SELECT {picks} FROM {mine} m WHERE NOT EXISTS (SELECT 1 FROM {other} o "
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
    """cmp_l / cmp_r with row number and occurrence index - built as tables once per run so
    every follow-up table (by key value, profiles, differing rows) is a plain join."""
    con = run["con"]
    if run.get("_pair_keys") == tuple(keys):
        return
    for side, name in (("left", "cmp_l"), ("right", "cmp_r")):
        ordered_view(con, run[side], f"{name}_v", keys)
        con.execute(f"CREATE OR REPLACE TABLE {ident(name)} AS SELECT * FROM {ident(name + '_v')}")
    run["_pair_keys"] = tuple(keys)


def discard_run(run: dict | None) -> None:
    """Remove a run's temp folder - only ever called once a newer run has replaced it."""
    if run and run.get("folder"):
        shutil.rmtree(Path(run["folder"]).parent, ignore_errors=True)


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


def matched_values(run: dict, cols: list[str], cap: int = 50000) -> pd.DataFrame:
    """A sample of the rows that paired, both sides side by side."""
    if "matched_sample" in run:
        return run["matched_sample"]
    cfg, con = run["cfg"], run["con"]
    keys = cfg["keys"] if run["mode"] == "key" else []
    pair_views(run, keys)
    picks = ([f"l.{ident(k)} AS {ident('k_' + k)}" for k in keys]
             + [f"l.{ident(c)} AS {ident('a_' + c)}" for c in cols]
             + [f"r.{ident(c)} AS {ident('b_' + c)}" for c in cols])
    df = (con.execute(f"SELECT {', '.join(picks)} FROM cmp_l l JOIN cmp_r r "
                      f"ON {join_on(keys)} ORDER BY l.__rn LIMIT {int(cap)}").fetchdf()
          if picks else pd.DataFrame())
    run["matched_sample"] = df
    return df


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


def paired_frame(run: dict, keys: list[str], cols: list[str], limit: int) -> pd.DataFrame:
    """Every paired row, A above B, for export."""
    con = run["con"]
    pair_views(run, keys)
    sel = ", ".join([f"l.{ident(k)} AS {ident('k_' + k)}" for k in keys]
                    + [f"l.{ident(c)} AS {ident('l_' + c)}" for c in cols]
                    + [f"r.{ident(c)} AS {ident('r_' + c)}" for c in cols])
    df = con.execute(f"SELECT {sel} FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} "
                     f"ORDER BY l.__rn LIMIT {int(limit)}").fetchdf()
    rows = []
    for _, row in df.iterrows():
        for side, prefix in (("A", "l_"), ("B", "r_")):
            rec = {"Side": side, **{k: row[f"k_{k}"] for k in keys},
                   **{c: row[f"{prefix}{c}"] for c in cols}}
            rows.append(rec)
    return pd.DataFrame(rows, columns=["Side"] + keys + cols) if rows else pd.DataFrame()


def bucket_profile(run: dict, keys: list[str], cols: list[str], bucket: str,
                   n: int = 10) -> dict[str, pd.DataFrame]:
    """Top values per column for one bucket of rows: 'matched' (paired on the key),
    'differ' (paired but not equal), 'left' (only in A) or 'right' (only in B). Key columns
    first. For paired buckets each value is counted on both sides, since a non-key column
    can differ."""
    con, cfg = run["con"], run["cfg"]
    cache = run.setdefault("_profiles", {})
    if bucket in cache:
        return cache[bucket]
    ordered = [k for k in keys] + [c for c in cols if c not in keys]
    out: dict[str, pd.DataFrame] = {}
    cache[bucket] = out                      # filled in place below
    if bucket in ("left", "right"):
        f = run["files"].get(f"{cfg['name']}__{bucket}_only.csv")
        if not f:
            return out
        con.execute(f"CREATE OR REPLACE TABLE one_side AS SELECT * FROM "
                    f"read_csv({lit(str(f))}, all_varchar=true)")
        have = {r[0] for r in con.execute("DESCRIBE one_side").fetchall()}
        total = con.execute("SELECT count(*) FROM one_side").fetchone()[0]
        for c in ordered:
            if c not in have:
                continue
            df = con.execute(f"SELECT {ident(c)} AS v, count(*) AS n FROM one_side "
                             f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(n)}").fetchdf()
            df["%"] = (df["n"] / max(total, 1) * 100).round(2)
            df["v"] = df["v"].map(label)
            df.columns = ["Value", "Rows", "%"]
            out[c] = df
        return out
    if not keys:
        return out
    pair_views(run, keys)
    picks = ", ".join([f"l.{ident(k)} AS {ident(k)}" for k in keys]
                      + [f"l.{ident(c)} AS {ident('a_' + c)}, r.{ident(c)} AS {ident('b_' + c)}"
                         for c in cols if c not in keys])
    if bucket == "matched":                       # every row that paired on the key
        con.execute(f"CREATE OR REPLACE TABLE differ AS SELECT {picks} "
                    f"FROM cmp_l l JOIN cmp_r r ON {join_on(keys)}")
    else:                                         # paired on the key, but not equal
        if not cells_table(run):
            return out
        occ = cd_occ(run)
        con.execute(f"CREATE OR REPLACE TABLE differ AS SELECT {picks} "
                    f"FROM cmp_l l JOIN cmp_r r ON {join_on(keys)} "
                    f"WHERE {row_key(keys, 'l.', '__occ' if occ else None)} IN (SELECT {row_key(keys, '', occ)} FROM cd)")
    total = con.execute("SELECT count(*) FROM differ").fetchone()[0]
    for c in ordered:
        if c in keys:
            df = con.execute(f"SELECT {ident(c)} AS v, count(*) AS n FROM differ "
                             f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {int(n)}").fetchdf()
            df["%"] = (df["n"] / max(total, 1) * 100).round(2)
            df["v"] = df["v"].map(label)
            df.columns = ["Value", "Rows", "%"]
        else:
            a, b = ident("a_" + c), ident("b_" + c)
            df = con.execute(f"""
                WITH ca AS (SELECT {a} AS v, count(*) AS na FROM differ GROUP BY 1),
                     cb AS (SELECT {b} AS v, count(*) AS nb FROM differ GROUP BY 1)
                SELECT coalesce(ca.v, cb.v) AS v, coalesce(na, 0) AS na, coalesce(nb, 0) AS nb
                FROM ca FULL OUTER JOIN cb ON ca.v IS NOT DISTINCT FROM cb.v
                ORDER BY greatest(coalesce(na, 0), coalesce(nb, 0)) DESC, 1 LIMIT {int(n)}""").fetchdf()
            df["v"] = df["v"].map(label)
            df.columns = ["Value", "Rows A", "Rows B"]
        out[c] = df
    return out


def top_values(series: pd.Series, total: int, n: int = 10) -> pd.DataFrame:
    counts = series.map(label).value_counts().head(n)
    return pd.DataFrame({"Value": counts.index, "Count": counts.values,
                         "%": (counts.values / max(total, 1) * 100).round(2)})


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
