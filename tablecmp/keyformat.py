"""Key columns whose two sides write the same values differently - '00123' against '123',
'emp-7' against 'EMP-7', 'EMP-0042' against '42' - found from the values, with the steps
that make them meet.

A fix is tried on a sample of one side's distinct values against every distinct value of
the other side, both ways round. It is taken when it makes most of the sample meet where
the raw values did not, and it never merges two values of a side into one (that would make
a unique key a duplicate one). Simple fixes - case, spaces, leading zeros, a trailing .0 -
are safe to apply as they are: `simple` is true and Auto and the Key section put them in
the column table and say so. The rest - dropping a prefix one side carries, keeping only
the digits - read meaning into the values, so they are suggested and applied on a press.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .keys import probe
from .sources import Side
from .sql import ident
from .values import ColSpec, ReadOptions, compile_steps, describe_steps, substitute_x

SAMPLE = 2_000          # distinct values of one side tried against the other side
AFFIX_SAMPLE = 500      # values a prefix or a suffix is looked for in
MIN_VALUES = 5          # fewer distinct values on a side than this says nothing
MIN_AFTER = 0.5         # share of the sample that must meet once the fix is applied
MIN_GAIN = 0.3          # and how much more of it than met before
AFFIX_SHARE = 0.9       # a prefix is one side's when this share of its values carry it


def _step(op: str, **params) -> dict:
    return {"op": op, "params": params}


UPPER, TRIM, NOSPACE = _step("upper"), _step("trim"), _step("remove spaces")
NOZERO = _step("strip leading zeros")
NODOT0 = _step("regex replace", a=r"\.0+$", b="")
SIMPLE = [([UPPER], "case"), ([TRIM], "spaces at the ends"), ([NOSPACE], "spaces"),
          ([NOZERO], "leading zeros"), ([NODOT0], "a trailing .0"),
          ([UPPER, NOZERO], "case and leading zeros"), ([UPPER, NOSPACE], "case and spaces")]
GUESSES = [([_step("letters and digits only")], "punctuation"),
           ([UPPER, _step("letters and digits only")], "case and punctuation"),
           ([_step("digits only")], "everything but the digits")]


@dataclass
class Fix:
    canon: str
    a_steps: list               # steps added after the column's own, on A
    b_steps: list               # and on B
    simple: bool                # safe to apply without asking
    what: str                   # what differs: 'leading zeros', 'a prefix EMP- on A'
    before: float               # share of the sample that met raw
    after: float                # and with the fix
    example: tuple[str, str] = ("", "")     # an A value and the B value it meets once fixed
    said: str = field(default="", init=False)

    def __post_init__(self):
        how = " · ".join(f"{w}: {describe_steps(s)}" for w, s in (("A", self.a_steps), ("B", self.b_steps)) if s)
        ex = f" ('{self.example[0]}' against '{self.example[1]}')" if self.example[0] else ""
        self.said = (f"{self.canon}: the two sides write the key differently - {self.what}{ex}; "
                     f"{how} makes {self.after:.0%} of the values meet, against {self.before:.0%} as written")


def _escape(text: str) -> str:
    """Text as a literal inside a regular expression."""
    return re.sub(r"([\\.^$|?*+()\[\]{}-])", r"\\\1", text)


def _affix(values: list[str], others: list[str], at_start: bool) -> str:
    """The non-digit run nearly every value of a side starts (or ends) with and the other
    side's values do not - 'EMP-' in 'EMP-0042' against '42'; else ''."""
    pat = re.compile(r"^[^0-9]+" if at_start else r"[^0-9]+$")
    runs = Counter(m.group(0) for v in values if (m := pat.search(v)))
    if not runs or not values:
        return ""
    run, n = runs.most_common(1)[0]
    has = (lambda v: v.startswith(run)) if at_start else (lambda v: v.endswith(run))
    if n / len(values) < AFFIX_SHARE or sum(map(has, others)) / max(len(others), 1) > 1 - AFFIX_SHARE:
        return ""
    return run


def _candidates(va: list[str], vb: list[str]) -> list[tuple[list, list, bool, str]]:
    """(A steps, B steps, simple, what) in the order they are preferred: simple first, then
    a prefix or a suffix one side carries, and last the guesses that throw characters away."""
    out = [(s, s, True, what) for s, what in SIMPLE]
    for at_start, where in ((True, "prefix"), (False, "suffix")):
        for which, mine, theirs in (("A", va, vb), ("B", vb, va)):
            run = _affix(mine, theirs, at_start)
            if not run:
                continue
            cut = _step("regex replace", a=("^" + _escape(run)) if at_start else (_escape(run) + "$"), b="")
            for extra, also in (([], ""), ([NOZERO], " and leading zeros")):
                mine_steps, their_steps = [cut, *extra], list(extra)
                a, b = (mine_steps, their_steps) if which == "A" else (their_steps, mine_steps)
                out.append((a, b, False, f"a {where} {run} on {which}{also}"))
    return out + [(s, s, False, what) for s, what in GUESSES]


