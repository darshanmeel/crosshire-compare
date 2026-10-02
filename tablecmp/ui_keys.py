"""The Key section: what is ticked, Suggest keys, Check key, and what to do without one."""
from __future__ import annotations

import duckdb
import streamlit as st

from . import ui_log
from .columns import set_steps
from .keyformat import Fix, applied, key_format_fixes
from .keys import MAX_KEY_COLS, key_affinity, key_uniqueness, suggest_keys
from .sources import Side
from .state import bump, forget_results
from .ui_columns import Setup
from .ui_text import tips
from .values import ReadOptions


# ---- key formats: a key the two sides write differently ----------------------------
def _apply_fix(setup: Setup, fx: Fix) -> bool:
    """The fix's steps after the column's own, into the column table; False when the column is gone."""
    spec = next((sp for sp in setup.specs if sp.canon == fx.canon), None)
    if spec is None:
        return False
    sa, sb = applied(spec, fx)
    cm = st.session_state["cmap"]
    set_steps(cm, fx.canon, "A", sa)
    set_steps(cm, fx.canon, "B", sb)
    return True


def key_like(A: Side, B: Side, setup: Setup) -> list[str]:
    """The key, or - with none ticked - the text columns whose names read like one."""
    return setup.keys or [sp.canon for sp in setup.specs if sp.kind == "text" and key_affinity(
        sp.canon, A.schema.get(sp.a_src, ""), B.schema.get(sp.b_src, "")) >= 3]


def check_formats(A: Side, B: Side, setup: Setup, opts: ReadOptions, cols: list[str]) -> bool:
    """Look for key columns written differently on the two sides: the simple fixes go into
    the column table now, the rest wait in the Key section for Apply. True when the table
    changed - the caller reruns."""
    fixes = key_format_fixes(A, B, setup.specs, cols, opts)
    done = [fx for fx in fixes if fx.simple and _apply_fix(setup, fx)]
    st.session_state["key_formats"] = (tuple(cols), [(fx, fx in done) for fx in fixes])
    if done:
        bump()
        forget_results()
    return bool(done)


def formats_panel(setup: Setup) -> None:
    """What the last format check found: what was applied, and Apply for each suggestion."""
    held = st.session_state.get("key_formats")
    if not held:
        return
    cols, found = held
    if not found:
        st.caption(f"Key formats checked ({', '.join(cols)}): the two sides write them alike.")
        return
    for i, (fx, done) in enumerate(found):
        if done:
            st.success(f":green[**Applied**] · {fx.said}. The steps are in the column table.")
            continue
        f1, f2 = st.columns([5, 1])
        f1.warning(f":orange[**Suggested**] · {fx.said}. It may drop something that matters - "
                   "your call.")
        if f2.button("Apply", key=f"kf_apply_{i}", width="stretch", type="primary"):
            if _apply_fix(setup, fx):
                found[i] = (fx, True)
                bump()
                forget_results()
            st.rerun()
    if st.button("Dismiss", key="kf_dismiss"):
        st.session_state.pop("key_formats", None)
        st.rerun()


def render(A: Side, B: Side, NA: str, NB: str, setup: Setup, opts: ReadOptions,
           profile: dict | None = None) -> str:
    """Returns the pairing mode: key, hash or position. A current profile, when given, saves
    Suggest keys measuring the single columns again."""
    keys = setup.keys
    if keys and st.session_state.pop("_check_formats", False):      # a key just picked
        try:
            if check_formats(A, B, setup, opts, keys):
                st.rerun()
        except duckdb.Error as exc:
            st.error(f"Could not check the key's formats: {exc}")
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
            tips("**hash** - rows identical on every compared column match; the rest are one-sided",
                 "**position** - line 1 against line 1: :orange[only when both files are sorted the same]",
                 key="nokey")
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
    tips("**Suggest keys** tries single columns, then pairs, threes, fours - stopping at the first "
         "level with a key",
         "Over 5,000 rows: a 5,000-row sample first, then a full count of what survived · the other "
         "side must agree",
         "A wide or big pair with no obvious key: :orange[minutes]",
         key="keysearch")
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
                st.session_state["_check_formats"] = True
                bump()
                forget_results()
                st.rerun()
            if st.button("Dismiss", width="stretch", key="sugg_dismiss"):
                st.session_state.pop("key_suggestions", None)
                st.rerun()

    check = check or (keys and st.session_state.pop("_check_again", False))
    if keys and check:
        try:
            if check_formats(A, B, setup, opts, keys):           # the key report counts the fixed values
                st.session_state["_check_again"] = True
                st.rerun()
        except duckdb.Error as exc:
            st.error(f"Could not check the key's formats: {exc}")
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
    formats_panel(setup)
    return "key" if keys else st.session_state.get("nokey_mode", "hash")
