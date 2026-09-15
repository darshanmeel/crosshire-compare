#!/usr/bin/env python3
"""
csvdiff.py - generic, config-driven CSV comparison powered by DuckDB.

Compares two CSV files (or two folders of CSV files) and reports:
  * rows present only on the left / only on the right
  * cell-level differences for rows that matched
  * schema differences (columns only on one side)

Matching strategies
-------------------
  key         join on one or more business-key columns (recommended)
  row_number  compare line 1 vs line 1, line 2 vs line 2, ... ("row by row")
  multiset    order-independent set comparison with duplicate counts
  auto        key if keys are configured, else row_number

Everything runs inside DuckDB, so files much larger than RAM are fine.
Only CSV (and CSV-like delimited text) is supported, by design.

Usage
-----
  python csvdiff.py file  a.csv b.csv --keys id --out out/
  python csvdiff.py folder dir_a dir_b --out out/ --keys id
  python csvdiff.py config diff_config.yaml --out out/
  python csvdiff.py init-config dir_a dir_b -o diff_config.yaml

Exit codes: 0 = identical, 1 = differences found, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:  # pragma: no cover
    sys.exit("duckdb is required:  pip install duckdb")

SRC = "duckdb://"   # left/right may name an existing relation instead of a file
RN = "__rn__"       # internal row number column
LRN, RRN = "__lrn__", "__rrn__"   # left/right row number kept through the join
OCC = "__occ__"     # internal occurrence index (for duplicate keys)
INTERNAL = (RN, OCC, LRN, RRN)


# --------------------------------------------------------------------------
# SQL helpers
# --------------------------------------------------------------------------
def ident(name: str) -> str:
    """Quote an identifier."""
    return '"' + str(name).replace('"', '""') + '"'


DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_OP_ALIASES = {"=": "eq", "==": "eq", "!=": "ne", "<>": "ne", ">": "gt", ">=": "ge",
               "<": "lt", "<=": "le", "~": "regex", "not in": "not_in",
               "not like": "not_like", "is null": "is_null", "is not null": "not_null"}

_WHERE_RE = re.compile(
    r"""^\s*(?P<col>[^\s:<>=!~]+)(?::(?P<type>string|number|date))?\s*
         (?P<op>between|not\s+in|in|is\s+not\s+null|is\s+null|not\s+like|ilike|like|
                ~|>=|<=|!=|<>|=|>|<)
         \s*(?P<val>.*)$""",
    re.IGNORECASE | re.VERBOSE)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_where(expr: str) -> tuple[str, dict[str, Any]]:
    """Parse a compact filter such as::

        order_date:date between 2024-01-01..2024-03-31
        region in EU,US,APAC
        amount:number >= 100
        status != CANCELLED
        note is null

    into ``(column, {op: value})``.
    """
    m = _WHERE_RE.match(expr)
    if not m:
        raise ValueError(f"cannot parse filter {expr!r}")
    col = _unquote(m["col"])
    op = re.sub(r"\s+", " ", m["op"].strip().lower())
    op = _OP_ALIASES.get(op, op)
    raw = _unquote(m["val"])
    spec: dict[str, Any] = {}
    if m["type"]:
        spec["type"] = m["type"].lower()
    if op in ("is_null", "not_null"):
        spec[op] = True
    elif op == "between":
        parts = re.split(r"\.\.|\s+and\s+", raw, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            raise ValueError(
                f"between needs two bounds separated by '..' or 'and', got {raw!r} "
                f"- e.g. \"{col} between 2026-07-20..2026-07-31\"")
        spec["between"] = [_unquote(parts[0]), _unquote(parts[1])]
    elif op in ("in", "not_in"):
        spec[op] = [_unquote(v) for v in raw.split(",") if v.strip()]
    else:
        spec[op] = _unquote(raw)
    return col, spec


def strip_bom(name: str) -> str:
    """DuckDB keeps the UTF-8 BOM in the first header name; drop it."""
    for prefix in ("\ufeff", "\\xef\\xbb\\xbf", "\xef\xbb\xbf"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def lit(value: Any) -> str:
    """Quote a string literal."""
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------------------
# Configuration objects
# --------------------------------------------------------------------------
@dataclass
class ColumnRule:
    """Per-column comparison behaviour."""
    type: str = "string"                # string | number | date
    tolerance: float | None = None      # absolute tolerance (number)
    rel_tolerance: float | None = None  # relative tolerance, 0.01 = 1%
    format: str | None = None           # strptime format, both sides
    left_format: str | None = None
    right_format: str | None = None
    ignore_case: bool | None = None
    ignore: bool = False                # skip this column entirely

    @staticmethod
    def parse(raw: Any) -> "ColumnRule":
        if isinstance(raw, str):                      # shorthand: "number"
            return ColumnRule(type=raw)
        if isinstance(raw, (int, float)):             # shorthand: 0.01
            return ColumnRule(type="number", tolerance=float(raw))
        known = {f for f in ColumnRule.__dataclass_fields__}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown column rule option(s): {sorted(unknown)}")
        return ColumnRule(**raw)


@dataclass
class Options:
    """Everything that can be set globally, per folder or per file pair."""
    # --- CSV parsing ---
    delimiter: str = ","
    quote: str = '"'
    escape: str = '"'
    header: bool = True
    encoding: str = "utf-8"
    nullstr: list[str] = field(default_factory=list)
    ignore_errors: bool = False

    # --- what to compare ---
    mode: str = "auto"                                     # auto|key|row_number|multiset
    keys: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)   # right name -> left name
    ignore_columns: list[str] = field(default_factory=list)
    only_columns: list[str] = field(default_factory=list)
    column_rules: dict[str, ColumnRule] = field(default_factory=dict)

    # --- how to compare ---
    case_insensitive_columns: bool = True   # match column *names* ignoring case
    trim: bool = True                       # strip surrounding whitespace
    treat_empty_as_null: bool = True        # '' and NULL are the same thing
    ignore_case_values: bool = False        # case-insensitive value compare
    tolerance: float = 0.0                  # global absolute numeric tolerance
    rel_tolerance: float = 0.0              # global relative numeric tolerance
    on_duplicate_keys: str = "index"        # index | first | error

    # --- row filters (applied to both files before matching) ---
    filters: dict[str, Any] = field(default_factory=dict)        # both sides
    left_filters: dict[str, Any] = field(default_factory=dict)   # left only
    right_filters: dict[str, Any] = field(default_factory=dict)  # right only
    filter_sql: str | None = None           # raw SQL escape hatch, both sides
    left_filter_sql: str | None = None
    right_filter_sql: str | None = None

    # --- output ---
    limit: int | None = None                # max diff rows written per file
    html: bool = True                       # write the side-by-side HTML report
    html_limit: int | None = 2000           # max rows per tab in the HTML report
    html_all_limit: int | None = 10000      # max rows in the "all rows" tab, 0 = off
    write_empty: bool = False               # write empty CSVs too, for a fixed file set

    def merged(self, override: dict[str, Any] | None) -> "Options":
        if not override:
            return self
        data = asdict(self)
        data["column_rules"] = dict(self.column_rules)
        for k, v in override.items():
            if v is None:
                continue
            if k in ("left", "right", "name", "defaults", "files"):
                continue
            if k not in data:
                raise ValueError(f"unknown option '{k}'")
            if k == "column_rules":
                rules = dict(data["column_rules"])
                rules.update({c: ColumnRule.parse(r) for c, r in v.items()})
                data[k] = rules
            elif k in ("column_map", "filters", "left_filters", "right_filters"):
                m = dict(data[k])
                m.update(v)
                data[k] = m
            elif k == "keys" and isinstance(v, str):
                data[k] = [s.strip() for s in v.split(",") if s.strip()]
            else:
                data[k] = v
        rules = data.pop("column_rules")
        opts = Options(**data)
        opts.column_rules = {c: (r if isinstance(r, ColumnRule) else ColumnRule.parse(r))
                             for c, r in rules.items()}
        return opts

    def rule_for(self, column: str) -> ColumnRule:
        for name, rule in self.column_rules.items():
            if self._fold(name) == self._fold(column):
                return rule
        return ColumnRule()

    def _fold(self, name: str) -> str:
        return name.lower() if self.case_insensitive_columns else name


@dataclass
class PairSpec:
    name: str
    left: str
    right: str
    options: Options


# --------------------------------------------------------------------------
# Result objects
# --------------------------------------------------------------------------
@dataclass
class PairResult:
    name: str
    left: str
    right: str
    mode: str = ""
    keys: list[str] = field(default_factory=list)
    rows_left: int = 0
    rows_right: int = 0
    rows_left_read: int = 0
    rows_right_read: int = 0
    filter_left: str | None = None
    filter_right: str | None = None
    matched_rows: int = 0
    only_left: int = 0
    only_right: int = 0
    cell_diffs: int = 0
    diff_rows: int = 0
    columns_compared: list[str] = field(default_factory=list)
    columns_only_left: list[str] = field(default_factory=list)
    columns_only_right: list[str] = field(default_factory=list)
    diffs_by_column: dict[str, int] = field(default_factory=dict)
    duplicate_keys_left: int = 0
    duplicate_keys_right: int = 0
    sample_unmatched_left: list[str] = field(default_factory=list)
    sample_unmatched_right: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    html: str | None = None
    error: str | None = None

    @property
    def identical(self) -> bool:
        return (self.error is None and not self.only_left and not self.only_right
                and not self.cell_diffs and not self.columns_only_left
                and not self.columns_only_right)

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        return "OK" if self.identical else "DIFF"


# --------------------------------------------------------------------------
# The comparer
# --------------------------------------------------------------------------
class CsvDiff:
    def __init__(self, con: duckdb.DuckDBPyConnection, verbose: bool = False):
        self.con = con
        self.verbose = verbose

    # ---------------- low level ----------------
    def _sql(self, sql: str):
        if self.verbose:
            print(f"-- SQL\n{sql}\n", file=sys.stderr)
        return self.con.execute(sql)

    def _read_csv_expr(self, path: str, o: Options) -> str:
        args = [
            lit(str(path)),
            "all_varchar = true",
            f"header = {'true' if o.header else 'false'}",
            f"delim = {lit(o.delimiter)}",
            f"quote = {lit(o.quote)}",
            f"escape = {lit(o.escape)}",
            "null_padding = true",
        ]
        if o.nullstr:
            args.append("nullstr = [" + ", ".join(lit(s) for s in o.nullstr) + "]")
        if o.encoding and o.encoding.lower().replace("-", "") != "utf8":
            args.append(f"encoding = {lit(o.encoding)}")
        if o.ignore_errors:
            args.append("ignore_errors = true")
        return f"read_csv({', '.join(args)})"

    def _load(self, table: str, path: str, o: Options) -> list[str]:
        """Materialise a side. `path` is a CSV file, or duckdb://<relation> for a
        table/view already present in the connection (used by the Streamlit app)."""
        if str(path).startswith(SRC):
            source = ident(str(path)[len(SRC):])
        else:
            if not Path(path).exists():
                raise FileNotFoundError(f"input file not found: {path}")
            source = self._read_csv_expr(path, o)
        self._sql(f"CREATE OR REPLACE TEMP TABLE {ident(table)} AS "
                  f"SELECT row_number() OVER () AS {ident(RN)}, * FROM {source}")
        cols = [r[0] for r in self.con.execute(f"DESCRIBE {ident(table)}").fetchall()]
        cols = [c for c in cols if c != RN]
        clash = [c for c in cols if c in INTERNAL]
        if clash:
            raise ValueError(f"{path}: column name(s) {clash} are reserved by csvdiff")
        return cols

    # ---------------- column resolution ----------------
    @staticmethod
    def _fold(name: str, o: Options) -> str:
        return name.lower() if o.case_insensitive_columns else name

    def _canonical(self, columns: list[str], o: Options, is_right: bool) -> dict[str, str]:
        """canonical name -> source column name."""
        mapping = {}
        if is_right:
            folded_map = {self._fold(k, o): v for k, v in o.column_map.items()}
        out: dict[str, str] = {}
        for col in columns:
            canon = strip_bom(col)
            if is_right:
                canon = folded_map.get(self._fold(canon, o), canon)
            canon = self._fold(canon, o)
            if canon in out:
                side = "right" if is_right else "left"
                raise ValueError(
                    f"{side} file: columns {out[canon]!r} and {col!r} both resolve to "
                    f"{canon!r} - fix column_map or disable case_insensitive_columns")
            out[canon] = col
        return out

    # ---------------- comparison expressions ----------------
    def _eq_expr(self, lref: str, rref: str, rule: ColumnRule, o: Options) -> str:
        ignore_case = o.ignore_case_values if rule.ignore_case is None else rule.ignore_case
        if ignore_case:
            str_eq = f"lower({lref}) IS NOT DISTINCT FROM lower({rref})"
        else:
            str_eq = f"{lref} IS NOT DISTINCT FROM {rref}"

        tol = o.tolerance if rule.tolerance is None else rule.tolerance
        rtol = o.rel_tolerance if rule.rel_tolerance is None else rule.rel_tolerance
        numeric = rule.type == "number" or tol > 0 or rtol > 0

        if rule.type == "date":
            lf = rule.left_format or rule.format
            rf = rule.right_format or rule.format
            lp = f"try_strptime({lref}, {lit(lf)})" if lf else f"try_cast({lref} AS TIMESTAMP)"
            rp = f"try_strptime({rref}, {lit(rf)})" if rf else f"try_cast({rref} AS TIMESTAMP)"
            cmp_expr = f"{lp} IS NOT DISTINCT FROM {rp}"
            return (f"CASE WHEN {lref} IS NULL AND {rref} IS NULL THEN TRUE "
                    f"WHEN {lref} IS NULL OR {rref} IS NULL THEN FALSE "
                    f"WHEN {lp} IS NOT NULL AND {rp} IS NOT NULL THEN {cmp_expr} "
                    f"ELSE {str_eq} END")

        if numeric:
            ln, rn = f"try_cast({lref} AS DOUBLE)", f"try_cast({rref} AS DOUBLE)"
            allowed = (f"greatest({tol}, {rtol} * greatest(abs({ln}), abs({rn})))"
                       if rtol else str(tol))
            num_eq = f"abs({ln} - {rn}) <= {allowed}"
            return (f"CASE WHEN {lref} IS NULL AND {rref} IS NULL THEN TRUE "
                    f"WHEN {lref} IS NULL OR {rref} IS NULL THEN FALSE "
                    f"WHEN {ln} IS NOT NULL AND {rn} IS NOT NULL THEN {num_eq} "
                    f"ELSE {str_eq} END")

        return str_eq

    # ---------------- row filters ----------------
    def _filter_col_expr(self, canon: str, ftype: str, o: Options, side: str,
                         date_only: bool) -> str:
        ref = ident(canon)
        if ftype == "number":
            return f"try_cast({ref} AS DOUBLE)"
        if ftype == "date":
            rule = o.rule_for(canon)
            fmt = (rule.left_format if side == "left" else rule.right_format) or rule.format
            expr = f"try_strptime({ref}, {lit(fmt)})" if fmt else f"try_cast({ref} AS TIMESTAMP)"
            return f"cast({expr} AS DATE)" if date_only else expr
        return ref

    @staticmethod
    def _filter_lit(value: Any, ftype: str, date_only: bool, col: str) -> str:
        if ftype == "number":
            try:
                return repr(float(str(value).strip()))
            except ValueError:
                raise ValueError(f"filter on {col!r}: {value!r} is not a number")
        if ftype == "date":
            cast = "DATE" if date_only else "TIMESTAMP"
            return f"cast({lit(value)} AS {cast})"
        return lit(value)

    def _column_filter(self, canon: str, spec: Any, o: Options, side: str) -> str:
        if isinstance(spec, list):
            spec = {"in": spec}
        elif not isinstance(spec, dict):
            spec = {"eq": spec}
        spec = {(_OP_ALIASES.get(str(k).strip().lower(), str(k).strip().lower())): v
                for k, v in spec.items()}
        ftype = spec.pop("type", None) or o.rule_for(canon).type or "string"

        values: list[Any] = []
        for op, val in spec.items():
            if op in ("is_null", "not_null"):
                continue
            values.extend(val if isinstance(val, (list, tuple)) else [val])
        date_only = ftype == "date" and all(DATE_ONLY.match(str(v)) for v in values)

        col = self._filter_col_expr(canon, ftype, o, side, date_only)
        raw = ident(canon)                      # text ops always use the raw value

        def val(v):
            return self._filter_lit(v, ftype, date_only, canon)

        parts = []
        for op, v in spec.items():
            if op == "eq":
                parts.append(f"{col} = {val(v)}")
            elif op == "ne":
                parts.append(f"{col} IS DISTINCT FROM {val(v)}")
            elif op in ("gt", "ge", "lt", "le"):
                sign = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}[op]
                parts.append(f"{col} {sign} {val(v)}")
            elif op == "in":
                parts.append(f"{col} IN ({', '.join(val(x) for x in v)})")
            elif op == "not_in":
                parts.append(f"({col} IS NULL OR {col} NOT IN "
                             f"({', '.join(val(x) for x in v)}))")
            elif op == "between":
                if not isinstance(v, (list, tuple)) or len(v) != 2:
                    raise ValueError(f"filter on {canon!r}: between needs [low, high]")
                parts.append(f"{col} BETWEEN {val(v[0])} AND {val(v[1])}")
            elif op in ("like", "ilike"):
                parts.append(f"{raw} {op.upper()} {lit(v)}")
            elif op == "not_like":
                parts.append(f"({raw} IS NULL OR {raw} NOT LIKE {lit(v)})")
            elif op == "regex":
                parts.append(f"regexp_matches({raw}, {lit(v)})")
            elif op == "is_null":
                parts.append(f"{raw} IS NULL" if v else f"{raw} IS NOT NULL")
            elif op == "not_null":
                parts.append(f"{raw} IS NOT NULL" if v else f"{raw} IS NULL")
            else:
                raise ValueError(f"filter on {canon!r}: unknown operator {op!r}")
        return "(" + " AND ".join(parts) + ")"

    def _compile_filters(self, o: Options, side: str, available: set[str]) -> str | None:
        specs = dict(o.filters)
        specs.update(o.left_filters if side == "left" else o.right_filters)
        parts = []
        for col, spec in specs.items():
            canon = self._fold(strip_bom(col), o)
            if canon not in available:
                raise ValueError(f"filter column {col!r} is not in the {side} file")
            parts.append(self._column_filter(canon, spec, o, side))
        raw_sql = o.filter_sql, (o.left_filter_sql if side == "left" else o.right_filter_sql)
        parts += [f"({sql})" for sql in raw_sql if sql]
        return " AND ".join(parts) if parts else None

    # ---------------- normalisation ----------------
    def _norm_view(self, view: str, table: str, canon: dict[str, str], o: Options,
                   where: str | None = None) -> None:
        parts = [ident(RN)]
        for name, src in canon.items():
            expr = ident(src)
            if o.trim:
                expr = f"trim({expr})"
            if o.treat_empty_as_null:
                expr = f"nullif({expr}, '')"
            parts.append(f"{expr} AS {ident(name)}")
        inner = f"SELECT {', '.join(parts)} FROM {ident(table)}"
        sql = inner if not where else f"SELECT * FROM ({inner}) WHERE {where}"
        self._sql(f"CREATE OR REPLACE TEMP VIEW {ident(view)} AS {sql}")

    def _keyed_view(self, view: str, src: str, keys: list[str], o: Options,
                    label: str = "") -> int:
        """Add an occurrence index so duplicate keys line up. Returns dup count."""
        part = ", ".join(ident(k) for k in keys)
        dups = self.con.execute(
            f"SELECT coalesce(sum(n - 1), 0) FROM "
            f"(SELECT count(*) AS n FROM {ident(src)} GROUP BY {part} HAVING count(*) > 1)"
        ).fetchone()[0]
        if dups and o.on_duplicate_keys == "error":
            raise ValueError(f"{dups} duplicate key row(s) in {label or src} "
                             f"(keys: {', '.join(keys)})")
        if o.on_duplicate_keys == "first":
            self._sql(f"CREATE OR REPLACE TEMP VIEW {ident(view)} AS "
                      f"SELECT *, 1 AS {ident(OCC)} FROM {ident(src)} "
                      f"QUALIFY row_number() OVER (PARTITION BY {part} ORDER BY {ident(RN)}) = 1")
        else:
            self._sql(f"CREATE OR REPLACE TEMP VIEW {ident(view)} AS "
                      f"SELECT *, row_number() OVER (PARTITION BY {part} "
                      f"ORDER BY {ident(RN)}) AS {ident(OCC)} FROM {ident(src)}")
        return int(dups)

    # ---------------- output ----------------
    def _dump(self, table: str, path: Path, o: Options, res: PairResult) -> int:
        n = self.con.execute(f"SELECT count(*) FROM {ident(table)}").fetchone()[0]
        if n or o.write_empty:
            path.parent.mkdir(parents=True, exist_ok=True)
            limit = f" LIMIT {int(o.limit)}" if o.limit else ""
            self._sql(f"COPY (SELECT * FROM {ident(table)}{limit}) TO {lit(str(path))} "
                      f"(FORMAT CSV, HEADER, DELIMITER ',')")
            res.outputs.append(str(path))
        return int(n)

    # ---------------- main entry point ----------------
    def compare(self, spec: PairSpec, out_dir: Path) -> PairResult:
        o = spec.options
        res = PairResult(name=spec.name, left=str(spec.left), right=str(spec.right))
        try:
            self._compare(spec, o, out_dir, res)
        except Exception as exc:  # keep the batch going
            msg = str(exc).strip().splitlines()[0][:300]
            res.error = f"{type(exc).__name__}: {msg}"
        return res

    def _compare(self, spec: PairSpec, o: Options, out_dir: Path, res: PairResult) -> None:
        lcols = self._load("__l_raw", spec.left, o)
        rcols = self._load("__r_raw", spec.right, o)
        lcanon = self._canonical(lcols, o, is_right=False)
        rcanon = self._canonical(rcols, o, is_right=True)

        res.rows_left_read = self.con.execute("SELECT count(*) FROM __l_raw").fetchone()[0]
        res.rows_right_read = self.con.execute("SELECT count(*) FROM __r_raw").fetchone()[0]
        res.columns_only_left = [c for c in lcanon if c not in rcanon]
        res.columns_only_right = [c for c in rcanon if c not in lcanon]

        lwhere = self._compile_filters(o, "left", set(lcanon))
        rwhere = self._compile_filters(o, "right", set(rcanon))
        res.filter_left, res.filter_right = lwhere, rwhere
        self._norm_view("__l", "__l_raw", lcanon, o, lwhere)
        self._norm_view("__r", "__r_raw", rcanon, o, rwhere)
        res.rows_left = (self.con.execute("SELECT count(*) FROM __l").fetchone()[0]
                         if lwhere else res.rows_left_read)
        res.rows_right = (self.con.execute("SELECT count(*) FROM __r").fetchone()[0]
                          if rwhere else res.rows_right_read)

        common = [c for c in lcanon if c in rcanon]
        ignored = {self._fold(c, o) for c in o.ignore_columns}
        only = {self._fold(c, o) for c in o.only_columns}
        keys = [self._fold(k, o) for k in o.keys]

        missing_keys = [k for k in keys if k not in common]
        mode = o.mode
        if mode == "auto":
            mode = "key" if keys else "row_number"
        if mode == "key" and missing_keys:
            print(f"  ! {spec.name}: key column(s) {missing_keys} not present in both "
                  f"files - falling back to row_number matching", file=sys.stderr)
            keys, mode = [], "row_number"
        res.mode, res.keys = mode, keys

        compare_cols = [
            c for c in common
            if c not in keys
            and c not in ignored
            and (not only or c in only)
            and not o.rule_for(c).ignore
        ]
        res.columns_compared = compare_cols

        base = out_dir / spec.name
        for stale in ("cell_diffs.csv", "left_only.csv", "right_only.csv",
                      "row_count_diffs.csv", "diff.html"):
            old = base / f"{spec.name}__{stale}"
            if old.exists():
                old.unlink()
        if mode == "multiset":
            self._multiset(spec, o, res, base, compare_cols, keys)
            return

        join_cols = keys if mode == "key" else [RN]
        if mode == "key":
            res.duplicate_keys_left = self._keyed_view("__lk", "__l", keys, o, spec.left)
            res.duplicate_keys_right = self._keyed_view("__rk", "__r", keys, o, spec.right)
            if o.on_duplicate_keys == "index":
                join_cols = keys + [OCC]
            lsrc, rsrc = "__lk", "__rk"
        else:
            lsrc, rsrc = "__l", "__r"

        on = " AND ".join(f"l.{ident(k)} IS NOT DISTINCT FROM r.{ident(k)}" for k in join_cols)
        rn_alias = "row_number"
        while rn_alias in lcanon or rn_alias in rcanon:
            rn_alias = "_" + rn_alias
        key_out = [(RN, rn_alias)] if mode == "row_number" else \
                  [(k, k) for k in keys] + ([(OCC, "occurrence")]
                                            if OCC in join_cols and
                                            (res.duplicate_keys_left or res.duplicate_keys_right)
                                            else [])

        sel = [f"l.{ident(RN)} IS NOT NULL AS __in_l__",
               f"r.{ident(RN)} IS NOT NULL AS __in_r__",
               f"l.{ident(RN)} AS {ident(LRN)}", f"r.{ident(RN)} AS {ident(RRN)}"]
        sel += [f"coalesce(l.{ident(k)}, r.{ident(k)}) AS {ident(k)}" for k in join_cols]
        sel += [f"l.{ident(c)} AS {ident('l__' + c)}, r.{ident(c)} AS {ident('r__' + c)}"
                for c in compare_cols]
        self._sql(f"CREATE OR REPLACE TEMP TABLE __joined AS SELECT {', '.join(sel)} "
                  f"FROM {ident(lsrc)} l FULL OUTER JOIN {ident(rsrc)} r ON {on}")

        res.matched_rows = self.con.execute(
            "SELECT count(*) FROM __joined WHERE __in_l__ AND __in_r__").fetchone()[0]

        # rows present on one side only (full original rows, keys included)
        anti = " AND ".join(f"x.{ident(k)} IS NOT DISTINCT FROM y.{ident(k)}" for k in join_cols)
        rn_col = f"x.{ident(RN)} AS {ident(rn_alias)}, " if mode == "row_number" else ""
        for side, src, other, label in (("left", lsrc, rsrc, "only_left"),
                                        ("right", rsrc, lsrc, "only_right")):
            tbl = f"__{side}_only"
            self._sql(
                f"CREATE OR REPLACE TEMP TABLE {ident(tbl)} AS "
                f"SELECT {rn_col}x.* EXCLUDE "
                f"({ident(RN)}{', ' + ident(OCC) if mode == 'key' else ''}) "
                f"FROM {ident(src)} x WHERE NOT EXISTS "
                f"(SELECT 1 FROM {ident(other)} y WHERE {anti})")
            setattr(res, label, self._dump(tbl, base / f"{spec.name}__{side}_only.csv", o, res))

        # a poor match rate almost always means the key values are formatted
        # differently on the two sides - grab samples so the user can see it
        floor = min(res.rows_left, res.rows_right)
        if mode == "key" and floor and res.matched_rows < 0.9 * floor:
            ksel = " || ' | ' || ".join(f"coalesce({ident(k)}, '<null>')" for k in keys)
            for tbl, attr in (("__left_only", "sample_unmatched_left"),
                              ("__right_only", "sample_unmatched_right")):
                setattr(res, attr, [r[0] for r in self.con.execute(
                    f"SELECT {ksel} FROM {ident(tbl)} LIMIT 3").fetchall()])

        # cell level differences
        neq = {}
        diff_expr = "[]::VARCHAR[]"
        if compare_cols:
            neq = {
                col: "NOT coalesce({}, FALSE)".format(
                    self._eq_expr(f"j.{ident('l__' + col)}", f"j.{ident('r__' + col)}",
                                  o.rule_for(col), o))
                for col in compare_cols}
            structs = ",\n    ".join(
                "{{'column': {c}, 'left_value': {lv}, 'right_value': {rv}, 'differs': {d}}}".format(
                    c=lit(col), lv=f"j.{ident('l__' + col)}", rv=f"j.{ident('r__' + col)}",
                    d=neq[col])
                for col in compare_cols)
            keysel = ", ".join(f"j.{ident(src)} AS {ident(alias)}" for src, alias in key_out)
            # only rows that actually differ are kept, which keeps both the
            # unnest and the HTML report cheap even on very wide tables
            any_diff = "\n               OR ".join(neq[c] for c in compare_cols)
            diff_cols = ", ".join(f"CASE WHEN {neq[c]} THEN {lit(c)} END" for c in compare_cols)
            diff_expr = f"list_filter([{diff_cols}], x -> x IS NOT NULL)"
            self._sql(
                f"CREATE OR REPLACE TEMP TABLE __diff_rows AS\n"
                f"SELECT *, {diff_expr} AS __diff_cols__\n"
                f"FROM __joined j\n"
                f"WHERE j.__in_l__ AND j.__in_r__ AND ({any_diff})")
            self._sql(
                f"CREATE OR REPLACE TEMP TABLE __cells AS\n"
                f"SELECT {keysel}, u.\"column\" AS column_name, u.left_value, u.right_value\n"
                f"FROM __diff_rows j,\n"
                f"     UNNEST([\n    {structs}\n]) AS t(u)\n"
                f"WHERE u.differs")
            res.diff_rows = self.con.execute(
                "SELECT count(*) FROM __diff_rows").fetchone()[0]
            res.cell_diffs = self._dump("__cells", base / f"{spec.name}__cell_diffs.csv", o, res)
            if res.cell_diffs:
                res.diffs_by_column = dict(self.con.execute(
                    "SELECT column_name, count(*) FROM __cells GROUP BY 1 ORDER BY 2 DESC"
                ).fetchall())
        else:
            self._sql("CREATE OR REPLACE TEMP TABLE __diff_rows AS "
                      "SELECT *, []::VARCHAR[] AS __diff_cols__ FROM __joined WHERE FALSE")

        if o.html:
            self._html_report(spec, o, res, base, lcanon, rcanon, lsrc, rsrc,
                              join_cols, key_out, compare_cols, ignored, diff_expr)

    # ---------------- html ----------------
    def _fetch(self, sql: str) -> tuple[list[str], list[tuple]]:
        cur = self._sql(sql)
        return [d[0] for d in cur.description], cur.fetchall()

    def _html_report(self, spec: PairSpec, o: Options, res: PairResult, base: Path,
                     lcanon: dict, rcanon: dict, lsrc: str, rsrc: str,
                     join_cols: list[str], key_out: list[tuple[str, str]],
                     compare_cols: list[str], ignored: set, diff_expr: str) -> None:
        limit = int(o.html_limit or 0) or None
        keyed = res.mode == "key"
        key_names = [alias for _, alias in key_out]

        # every column of either file, keys first, left order then right extras
        columns = key_names + [c for c in lcanon if c not in key_names]
        columns += [c for c in rcanon if c not in columns]

        # full left + right row for a set of matched rows, in file order
        def row_pairs(source: str, diff_expr: str, cap: int | None,
                      where: str = "") -> list[dict]:
            if not cap:
                return []
            sel = [f"j.{ident(src)} AS {ident('K__' + alias)}" for src, alias in key_out]
            sel += [f"l.{ident(c)} AS {ident('L__' + c)}" for c in lcanon]
            sel += [f"r.{ident(c)} AS {ident('R__' + c)}" for c in rcanon]
            sel.append(f"{diff_expr} AS __diff_cols__")
            on_l = " AND ".join(f"j.{ident(k)} IS NOT DISTINCT FROM l.{ident(k)}"
                                for k in join_cols)
            on_r = " AND ".join(f"j.{ident(k)} IS NOT DISTINCT FROM r.{ident(k)}"
                                for k in join_cols)
            cols, rows = self._fetch(
                f"SELECT {', '.join(sel)} FROM {source} j "
                f"JOIN {ident(lsrc)} l ON {on_l} JOIN {ident(rsrc)} r ON {on_r} "
                + (f"WHERE {where} " if where else "")
                + f"ORDER BY coalesce(j.{ident(LRN)}, j.{ident(RRN)}) LIMIT {cap}")
            idx = {c: i for i, c in enumerate(cols)}
            out = []
            for row in rows:
                keyvals = {a: row[idx["K__" + a]] for _, a in key_out}
                out.append({
                    "left": dict(keyvals, **{c: row[idx["L__" + c]] for c in lcanon}),
                    "right": dict(keyvals, **{c: row[idx["R__" + c]] for c in rcanon}),
                    "diffs": list(row[idx["__diff_cols__"]] or []),
                })
            return out

        pairs = row_pairs("__diff_rows", "j.__diff_cols__", limit)
        all_rows = row_pairs("__joined", diff_expr, int(o.html_all_limit or 0),
                             where="j.__in_l__ AND j.__in_r__")

        def side_rows(table: str) -> list[dict]:
            if not self.con.execute(
                    f"SELECT count(*) FROM information_schema.tables "
                    f"WHERE table_name = {lit(table)}").fetchone()[0]:
                return []
            c, r = self._fetch(f"SELECT * FROM {ident(table)}"
                               + (f" LIMIT {limit}" if limit else ""))
            return [dict(zip(c, row)) for row in r]

        left_only = side_rows("__left_only")
        right_only = side_rows("__right_only")
        csvs = [(label, f"{spec.name}__{stem}.csv")
                for label, stem in (("cell diffs", "cell_diffs"),
                                    ("left only", "left_only"),
                                    ("right only", "right_only"),
                                    ("row counts", "row_count_diffs"))
                if (base / f"{spec.name}__{stem}.csv").exists()]
        report = {
            "name": spec.name, "left_path": spec.left, "right_path": spec.right,
            "csvs": csvs,
            "mode": res.mode, "keys": key_names, "columns": columns,
            "left_columns": set(lcanon) | set(key_names),
            "right_columns": set(rcanon) | set(key_names),
            "compared": set(compare_cols),
            "ignored": {c for c in columns if c in ignored},
            "diff_columns": set(res.diffs_by_column),
            "pairs": pairs,
            "all_rows": all_rows,
            "left_only": left_only,
            "right_only": right_only,
            "result": res,
            "truncated": {
                "all rows": res.matched_rows > len(all_rows),
                "differing rows": bool(limit) and len(pairs) >= limit,
                "left only": res.only_left > len(left_only),
                "right only": res.only_right > len(right_only),
            },
        }
        if not (pairs or left_only or right_only):
            return
        path = base / f"{spec.name}__diff.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_html(report), encoding="utf-8")
        res.html = str(path)
        res.outputs.append(str(path))

    def _multiset(self, spec, o: Options, res: PairResult, base: Path,
                  compare_cols: list[str], keys: list[str]) -> None:
        cols = keys + compare_cols
        if not cols:
            raise ValueError("multiset mode needs at least one comparable column")
        sel = ", ".join(ident(c) for c in cols)
        on = " AND ".join(f"l.{ident(c)} IS NOT DISTINCT FROM r.{ident(c)}" for c in cols)
        coal = ", ".join(f"coalesce(l.{ident(c)}, r.{ident(c)}) AS {ident(c)}" for c in cols)
        self._sql(f"""
            CREATE OR REPLACE TEMP TABLE __ms AS
            WITH lg AS (SELECT {sel}, count(*) AS n FROM __l GROUP BY ALL),
                 rg AS (SELECT {sel}, count(*) AS n FROM __r GROUP BY ALL)
            SELECT {coal}, coalesce(l.n, 0) AS left_count, coalesce(r.n, 0) AS right_count
            FROM lg l FULL OUTER JOIN rg r ON {on}
            WHERE coalesce(l.n, 0) <> coalesce(r.n, 0)
        """)
        res.only_left = self.con.execute(
            "SELECT coalesce(sum(greatest(left_count - right_count, 0)), 0) FROM __ms").fetchone()[0]
        res.only_right = self.con.execute(
            "SELECT coalesce(sum(greatest(right_count - left_count, 0)), 0) FROM __ms").fetchone()[0]
        self._dump("__ms", base / f"{spec.name}__row_count_diffs.csv", o, res)
        res.matched_rows = min(res.rows_left, res.rows_right) - min(res.only_left, res.only_right)
        if o.html:
            limit = int(o.html_limit or 0) or None
            names, rows = self._fetch(f"SELECT * FROM __ms"
                                      + (f" LIMIT {limit}" if limit else ""))
            data = [dict(zip(names, row)) for row in rows]
            side = {"left": [d for d in data if d["left_count"] > d["right_count"]],
                    "right": [d for d in data if d["right_count"] > d["left_count"]]}
            rep = {
                "name": spec.name, "left_path": spec.left, "right_path": spec.right,
                "csvs": [("row counts", f"{spec.name}__row_count_diffs.csv")]
                        if (base / f"{spec.name}__row_count_diffs.csv").exists() else [],
                "mode": res.mode, "keys": keys, "columns": names,
                "left_columns": set(names), "right_columns": set(names),
                "compared": set(compare_cols), "ignored": set(), "diff_columns": set(),
                "pairs": [], "all_rows": [],
                "left_only": side["left"], "right_only": side["right"],
                "result": res,
                "truncated": {"left only": bool(limit) and len(rows) >= limit,
                              "right only": bool(limit) and len(rows) >= limit},
            }
            if data:
                path = base / f"{spec.name}__diff.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_html(rep), encoding="utf-8")
                res.html = str(path)
                res.outputs.append(str(path))


# --------------------------------------------------------------------------
# Config file handling
# --------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".json",):
        return json.loads(text)
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML is needed for YAML configs (pip install pyyaml), "
                         "or use a .json config file instead")
    return yaml.safe_load(text) or {}


def list_csvs(folder: Path, pattern: str, recursive: bool) -> dict[str, Path]:
    it = folder.rglob("*") if recursive else folder.glob("*")
    out = {}
    for p in sorted(it):
        if p.is_file() and fnmatch.fnmatch(p.name, pattern):
            out[str(p.relative_to(folder))] = p
    return out


def pair_folders(left_dir: Path, right_dir: Path, pattern: str, recursive: bool,
                 case_insensitive: bool = True) -> tuple[list[tuple[str, Path, Path]], list[str], list[str]]:
    left = list_csvs(left_dir, pattern, recursive)
    right = list_csvs(right_dir, pattern, recursive)
    rkey = {(k.lower() if case_insensitive else k): k for k in right}
    pairs, unmatched_left = [], []
    for name, lpath in left.items():
        match = rkey.get(name.lower() if case_insensitive else name)
        if match:
            pairs.append((name, lpath, right[match]))
        else:
            unmatched_left.append(name)
    matched_right = {m for _, _, m in [(n, l, right[rkey[n.lower() if case_insensitive else n]])
                                       for n, l in left.items()
                                       if (n.lower() if case_insensitive else n) in rkey]}
    unmatched_right = [n for n, p in right.items() if p not in matched_right]
    return pairs, unmatched_left, unmatched_right


def build_specs(cfg: dict, base_opts: Options, cli_override: dict) -> tuple[list[PairSpec], list[str]]:
    defaults = base_opts.merged(cfg.get("defaults") or {}).merged(cli_override)
    specs: dict[str, PairSpec] = {}
    notes: list[str] = []

    for entry in cfg.get("folders") or []:
        ldir, rdir = Path(entry["left_dir"]), Path(entry["right_dir"])
        pattern = entry.get("pattern", "*.csv")
        recursive = bool(entry.get("recursive", False))
        fdefaults = defaults.merged(entry.get("defaults") or {}).merged(cli_override)
        pairs, ul, ur = pair_folders(ldir, rdir, pattern, recursive)
        notes += [f"only in {ldir}: {n}" for n in ul] + [f"only in {rdir}: {n}" for n in ur]
        per_file = entry.get("files") or {}
        for name, lp, rp in pairs:
            opts = fdefaults.merged(per_file.get(name) or per_file.get(Path(name).stem) or {})
            key = name[:-4] if name.lower().endswith(".csv") else name
            specs[key] = PairSpec(key.replace(os.sep, "_"), str(lp), str(rp), opts)

    for entry in cfg.get("pairs") or []:
        name = entry.get("name") or Path(entry["left"]).stem
        try:
            opts = defaults.merged(entry).merged(cli_override)
        except ValueError as exc:
            raise SystemExit(f"config error in pair '{name}': {exc}")
        specs[name] = PairSpec(name, entry["left"], entry["right"], opts)

    return list(specs.values()), notes


def generate_config(left_dir: Path, right_dir: Path, pattern: str, recursive: bool) -> str:
    pairs, ul, ur = pair_folders(left_dir, right_dir, pattern, recursive)
    lines = [
        "# csvdiff configuration - generated skeleton",
        "defaults:",
        "  keys: []                 # business key column(s) used to match rows",
        "  trim: true",
        "  treat_empty_as_null: true",
        "  case_insensitive_columns: true",
        "  tolerance: 0             # absolute numeric tolerance for every column",
        "  ignore_columns: []",
        "",
        "pairs:",
    ]
    for name, lp, rp in pairs:
        stem = Path(name).stem
        try:
            with open(lp, newline="", encoding="utf-8", errors="replace") as fh:
                lhead = next(csv.reader(fh), [])
            with open(rp, newline="", encoding="utf-8", errors="replace") as fh:
                rhead = next(csv.reader(fh), [])
        except OSError:
            lhead = rhead = []
        extra_right = [c for c in rhead if c.lower() not in {x.lower() for x in lhead}]
        lines += [
            f"  - name: {stem}",
            f"    left: {lp}",
            f"    right: {rp}",
            f"    keys: []               # columns available: {', '.join(lhead) or 'n/a'}",
            "    column_map: {}         # right_column: left_column"
            + (f"   # unmatched on right: {', '.join(extra_right)}" if extra_right else ""),
            "    ignore_columns: []",
            "    column_rules: {}       # amount: {type: number, tolerance: 0.01}",
            "",
        ]
    for n in ul:
        lines.append(f"# no counterpart on the right: {n}")
    for n in ur:
        lines.append(f"# no counterpart on the left:  {n}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# HTML report
# --------------------------------------------------------------------------
_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#ffffff;color:#1f2328;
     font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{padding:18px 22px 12px;border-bottom:1px solid #d8dee4}
h1{margin:0 0 6px;font-size:17px;font-weight:650}
.files{display:flex;flex-wrap:wrap;gap:8px;align-items:center;color:#656d76;
       font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.chip{display:inline-block;padding:1px 7px;border-radius:11px;font-weight:700;font-size:11px}
.chip.l{background:#eef4ff;color:#0a4a9e;border:1px solid #bcd3f7}
.chip.r{background:#fff6e8;color:#9a5b00;border:1px solid #f2d5a8}
.stats{margin-top:10px;display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:#656d76}
.stats b{color:#1f2328;font-variant-numeric:tabular-nums}
nav{display:flex;gap:2px;padding:0 22px;border-bottom:1px solid #d8dee4;background:#fafbfc}
thead th{top:0}
nav button{border:0;border-bottom:2px solid transparent;background:none;padding:10px 14px;
           font:inherit;font-size:13px;color:#656d76;cursor:pointer}
nav button:hover{color:#1f2328}
nav button.on{color:#1f2328;border-bottom-color:#0969da;font-weight:600}
nav .n{display:inline-block;margin-left:6px;padding:0 6px;border-radius:9px;
       background:#e7ebef;color:#4a5157;font-size:11px;font-variant-numeric:tabular-nums}
.toolbar{display:flex;gap:14px;align-items:center;padding:10px 22px;flex-wrap:wrap;
         border-bottom:1px solid #d8dee4}
.toolbar input[type=search]{padding:5px 9px;border:1px solid #d8dee4;border-radius:6px;
         font:inherit;font-size:13px;min-width:230px}
.toolbar label{font-size:12.5px;color:#656d76;display:flex;gap:5px;align-items:center;
         cursor:pointer;user-select:none}
.legend{margin-left:auto;display:flex;gap:14px;font-size:11.5px;color:#656d76}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;
          vertical-align:-1px;border:1px solid rgba(0,0,0,.12)}
.pred{margin-top:5px;font:11.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
      color:#656d76;overflow-wrap:anywhere}
.pred .chip{margin-right:6px}
a.dl{color:#0969da;text-decoration:none;border:1px solid #d8dee4;border-radius:6px;
     padding:1px 8px;font-size:12px;background:#fff}
a.dl:hover{background:#f4f8ff;border-color:#0969da}
.wrap{padding-bottom:40px}
table{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;
      font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
th,td{padding:5px 9px;border-bottom:1px solid #d8dee4;text-align:left;vertical-align:top;
      white-space:pre-wrap;overflow-wrap:anywhere;max-width:340px}
thead th{position:sticky;top:0;z-index:3;background:#f4f5f7;border-bottom:1px solid #c7ced6;
         font-family:inherit;font-size:11.5px;font-weight:650;letter-spacing:.02em;
         text-transform:uppercase;color:#4a5157;white-space:nowrap}
thead th.ignored{color:#8b949e;font-style:italic}
tbody.grp>tr:first-child>td{border-top:1px solid #c7ced6}
tr.l td{background:#eef4ff}
tr.r td{background:#fff6e8}
tr.l td.src{color:#0a4a9e} tr.r td.src{color:#9a5b00}
td.src{position:sticky;left:0;z-index:2;font-weight:700;text-align:center;width:26px;
       border-right:1px solid #d8dee4}
thead th.src{left:0;z-index:4;background:#f4f5f7}
td.key{font-weight:650}
td.diff{background:#ffe3e3!important;color:#b0202b;font-weight:700;
        box-shadow:inset 2px 0 0 #e5484d}
tbody.dirty td.src{box-shadow:inset 3px 0 0 #e5484d}
td.na{background:#f6f8fa!important;color:#b0b7bf;font-style:italic}
.null{color:#9aa2ab;font-style:italic}
.hidesame td.same,.hidesame th.same{display:none}
.empty{padding:34px 22px;color:#656d76;font-size:13px}
.note{padding:9px 22px;background:#fff8e1;border-bottom:1px solid #f0e0b0;font-size:12.5px}
section{display:none} section.on{display:block}
"""

