"""How a value is read: transform steps, null folding, trim, then the type.

Both files are read as text. Each value on each side goes through the same
stages - the side's transform steps, null folding, trim, the pair's Type - and
comes out as canonical text, so both sides compare on the same thing. A value
that fails to convert keeps its original text, which makes it show up as a
difference instead of vanishing.
"""
from __future__ import annotations

import difflib
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
# two-digit years before %Y/%m/%d and %d/%m/%Y, which read 03/11/26 as the year 3 or 26; %n takes
# up to nine digits of a fraction, %f six
FALLBACK_FORMATS = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%y %H:%M:%S.%n", "%d/%m/%y %H:%M:%S", "%d/%m/%y", "%d-%m-%y",
                    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d",
                    "%d-%b-%Y", "%d %b %Y", "%b %d %Y"]


def cast_date(t: str, to: str = "TIMESTAMP") -> str:
    """try_cast to a date type, but not a value starting with a day: a cast reads 03/11/26 or
    03-11-26 as the year 3. Those are left to the formats; 2026/11/03 still casts."""
    return f"CASE WHEN NOT regexp_matches(CAST({t} AS VARCHAR), '^\\s*[0-9][0-9]?[-/]') THEN try_cast({t} AS {to}) END"


def strptime_any(t: str, formats: list[str] | None = None) -> str:
    """The first of the formats that reads t, as a plain TIMESTAMP. A %n format is read on its own:
    one in a list makes the whole read TIMESTAMP_NS, which 9999-12-31 overflows."""
    formats = FALLBACK_FORMATS if formats is None else formats
    plain = [lit(f) for f in formats if "%n" not in f]
    reads = [f"try_strptime({t}, [{', '.join(plain)}])"] if plain else []
    reads += [f"CAST(try_strptime({t}, {lit(f)}) AS TIMESTAMP)" for f in formats if "%n" in f]
    return f"coalesce({', '.join(reads)})"


NULL_TOKENS_DEFAULT = "NULL, \\N, N/A, NA, NaN, None, (null)"

# what a date / time value looks like -> the strptime format that reads it
FORMAT_PRESETS = {
    "2026-08-27": "%Y-%m-%d", "27/08/2026": "%d/%m/%Y", "08/27/2026": "%m/%d/%Y",
    "20260827": "%Y%m%d", "27-08-2026": "%d-%m-%Y", "27.08.2026": "%d.%m.%Y",
    "27-Aug-2026": "%d-%b-%Y", "27 August 2026": "%d %B %Y", "Aug 27, 2026": "%b %d, %Y",
    "27/08/26": "%d/%m/%y", "27/08/26 10:11:12": "%d/%m/%y %H:%M:%S",
    "27/08/26 10:11:12.123456789": "%d/%m/%y %H:%M:%S.%n", "2026-08-27 10:11:12": "%Y-%m-%d %H:%M:%S",
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
    # null, or nothing but spaces, tabs, line breaks and non-breaking spaces
    "if empty, use": ("CASE WHEN x IS NULL OR trim(x, ' ' || chr(9) || chr(10) || chr(13) || chr(160)) = '' "
                      "THEN {v} ELSE x END", ("v",)),
    "to number": ("__number__", ()),
    "to timestamp": ("__timestamp__", ("fmt",)),
    "to date": ("__date__", ("fmt",)),
    "to boolean": ("__boolean__", ()),
    "custom expression": ("{expr}", ("expr",)),
}
PARAM_LABELS = {"n": "N", "m": "M", "a": "find", "b": "replace with", "c": "pad character",
                "s": "separator", "fmt": "format - blank tries the usual spellings",
                "expr": "expression, x = the value", "v": "value"}
NUMERIC_PARAMS = {"n", "m"}
TEXT_PARAMS = {"a", "b", "c", "s", "v"}     # quoted into the SQL as typed, spaces included
NEEDED_TEXT = {"a", "c", "s", "v"}          # blank: find does nothing, pad fails, split gives one character
# what x is in a custom expression, by the pair's Type
X_TYPES = {"text": "VARCHAR", "number": "DOUBLE", "date": "DATE", "timestamp": "TIMESTAMP",
           "boolean": "BOOLEAN"}
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
        return compile_steps(self.steps(which), self.kind)

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


