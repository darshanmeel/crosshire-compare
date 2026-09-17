"""The Profiling page: one table on its own - its statistics and the most and least
frequent values of every column, the same measures the Compare page's Profile section
takes of a pair."""
from __future__ import annotations

import json

import duckdb
import pandas as pd
import streamlit as st

from . import ui_log
from .columns import single_specs
from .outputs import run_id
from .profile import profile_single
from .sniff import looks_like
from .sources import Side, preview_rows, slug
from .ui_results import save_row
from .values import ReadOptions


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
                st.session_state["profile_P"] = (key, make_profile(P, opts, box.write), run_id())
                box.update(label="Profile ready", state="complete")
        except duckdb.Error as exc:
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


def make_profile(P: Side, opts: ReadOptions, say) -> dict:
    """The profile: what the values look like decides the types (there is no column
    table here to take a suggestion in), then the statistics and frequencies."""
    say("Looking at the values…")
    return profile_single(P, single_specs(P, looks_like(P, P.columns, opts=opts)), opts, say)


def show_profile(prof: dict, NP: str, made: str) -> None:
    """The statistics table with its two save routes, then a fold per column with its
    most and least frequent values."""
    st.subheader("Profile")
    stats: pd.DataFrame = prof["stats"]
    st.dataframe(stats, width="stretch", hide_index=True, height=min(560, 45 + 35 * len(stats)))
    stem = slug(NP) or "Table"
    fname = f"{stem}__profile.csv"
    csv = stats.to_csv(index=False, lineterminator="\n").encode("utf-8")
    d1, d2 = st.columns([1, 3])
    with d1:
        # on_click="ignore": the click must not rerun the page (see ui_results.report_tab)
        st.download_button("Download profile.csv", csv, fname, "text/csv", width="stretch",
                           key="dl_profile_P", on_click="ignore")
    with d2:
        save_row({fname: csv}, "Save to folder", key="save_profile_P",
                 run={"pair": stem, "run_id": made}, tag="P")
    st.markdown("**Value frequencies** - 10 most and 10 least frequent per column")
    by_col = stats.set_index("Column")
    for col, (top, bottom) in prof["freq"].items():
        with st.expander(f"**{col}** - {by_col.at[col, 'Type']} · {by_col.at[col, 'Distinct']:,} distinct · "
                         f"{by_col.at[col, 'Null %']}% null"):
            freq_tables(top, bottom)