_JS = """
const tabs=[...document.querySelectorAll('nav button')];
const secs=[...document.querySelectorAll('section')];
tabs.forEach(b=>b.onclick=()=>{
  tabs.forEach(x=>x.classList.toggle('on',x===b));
  secs.forEach(s=>s.classList.toggle('on',s.id==='tab-'+b.dataset.tab));
  document.getElementById('search').value='';filter();
});
const cache=new WeakMap();
function rowText(g){let t=cache.get(g);if(t===undefined){t=g.textContent.toLowerCase();cache.set(g,t);}return t;}
function filter(){
  const q=document.getElementById('search').value.toLowerCase();
  const sec=document.querySelector('section.on');if(!sec)return;
  let shown=0;
  sec.querySelectorAll('tbody.grp').forEach(g=>{
    const hit=!q||rowText(g).includes(q);
    g.style.display=hit?'':'none';if(hit)shown++;
  });
  document.getElementById('shown').textContent=q?shown+' matching':'';
}
let timer;
document.getElementById('search').oninput=()=>{clearTimeout(timer);timer=setTimeout(filter,150);};
document.getElementById('onlydiff').onchange=e=>{
  document.querySelectorAll('table').forEach(t=>t.classList.toggle('hidesame',e.target.checked));
};
"""


def _cell(value: Any) -> str:
    if value is None:
        return '<span class="null">null</span>'
    text = str(value)
    return html.escape(text) if text != "" else '<span class="null">empty</span>'


