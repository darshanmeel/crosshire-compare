"""How a value is read: transform steps, null folding, trim, then the type.

Both files are read as text. Each value on each side goes through the same
stages - the side's transform steps, null folding, trim, the pair's Type - and
comes out as canonical text, so both sides compare on the same thing. A value
that fails to convert keeps its original text, which makes it show up as a
difference instead of vanishing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

import duckdb
import pandas as pd

from .sources import Side, source_expr
from .sql import ident, lit, memory_limit_bytes, scratch

NUMERIC_TYPES = ("INT", "DECIMAL", "NUMERIC", "DOUBLE", "FLOAT", "REAL", "BIGINT",
                 "SMALLINT", "TINYINT", "HUGEINT", "NUMBER")
DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME")
TYPES = ["text", "number", "date", "timestamp", "boolean"]
CASES = ["", "ignore", "exact"]         # a text pair's case: blank follows the global switch
FALLBACK_FORMATS = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d",
                    "%d-%b-%Y", "%d %b %Y", "%b %d %Y"]
NULL_TOKENS_DEFAULT = "NULL, \\N, N/A, NA, NaN, None, (null)"

# what a date / time value looks like -> the strptime format that reads it
FORMAT_PRESETS = {
    "2026-08-27": "%Y-%m-%d", "27/08/2026": "%d/%m/%Y", "08/27/2026": "%m/%d/%Y",
    "20260827": "%Y%m%d", "27-08-2026": "%d-%m-%Y", "27.08.2026": "%d.%m.%Y",
    "27-Aug-2026": "%d-%b-%Y", "27 August 2026": "%d %B %Y", "Aug 27, 2026": "%b %d, %Y",
    "27/08/26": "%d/%m/%y", "2026-08-27 10:11:12": "%Y-%m-%d %H:%M:%S",
    "2026-08-27 10:11:12.123": "%Y-%m-%d %H:%M:%S.%g",
    "2026-08-27 10:11:12.123456": "%Y-%m-%d %H:%M:%S.%f",
    "2026-08-27T10:11:12": "%Y-%m-%dT%H:%M:%S", "27/08/2026 10:11": "%d/%m/%Y %H:%M",
    "27/08/2026 10:11:12 PM": "%d/%m/%Y %I:%M:%S %p", "20260827101112": "%Y%m%d%H%M%S",
}

# transform steps: label -> (template on x, parameter names). Text parameters are
# quoted, N / M are numbers, fmt is a strptime format, expr is a whole expression.
STEPS = {
    "trim": ("trim(x)", ()),
    "upper": ("upper(x)", ()),
    "lower": ("lower(x)", ()),
    "left N characters": ("left(x, {n})", ("n",)),
    "right N characters": ("right(x, {n})", ("n",)),
    "length": ("length(x)", ()),
    "characters from N, M long": ("substr(x, {n}, {m})", ("n", "m")),
    "replace text": ("replace(x, {a}, {b})", ("a", "b")),
    "regex replace": ("regexp_replace(x, {a}, {b}, 'g')", ("a", "b")),
    "remove spaces": ("replace(x, ' ', '')", ()),
    "collapse repeated spaces": ("regexp_replace(trim(x), ' +', ' ', 'g')", ()),
    "strip leading zeros": ("regexp_replace(x, '^0+', '')", ()),
    "pad left to N with C": ("lpad(x, {n}, {c})", ("n", "c")),
    "digits only": ("regexp_replace(x, '[^0-9]', '', 'g')", ()),
    "letters and digits only": ("regexp_replace(x, '[^A-Za-z0-9]', '', 'g')", ()),
    "part N split by S": ("split_part(x, {s}, {n})", ("s", "n")),
    "remove thousands separators": ("replace(x, ',', '')", ()),
    "to number": ("__number__", ()),
    "to timestamp": ("__timestamp__", ("fmt",)),
    "to date": ("__date__", ("fmt",)),
    "to boolean": ("__boolean__", ()),
    "custom expression": ("{expr}", ("expr",)),
}
PARAM_LABELS = {"n": "N", "m": "M", "a": "find", "b": "replace with", "c": "pad character",
                "s": "separator", "fmt": "format - blank tries the usual spellings",
                "expr": "expression, x = the value"}
NUMERIC_PARAMS = {"n", "m"}
TEXT_PARAMS = {"a", "b", "c", "s"}      # quoted into the SQL as typed, spaces included
NEEDED_TEXT = {"a", "c", "s"}           # blank: find does nothing, pad fails, split gives one character
CONVERSIONS = {"to number": "number", "to timestamp": "timestamp", "to date": "date",
               "to boolean": "boolean"}


@dataclass(frozen=True)
class ReadOptions:
    """The global switches under 'How values are read'."""
    tokens: tuple[str, ...] = tuple(t.strip() for t in NULL_TOKENS_DEFAULT.split(",")) + ("",)
    trim: bool = True

    @classmethod
    def from_state(cls, state) -> "ReadOptions":
        raw = str(state.get("null_tokens", NULL_TOKENS_DEFAULT))
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
        if state.get("opt_empty", True):
            tokens.append("")
        return cls(tuple(tokens), bool(state.get("opt_trim", True)))


@dataclass
class ColSpec:
    """One shared column: where it comes from on each side and how it is read.

    `case` is a text pair's own say on case - "ignore", "exact", or "" to follow the
    Ignore case in values switch; a pair of any other Type takes no notice of it.
    """
    canon: str
    a_src: str
    b_src: str
    kind: str = "text"
    a_steps: list = field(default_factory=list)
    b_steps: list = field(default_factory=list)
    tolerance: float = 0.0
    case: str = ""

    def src(self, which: str) -> str:
        return self.a_src if which == "A" else self.b_src

    def steps(self, which: str) -> list:
        return self.a_steps if which == "A" else self.b_steps

    def tx(self, which: str) -> str:
        return compile_steps(self.steps(which))

    def case_rule(self) -> bool | None:
        """The engine's ignore_case for this column: True, False, or None to follow the switch."""
        if self.kind != "text" or self.case not in ("ignore", "exact"):
            return None
        return self.case == "ignore"

    def describe(self, which: str | None = None) -> str:
        """How the column is read, for captions: 'date · B: trim → to date (%d/%m/%Y)',
        'text · ignore case'."""
        bits = [self.kind]
        if self.case_rule() is not None:
            bits.append(f"{self.case} case")
        for w in ([which] if which else ["A", "B"]):
            d = describe_steps(self.steps(w))
            if d:
                bits.append(d if which else f"{w}: {d}")
        return " · ".join(bits)


