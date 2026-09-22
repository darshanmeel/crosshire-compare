"""The Key section: what is ticked, Suggest keys, Check key, and what to do without one."""
from __future__ import annotations

import duckdb
import streamlit as st

from . import ui_log
from .keys import MAX_KEY_COLS, key_uniqueness, suggest_keys
from .sources import Side
from .state import bump, forget_results
from .ui_columns import Setup
from .values import ReadOptions


def render(A: Side, B: Side, NA: str, NB: str, setup: Setup, opts: ReadOptions,
           profile: dict | None = None) -> str:
    """Returns the pairing mode: key, hash or position. A current profile, when given, saves
    Suggest keys measuring the single columns again."""
    keys = setup.keys
    k1, k2, k3 = st.columns([4, 1, 1])
    with k1:
        if keys:
            st.markdown(f"Rows are matched on **{' + '.join(keys)}** - the columns ticked "
                        "*Key* in the table.")
        else:
            st.markdown("No key ticked. Rows can still be compared:")
            st.radio("Without a key", ["hash", "position"], key="nokey_mode",
                     label_visibility="collapsed", horizontal=True,
                     format_func=lambda m: {
                         "hash": "match identical rows by hashing the compared columns",
                         "position": "pair by position - line 1 against line 1"}[m])
            st.caption("Hashing finds the rows that are identical on every compared column and "
                       "reports the rest as one-sided, with the columns whose values only exist "
                       "on one side - useful when there is no key at all. Position only works "
                       "when both files are sorted identically.")
    with k2:
        suggest = st.button("Suggest keys", width="stretch", key="sugg_btn",
                            help="Finds the column combinations that identify a row on both sides, "
                                 "a level at a time - every column, then every pair, then three, "
                                 "then four - counted on the first side and verified on the second, "
                                 "with Desbordante (HyUCC / PyroUCC) when it is installed. Minutes "
                                 "on a wide or big pair. Only runs when pressed.")
    with k3:
        check = st.button("Check key", width="stretch", disabled=not keys, key="check_btn",
                          help="Counts distinct key values against rows on each side.")
    st.caption("Suggest keys measures every column and, when none is unique, every pair of the "
               "most key-like columns, then combinations of three and of four - each level only "
               "when the one before found no key. The counting reads one side: over 5,000 rows a "
               "level is counted on a random sample of 5,000 rows of it first, only the "
               "combinations unique there are counted on every row - a full count each, which is "
               "where the time goes on a wide or big pair with no obvious key: minutes - and what "
               "is unique there is verified on the other side, where it has to be unique too and "
               "to share values before it is the key.")
    if suggest:                                   # under the row, so the disc has the width
        try:
            with ui_log.running("Looking for keys…", "Key search", here=True) as box:
                st.session_state["key_suggestions"] = suggest_keys(
                    A, B, setup.specs, NA, NB, opts, progress=box.write, profile=profile)
                table, combos, _ = st.session_state["key_suggestions"]
                best = combos[0] if combos else None
                box.update(label=("Best key: " + " + ".join(best)) if best else "No key found",
                           state="complete")
        except (duckdb.Error, RuntimeError) as exc:
            st.error(f"Could not measure the columns: {exc}")

    sugg = st.session_state.get("key_suggestions")
    if sugg is not None:
        table, combos, note = sugg
        good = table[table["Unique on both"] == "yes"] if len(table) else table
        if len(good):
            st.success(f"{len(good)} combination(s) identify a single row on both sides - "
                       f"best: **{good.iloc[0]['Key columns']}**. {note}.")
        else:
            st.warning(f"Nothing up to {MAX_KEY_COLS} columns was unique on both sides - "
                       f"the closest are below. {note}.")
        s1, s2 = st.columns([3, 1])
        s1.dataframe(table, width="stretch", hide_index=True)
        with s2:
            labels = [" + ".join(c) for c in combos]
            picks = st.multiselect("Use these", labels, key="key_pick",
                                   label_visibility="collapsed", placeholder="pick one or more rows",
                                   help="Pick several and their columns are combined into one key.")
            chosen = list(dict.fromkeys(c for lbl in picks for c in combos[labels.index(lbl)]))
            if chosen:
                st.caption("Key would be **" + " + ".join(chosen) + "**")
            if st.button("Use as key", width="stretch", type="primary", disabled=not chosen):
                cm = st.session_state["cmap"]
                paired = (cm["A column"] != "") & (cm["B column"] != "")
                cm.loc[paired, "Key"] = cm.loc[paired, "Common name"].isin(chosen)
                st.session_state.pop("key_suggestions", None)
                bump()
                forget_results()
                st.rerun()
            if st.button("Dismiss", width="stretch", key="sugg_dismiss"):
                st.session_state.pop("key_suggestions", None)
                st.rerun()

    if keys and check:
        try:
            with st.spinner("Counting distinct keys on both sides…"):
                st.session_state["key_report"] = (tuple(keys),
                                                  key_uniqueness(A, B, setup.specs, keys, NA, NB, opts))
        except duckdb.Error as exc:
            st.error(f"Key check failed: {exc}")
    held = st.session_state.get("key_report")
    if keys and held and held[0] == tuple(keys):
        report = held[1]
        u1, u2 = st.columns([1, 2])
        u1.dataframe(report, width="stretch", hide_index=True)
        if (report["Unique"] == "yes").all():
            u2.success(f"**{' + '.join(keys)}** identifies a single row on both sides.")
        else:
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
            u2.warning(" ".join(said))
    return "key" if keys else st.session_state.get("nokey_mode", "hash")