def render_html(rep: dict) -> str:
    res = rep["result"]
    cols: list[str] = rep["columns"]
    keys = set(rep["keys"])
    # a column is "interesting" if it is a key or differs somewhere
    same = {c for c in cols if c not in keys and c not in rep["diff_columns"]}

    only_l = {c for c in cols if c in rep["left_columns"] and c not in rep["right_columns"]}
    only_r = {c for c in cols if c in rep["right_columns"] and c not in rep["left_columns"]}
    skipped = {c for c in cols if c not in keys and c not in rep["compared"]
               and c not in only_l and c not in only_r}

    def head() -> str:
        cells = ['<th class="src"></th>']
        for c in cols:
            klass = []
            if c in same:
                klass.append("same")
            if c in skipped or c in only_l or c in only_r:
                klass.append("ignored")
            if c in only_l:
                mark, why = "<sup>L</sup>", "only in the left file"
            elif c in only_r:
                mark, why = "<sup>R</sup>", "only in the right file"
            elif c in skipped:
                mark, why = "*", "present in both files but not compared"
            else:
                mark, why = "", "compared"
            attr = f' class="{" ".join(klass)}"' if klass else ""
            cells.append(f'<th{attr} title="{html.escape(c)} - {why}">'
                         f'{html.escape(c)}{mark}</th>')
        return "<thead><tr>" + "".join(cells) + "</tr></thead>"

    def row(data: dict, side: str, diffs: set[str], present: set[str]) -> str:
        tds = [f'<td class="src">{side.upper()}</td>']
        for c in cols:
            klass = []
            if c in same:
                klass.append("same")
            if c in keys:
                klass.append("key")
            if c in diffs:
                klass.append("diff")
            if c not in present:
                tds.append(f'<td class="{" ".join(klass + ["na"])}">n/a</td>')
            else:
                attr = f' class="{" ".join(klass)}"' if klass else ""
                tds.append(f"<td{attr}>{_cell(data.get(c))}</td>")
        return f'<tr class="{side}">' + "".join(tds) + "</tr>"

    def table(body: str) -> str:
        return f'<div class="wrap"><table>{head()}{body}</table></div>'

    # ---- matched rows, left row above right row ----
    def pair_table(items: list[dict], mark_clean: bool) -> str:
        body = []
        for p in items:
            diffs = set(p["diffs"])
            klass = "grp dirty" if diffs and mark_clean else "grp"
            body.append(f'<tbody class="{klass}">'
                        + row(p["left"], "l", diffs, rep["left_columns"])
                        + row(p["right"], "r", diffs, rep["right_columns"])
                        + "</tbody>")
        return table("".join(body))

    cells_tab = (pair_table(rep["pairs"], False) if rep["pairs"]
                 else '<div class="empty">No differing values in matched rows.</div>')
    all_tab = (pair_table(rep["all_rows"], True) if rep["all_rows"]
               else '<div class="empty">No matched rows.</div>')

    def one_side(rows: list[dict], side: str, present: set[str], noun: str) -> str:
        if not rows:
            return f'<div class="empty">No rows {noun}.</div>'
        return table("".join('<tbody class="grp">' + row(r, side, set(), present) + "</tbody>"
                             for r in rows))

    left_tab = one_side(rep["left_only"], "l", rep["left_columns"],
                        "present only in the left file")
    right_tab = one_side(rep["right_only"], "r", rep["right_columns"],
                         "present only in the right file")

    all_button = (f'<button data-tab="all">All rows'
                  f'<span class="n">{res.matched_rows:,}</span></button>'
                  if rep["all_rows"] else "")
    all_section = (f'<section id="tab-all">{all_tab}</section>'
                   if rep["all_rows"] else "")

    totals = {"all rows": (len(rep["all_rows"]), res.matched_rows),
              "differing rows": (len(rep["pairs"]), res.diff_rows),
              "left only": (len(rep["left_only"]), res.only_left),
              "right only": (len(rep["right_only"]), res.only_right)}
    trunc = [f"{k} ({totals[k][0]:,} of {totals[k][1]:,})"
             for k, v in rep["truncated"].items() if v and k in totals]
    note = (f'<div class="note"><b>Truncated:</b> {"; ".join(trunc)}. '
            f'Raise --html-all-limit / --html-limit to show more here; the CSV files next '
            f'to this report always hold the complete diff result.</div>' if trunc else "")

    links = ""
    if rep.get("csvs"):
        links = ('<div class="stats"><span>csv:</span>'
                 + "".join(f'<a class="dl" href="{html.escape(f)}" download>{html.escape(l)}</a>'
                           for l, f in rep["csvs"]) + "</div>")

    def col_list(names):
        names = sorted(names)
        shown = ", ".join(names[:6]) + (f" +{len(names) - 6} more" if len(names) > 6 else "")
        return html.escape(shown)

    columns_note = [f"<b>{len(rep['compared'])}</b> compared"]
    if skipped:
        columns_note.append(f"<b>{len(skipped)}</b> not compared ({col_list(skipped)})")
    if only_l:
        columns_note.append(f"<b>{len(only_l)}</b> only in left ({col_list(only_l)})")
    if only_r:
        columns_note.append(f"<b>{len(only_r)}</b> only in right ({col_list(only_r)})")

    stats = [f"rows read <b>{res.rows_left_read:,}</b> / <b>{res.rows_right_read:,}</b>"]
    preds = ""
    if res.filter_left or res.filter_right:
        stats.append(f"after filter <b>{res.rows_left:,}</b> / <b>{res.rows_right:,}</b> "
                     f"(everything below is this subset)")
        if res.filter_left == res.filter_right:
            preds = f'<div class="pred">filter: {html.escape(res.filter_left)}</div>'
        else:
            preds = "".join(
                f'<div class="pred"><span class="chip {side[0]}">{side[0].upper()}</span>'
                f'{html.escape(sql)}</div>'
                for side, sql in (("left", res.filter_left), ("right", res.filter_right)) if sql)
    stats += [f"columns {' &middot; '.join(columns_note)}",
              f"matched <b>{res.matched_rows:,}</b>",
              f"only left <b>{res.only_left:,}</b>",
              f"only right <b>{res.only_right:,}</b>",
              f"differing rows <b>{res.diff_rows:,}</b>",
              f"differing cells <b>{res.cell_diffs:,}</b>"]
    filters = "".join(f"<span>{x}</span>" for x in stats) + "</div>" + preds

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>csvdiff - {html.escape(rep["name"])}</title>
<style>{_CSS}</style></head><body>
<header>
  <h1>{html.escape(rep["name"])}</h1>
  <div class="files">
    <span class="chip l">L</span>{html.escape(rep["left_path"])}
    <span class="chip r">R</span>{html.escape(rep["right_path"])}
  </div>
  <div class="stats">
    <span>matched on <b>{html.escape(", ".join(rep["keys"]) or rep["mode"])}</b></span>
    {filters}
  {links}