_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def typed_x(text: str, kind: str) -> str:
    """The text as the Read as type, the safe way: NULL when it is not one (' - ', '.', a space).
    A number may carry thousands separators."""
    if kind == "number":
        return f"try_cast(replace(trim({text}), ',', '') AS DOUBLE)"
    if kind in ("date", "timestamp", "boolean"):
        return typed_exprs(text, kind)[0]
    return text


def step_sql(step: dict, kind: str = "text") -> str:
    """The SQL for one step, on x. Conversions keep the original text when they fail. In a
    custom expression x is the value as the pair's Type (typed_x), and the result goes back to
    text for the steps after it."""
    tpl, params = STEPS[step["op"]]
    p = step.get("params", {})
    if tpl.startswith("__"):
        _, value = typed_exprs("x", tpl.strip("_"), str(p.get("fmt", "")), trim_text=True)
        return value
    if step["op"] == "custom expression":
        expr = str(p.get("expr", "x")).strip() or "x"
        if ";" in _QUOTED.sub("", expr):          # one expression, never a second statement
            raise ValueError("A custom expression is one expression - take out the ';'.")
        if not typed_only(expr, kind):
            return expr                           # reads on text x (trim, nullif(x, '-')...): as it always did
        return f"CAST(({substitute_x(expr, typed_x('x', kind))}) AS VARCHAR)"
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


def compile_steps(steps: list, kind: str = "text") -> str:
    """Nest the steps into one expression on x; empty when there are no steps. `kind` is the
    pair's Type - what x is in a custom expression."""
    expr = "x"
    for s in steps or []:
        expr = substitute_x(step_sql(s, kind), expr)
    return "" if expr == "x" else expr


def expr_problem(expr: str, kind: str = "text") -> str:
    """'' when a custom expression reads with x as the pair's Type - or as text, the way one
    written before x was typed reads - else a plain sentence on what is wrong."""
    bare = _QUOTED.sub("", expr)
    if ";" in bare:
        return "A custom expression is one expression - take out the ';'."
    opened, closed = bare.count("("), bare.count(")")
    if opened != closed:
        return f"The brackets don't match - {opened} opened, {closed} closed."
    as_text = _bind_problem(expr, "text")
    return "" if not as_text or typed_only(expr, kind) else (_bind_problem(expr, kind) if kind != "text" else as_text)


def typed_only(expr: str, kind: str) -> bool:
    """True when x must be the pair's Type for the expression to read - `case when x is null then
    0.0 else x end` on a number pair. One that reads on text keeps text x, so what it does never
    changes under a Type."""
    return kind != "text" and bool(_bind_problem(expr, "text")) and not _bind_problem(expr, kind)


PROBE = {"number": "1", "date": "DATE '2000-01-01'", "timestamp": "TIMESTAMP '2000-01-01'",
         "boolean": "true"}


@lru_cache(maxsize=512)
def _bind_problem(expr: str, kind: str) -> str:
    """'' when the expression reads with x of the pair's Type, else the plain sentence. A typed x
    is also run on one probe value, so a text literal that cannot be the Type (x = '-' on a
    number) fails here, not on every row of the run; text is only bound - any text is data."""
    xt = X_TYPES.get(kind, "VARCHAR")
    rows = f"UNION ALL SELECT CAST({PROBE[kind]} AS {xt})) AS t" if kind in PROBE else ") AS t LIMIT 0"
    try:
        with duckdb.connect() as con:
            con.execute(f"SELECT CAST(({expr}) AS VARCHAR) FROM (SELECT CAST(NULL AS {xt}) AS x {rows}").fetchall()
    except duckdb.ParserException as exc:
        near = re.search(r'at or near "([^"]*)"', str(exc))
        return (f"Not a valid expression near '{near.group(1)}'." if near
                else f"Not a valid expression: {short_error(exc)}")
    except duckdb.CatalogException as exc:
        m = re.search(r"with name (\S+) does not exist", str(exc))
        if not m:
            return f"The expression does not read: {short_error(exc)}"
        near = difflib.get_close_matches(m.group(1).lower(), _function_names(), n=1)
        return f"There is no function called {m.group(1)}" + (f" - did you mean {near[0]}?" if near else ".")
    except duckdb.ConversionException as exc:
        bad = _NOT_CONVERTED.search(str(exc))
        if bad:
            return (f"x is a {kind} here, so '{bad.group(2)}' cannot be one - values that are not a {kind} "
                    "already read as null: test x is null instead.")
        return f"The expression does not read: {short_error(exc)}"
    except duckdb.Error as exc:
        said = short_error(exc)
        if isinstance(exc, duckdb.BinderException) and (xt in said or "DECIMAL" in said):
            how = ("use CAST(x AS VARCHAR) for text functions" if kind != "text"
                   else "set Read as, or convert it with try_cast(x AS DOUBLE)")
            return f"x is {'text' if kind == 'text' else 'a ' + kind} ({xt}) here - {how}. DuckDB says: {said}"
        return f"The expression does not read: {said}"
    return ""


