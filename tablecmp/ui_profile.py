"""The Profiling page: one table on its own - which columns identify a row, what stands
out, its statistics, where the numbers and dates run wild, the shapes its text takes,
which columns determine which, and the most and least frequent values of every column -
the statistics and frequencies being the same measures the Compare page's Profile
section takes of a pair."""
from __future__ import annotations

import json

import duckdb
import pandas as pd
import streamlit as st

from . import ui_log
from .columns import single_specs
from .keys import MAX_KEY_COLS
from .outputs import run_id
from .profile import profile_single
from .sniff import looks_like
from .sources import Side, preview_rows, slug
from .ui_results import save_row
from .values import ReadOptions

DEP_FILE_COLS = ["Column A", "Column B", "Kind", "Distinct", "r"]   # dependencies.csv: deps then corr


def render(P: Side, NP: str, opts: ReadOptions) -> None:
    if not P.loaded:
        st.info("Load a table in the sidebar - a CSV or JSON file, or a database table.")
        return
    st.subheader("File")
    st.caption(f"**{NP}** {P.origin or P.label} - {P.rows:,} rows × {len(P.schema)} columns"
               + (f" · {P.cut}" if P.cut else ""))
    with st.expander("First 10 rows", expanded=False):
        try:
            st.dataframe(preview_rows(P), width="stretch", hide_index=True, height=390)
        except duckdb.Error as exc:
            st.error(str(exc))
    key = json.dumps([P.read_key, opts.tokens, opts.trim], default=str)
    if st.button("Profile", key="do_profile_P", type="primary"):
        try:
            with ui_log.running("Profiling…", "Profile") as box:
                found = make_profile(P, NP, opts, box.write)
                st.session_state["profile_P"] = (key, found, run_id())
                best = best_key(found)
                box.update(label="Profile ready - " + (f"key: {' + '.join(best)}" if best else "no key"),
                           state="complete")
                # the notes as their own entry, the way Auto's decisions are logged
                notes = found["notes"]
                ui_log.note("Profile notes", f"{len(notes)} thing{'s' if len(notes) != 1 else ''} "
                            f"stand{'' if len(notes) != 1 else 's'} out", notes)
        except (duckdb.Error, ValueError, OverflowError) as exc:
            # a measure that cannot be taken - a query DuckDB refuses, a date past Python's
            # range - is a line on the page, not a traceback
            st.error(f"Profile failed: {exc}")
    prof = st.session_state.get("profile_P")
    if not prof:
        return
    if prof[0] != key:
        stale_caption()
    show_profile(prof[1], NP, prof[2])


def stale_caption() -> None:
    """Under a profile measured on other settings than the page's - here and on the Compare page."""
    st.caption("This profile is from earlier settings - run it again to refresh.")


def freq_tables(top: pd.DataFrame, bottom: pd.DataFrame) -> None:
    """The most and the least frequent values of a column, side by side."""
    t1, t2 = st.columns(2)
    t1.markdown("Most frequent")
    t1.dataframe(top, width="stretch", hide_index=True)
    t2.markdown("Least frequent")
    t2.dataframe(bottom, width="stretch", hide_index=True)


def make_profile(P: Side, NP: str, opts: ReadOptions, say) -> dict:
    """The profile: what the values look like decides the types (there is no column
    table here to take a suggestion in), then the statistics, frequencies, keys and what
    stands out - the looks go along, so the notes can say what was read as what."""
    say("Looking at the values…")
    looks = looks_like(P, P.columns, opts=opts)
    return profile_single(P, single_specs(P, looks), opts, say, name=NP, looks=looks)


def best_key(prof: dict) -> list[str] | None:
    """The key: the best candidate when it is unique on every row, else None. The
    candidates come unique first, so the top row decides."""
    table, combos, _ = prof["keys"]
    return combos[0] if combos and len(table) and table.iloc[0]["Unique"] == "yes" else None


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