</header>
<nav>
  <button class="on" data-tab="cells">Differing rows<span class="n">{res.diff_rows:,}</span></button>
  <button data-tab="left">Left only<span class="n">{res.only_left:,}</span></button>
  <button data-tab="right">Right only<span class="n">{res.only_right:,}</span></button>
  {all_button}
</nav>
<div class="toolbar">
  <input type="search" id="search" placeholder="filter rows...">
  <label><input type="checkbox" id="onlydiff"> only columns with differences</label>
  <span id="shown" style="font-size:12px;color:#656d76"></span>
  <span class="legend">
    <span><i style="background:#eef4ff"></i>left</span>
    <span><i style="background:#fff6e8"></i>right</span>
    <span><i style="background:#ffe3e3"></i>different</span>
    <span><i style="background:#f6f8fa"></i>not in this file</span>
    <span>* not compared</span>
    <span>L / R only in that file</span>
  </span>
</div>
{note}
<section id="tab-cells" class="on">{cells_tab}</section>
<section id="tab-left">{left_tab}</section>
<section id="tab-right">{right_tab}</section>
{all_section}
<script>{_JS}</script>
</body></html>
"""


def render_index(results: list[PairResult], out_dir: Path) -> str:
    rows = []
    for r in results:
        link = (f'<a href="{html.escape(os.path.relpath(r.html, out_dir))}">'
                f'{html.escape(r.name)}</a>') if r.html else html.escape(r.name)
        colour = {"OK": "#1a7f37", "DIFF": "#b0202b", "ERROR": "#9a5b00"}[r.status]
        rows.append(
            f"<tr><td>{link}</td><td>{html.escape(r.mode or '-')}</td>"
            f"<td>{r.rows_left}</td><td>{r.rows_right}</td><td>{r.matched_rows}</td>"
            f"<td>{r.only_left}</td><td>{r.only_right}</td><td>{r.cell_diffs}</td>"
            f'<td style="color:{colour};font-weight:700">{r.status}</td></tr>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>csvdiff - summary</title><style>{_CSS}
table{{width:auto;margin:18px 22px;font-size:13px}}
td,th{{border-bottom:1px solid #d8dee4}} a{{color:#0969da}}
</style></head><body>
<header><h1>csvdiff summary</h1>
<div class="stats"><span><b>{len(results)}</b> file pairs</span>
<span><b>{sum(1 for r in results if r.status == 'OK')}</b> identical</span>
<span><b>{sum(1 for r in results if r.status == 'DIFF')}</b> with differences</span></div>
</header>
<table><thead><tr><th>pair</th><th>mode</th><th>rows L</th><th>rows R</th><th>matched</th>
<th>only L</th><th>only R</th><th>cell diffs</th><th>status</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
</body></html>
"""


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def print_report(results: list[PairResult], out_dir: Path) -> None:
    headers = ["pair", "mode", "rows L", "rows R", "matched", "only L", "only R",
               "cell diffs", "status"]
    def num(v):
        return f"{v:,}"
    def rows_cell(shown, read):
        return num(shown) if shown == read else f"{num(shown)} of {num(read)}"
    rows = [[r.name, r.mode or "-",
             rows_cell(r.rows_left, r.rows_left_read),
             rows_cell(r.rows_right, r.rows_right_read),
             num(r.matched_rows), num(r.only_left), num(r.only_right),
             num(r.cell_diffs), r.status] for r in results]
    widths = [max(len(str(h)), *(len(str(row[i])) for row in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print("\n" + line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))

    for r in results:
        if r.error:
            print(f"\n! {r.name}: {r.error}")
            continue
        details = []
        if r.filter_left or r.filter_right:
            details.append(f"comparing {r.rows_left:,} of {r.rows_left_read:,} left rows "
                           f"and {r.rows_right:,} of {r.rows_right_read:,} right rows")
            if r.filter_left == r.filter_right:
                details.append(f"  filter: {r.filter_left}")
            else:
                for side, sql in (("left", r.filter_left), ("right", r.filter_right)):
                    if sql:
                        details.append(f"  filter ({side}): {sql}")
        if r.columns_only_left:
            details.append(f"columns only in left : {', '.join(r.columns_only_left)}")
        if r.columns_only_right:
            details.append(f"columns only in right: {', '.join(r.columns_only_right)}")
        if r.duplicate_keys_left or r.duplicate_keys_right:
            details.append(f"duplicate key rows: left={r.duplicate_keys_left} "
                           f"right={r.duplicate_keys_right}")
        if r.diffs_by_column:
            top = ", ".join(f"{c} ({n:,})" for c, n in list(r.diffs_by_column.items())[:8])
            details.append(f"differing columns: {top}")
        if r.sample_unmatched_left or r.sample_unmatched_right:
            floor = min(r.rows_left, r.rows_right) or 1
            details.append(
                f"only {r.matched_rows:,} of {floor:,} rows matched on "
                f"{'+'.join(r.keys)} - if that looks wrong the key values are probably "
                f"formatted differently on the two sides:")
            for side, sample in (("left ", r.sample_unmatched_left),
                                 ("right", r.sample_unmatched_right)):
                for value in sample:
                    details.append(f"  unmatched {side}: {value}")
        if details:
            print(f"\n{r.name}:")
            for d in details:
                print(f"  {d}")

    def write_summary(rows: list[PairResult], folder: Path, stem: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{stem}.json").write_text(
            json.dumps([asdict(r) for r in rows], indent=2), encoding="utf-8")
        with open(folder / f"{stem}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["pair", "left", "right", "mode", "keys", "rows_left_read",
                        "rows_right_read", "rows_left", "rows_right", "matched",
                        "only_left", "only_right", "diff_rows", "cell_diffs",
                        "columns_only_left", "columns_only_right",
                        "filter_left", "filter_right", "status", "error"])
            for r in rows:
                w.writerow([r.name, r.left, r.right, r.mode, "|".join(r.keys),
                            r.rows_left_read, r.rows_right_read, r.rows_left, r.rows_right,
                            r.matched_rows, r.only_left, r.only_right, r.diff_rows,
                            r.cell_diffs, "|".join(r.columns_only_left),
                            "|".join(r.columns_only_right), r.filter_left or "",
                            r.filter_right or "", r.status, r.error or ""])

    # each pair keeps its own summary next to its own diff files
    for r in results:
        write_summary([r], out_dir / r.name, f"{r.name}__summary")
    # a roll-up at the top level only when there is more than one pair
    if len(results) > 1:
        write_summary(results, out_dir, "summary")

    htmls = [r for r in results if r.html]
    if htmls:
        if len(results) > 1:
            (out_dir / "index.html").write_text(render_index(results, out_dir),
                                                encoding="utf-8")
            print(f"\nopen {out_dir / 'index.html'}")
        else:
            print(f"\nopen {htmls[0].html}")
    print(f"reports written to {out_dir}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def cli_overrides(args) -> dict:
    over: dict[str, Any] = {}
    for name in ("mode", "delimiter", "quote", "encoding", "on_duplicate_keys", "limit",
                 "tolerance", "rel_tolerance", "html_limit"):
        val = getattr(args, name, None)
        if val is not None:
            over[name] = val
    if getattr(args, "keys", None):
        over["keys"] = [k.strip() for k in args.keys.split(",") if k.strip()]
    if getattr(args, "ignore", None):
        over["ignore_columns"] = [c.strip() for c in args.ignore.split(",") if c.strip()]
    if getattr(args, "only", None):
        over["only_columns"] = [c.strip() for c in args.only.split(",") if c.strip()]
    if getattr(args, "map", None):
        over["column_map"] = dict(m.split("=", 1) for m in args.map)
    for flag, target in (("where", "filters"), ("where_left", "left_filters"),
                         ("where_right", "right_filters")):
        exprs = getattr(args, flag, None)
        if exprs:
            merged: dict[str, Any] = {}
            for expr in exprs:
                try:
                    col, spec = parse_where(expr)
                except ValueError as exc:
                    raise SystemExit(
                        f"{exc}\nexpected e.g. \"date:date between 2024-01-01..2024-03-31\", "
                        f"\"region in EU,US\", \"amount:number >= 100\", \"status != VOID\"")
                merged.setdefault(col, {}).update(spec)
            over[target] = merged
    if getattr(args, "filter_sql", None):
        over["filter_sql"] = args.filter_sql
    if getattr(args, "no_header", False):
        over["header"] = False
    if getattr(args, "no_html", False):
        over["html"] = False
    if getattr(args, "write_empty", False):
        over["write_empty"] = True
    if getattr(args, "html_limit", None) is not None:
        over["html_limit"] = args.html_limit
    if getattr(args, "html_all_limit", None) is not None:
        over["html_all_limit"] = args.html_all_limit
    if getattr(args, "ignore_case_values", False):
        over["ignore_case_values"] = True
    return over


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="csvdiff", description="Compare CSV files row by row with DuckDB.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--out", "-o", default="diff_out", help="output folder")
        sp.add_argument("--keys", help="comma separated key columns")
        sp.add_argument("--map", action="append", metavar="RIGHT=LEFT",
                        help="rename a right column (repeatable)")
        sp.add_argument("--ignore", help="comma separated columns to skip")
        sp.add_argument("--only", help="comma separated columns to compare "
                                       "(everything else is ignored)")
        sp.add_argument("--mode", choices=["auto", "key", "row_number", "multiset"])
        sp.add_argument("--tolerance", type=float, help="absolute numeric tolerance")
        sp.add_argument("--rel-tolerance", dest="rel_tolerance", type=float,
                        help="relative numeric tolerance, e.g. 0.01 for 1%%")
        sp.add_argument("--ignore-case-values", action="store_true")
        sp.add_argument("--where", action="append", metavar="EXPR",
                        help="row filter applied to both files, repeatable, e.g. "
                             "--where \"order_date:date between 2024-01-01..2024-03-31\" "
                             "--where \"region in EU,US\"")
        sp.add_argument("--where-left", dest="where_left", action="append", metavar="EXPR",
                        help="row filter for the left file only")
        sp.add_argument("--where-right", dest="where_right", action="append", metavar="EXPR",
                        help="row filter for the right file only")
        sp.add_argument("--filter-sql", dest="filter_sql",
                        help="raw SQL predicate applied to both files")
        sp.add_argument("--delimiter", "-d")
        sp.add_argument("--quote")
        sp.add_argument("--encoding")
        sp.add_argument("--no-header", action="store_true")
        sp.add_argument("--on-duplicate-keys", dest="on_duplicate_keys",
                        choices=["index", "first", "error"])
        sp.add_argument("--limit", type=int, help="max rows written per output file")
        sp.add_argument("--no-html", action="store_true",
                        help="skip the side-by-side HTML report")
        sp.add_argument("--write-empty", dest="write_empty", action="store_true",
                        help="write every CSV even when empty, so the file set is fixed")
        sp.add_argument("--html-limit", dest="html_limit", type=int,
                        help="max rows shown per HTML tab (default 2000)")
        sp.add_argument("--html-all-limit", dest="html_all_limit", type=int,
                        help="max rows in the 'all rows' tab (default 10000, 0 = no tab)")
        sp.add_argument("--memory-limit", help="e.g. 4GB")
        sp.add_argument("--threads", type=int)
        sp.add_argument("--temp-dir", help="spill directory for large joins")
        sp.add_argument("--no-fail-on-diff", action="store_true",
                        help="always exit 0, even when differences are found")
        sp.add_argument("--verbose", "-v", action="store_true", help="print generated SQL")

    sp = sub.add_parser("file", help="compare two CSV files")
    sp.add_argument("left"); sp.add_argument("right"); sp.add_argument("--name")
    common(sp)

    sp = sub.add_parser("folder", help="compare every CSV in two folders")
    sp.add_argument("left_dir"); sp.add_argument("right_dir")
    sp.add_argument("--pattern", default="*.csv")
    sp.add_argument("--recursive", "-r", action="store_true")
    common(sp)

    sp = sub.add_parser("config", help="run the comparisons described in a config file")
    sp.add_argument("config")
    common(sp)

    sp = sub.add_parser("init-config", help="write a config skeleton for two folders")
    sp.add_argument("left_dir"); sp.add_argument("right_dir")
    sp.add_argument("--pattern", default="*.csv")
    sp.add_argument("--recursive", "-r", action="store_true")
    sp.add_argument("--out", "-o", default="csvdiff_config.yaml")

    args = p.parse_args(argv)

    if args.cmd == "init-config":
        text = generate_config(Path(args.left_dir), Path(args.right_dir),
                               args.pattern, args.recursive)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
        return 0

    out_dir = Path(args.out)
    over = cli_overrides(args)
    base = Options()
    notes: list[str] = []

    if args.cmd == "file":
        name = args.name or Path(args.left).stem
        specs = [PairSpec(name, args.left, args.right, base.merged(over))]
    elif args.cmd == "folder":
        cfg = {"folders": [{"left_dir": args.left_dir, "right_dir": args.right_dir,
                            "pattern": args.pattern, "recursive": args.recursive}]}
        specs, notes = build_specs(cfg, base, over)
    else:
        cfg = load_config(Path(args.config))
        specs, notes = build_specs(cfg, base, over)

    if not specs:
        print("nothing to compare", file=sys.stderr)
        return 2

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = true")
    if args.memory_limit:
        con.execute(f"SET memory_limit = {lit(args.memory_limit)}")
    if args.threads:
        con.execute(f"SET threads = {int(args.threads)}")
    if args.temp_dir:
        con.execute(f"SET temp_directory = {lit(args.temp_dir)}")

    differ = CsvDiff(con, verbose=args.verbose)
    results = []
    for spec in specs:
        print(f"comparing {spec.name}: {spec.left} <-> {spec.right}")
        results.append(differ.compare(spec, out_dir))

    for n in notes:
        print(f"  ! unmatched file - {n}", file=sys.stderr)
    print_report(results, out_dir)

    if any(r.error for r in results):
        return 2
    if any(not r.identical for r in results) or notes:
        return 0 if args.no_fail_on_diff else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
