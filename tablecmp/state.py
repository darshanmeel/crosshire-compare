"""Session state: defaults, what a run keeps across the two pages, and what to forget when
the inputs change."""
from __future__ import annotations

import streamlit as st

from .sources import Side
from .values import NULL_TOKENS_DEFAULT

DEFAULT_NAMES = {"A": "Left", "B": "Right", "P": "Table"}    # what a side is called until it is named

# the sidebar panel's widgets, per tag (A and B on Compare, P on Profiling) - the ones whose
# value is worth keeping when the page is switched; the upload box cannot be kept, nor the
# quick-filter pickers, whose options are the file's columns
PANEL_KEYS = ("nick", "how", "pt", "dl", "hd", "ob", "od", "top", "nm", "pq",
              "conn", "pw", "dbmode", "tbl", "sql", "cap")
# Streamlit forgets a widget's value when a run does not draw it, and a run draws one page
# only: every run writes these back before any widget is drawn, so the Compare page's
# settings and both sidebars survive a trip to the other page. A widget listed here takes
# its default from DEFAULTS, not from a value= of its own - the value written back is the
# only one Streamlit sees.
KEEP = ("opt_trim", "opt_empty", "opt_case", "opt_tol", "null_tokens", "disp_rows", "auto_rerun",
        "nokey_mode", "out_fmt", "auto_profile",
        # the results page draws one view at a time, so a widget on another view is not drawn
        # on this run either - these are what the reader picked, and picking again is the work
        "res_view", "col_cards", "freq_cols_pair", "freq_cols_P",
        *(f"{k}_{tag}" for tag in "ABP" for k in PANEL_KEYS))
KEEP_PREFIXES = ("bucket_cols_",)             # one picker per bucket, named for the bucket

DEFAULTS = {"A": Side, "B": Side, "P": Side,  # the two sides compared, the one table profiled
            "result": lambda: None, "cmap": lambda: None,
            "cmap_seed": lambda: None, "map_rev": lambda: 0, "nokey_mode": lambda: "hash",
            "db_passwords": dict,                 # typed this session, never written anywhere
            "fetched_A": lambda: None, "fetched_B": lambda: None,   # the database fetch each side holds
            "fetched_P": lambda: None,
            # the widgets kept across pages that do not start blank, off or at zero
            "opt_trim": lambda: True, "opt_empty": lambda: True,
            "auto_profile": lambda: False,        # profiling is the slow part: asked for, not assumed
            "null_tokens": lambda: NULL_TOKENS_DEFAULT, "disp_rows": lambda: 1000,
            **{f"nick_{tag}": (lambda name=name: name) for tag, name in DEFAULT_NAMES.items()},
            **{f"{k}_{tag}": (lambda: True) for tag in "ABP" for k in ("hd", "pq")},
            **{f"dl_{tag}": (lambda: ",") for tag in "ABP"}}


def init_state() -> None:
    for key, make in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = make()
    kept = [*KEEP, *(k for k in list(st.session_state) if k.startswith(KEEP_PREFIXES))]
    for key in kept:                              # see KEEP: written back before any widget is drawn
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def kept_picks(key: str, options: list[str], default: list[str] | None = None) -> list[str]:
    """What a multiselect holds, kept across a run that does not draw it (see KEEP) and cut
    back to the options on offer: a new file can take a column away, and Streamlit raises on
    a value that is not among the options. The default is used once, when nothing is held."""
    have = set(options)
    held = st.session_state[key] if key in st.session_state else list(default or [])
    st.session_state[key] = [c for c in held if c in have]
    return st.session_state[key]


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