# ---- steps -----------------------------------------------------------------
SQL_LITERAL = re.compile(r"'(?:[^']|'')*'")
X_WORD = re.compile(r"\bx\b")


def has_x(expr: str) -> bool:
    """Does the expression refer to the value, outside string literals?"""
    return bool(X_WORD.search(SQL_LITERAL.sub("''", expr)))


def substitute_x(expr: str, value: str) -> str:
    """Replace the placeholder x with the value expression, leaving 'x' in quotes alone."""
    out, pos = [], 0
    for m in SQL_LITERAL.finditer(expr):
        out.append(X_WORD.sub(lambda _: value, expr[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(X_WORD.sub(lambda _: value, expr[pos:]))
    return "".join(out)


def step_sql(step: dict) -> str:
    """The SQL for one step, on x. Conversions keep the original text when they fail."""
    tpl, params = STEPS[step["op"]]
    p = step.get("params", {})
    if tpl.startswith("__"):
        _, value = typed_exprs("x", tpl.strip("_"), str(p.get("fmt", "")), trim_text=True)
        return value
    if step["op"] == "custom expression":
        return str(p.get("expr", "x")).strip() or "x"
    out = tpl
    for name in params:
        v = str(p.get(name, ""))
        if name in NUMERIC_PARAMS:
            try:
                v = str(int(float(v.strip() or 0)))
            except ValueError:
                v = "0"
            out = out.replace("{" + name + "}", v)
        else:
            # as typed: a separator or find text of one space is a real value
            out = out.replace("{" + name + "}", lit(v))
    return out


def compile_steps(steps: list) -> str:
    """Nest the steps into one expression on x; empty when there are no steps."""
    expr = "x"
    for s in steps or []:
        expr = substitute_x(step_sql(s), expr)
    return "" if expr == "x" else expr


def describe_step(step: dict) -> str:
    op, p = step["op"], step.get("params", {})
    _, params = STEPS[op]
    if not params:
        return op
    shown = ", ".join(f"{PARAM_LABELS[k].split(' -')[0].split(',')[0]}={v}"
                      for k in params if (v := shown_param(k, p.get(k, ""))))
    return f"{op} ({shown})" if shown else op


def shown_param(name: str, value) -> str:
    """A parameter as the caption shows it: text as typed, quoted when a space at
    either end would hide it; a blank format or expression is not shown."""
    v = str(value)
    if name in TEXT_PARAMS:
        return v if v == v.strip() else lit(v)
    return v.strip()


def blank_param(step: dict) -> str | None:
    """The label of a text parameter that must not be empty but is, else None.
    One space is a value; only nothing at all is blank."""
    _, params = STEPS[step["op"]]
    p = step.get("params", {})
    for name in params:
        if name in NEEDED_TEXT and str(p.get(name, "")) == "":
            return PARAM_LABELS[name]
    return None


def describe_steps(steps: list) -> str:
    return " → ".join(describe_step(s) for s in steps or [])


def steps_json(steps: list) -> str:
    return json.dumps(steps or [])


def steps_from_json(text) -> list:
    try:
        out = json.loads(text) if isinstance(text, str) and text.strip() else []
    except ValueError:
        return []
    return [s for s in out if isinstance(s, dict) and s.get("op") in STEPS]


def final_kind(steps: list) -> str | None:
    """The type the last conversion step produces, if any."""
    for s in reversed(steps or []):
        if s["op"] in CONVERSIONS:
            return CONVERSIONS[s["op"]]
    return None


def date_format(steps: list) -> str:
    """The format the last to date / to timestamp step reads with; blank when there is no
    such step or it tries the usual spellings."""
    for s in reversed(steps or []):
        if s["op"] in ("to date", "to timestamp"):
            return str(s.get("params", {}).get("fmt", "")).strip()
    return ""


# ---- reading one value -------------------------------------------------------
def fold_nulls(base: str, tokens: tuple[str, ...]) -> str:
    if not tokens:
        return base
    listed = ", ".join(lit(t.upper()) for t in tokens)
    return f"CASE WHEN upper(trim({base})) IN ({listed}) THEN NULL ELSE {base} END"


def typed_exprs(text: str, kind: str, fmt: str = "", trim_text: bool = True) -> tuple[str, str]:
    """(probe, value): probe is NULL when the text does not convert; value is the
    canonical text, the original kept when it does not convert."""
    t = f"trim({text})"
    if kind == "number":
        # DECIMAL(18, 8) is int64 underneath and fast; the wide DECIMAL(38, 10) only
        # runs for values that overflow it, DOUBLE for anything stranger still
        dec18 = f"try_cast({t} AS DECIMAL(18, 8))"
        dec38 = f"try_cast({t} AS DECIMAL(38, 10))"
        dbl = f"try_cast({t} AS DOUBLE)"
        strip = "rtrim(rtrim(CAST({} AS VARCHAR), '0'), '.')"      # always has a '.'
        fast = f"CASE WHEN length(split_part({t}, '.', 2)) <= 8 THEN {strip.format(dec18)} END"
        return dbl, (f"coalesce({fast}, {strip.format(dec38)}, CAST({dbl} AS VARCHAR), {text})")
    if kind in ("date", "timestamp"):
        if fmt.strip():
            ts = f"try_strptime({t}, {lit(fmt.strip())})"
        else:
            fl = "[" + ", ".join(lit(f) for f in FALLBACK_FORMATS) + "]"
            ts = f"coalesce(try_cast({t} AS TIMESTAMP), try_strptime({t}, {fl}))"
        if kind == "date":
            ts = f"CAST({ts} AS DATE)"
        return ts, f"coalesce(CAST({ts} AS VARCHAR), {text})"
    if kind == "boolean":
        b = f"try_cast({t} AS BOOLEAN)"
        return b, f"coalesce(CAST({b} AS VARCHAR), {text})"
    return text, (t if trim_text else text)


def raw_text(side: Side, eff: str) -> str:
    return f"CAST({ident(side.source_of.get(eff, eff))} AS VARCHAR)"


def folded_text(side: Side, spec: ColSpec, which: str, opts: ReadOptions) -> str:
    """The value after the steps and null folding, still text."""
    base = raw_text(side, spec.src(which))
    tx = spec.tx(which)
    if tx:
        base = f"CAST(({substitute_x(tx, base)}) AS VARCHAR)"
    return fold_nulls(base, opts.tokens)


def column_exprs(side: Side, spec: ColSpec, which: str, opts: ReadOptions) -> tuple[str, str]:
    """(probe, value) for one column on one side: steps, null folding, trim, type."""
    return typed_exprs(folded_text(side, spec, which, opts), spec.kind, "", opts.trim)


def register(con: duckdb.DuckDBPyConnection, side: Side, name: str, specs: list[ColSpec],
             which: str, opts: ReadOptions, materialize: bool = False, sample: int = 0) -> str:
    """Expose one side under the shared column names, canonical values applied.

    A view streams from the file every time it is read; a table is read once,
    which is what the comparison and the key search want. With `sample`, a random
    sample of that many rows (reservoir, the same rows each time): drawn from the file
    before the steps and the types, which then run on the sample alone - a sample of
    the finished view would run them on every row first.
    """
    # two layers: steps and null folding once per value, then the type on that result,
    # so an expression that mentions the value several times does not redo the work
    inner = [f"{folded_text(side, s, which, opts)} AS {ident('__' + s.canon)}" for s in specs]
    outer = [f"{typed_exprs(ident('__' + s.canon), s.kind, '', opts.trim)[1]} AS {ident(s.canon)}"
             for s in specs]
    src = source_expr(side) + (f" USING SAMPLE reservoir({int(sample)} ROWS) REPEATABLE (1)"
                               if sample else "")
    sql = (f"SELECT {', '.join(outer)} FROM (SELECT {', '.join(inner)} FROM {src})"
           if specs else f"SELECT 1 AS __none FROM {src}")
    what = "TABLE" if materialize else "VIEW"
    con.execute(f"CREATE OR REPLACE {what} {ident(name)} AS {sql}")
    return name


BYTES_A_CELL = 24                   # a canonical text value in a DuckDB table, on average
HOLD_SHARE = 0.25                   # of DuckDB's memory a held table may take


def hold(con: duckdb.DuckDBPyConnection, side: Side, name: str, specs: list[ColSpec],
         which: str, opts: ReadOptions, rows: int | None = None) -> str:
    """One side under the shared names, held the way its size allows: a table, read and
    typed once, when it fits in a quarter of DuckDB's memory; else a view, which reads and
    types the columns a query asks for from the file each time - slower per query, but a
    table of any size profiles without a copy of it in memory. Returns "table" or "view".
    `rows` is the side's row count when known, else it is counted."""
    if rows is None:
        rows = side.rows if side.rows is not None else int(
            con.execute(f"SELECT count(*) FROM {source_expr(side)}").fetchone()[0])
    fits = fits_held(con, rows, len(specs))
    register(con, side, name, specs, which, opts, materialize=fits)
    return "table" if fits else "view"


def fits_held(con: duckdb.DuckDBPyConnection, rows: int, cols: int) -> bool:
    """Whether a table of that shape fits the share of DuckDB's memory a held copy may
    take - what decides between holding a table and reading a view each time."""
    return rows * max(cols, 1) * BYTES_A_CELL <= memory_limit_bytes(con) * HOLD_SHARE


def register_plain(con, side: Side, name: str, cols: list[str], opts: ReadOptions,
                   materialize: bool = False) -> str:
    """The side's own columns as plain text, under their own names."""
    return register(con, side, name, [ColSpec(c, c, c) for c in cols], "A", opts, materialize)


def conversion_report(A: Side, B: Side, specs: list[ColSpec], name_a: str, name_b: str,
                      opts: ReadOptions) -> pd.DataFrame:
    """Every typed or transformed column: values, converted, failed, an example."""
    rows = []
    for side, which, name in ((A, "A", name_a), (B, "B", name_b)):
        picked = [s for s in specs if s.kind != "text" or s.tx(which)]
        if not picked:
            continue
        con = scratch()
        aggs = []
        for s in picked:
            raw = raw_text(side, s.src(which))
            probe, value = column_exprs(side, s, which, opts)
            bad = f"FILTER (WHERE {raw} IS NOT NULL AND {probe} IS NULL)"
            aggs += [f"count({raw})", f"count({probe})",
                     f"min({raw}) {bad}", f"max({raw}) {bad}",
                     f"min({raw}) FILTER (WHERE {raw} IS NOT NULL)",
                     f"arg_min({value}, {raw}) FILTER (WHERE {raw} IS NOT NULL)"]
        vals = con.execute(f"SELECT {', '.join(aggs)} FROM {source_expr(side)}").fetchone()
        for i, s in enumerate(picked):
            filled, ok, ex1, ex2, before, after = vals[6 * i: 6 * i + 6]
            examples = [str(x) for x in (ex1, ex2) if x is not None]
            rows.append({"Column": s.canon, "Side": name, "Read as": s.describe(which),
                         "Values": int(filled), "Converted": int(ok),
                         "Failed": int(filled - ok),
                         "Failed %": round((filled - ok) / max(filled, 1) * 100, 2),
                         "Example": (f"{before} → {after}" if before is not None else ""),
                         "Examples of failures": ", ".join(dict.fromkeys(examples))})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Failed", "Column"], ascending=[False, True])


def try_steps(side: Side, eff: str, steps: list, kind: str, opts: ReadOptions,
              n: int = 5) -> pd.DataFrame:
    """The first n rows of one column: in the file, after the steps, compared as.

    Raises duckdb.Error with DuckDB's own message when a step is wrong.
    """
    spec = ColSpec("v", eff, eff, kind, list(steps), list(steps))
    raw = raw_text(side, eff)
    tx = spec.tx("A")
    after = f"CAST(({substitute_x(tx, raw)}) AS VARCHAR)" if tx else raw
    probe, value = column_exprs(side, spec, "A", opts)
    df = scratch(ordered=True).execute(
        f"SELECT raw, after, value, probe IS NOT NULL AS ok FROM ("
        f"SELECT {raw} AS raw, {after} AS after, {value} AS value, {probe} AS probe "
        f"FROM {source_expr(side)} LIMIT {int(n)})").fetchdf()
    label = lambda v: "∅ null" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
    out = pd.DataFrame({"In the file": df["raw"].map(label),
                        "After the steps": df["after"].map(label),
                        "Compared as": df["value"].map(label)})
    if kind != "text":
        out["Converts"] = df["ok"].map(lambda v: "yes" if v else "no")
    return out


# ---- DuckDB's function catalog, for the custom-expression step -----------------
SKIP_FUNCS = ("list_", "array_", "bit", "blob", "sha", "md5", "hash", "hex", "unhex", "bin",
              "unbin", "base64", "encode", "decode", "octet", "unicode", "ord", "chr", "prefix",
              "suffix", "format_bytes", "formatreadable", "to_", "from_", "epoch", "make_",
              "current_", "now", "today", "get_current", "age", "time_bucket", "json", "uuid",
              "gen_random", "random", "like_escape", "ilike_escape", "not_", "regexp_full_match",
              "regexp_split_to_table", "regexp_escape", "julian", "era", "timezone", "tz",
              "constant_or_null", "printf", "format", "hamming", "mismatches", "utf8", "print",
              "error", "icu", "nfc", "bar", "parse_", "url_", "ascii", "editdist3",
              "character_length", "char_length", "left_grapheme", "right_grapheme",
              "length_grapheme", "substring_grapheme", "lcase", "ucase", "len", "strpos",
              "string_to_array", "str_split", "string_split", "split", "regexp_extract_all")
EXTRA_FUNCS = ("split_part", "strptime", "try_strptime", "strftime", "date_trunc", "year",
               "month", "day", "hour", "minute", "second", "dayname", "monthname", "week",
               "quarter", "last_day", "nullif", "coalesce", "round", "abs", "floor", "ceil",
               "greatest", "least", "levenshtein", "jaccard", "jaro_winkler_similarity")


def make_template(name: str, params: list[str], types: list[str]) -> str:
    if not params:
        return f"{name}(x)"
    xi = next((i for i, t in enumerate(types) if t == "VARCHAR"), 0)
    parts = ["x" if i == xi else (f"'{p}'" if t == "VARCHAR" else p)
             for i, (p, t) in enumerate(zip(params, types))]
    return f"{name}({', '.join(parts)})"


@lru_cache(maxsize=1)
def function_catalog() -> pd.DataFrame:
    """DuckDB's own catalog of text / regex / date functions: signature, description, example."""
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT function_name AS name, parameters, parameter_types, description, examples
        FROM duckdb_functions()
        WHERE function_type = 'scalar' AND coalesce(description, '') <> ''
          AND regexp_matches(function_name, '^[a-z][a-z0-9_]*$')
          AND (list_has_any(categories, ['string', 'regex', 'text_similarity', 'date', 'timestamp'])
               OR function_name IN ({', '.join(lit(f) for f in EXTRA_FUNCS)}))
        ORDER BY function_name, CASE WHEN parameter_types[1] = 'VARCHAR' THEN 0 ELSE 1 END,
                 len(parameters)""").fetchdf()
    df = df[~df["name"].str.startswith(SKIP_FUNCS)].drop_duplicates("name")
    rows = []
    for r in df.itertuples(index=False):
        params = [] if r.parameters is None else list(r.parameters)
        types = [] if r.parameter_types is None else list(r.parameter_types)
        ex = [] if r.examples is None else list(r.examples)
        rows.append({"signature": f"{r.name}({', '.join(params)})",
                     "template": make_template(r.name, params, types),
                     "description": str(r.description).replace("`", ""),
                     "example": ex[0] if ex else ""})
    return pd.DataFrame(rows)
