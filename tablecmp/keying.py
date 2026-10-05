"""The Key section and Profile both files, with no page attached: the columns that read like a
key, a key written differently on the two sides and its fix, the key picked from a suggestion,
the sentences said about a key, and the profile's Both sides table. The Streamlit page and the
React page's server both call these - nothing here imports a UI.

Every function that changes the column table returns a new one and leaves the one it was given
as it was."""
from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd

from .columns import set_steps, specs_from
from .keyformat import Fix, applied, key_format_fixes
from .keys import MAX_KEY_COLS, key_affinity
from .sources import Side
from .values import ColSpec, ReadOptions

NOKEY_MODES = {"hash": "match identical rows by hashing the compared columns",
               "position": "pair by position - line 1 against line 1"}
KEY_TIPS = ["**Suggest keys** tries single columns, then pairs, threes, fours - stopping at the first "
            "level with a key",
            "Over 5,000 rows: a 5,000-row sample first, then a full count of what survived · the other "
            "side must agree",
            "A wide or big pair with no obvious key: :orange[minutes]"]
NOKEY_TIPS = ["**hash** - rows identical on every compared column match; the rest are one-sided",
              "**position** - line 1 against line 1: :orange[only when both files are sorted the same]"]


def key_like(A: Side, B: Side, keys: list[str], specs: list[ColSpec]) -> list[str]:
    """The key, or - with none ticked - the text columns whose names read like one."""
    return list(keys) or [sp.canon for sp in specs if sp.kind == "text" and key_affinity(
        sp.canon, A.schema.get(sp.a_src, ""), B.schema.get(sp.b_src, "")) >= 3]


def with_fix(cmap: pd.DataFrame, fx: Fix) -> pd.DataFrame | None:
    """The table with the fix's steps after the column's own, on both sides - None when the
    column is no longer paired."""
    spec = next((sp for sp in specs_from(cmap) if sp.canon == fx.canon), None)
    if spec is None:
        return None
    sa, sb = applied(spec, fx)
    out = cmap.copy()
    set_steps(out, fx.canon, "A", sa)
    set_steps(out, fx.canon, "B", sb)
    return out


def check_formats(A: Side, B: Side, cmap: pd.DataFrame, cols: list[str], opts: ReadOptions
                  ) -> tuple[pd.DataFrame, list[tuple[Fix, bool]]]:
    """Key columns written differently on the two sides: the table with every simple fix in it,
    and each fix found with whether it went in - the rest wait for Apply. duckdb.Error when the
    values cannot be read."""
    out = cmap
    found: list[tuple[Fix, bool]] = []
    for fx in key_format_fixes(A, B, specs_from(cmap), cols, opts):
        done = fx.simple and (fixed := with_fix(out, fx)) is not None
        if done:
            out = fixed
        found.append((fx, done))
    return out, found


def formats_said(cols: list[str], found: list[tuple[Fix, bool]]) -> list[tuple[str, str]]:
    """What the last format check says, one (tone, text) a fix - or one caption when the two
    sides write the key alike."""
    if not found:
        return [("caption", f"Key formats checked ({', '.join(cols)}): the two sides write them alike.")]
    return [("success", f":green[**Applied**] · {fx.said}. The steps are in the column table.") if done
            else ("warning", f":orange[**Suggested**] · {fx.said}. It may drop something that matters - "
                             "your call.")
            for fx, done in found]


def with_key(cmap: pd.DataFrame, chosen: list[str]) -> pd.DataFrame:
    """The table with exactly these paired columns ticked Key."""
    out = cmap.copy()
    paired = (out["A column"] != "") & (out["B column"] != "")
    out.loc[paired, "Key"] = out.loc[paired, "Common name"].isin(chosen)
    return out


def chosen_key(combos: list[list[str]], picks: list[int]) -> list[str]:
    """The columns of the picked suggestions, as one key, each once, in the order picked."""
    return list(dict.fromkeys(c for i in picks if 0 <= i < len(combos) for c in combos[i]))


