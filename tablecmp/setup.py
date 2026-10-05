"""The Compare page's setup, with no page attached: the column table and the card under it, the
steps a column is read with, and the switches under How values are read. The Streamlit page and
the React page's server both call these - nothing here imports a UI.

Every function that changes the column table returns a new one and leaves the one it was given
as it was: the React server swaps the new table in whole, so a request that reads the table while
another changes it sees one table or the other, never half of each."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from .columns import (fill_looks, normalise, only_in, reused, role_tone, roles, set_steps, shape,
                      specs_from, table_compare, table_keys, untaken)
from .compare import build_filters
from .sniff import looks_like
from .sources import Side
from .theme import esc
from .values import NULL_TOKENS_DEFAULT, TYPES, ColSpec, ReadOptions, blank_param, final_kind, has_x

LOOKS_HELP = ("What a sample of this side's values looks like - a type, and the date format or "
              "the thousands separators that go with it. A suggestion only: the Type stays what "
              "you set, and a column DuckDB already typed gets none.")
# the cells a person may change; the rest are worked out (Matched by, detected, looks like)
EDITABLE = ("A column", "B column", "Common name", "Type", "Key", "Compare", "Case")
# How values are read, and the pairing without a key - what a fresh page starts with
SETTINGS_DEFAULT = {"trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0,
                    "null_tokens": NULL_TOKENS_DEFAULT, "nokey_mode": "hash"}
STEP_ACTIONS = ("add", "pop", "clear", "copy")
FILTER_TYPES = ["auto", "string", "number", "date"]     # what a Rows filter's value is read as


@dataclass
class Setup:
    cmap: pd.DataFrame
    specs: list[ColSpec]
    keys: list[str]
    compare: list[str]
    only_a: list[str]
    only_b: list[str]

    @property
    def canon(self) -> list[str]:
        return [s.canon for s in self.specs]


def setup_of(cmap: pd.DataFrame) -> Setup:
    """What the column table amounts to: the pairs as specs, the key, the compared columns and
    the columns only one side has."""
    return Setup(cmap, specs_from(cmap), table_keys(cmap), table_compare(cmap),
                 only_in(cmap, "A"), only_in(cmap, "B"))


# ---- the column table -----------------------------------------------------------------
def seed_key(A: Side, B: Side) -> tuple:
    """What a column table was built for: both files' names and columns. A new one of either
    starts the table afresh."""
    return (A.label, tuple(A.columns), B.label, tuple(B.columns))


def sniff_sides(A: Side, B: Side, opts: ReadOptions) -> tuple[dict, list[str]]:
    """What each side's text columns look like - {"A": {column: suggestion}, "B": {...}} - and a
    sentence for each side whose values could not be sampled."""
    out: dict = {}
    said: list[str] = []
    for which, side in (("A", A), ("B", B)):
        try:
            out[which] = looks_like(side, side.columns, opts=opts)
        except duckdb.Error as exc:
            out[which] = {}
            said.append(f"Could not sample the values of {side.name or which} for the "
                        f"*looks like* cells: {exc}")
    return out, said


def edit_cell(cmap: pd.DataFrame, looks: dict | None, A: Side, B: Side, row: int, column: str,
              value) -> tuple[pd.DataFrame, bool]:
    """One cell changed and the table made whole again (columns.normalise) - with whether rows
    moved, merged or went, which is when what was worked out from the table goes too.
    ValueError for a cell that cannot be changed, IndexError for a row the table has not."""
    if column not in EDITABLE:
        raise ValueError(f"{column} is worked out, not typed.")
    if not 0 <= int(row) < len(cmap):
        raise IndexError(f"The table has no row {row}.")
    prev = fill_looks(cmap, looks).reset_index(drop=True)
    edited = prev.copy()
    edited[column] = edited[column].astype(object)
    edited.at[int(row), column] = bool(value) if column in ("Key", "Compare") else str(value or "")
    new = normalise(edited, prev, A, B, looks)
    return new, shape(new) != shape(edited) or len(new) != len(prev)


def duplicate_names(cmap: pd.DataFrame) -> list[str]:
    """The common names used more than once - a run cannot tell those columns apart."""
    return sorted(set(cmap["Common name"][cmap["Common name"].duplicated()]))


def chip_items(cmap: pd.DataFrame, name_a: str, name_b: str) -> list[tuple[str, str]]:
    """The strip under the table as (text, class): "key" green, "off" red with the reason, ""
    plain - what columns.chips_html draws, as data."""
    out = []
    for (_, r), role in zip(cmap.iterrows(), roles(cmap, name_a, name_b)):
        paired = bool(r["A column"] and r["B column"])
        name = r["Common name"] if paired else (r["A column"] or r["B column"])
        cls = {"pos": "key", "neg": "off"}.get(role_tone(role), "")
        out.append((f"{name} · {role}" if cls == "off" else str(name), cls))
    return out


def card_rows(s: Setup, NA: str, NB: str) -> list[tuple[str, str]]:
    """The setup card under the table, as (label, value) - the value is HTML with every name
    escaped: key, compare list, how each column is read, what one side alone has."""
    typed = [sp for sp in s.specs
             if sp.kind != "text" or sp.a_steps or sp.b_steps or sp.case_rule() is not None]
    key_html = (f"<code>{esc(' + '.join(s.keys))}</code>" if s.keys
                else '<span class="warn">none ticked - rows will be matched by hashing the compared '
                     'columns, or by position; see the Key section</span>')
    off = [c for c in s.canon if c not in s.keys and c not in s.compare]
    rows = [
        ("Paired", f"{len(s.specs)} columns" + (f' · <span class="m">{len(s.only_a)} only in {esc(NA)}, '
                                                 f'{len(s.only_b)} only in {esc(NB)}</span>'
                                                 if s.only_a or s.only_b else "")
                   + "".join(f' · <span class="m">{esc(u)}</span>' for u in reused(s.specs, NA, NB))),
        ("Key", key_html),
        ("Compare", (f"{len(s.compare)} columns: " + esc(", ".join(s.compare)) if s.compare
                     else '<span class="warn">nothing ticked</span>')
                    + (f' <span class="m">· not compared: {esc(", ".join(off))}</span>' if off else "")),
        ("Read as", ("<br>".join(f"<code>{esc(sp.canon)}</code> {esc(sp.describe())}" for sp in typed)
                     or '<span class="m">all text, no transforms</span>')
                    + "".join(f'<br><code>{esc(canon)}</code> <span class="m">· {esc(hint)}</span>'
                              for canon, hint in untaken(s.cmap, NA, NB))),
    ]
    if s.only_a:
        rows.append((f"Only in {NA}", esc(", ".join(s.only_a))
                     + f' <span class="m">· null on the {esc(NB)} side, not compared</span>'))
    if s.only_b:
        rows.append((f"Only in {NB}", esc(", ".join(s.only_b))
                     + f' <span class="m">· null on the {esc(NA)} side, not compared</span>'))
    return rows


# ---- Transform and convert --------------------------------------------------------------
def spec_of(cmap: pd.DataFrame, canon: str) -> ColSpec | None:
    return next((s for s in specs_from(cmap) if s.canon == canon), None)


def with_type(cmap: pd.DataFrame, canon: str, kind: str) -> pd.DataFrame:
    """The table with one pair read as another Type."""
    if kind not in TYPES:
        raise ValueError(f"A Type is one of {', '.join(TYPES)}.")
    out = cmap.copy()
    out.loc[out["Common name"] == canon, "Type"] = kind
    return out


def with_steps(cmap: pd.DataFrame, canon: str, which: str, steps: list) -> pd.DataFrame:
    """The table with one side of a pair read through these steps - and the Type the last
    conversion step makes, when there is one."""
    out = cmap.copy()
    set_steps(out, canon, which, steps)
    fk = final_kind(steps)
    if fk:
        out.loc[out["Common name"] == canon, "Type"] = fk
    return out


def step_problem(step: dict) -> str:
    """'' when a step can be added, else the sentence that says what it lacks."""
    if step.get("op") == "custom expression" and not has_x(str(step.get("params", {}).get("expr", ""))):
        return "The expression must mention `x`, the value."
    missing = blank_param(step)
    return f"Type the {missing} first - one space counts." if missing else ""


def steps_after(spec: ColSpec, which: str, action: str, step: dict | None = None) -> tuple[str, list]:
    """(the side the steps land on, the steps) after Add, Remove last, Clear or Copy to the
    other side. ValueError with the sentence the page shows."""
    steps = list(spec.steps(which))
    if action == "add":
        problem = step_problem(step or {})
        if problem:
            raise ValueError(problem)
        return which, steps + [{"op": step["op"], "params": dict(step.get("params") or {})}]
    if action == "pop":
        return which, steps[:-1]
    if action == "clear":
        return which, []
    if action == "copy":
        return ("B" if which == "A" else "A"), steps
    raise ValueError(f"An action is one of {', '.join(STEP_ACTIONS)}.")


# ---- How values are read ----------------------------------------------------------------
def settings_of(saved: dict | None) -> dict:
    """The switches as set - a config's, or the page's - over the defaults."""
    return {**SETTINGS_DEFAULT, **{k: v for k, v in (saved or {}).items() if v is not None}}


def read_options(settings: dict) -> ReadOptions:
    """The engine's ReadOptions from the switches: the null words, Empty = null, Trim."""
    s = settings_of(settings)
    return ReadOptions.from_state({"null_tokens": s["null_tokens"], "opt_empty": s["empty_as_null"],
                                   "opt_trim": s["trim"]})


# ---- Rows -----------------------------------------------------------------------------------
def filter_error(rows: pd.DataFrame, name_a: str, name_b: str, specs: list[ColSpec]) -> str:
    """'' when the Rows filters read, else the engine's sentence about the first that does not."""
    try:
        build_filters(rows, name_a, name_b, specs)
    except ValueError as exc:
        return str(exc)
    return ""