@lru_cache(maxsize=1)
def _function_names() -> list[str]:
    """DuckDB's function names, and SQL's own the catalog leaves out - for 'did you mean'."""
    with duckdb.connect() as con:
        names = [r[0] for r in con.execute("SELECT DISTINCT function_name FROM duckdb_functions() "
                                           "WHERE function_type IN ('scalar', 'macro')").fetchall()]
    return names + ["coalesce", "nullif", "try_cast", "cast", "ifnull"]


def short_error(exc: Exception) -> str:
    """DuckDB's message without the SQL it quotes: its first lines, up to 'LINE n:'."""
    text = str(exc).split("\nLINE ")[0].strip()
    return " ".join(line.strip() for line in text.splitlines() if line.strip())


_NOT_CONVERTED = re.compile(r"Could not convert string (['\"])(.*?)\1 to ([A-Z]+)")
TYPE_WORDS = {"DATE": "date", "TIMESTAMP": "timestamp", "BOOLEAN": "boolean"}   # else a number


def plain_error(exc: Exception, sides: list[tuple[Side, str, str]], specs: list[ColSpec]) -> str:
    """A run's or a preview's DuckDB error in a sentence. A value a step's cast could not convert
    is found on the sides - [(side, "A" or "B", its name)] - and counted there:
    "amount on Left: 208 rows hold ' - ', which is not a number. ..." Else "DuckDB says:" and its
    own message, without the SQL it quotes."""
    m = _NOT_CONVERTED.search(str(exc))
    if not isinstance(exc, duckdb.ConversionException) or not m:
        return f"DuckDB says: {short_error(exc)}"
    value, word = m.group(2), TYPE_WORDS.get(m.group(3), "number")
    named = re.search(r"when casting from source column (\S+)", str(exc))
    with scratch() as con:
        for side, which, name in sides:
            for spec in specs:
                src = spec.src(which)
                # only a conversion or a custom expression casts; a source column DuckDB names must be this one
                casts = any(s["op"] in CONVERSIONS or s["op"] == "custom expression" for s in spec.steps(which))
                if not src or not casts or (named and named.group(1) != src):
                    continue
                raw = raw_text(side, src)
                try:
                    n = con.execute(f"SELECT count(*) FROM {source_expr(side)} WHERE {raw} = {lit(value)} "
                                    f"OR trim({raw}) = trim({lit(value)})").fetchone()[0]
                except duckdb.Error:
                    continue
                if n:
                    holds = "row holds" if n == 1 else "rows hold"
                    return (f"{spec.canon} on {name}: {n:,} {holds} '{value}', which is not a {word}. "
                            f"Use try_cast, or the 'if empty, use' step. (DuckDB says: {short_error(exc)})")
    return f"DuckDB says: {short_error(exc)}"


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
    """The value, with the null tokens read as null. list_contains over a constant list,
    never `IN (...)`: DuckDB plans an IN over a list of constants as a join, and a
    statement holding one per column plans hundreds of them - 200 columns of a 100,000-row
    table took seven minutes that way and take four seconds this way."""
    if not tokens:
        return base
    listed = ", ".join(lit(t.upper()) for t in tokens)
    return f"CASE WHEN list_contains([{listed}], upper(trim({base}))) THEN NULL ELSE {base} END"


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
            ts = strptime_any(t, [fmt.strip()])
        else:
            ts = f"coalesce({cast_date(t)}, {strptime_any(t)})"
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
            # converted counts the file's own values: a step may fill a null ('if empty, use')
            aggs += [f"count({raw})", f"count({probe}) FILTER (WHERE {raw} IS NOT NULL)",
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
