"""The column table and the setup card under it."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from .columns import (SHOWN_COLS, apply_mapping_json, build_table, default_kind, mapping_json,
                      match_columns_by_data, normalise, only_in, pair_rows, shape, specs_from,
                      table_compare, table_keys)
from .sources import Side
from .state import bump, forget_results
from .theme import card, esc
from .values import TYPES, ColSpec, ReadOptions


@dataclass
class Setup:
    cmap: pd.DataFrame
    specs: list[ColSpec]
    keys: list[str]
    compare: list[str]
    only_a: list[str]
    only_b: list[str]
    confirmed: bool = False

    @property
    def canon(self) -> list[str]:
        return [s.canon for s in self.specs]


def seed_table(A: Side, B: Side) -> None:
    seed_key = (A.label, tuple(A.columns), B.label, tuple(B.columns))
    if st.session_state["cmap_seed"] != seed_key:
        st.session_state["cmap"] = build_table(A, B)
        st.session_state["cmap_seed"] = seed_key
        st.session_state.pop("auto_notes", None)
        bump()
        forget_results()


def render(A: Side, B: Side, NA: str, NB: str, opts: ReadOptions) -> Setup:
    seed_table(A, B)
    notes = st.session_state.get("auto_notes")
    if notes:
        with st.expander(f"What Auto decided - {len(notes)} decisions, every one a cell below",
                         expanded=True):
            for n_ in notes:
                st.markdown(f"- {n_}")
            if st.button("Dismiss", key="auto_dismiss"):
                st.session_state.pop("auto_notes", None)
                st.rerun()

    confirmed = bool(st.session_state.get("confirmed"))
    prev: pd.DataFrame = st.session_state["cmap"]
    n_pairs = int(((prev["A column"] != "") & (prev["B column"] != "")).sum())
    with st.expander(f"Column table - {n_pairs} pairs · every column from either file",
                     expanded=not confirmed):
        st.caption(
            f"One row per column from either file. Pick the counterpart in the *{NA} column* "
            f"or *{NB} column* dropdown - blank means no counterpart. Give the pair its "
            "**common name**, choose the **Type** both sides are converted to, tick **Key** "
            "on what identifies a row and **Compare** on what to compare. Double-click a cell "
            "to change it; greyed cells are information. Transforms live in the next section.")
        tcol, bcol = st.columns([4, 1.25])
        with tcol:
            edited = st.data_editor(
                prev, key=f"cmap_{st.session_state['map_rev']}", hide_index=True,
                width="stretch", num_rows="fixed", column_order=SHOWN_COLS,
                height=min(640, 45 + 35 * len(prev)),
                disabled=["Matched by", "A detected", "B detected"],
                column_config={
                    "A column": st.column_config.SelectboxColumn(f"{NA} column", options=[""] + A.columns),
                    "B column": st.column_config.SelectboxColumn(f"{NB} column", options=[""] + B.columns),
                    "Common name": st.column_config.TextColumn("Common name"),
                    "Type": st.column_config.SelectboxColumn(
                        "Type · both sides", options=TYPES, required=True,
                        help="The type both files are converted to before comparing. "
                             "number: 100.00 = 100 · date: 27/08/2026 = 2026-08-27 · "
                             "timestamp keeps the time · boolean: 1 = yes = true."),
                    "Key": st.column_config.CheckboxColumn("Key", help="Part of the row key."),
                    "Compare": st.column_config.CheckboxColumn("Compare", help="Compare this column "
                                                                               "(ignored on keys)."),
                    "Matched by": st.column_config.TextColumn("Matched by", width="small"),
                    "A detected": st.column_config.TextColumn(f"{NA} detected", width="small"),
                    "B detected": st.column_config.TextColumn(f"{NB} detected", width="small"),
                })
        cmap = normalise(edited, prev, A, B)
        st.session_state["cmap"] = cmap
        if shape(cmap) != shape(edited) or len(cmap) != len(prev):
            bump()                              # rows moved or merged: redraw the editor
            st.session_state["confirmed"] = False
            forget_results()
            st.rerun()

        dup_n = sorted(set(cmap["Common name"][cmap["Common name"].duplicated()]))
        if dup_n:
            st.error("Common name used more than once: **" + ", ".join(dup_n) + "**")

        with bcol:
            only_a, only_b = only_in(cmap, "A"), only_in(cmap, "B")
            if st.button("Match by data", width="stretch", type="primary",
                         disabled=not (only_a and only_b),
                         help="Reads a sample of both files and pairs the unpaired columns "
                              "that hold the same values, whatever they are called."):
                with st.spinner("Comparing the values in each column…"):
                    table, found = match_columns_by_data(A, B, only_a, only_b, NA, NB, opts)
                st.session_state["data_match"] = (table, found)
            if st.button("Reset to name matches", width="stretch"):
                st.session_state["cmap"] = build_table(A, B)
                st.session_state["confirmed"] = False
                bump()
                forget_results()
                st.rerun()
            st.download_button("Save mapping", mapping_json(cmap), "mapping.json",
                               "application/json", width="stretch")
            up_map = st.file_uploader("Load mapping", type=["json"], key="map_up",
                                      label_visibility="collapsed")
            if up_map is not None:
                fid = getattr(up_map, "file_id", f"{up_map.name}:{up_map.size}")
                if st.session_state.get("map_loaded") != fid:
                    try:
                        st.session_state["cmap"] = apply_mapping_json(
                            up_map.getvalue().decode("utf-8"), A, B)
                    except (ValueError, KeyError, AttributeError, TypeError) as exc:
                        st.error(f"Could not read the mapping file: {exc}")
                    else:
                        st.session_state["map_loaded"] = fid
                        bump()
                        forget_results()
                        st.rerun()

        dm = st.session_state.get("data_match")
        if dm is not None:
            table, found = dm
            if not len(table):
                st.info("No unpaired column on one side holds the same values as one on "
                        "the other - they look like genuinely different fields.")
            else:
                st.success(f"{len(table)} pair(s) of columns hold the same values.")
                st.dataframe(table, width="stretch", hide_index=True)
            d1, d2, _ = st.columns([1, 1, 4])
            if len(table) and d1.button("Apply these pairs", type="primary"):
                st.session_state["cmap"] = pair_rows(st.session_state["cmap"], found, A, B)
                st.session_state.pop("data_match", None)
                bump()
                forget_results()
                st.rerun()
            if d2.button("Dismiss", key="dm_dismiss"):
                st.session_state.pop("data_match", None)
                st.rerun()

        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Confirm columns", type="primary", width="stretch", key="confirm_cols",
                     help="Folds the table away and shows the setup it amounts to."):
            st.session_state["confirmed"] = True
            st.rerun()
        if confirmed and c2.button("Edit columns", width="stretch", key="edit_cols"):
            st.session_state["confirmed"] = False
            st.rerun()

    cmap = st.session_state["cmap"]
    specs = specs_from(cmap)
    setup = Setup(cmap, specs, table_keys(cmap), table_compare(cmap),
                  only_in(cmap, "A"), only_in(cmap, "B"), confirmed)
    render_setup_card(setup, NA, NB)
    return setup


def render_setup_card(s: Setup, NA: str, NB: str) -> None:
    """What the table amounts to: key, compare list, types and steps, what is missing."""
    typed = [sp for sp in s.specs if sp.kind != "text" or sp.a_steps or sp.b_steps]
    key_html = (f"<code>{esc(' + '.join(s.keys))}</code>" if s.keys
                else '<span class="warn">none ticked - rows will be matched by hashing the compared '
                     'columns, or by position; see the Key section</span>')
    off = [c for c in s.canon if c not in s.keys and c not in s.compare]
    rows = [
        ("Paired", f"{len(s.specs)} columns" + (f' · <span class="m">{len(s.only_a)} only in {esc(NA)}, '
                                                 f'{len(s.only_b)} only in {esc(NB)}</span>'
                                                 if s.only_a or s.only_b else "")),
        ("Key", key_html),
        ("Compare", (f"{len(s.compare)} columns: " + esc(", ".join(s.compare)) if s.compare
                     else '<span class="warn">nothing ticked</span>')
                    + (f' <span class="m">· not compared: {esc(", ".join(off))}</span>' if off else "")),
        ("Read as", "<br>".join(f"<code>{esc(sp.canon)}</code> {esc(sp.describe())}" for sp in typed)
                    or '<span class="m">all text, no transforms</span>'),
    ]
    if s.only_a:
        rows.append((f"Only in {NA}", esc(", ".join(s.only_a))
                     + f' <span class="m">· null on the {esc(NB)} side, not compared</span>'))
    if s.only_b:
        rows.append((f"Only in {NB}", esc(", ".join(s.only_b))
                     + f' <span class="m">· null on the {esc(NA)} side, not compared</span>'))
    st.markdown(card(rows), unsafe_allow_html=True)