def _on(steps: list, col: str) -> str:
    expr = compile_steps(steps)
    return f"CAST(({substitute_x(expr, col)}) AS VARCHAR)" if expr else col


def _share(con, mine: str, theirs: str, s_mine: list, s_theirs: list) -> tuple[float, bool]:
    """(share of a sample of `mine` that meets `theirs` once fixed, whether the fix merged
    two values of either side into one)."""
    fm, ft = _on(s_mine, "v"), _on(s_theirs, "v")
    met, n, n_fixed = con.execute(
        f"SELECT count(*) FILTER (WHERE {fm} IN (SELECT {ft} FROM {theirs})), count(*), "
        f"count(DISTINCT {fm}) FROM {mine}").fetchone()
    merged = n_fixed < n
    if not merged and s_theirs:
        t, t_fixed = con.execute(f"SELECT count(*), count(DISTINCT {ft}) FROM {theirs}").fetchone()
        merged = t_fixed < t
    return (met / n if n else 0.0), merged


def _example(con, a_steps: list, b_steps: list) -> tuple[str, str]:
    row = con.execute(f"SELECT a.v, b.v FROM sa a JOIN db b ON {_on(a_steps, 'a.v')} = {_on(b_steps, 'b.v')} "
                      f"WHERE a.v <> b.v LIMIT 1").fetchone()
    return (str(row[0]), str(row[1])) if row else ("", "")


def check_column(con, canon: str) -> Fix | None:
    """The best fix for one text column held as probe_a / probe_b, or None when the two
    sides already meet, or nothing tried makes them."""
    c = ident(canon)
    for side, short in (("a", "a"), ("b", "b")):
        con.execute(f"CREATE OR REPLACE TEMP TABLE d{short} AS SELECT DISTINCT CAST({c} AS VARCHAR) AS v "
                    f"FROM probe_{side} WHERE {c} IS NOT NULL")
        con.execute(f"CREATE OR REPLACE TEMP TABLE s{short} AS SELECT v FROM d{short} "
                    f"USING SAMPLE reservoir({SAMPLE} ROWS) REPEATABLE (1)")
    va = [r[0] for r in con.execute(f"SELECT v FROM sa LIMIT {AFFIX_SAMPLE}").fetchall()]
    vb = [r[0] for r in con.execute(f"SELECT v FROM sb LIMIT {AFFIX_SAMPLE}").fetchall()]
    if min(len(va), len(vb)) < MIN_VALUES:
        return None

    def both_ways(sa_: list, sb_: list) -> tuple[float, bool]:
        ab, m1 = _share(con, "sa", "db", sa_, sb_)
        ba, m2 = _share(con, "sb", "da", sb_, sa_)
        return max(ab, ba), m1 or m2

    before, _ = both_ways([], [])
    if before >= 1 - MIN_GAIN:
        return None
    tried = []
    for a_s, b_s, simple, what in _candidates(va, vb):
        after, merged = both_ways(a_s, b_s)
        if not merged and after >= MIN_AFTER and after - before >= MIN_GAIN:
            tried.append((after, a_s, b_s, simple, what))
    if not tried:
        return None
    best = max(t[0] for t in tried)
    # the first - the simplest - that comes within a whisker of the best
    after, a_s, b_s, simple, what = next(t for t in tried if t[0] >= best - 0.02)
    return Fix(canon, a_s, b_s, simple, what, before, after, _example(con, a_s, b_s))


def key_format_fixes(A: Side, B: Side, specs: list[ColSpec], cols: list[str], opts: ReadOptions) -> list[Fix]:
    """A fix for every column in `cols` (text pairs only) whose two sides write the values
    differently."""
    text = [sp for sp in specs if sp.canon in cols and sp.kind == "text"]
    if not text:
        return []
    con = probe(A, B, text, opts)
    return [f for sp in text if (f := check_column(con, sp.canon)) is not None]


def applied(spec: ColSpec, fix: Fix) -> tuple[list, list]:
    """The column's own steps with the fix's after them, A and B."""
    return list(spec.a_steps) + fix.a_steps, list(spec.b_steps) + fix.b_steps


def suggestion(fix: Fix) -> str:
    return fix.said + (" - applied" if fix.simple else " - suggested, not applied")