def show_profile(prof: dict, NP: str, made: str) -> None:
    """Top to bottom: the headline, the keys, the statistics table with its two save
    routes, what stands out, the outliers, patterns and dependencies folded, then a fold
    per column with its most and least frequent values."""
    st.subheader("Profile")
    st.caption(prof["headline"])

    # keys: the line, then every candidate the search offered
    table, combos, note = prof["keys"]
    best = best_key(prof)
    st.markdown("**Keys**")
    if best:
        st.success(f"Key: **{' + '.join(best)}** - unique on every row. {note}.")
    else:
        st.warning(f"Nothing up to {MAX_KEY_COLS} columns is unique"
                   + (" - the closest are below" if len(table) else "") + f". {note}.")
    st.dataframe(table, width="stretch", hide_index=True)

    notes: list[str] = prof["notes"]
    st.markdown("**Statistics**")
    stats: pd.DataFrame = prof["stats"]
    st.dataframe(stats, width="stretch", hide_index=True, height=min(560, 45 + 35 * len(stats)))
    stem = slug(NP) or "Table"
    fname = f"{stem}__profile.csv"
    csv = csv_bytes(stats)
    files = {fname: csv,
             f"{stem}__keys.csv": csv_bytes(table),
             f"{stem}__notes.txt": (prof["headline"] + "\n\n" + "\n".join(notes) + "\n").encode("utf-8"),
             f"{stem}__outliers.csv": csv_bytes(prof["outliers"]),
             f"{stem}__patterns.csv": csv_bytes(prof["patterns"]),
             f"{stem}__dependencies.csv": csv_bytes(dependencies_frame(prof))}
    d1, d2 = st.columns([1, 3])
    with d1:
        # on_click="ignore": the click must not rerun the page (see ui_results.report_tab)
        st.download_button("Download profile.csv", csv, fname, "text/csv", width="stretch",
                           key="dl_profile_P", on_click="ignore")
    with d2:
        save_row(files, "Save to folder", key="save_profile_P",
                 run={"pair": stem, "run_id": made}, tag="P")

    st.markdown("**What stands out**")
    if notes:
        st.markdown("\n".join(f"- {n}" for n in notes))
    else:
        st.caption("Nothing stands out - no nulls, no duplicates, no constant columns, no outliers.")

    with st.expander("Outliers", expanded=False):
        out: pd.DataFrame = prof["outliers"]
        if len(out):
            st.caption("One row per number, date and timestamp column: percentiles, Tukey's fences "
                       "(1.5 × IQR) and the values outside them, zeros and negatives.")
            st.dataframe(out, width="stretch", hide_index=True)
        else:
            st.caption("No number, date or timestamp columns - nothing to measure.")
    with st.expander("Patterns", expanded=False):
        pat: pd.DataFrame = prof["patterns"]
        if len(pat):
            st.caption("The three most common shapes of each text column - a letter is A, a digit 9, "
                       "the rest as written - with the first value of each shape.")
            st.dataframe(pat, width="stretch", hide_index=True)
        else:
            st.caption("No text columns with values - no shapes to show.")
    with st.expander("Dependencies", expanded=False):
        deps: pd.DataFrame = prof["deps"]
        corr: pd.DataFrame = prof["corr"]
        if len(deps):
            st.caption("Functional dependencies - X → Y: every X has one Y; one-to-one when it "
                       "holds the other way too.")
            st.dataframe(deps, width="stretch", hide_index=True)
        else:
            st.caption("No column determines another.")
        if len(corr):
            st.caption("Correlated number columns - |r| ≥ 0.7, the strongest first.")
            st.dataframe(corr, width="stretch", hide_index=True)
        else:
            st.caption("No correlated number columns.")

    st.markdown("**Value frequencies** - 10 most and 10 least frequent per column")
    by_col = stats.set_index("Column")
    for col, (top, bottom) in prof["freq"].items():
        with st.expander(f"**{col}** - {by_col.at[col, 'Type']} · {by_col.at[col, 'Distinct']:,} distinct · "
                         f"{by_col.at[col, 'Null %']}% null"):
            freq_tables(top, bottom)
