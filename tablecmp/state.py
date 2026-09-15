"""Session state: defaults, and what to forget when the inputs change."""
from __future__ import annotations

import streamlit as st

from .sources import Side

DEFAULTS = {"A": Side, "B": Side, "result": lambda: None, "cmap": lambda: None,
            "cmap_seed": lambda: None, "map_rev": lambda: 0, "confirmed": lambda: False,
            "nokey_mode": lambda: "hash"}


def init_state() -> None:
    for key, make in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = make()


def forget_results() -> None:
    """Derived caches are stale once the files or the column table change. The last
    comparison is kept - the page marks it stale rather than throwing it away."""
    for k in ("profile", "conv", "key_report", "key_suggestions", "data_match"):
        st.session_state.pop(k, None)


def drop_result() -> None:
    """A new file: the last comparison no longer means anything."""
    st.session_state["result"] = None
    st.session_state["cmap_seed"] = None
    forget_results()


def bump() -> None:
    """The column table changed shape or content from code: give the editor a fresh key."""
    st.session_state["map_rev"] = st.session_state.get("map_rev", 0) + 1