def best_label(combos: list[list[str]]) -> str:
    """The Key search's last word on its Log entry."""
    return ("Best key: " + " + ".join(combos[0])) if combos else "No key found"


def suggestions_said(table: pd.DataFrame, note: str) -> tuple[str, str]:
    good = table[table["Unique on both"] == "yes"] if len(table) else table
    if len(good):
        return ("success", f"{len(good)} combination(s) identify a single row on both sides - "
                           f"best: **{good.iloc[0]['Key columns']}**. {note}.")
    return ("warning", f"Nothing up to {MAX_KEY_COLS} columns was unique on both sides - "
                       f"the closest are below. {note}.")


def report_said(report: pd.DataFrame, keys: list[str]) -> tuple[str, str]:
    """What Check key found: unique on both sides, or the null and duplicate keys in a sentence."""
    if (report["Unique"] == "yes").all():
        return ("success", f"**{' + '.join(keys)}** identifies a single row on both sides.")
    nulls = report[report["Null keys"] > 0]
    dup = report[report["Duplicate rows"] > 0]
    said = []
    if len(nulls):
        said.append("This key is null on " + " and ".join(
            f"{r['Null keys']:,} rows of {r['Side']}" for _, r in nulls.iterrows())
            + " - those rows cannot match.")
    if len(dup):
        said.append("This key is not unique on " + " and ".join(
            f"{r['Side']} ({r['Duplicate rows']:,} duplicate rows)" for _, r in dup.iterrows())
            + ". Rows sharing a key are paired in file order, which can produce "
              "differences that are really mis-pairing. Tick another column.")
    return ("warning", " ".join(said))


# ---- Profile both files -------------------------------------------------------------------
def profile_key_for(A: Side, B: Side, specs: list[ColSpec], opts: ReadOptions) -> str:
    """What a profile was measured on - the two reads, the column specs, the null rules."""
    return json.dumps([A.read_key, B.read_key, [asdict(s) for s in specs], opts.tokens, opts.trim],
                      default=str)


def both_table(prof: dict, canon: list[str], NA: str, NB: str) -> pd.DataFrame:
    """The profile's Both sides tab: nulls, distinct values and the range of each paired column on
    each side, the biggest gap in nulls first."""
    ia, ib = prof["stats"]["A"].set_index("Column"), prof["stats"]["B"].set_index("Column")
    both = pd.DataFrame([{
        "Column": c, "Type": ia.at[c, "Type"],
        f"Null % {NA}": ia.at[c, "Null %"], f"Null % {NB}": ib.at[c, "Null %"],
        "Null % gap": round(abs(ia.at[c, "Null %"] - ib.at[c, "Null %"]), 2),
        f"Distinct {NA}": ia.at[c, "Distinct"], f"Distinct {NB}": ib.at[c, "Distinct"],
        f"Min {NA}": ia.at[c, "Min"], f"Min {NB}": ib.at[c, "Min"],
        f"Max {NA}": ia.at[c, "Max"], f"Max {NB}": ib.at[c, "Max"],
    } for c in canon if c in ia.index and c in ib.index])
    return both.sort_values("Null % gap", ascending=False) if len(both) else both


def freq_title(prof: dict, c: str, keys: list[str], NA: str, NB: str) -> str:
    """The heading over one column's value frequencies."""
    ia, ib = prof["stats"]["A"].set_index("Column"), prof["stats"]["B"].set_index("Column")
    return (f"**{c}**{' · key' if c in keys else ''} - {ia.at[c, 'Type']} · "
            f"{NA}: {ia.at[c, 'Distinct']:,} distinct · {NB}: {ib.at[c, 'Distinct']:,} distinct")


def freq_columns(prof: dict, canon: list[str]) -> list[str]:
    """The paired columns whose frequencies the profile holds."""
    return [c for c in canon if c in prof["freq"] and "A" in prof["freq"][c]]
