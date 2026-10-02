"""Short points instead of paragraphs: the page explains itself in a few bullets, each one
line, with the words that matter coloured - :green[key], :red[not compared], :orange[slow]
(Streamlit's colour markdown, set to the house pos / neg / accent in theme.py)."""
from __future__ import annotations

import streamlit as st


def tips(*points: str, key: str) -> None:
    """A tight, muted bullet list - the `tips_` key gives it its style (theme.css)."""
    with st.container(key=f"tips_{key}"):
        st.markdown("\n".join(f"- {p}" for p in points if p))
