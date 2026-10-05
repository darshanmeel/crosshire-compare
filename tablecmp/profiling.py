"""The Profiling page with no page attached: the profile made, the key it was measured on, the
lines said about it, the six files it saves as, and the save itself - what the React
server (web/routes_profiling) calls."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

from .columns import single_specs
from .keys import MAX_KEY_COLS
from .profile import profile_single
from .results import default_save_base, save_base_after, save_files, saved_line  # noqa: F401 - one home for both pages' saves
from .sniff import looks_like
from .sources import Side, slug
from .values import ReadOptions

DEP_FILE_COLS = ["Column A", "Column B", "Kind", "Distinct", "r"]   # dependencies.csv: deps then corr
FILE_PARTS = ("profile.csv", "keys.csv", "notes.txt", "outliers.csv", "patterns.csv", "dependencies.csv")


KEY_COLS = 5                # the Profile page's key search: combinations up to five columns
TOP_KEYS = 5                # and the best five candidates listed - both set on the page
KEY_SAMPLE_ROWS = 100_000   # the search runs on a random sample this big, whatever the table
SHORTLIST = 10              # and the best ten unique there are checked on every row


def profile_key(P: Side, opts: ReadOptions) -> str:
    """What a profile was measured on: the rows read and how values are read. Another key
    means the profile is from earlier settings."""
    return json.dumps([P.read_key, opts.tokens, opts.trim], default=str)


def make_profile(P: Side, NP: str, opts: ReadOptions, say: Callable[[str], None],
                 key_cols: int = KEY_COLS, top_keys: int = TOP_KEYS,
                 key_sample: int = KEY_SAMPLE_ROWS, shortlist: int = SHORTLIST) -> dict:
    """The profile: what the values look like decides the types (there is no column
    table here to take a suggestion in), then the statistics, frequencies, keys and what
    stands out - the looks go along, so the notes can say what was read as what."""
    say("Looking at the values…")
    looks = looks_like(P, P.columns, opts=opts)
    return profile_single(P, single_specs(P, looks), opts, say, name=NP, looks=looks,
                          key_cols=key_cols, top_keys=top_keys,
                          key_sample=key_sample, shortlist=shortlist)


def best_key(prof: dict) -> list[str] | None:
    """The key: the best candidate when it is unique on every row, else None. The
    candidates come unique first, so the top row decides."""
    table, combos, _ = prof["keys"]
    return combos[0] if combos and len(table) and table.iloc[0]["Unique"] == "yes" else None


def ready_label(prof: dict) -> str:
    best = best_key(prof)
    return "Profile ready - " + (f"key: {' + '.join(best)}" if best else "no key")


def notes_label(notes: list[str]) -> str:
    n = len(notes)
    return f"{n} thing{'s' if n != 1 else ''} stand{'' if n != 1 else 's'} out"


def keys_line(prof: dict) -> tuple[str, str]:
    """The line over the keys table: the key, or how far the search went and found none."""
    table, _, note = prof["keys"]
    best = best_key(prof)
    if best:
        return "success", f"Key: **{' + '.join(best)}** - unique on every row. {note}."
    return "warning", (f"Nothing up to {prof.get('key_cols', MAX_KEY_COLS)} columns is unique"
                       + (" - the closest are below" if len(table) else "") + f". {note}.")


def fold_title(stats: pd.DataFrame, col: str) -> str:
    """A column's fold under Value frequencies: its name, type, distinct count and null share."""
    by_col = stats.set_index("Column")
    return (f"**{col}** - {by_col.at[col, 'Type']} · {by_col.at[col, 'Distinct']:,} distinct · "
            f"{by_col.at[col, 'Null %']}% null")


def fold_titles(stats: pd.DataFrame, cols: list[str]) -> dict[str, str]:
    """fold_title for many columns with one pass over the statistics, not one index per column."""
    by_col = stats.set_index("Column")
    return {c: (f"**{c}** - {by_col.at[c, 'Type']} · {by_col.at[c, 'Distinct']:,} distinct · "
                f"{by_col.at[c, 'Null %']}% null") for c in cols}


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8")


def dependencies_frame(prof: dict) -> pd.DataFrame:
    """The dependencies and the correlated pairs as one sheet, Kind telling them apart -
    a dependency runs from Column A to Column B, a correlated pair has an r."""
    deps = prof["deps"].rename(columns={"Determines": "Column A", "Determined": "Column B"})
    corr = prof["corr"].assign(Kind="correlated")
    out = pd.concat([deps, corr], ignore_index=True).reindex(columns=DEP_FILE_COLS)
    out["Distinct"] = pd.to_numeric(out["Distinct"], errors="coerce").astype("Int64")   # whole, blank on a pair
    return out


def file_stem(NP: str) -> str:
    return slug(NP) or "Table"


def profile_files(prof: dict, NP: str) -> dict[str, bytes]:
    """The six files Save to folder writes, named after the table, in FILE_PARTS order."""
    stem = file_stem(NP)
    notes = "\n".join(prof["notes"])
    data = [csv_bytes(prof["stats"]), csv_bytes(prof["keys"][0]),
            (prof["headline"] + "\n\n" + notes + "\n").encode("utf-8"),
            csv_bytes(prof["outliers"]), csv_bytes(prof["patterns"]), csv_bytes(dependencies_frame(prof))]
    return {f"{stem}__{part}": d for part, d in zip(FILE_PARTS, data)}
