"""The sidebar: load side A and side B - a CSV or JSON file - and the Auto button.
Nothing else lives here."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import duckdb
import streamlit as st

from .sources import (Side, apply_names, file_stamp, kind_of, looks_headerless, quick_clause,
                      row_count, short_header, snapshot, source_schema)
from .state import drop_result

DEFAULT_NAMES = {"A": "Left", "B": "Right"}
QUICK_OPS = ["=", "!=", ">", ">=", "<", "<=", "contains", "starts with",
             "in (comma separated)", "is null", "is not null"]


def staged_upload(tag: str, up) -> str:
    """Write an upload to the temp folder once, so DuckDB can stream it from disk."""
    fid = getattr(up, "file_id", None) or f"{up.name}:{up.size}"
    held = st.session_state.get(f"staged_{tag}")
    if held and held[0] == fid and Path(held[1]).exists():
        return held[1]
    tmp = Path(tempfile.gettempdir()) / f"cmp_{tag}_{int(time.time())}_{up.name}"
    tmp.write_bytes(up.getvalue())
    st.session_state[f"staged_{tag}"] = (fid, str(tmp))
    return str(tmp)


def source_panel(tag: str) -> None:
    st.markdown(f"#### File {tag}")
    name = st.text_input("Name", value=DEFAULT_NAMES[tag], key=f"nick_{tag}",
                         help="What to call this side throughout the app. Keep it short.")
    how = st.radio("From", ["Upload", "Path on disk"], horizontal=True, key=f"how_{tag}",
                   label_visibility="collapsed")
    path, label, origin = "", "", ""
    if how == "Upload":
        up = st.file_uploader("CSV or JSON file", type=["csv", "txt", "tsv", "dat", "json", "jsonl", "ndjson", "parquet"],
                              key=f"up_{tag}", help="CSV / delimited text, or JSON - an array of objects or one object per line")
        if up is not None:
            path, label = staged_upload(tag, up), up.name
    else:
        p = st.text_input("Path to CSV or JSON", key=f"pt_{tag}",
                          placeholder=r"C:\data\exports\orders_2026-09.csv").strip()
        if p:
            if Path(p).is_file():
                path, label = p, Path(p).name
            else:
                st.error("File not found.")
    kind = kind_of(path) if path else "csv"

    delim, hdr = ",", True
    if kind == "csv":
        d1, d2 = st.columns([1, 2])
        delim = d1.text_input("Delimiter", value=",", key=f"dl_{tag}", max_chars=3)
        hdr = d2.checkbox("First row is a header", value=True, key=f"hd_{tag}")

    schema: dict[str, str] = {}
    if path:
        try:
            schema = source_schema(path, kind, delim, hdr, file_stamp(path))
        except duckdb.Error as exc:
            st.error(f"Could not read the {kind} file: {exc}")
    cols = list(schema)
    if cols:
        st.caption(f"{len(cols)} columns: " + ", ".join(cols[:12])
                   + (f" … +{len(cols) - 12} more" if len(cols) > 12 else ""))

    rev = st.session_state.get(f"where_rev_{tag}", 0)
    with st.expander("Rows to read - filter, order, top N", expanded=False):
        st.caption("Applied as the file is read, on its own column names, before anything "
                   "else - how a huge file is made small. Values are text here: "
                   "`date >= '2026-07-20'`.")
        if cols:
            qc = st.selectbox("Column", cols, key=f"qf_col_{tag}")
            qo = st.selectbox("Condition", QUICK_OPS, key=f"qf_op_{tag}")
            qv = st.text_input("Value", key=f"qf_val_{tag}",
                               disabled=qo in ("is null", "is not null"),
                               placeholder="2026-07-20 · GB · 100")
            if st.button("Add to filter", key=f"qf_add_{tag}", width="stretch"):
                clause = quick_clause(qc, qo, qv)
                cur = st.session_state.get(f"where_{tag}", "")
                st.session_state[f"where_{tag}"] = (f"{cur.strip()}\nAND {clause}"
                                                    if cur.strip() else clause)
                st.session_state[f"where_rev_{tag}"] = rev + 1
                st.rerun()
        where = st.text_area("Filter (WHERE)", value=st.session_state.get(f"where_{tag}", ""),
                             key=f"cw_{tag}_{rev}", height=90,
                             placeholder="date >= '2026-07-20'\nAND country = 'GB'")
        st.session_state[f"where_{tag}"] = where
        order = st.multiselect("Order by", cols, key=f"ob_{tag}_{abs(hash(tuple(cols)))}",
                               placeholder="file order")
        desc = st.checkbox("Descending", key=f"od_{tag}", disabled=not order)
        top = st.number_input("Top N rows (0 = all)", 0, 500_000_000, 0, step=10_000,
                              key=f"top_{tag}",
                              help="Taken after the filter and the order, so 'order by date "
                                   "descending, top 100,000' is the latest 100,000 rows.")

    with st.expander("Advanced", expanded=False):
        names_txt = st.text_area("Column names - comma separated, overrides the header row",
                                 key=f"nm_{tag}", height=68,
                                 placeholder="index_symbol, date, next_trading_day, ...",
                                 help="Use this when the header row is missing names.")
        snap = st.checkbox("Snapshot the rows read to Parquet", value=True, key=f"pq_{tag}",
                           help="Reads the CSV once, keeps the result as a compact Parquet "
                                "file in the temp folder, and everything below reads that "
                                "instead of re-parsing the CSV. Recommended for big files.")

    if st.button(f"Load {tag}", key=f"load_{tag}", type="primary", width="stretch",
                 disabled=not cols):
        side = Side(name=name.strip() or tag, label=label, csv_path=path, kind=kind, origin=origin,
                    delimiter=delim, header=hdr, where=where, order_by=list(order),
                    desc=bool(desc), limit=int(top))
        names = names_txt.split(",") if names_txt.strip() else []
        if names and len(names) != len(schema):
            st.warning(f"You gave {len(names)} names but the file has {len(schema)} "
                       "columns - the surplus was ignored / the shortfall kept its original name.")
        side.schema = apply_names(schema, names) if names else dict(schema)
        side.source_columns = list(schema)
        try:
            with st.spinner("Reading the rows…"):
                if snap:
                    pq = Path(tempfile.gettempdir()) / f"cmp_{tag}_{int(time.time())}.parquet"
                    snapshot(side, str(pq))
                side.rows = row_count(side)
        except duckdb.Error as exc:
            st.error(f"Could not read the rows: {exc}")
            return
        finish(tag, side)

    side: Side = st.session_state[tag]      # re-read: it may have just been loaded
    if side.loaded:
        st.caption(f"**{side.name}** · {side.origin or side.label} - {side.rows:,} rows, "
                   f"{len(side.schema)} columns"
                   + (f"  ·  {side.cut}" if side.cut else "")
                   + ("  ·  Parquet snapshot" if side.cache_path else ""))
        if side.rows == 0:
            st.warning("The filter left no rows.")
        if side.kind == "csv" and side.header and looks_headerless(side.schema):
            st.error("These column names look like a data row. Untick **First row is a "
                     "header** and load again.")
        missing = short_header(side.schema) if side.kind == "csv" else 0
        if missing:
            named = len(side.schema) - missing
            st.error(f"The header row names only **{named}** columns but the data has "
                     f"**{len(side.schema)}** fields, so the last {missing} were auto-named. "
                     "Paste the full comma-separated list into **Advanced → Column names** "
                     "and load again.")



def finish(tag: str, side: Side) -> None:
    old: Side = st.session_state[tag]
    if old.cache_path and old.cache_path != side.cache_path:
        Path(old.cache_path).unlink(missing_ok=True)
    st.session_state[tag] = side
    drop_result()


def auto_panel() -> None:
    st.markdown("#### Auto")
    A, B = st.session_state.A, st.session_state.B
    both_in = A.loaded and B.loaded
    st.caption("Auto does everything by itself - pairs the columns, finds the key, "
               "compares, and lists each decision so you can change it.")
    if st.button("Figure it all out and compare", type="primary", width="stretch",
                 disabled=not both_in, key="auto_btn"):
        st.session_state["auto_request"] = True
