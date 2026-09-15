"""
compare_app.py - compare two tables (CSV, Parquet, JSON, Snowflake, SQL Server), row by row, on a key you choose.

    pip install streamlit duckdb
    pip install desbordante        # optional: exact key discovery
    python compare_app.py          # starts the app with its own settings
    streamlit run compare_app.py   # also works

Files: compare_app.py, csvdiff.py (the engine) and the tablecmp/ folder, together.
Everything else - colours, fonts, limits - is in tablecmp/theme.py.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    from tablecmp.theme import APP_NAME, APP_TAGLINE, STREAMLIT_THEME, THEME, brand_html  # noqa: E402
except ModuleNotFoundError as _exc:                # the package folder is not next to this file
    if _exc.name and _exc.name.split(".")[0] == "tablecmp":
        _loose = sorted(p.name for p in HERE.glob("*.py")
                        if p.name not in ("compare_app.py", "csvdiff.py"))
        _hint = (f"\nThese look like its modules, loose in the same folder: {', '.join(_loose)}\n"
                 f"Make a folder called  tablecmp  next to compare_app.py and move them into it."
                 if _loose else "")
        raise SystemExit(
            f"compare_app.py needs the folder  {HERE / 'tablecmp'}  (with __init__.py, theme.py, "
            f"compare.py, ... inside) next to it, and it is not there.{_hint}\n"
            f"Expected layout:\n  {HERE.name}\\\n    compare_app.py\n    csvdiff.py\n"
            f"    tablecmp\\\n      __init__.py  theme.py  sql.py  state.py  sources.py  values.py\n"
            f"      columns.py  keys.py  profile.py  compare.py  report.py  auto.py\n"
            f"      ui_sidebar.py  ui_columns.py  ui_transform.py  ui_keys.py  ui_results.py") from None
    raise

if __name__ == "__main__":
    import streamlit.runtime as _rt
    if not _rt.exists():                         # `python compare_app.py`: start the server
        from streamlit.web import bootstrap
        bootstrap.run(__file__, False, [], {"server.maxUploadSize": THEME["upload_mb"],
                                            "browser.gatherUsageStats": False, **STREAMLIT_THEME})
        raise SystemExit

import duckdb                                     # noqa: E402
import pandas as pd                               # noqa: E402
import streamlit as st                            # noqa: E402
from streamlit import config as _cfg              # noqa: E402

if _cfg.get_option("theme.primaryColor") != THEME["brass"]:     # under `streamlit run`
    for _k, _v in STREAMLIT_THEME.items():
        try:
            _cfg.set_option(_k, _v)
        except Exception:
            pass
    if not st.session_state.get("_themed"):
        st.session_state["_themed"] = True
        st.rerun()

st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")

try:
    import csvdiff                                # noqa: F401  the engine, next to this file
except ImportError:
    st.error("csvdiff.py must sit in the same folder as compare_app.py.")
    st.stop()


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


for pkg, need, have in (("streamlit", "1.49", st.__version__), ("duckdb", "1.1", duckdb.__version__)):
    if _version(have) < _version(need):
        st.error(f"{pkg} {need} or newer is needed (found {have}). Run `pip install -U {pkg}`.")
        st.stop()

from tablecmp import ui_columns, ui_keys, ui_results, ui_sidebar, ui_transform   # noqa: E402
from tablecmp.auto import auto_configure                                          # noqa: E402
from tablecmp.compare import discard_run, OPS, build_filters, run_comparison, signature       # noqa: E402
from tablecmp.profile import profile_tables                                       # noqa: E402
from tablecmp.sources import Side, preview_rows                                   # noqa: E402
from tablecmp.state import bump, forget_results, init_state                       # noqa: E402
from tablecmp.theme import css, status_strip                                      # noqa: E402
from tablecmp.values import NULL_TOKENS_DEFAULT, ReadOptions                      # noqa: E402

init_state()
st.markdown(css(), unsafe_allow_html=True)
st.markdown(f'<div class="eyebrow">{APP_NAME} · <span>CSV or JSON, either side</span></div>'
            '<h1 class="hero-h">Two tables, <em>every difference.</em></h1>'
            '<p class="lede">Read by DuckDB, paired in one table, compared row by row on a key '
            'you choose - or let <strong>Auto</strong> work the whole thing out.</p>',
            unsafe_allow_html=True)
strip = st.empty()

with st.sidebar:
    st.markdown(f'<div class="rail-mark">{brand_html()}</div>'
                f'<div class="rail-sub">{APP_TAGLINE}</div>', unsafe_allow_html=True)
    ui_sidebar.source_panel("A")
    st.markdown("---")
    ui_sidebar.source_panel("B")
    st.markdown("---")
    ui_sidebar.auto_panel()

A: Side = st.session_state.A
B: Side = st.session_state.B
if not (A.loaded and B.loaded):
    n = sum(1 for s in (A, B) if s.loaded)
    status_strip(strip, f"{n} of 2 loaded", "-", "-", "-", "-", {"Files": "warn"})
    st.info("Load **A** and **B** in the sidebar - a CSV, Parquet or JSON file, or a table, query or "
            "stored procedure on Snowflake or SQL Server. For a big source, open **Rows to read** "
            "there first and cut it down before pressing Load.")
    st.stop()

NA = (st.session_state.get("nick_A") or A.name or "Left").strip()
NB = (st.session_state.get("nick_B") or B.name or "Right").strip()
OPTS = ReadOptions.from_state(st.session_state)

# ---- Auto -------------------------------------------------------------------
if st.session_state.pop("auto_request", False):
    with st.status("Working it out…", expanded=True) as box:
        try:
            t0 = time.perf_counter()
            new_map, notes, chosen = auto_configure(A, B, NA, NB, OPTS, box.write)
        except (duckdb.Error, RuntimeError) as exc:
            box.update(label="Auto could not finish", state="error")
            st.error(f"Auto stopped: {exc}")
        else:
            box.update(label=f"Worked out in {time.perf_counter() - t0:.1f}s - key: "
                             + (" + ".join(chosen) if chosen else "none, hashing") + " - comparing now",
                       state="complete", expanded=False)
            st.session_state["cmap"] = new_map
            st.session_state["cmap_seed"] = (A.label, tuple(A.columns), B.label, tuple(B.columns))
            st.session_state["auto_notes"] = notes
            st.session_state["auto_go"] = True
            st.session_state["confirmed"] = True
            bump()
            forget_results()
            st.rerun()

# ---- Files ----------------------------------------------------------------
st.subheader("Files")
st.caption(f"**{NA}** {A.label} - {A.rows:,} rows × {len(A.schema)} columns"
           + (f" · {A.cut}" if A.cut else "") + f" &nbsp;|&nbsp; **{NB}** {B.label} - "
           f"{B.rows:,} rows × {len(B.schema)} columns" + (f" · {B.cut}" if B.cut else ""))
with st.expander("First 10 rows of each file", expanded=False):
    p1, p2 = st.columns(2)
    for slot, side, name in ((p1, A, NA), (p2, B, NB)):
        with slot:
            st.caption(name)
            try:
                st.dataframe(preview_rows(side), width="stretch", hide_index=True, height=390)
            except duckdb.Error as exc:
                st.error(str(exc))

# ---- Columns ----------------------------------------------------------------
st.subheader("Columns")
setup = ui_columns.render(A, B, NA, NB, OPTS)
files_cell = f"{NA} {A.rows:,} · {NB} {B.rows:,} rows"
cols_cell = f"{len(setup.specs)} paired · {len(setup.only_a) + len(setup.only_b)} one-sided"
key_cell = " + ".join(setup.keys) if setup.keys else "none"
status_strip(strip, files_cell, cols_cell, key_cell,
             f"{len(setup.compare)} columns", "not run",
             {"Key": "" if setup.keys else "warn", "Columns": "" if setup.specs else "warn"})
if not setup.specs:
    st.warning(f"Nothing is paired yet - pick a counterpart for at least one column in the table.")
    st.stop()

# ---- Values -----------------------------------------------------------------
st.subheader("Values")
ui_transform.render(A, B, NA, NB, setup, OPTS)
with st.expander("How values are read - nulls, whitespace, case, tolerance", expanded=False):
    o1, o2, o3, o4 = st.columns(4)
    trim = o1.checkbox("Trim whitespace", value=True, key="opt_trim")
    empty_as_null = o2.checkbox("Empty = null", value=True, key="opt_empty")
    ignore_case = o3.checkbox("Ignore case in values", value=False, key="opt_case")
    tolerance = o4.number_input("Numeric tolerance", 0.0, 1e9, 0.0, format="%.6f", key="opt_tol")
    st.text_input("Also treat these as null (comma separated, case-insensitive)",
                  value=NULL_TOKENS_DEFAULT, key="null_tokens")
    st.caption("Order, per value: transform steps → null folding → trim → Type.")

# ---- Key ---------------------------------------------------------------------
st.subheader("Key")
mode = ui_keys.render(A, B, NA, NB, setup, OPTS)
key_cell = " + ".join(setup.keys) if setup.keys else f"none - {mode}"

# ---- Rows and profile ---------------------------------------------------------
st.subheader("Rows")
with st.expander("Filters - which rows take part, on the common names", expanded=False):
    st.caption("Applied to both sides after types. To shrink a big file before it is even "
               "read, use *Rows to read* under that file in the sidebar.")
    blank = pd.DataFrame([{"Apply to": "Both", "Column": "", "Operator": "=", "Value": "", "Type": "auto"}])
    filter_rows = st.data_editor(
        blank, num_rows="dynamic", width="stretch", hide_index=True, key="filters",
        column_config={
            "Apply to": st.column_config.SelectboxColumn(options=["Both", NA, NB]),
            "Column": st.column_config.SelectboxColumn(options=[""] + setup.canon),
            "Operator": st.column_config.SelectboxColumn(options=OPS),
            "Value": st.column_config.TextColumn(help="in / not in: comma separated. between: two values."),
            "Type": st.column_config.SelectboxColumn(options=["auto", "string", "number", "date"])})
profile_key = json.dumps([A.read_key, B.read_key, [asdict(s) for s in setup.specs], OPTS.tokens, OPTS.trim],
                         default=str)
with st.expander("Profile - statistics and the 10 most and least frequent values, per column, "
                 "per file (only when pressed)", expanded=False):
    if st.button("Profile both files", key="do_profile", type="primary"):
        try:
            with st.status("Profiling…", expanded=True) as box:
                st.session_state["profile"] = (profile_key, profile_tables(A, B, setup.specs, OPTS, box.write))
                box.update(label="Profile ready", state="complete", expanded=False)
        except duckdb.Error as exc:
            st.error(f"Profile failed: {exc}")
    prof = st.session_state.get("profile")
    if prof and prof[0] != profile_key:
        st.caption("This profile is from earlier settings - run it again to refresh.")
    if prof:
        pa, pb = prof[1]["stats"]["A"], prof[1]["stats"]["B"]
        freq = prof[1]["freq"]
        ia, ib = pa.set_index("Column"), pb.set_index("Column")
        both = pd.DataFrame([{
            "Column": c, "Type": ia.at[c, "Type"],
            f"Null % {NA}": ia.at[c, "Null %"], f"Null % {NB}": ib.at[c, "Null %"],
            "Null % gap": round(abs(ia.at[c, "Null %"] - ib.at[c, "Null %"]), 2),
            f"Distinct {NA}": ia.at[c, "Distinct"], f"Distinct {NB}": ib.at[c, "Distinct"],
            f"Min {NA}": ia.at[c, "Min"], f"Min {NB}": ib.at[c, "Min"],
            f"Max {NA}": ia.at[c, "Max"], f"Max {NB}": ib.at[c, "Max"],
        } for c in setup.canon if c in ia.index and c in ib.index])
        tabs_p = st.tabs(["Both sides", NA, NB])
        with tabs_p[0]:
            st.dataframe(both.sort_values("Null % gap", ascending=False) if len(both) else both,
                         width="stretch", hide_index=True, height=min(560, 45 + 35 * len(both)))
        with tabs_p[1]:
            st.dataframe(pa, width="stretch", hide_index=True, height=min(560, 45 + 35 * len(pa)))
        with tabs_p[2]:
            st.dataframe(pb, width="stretch", hide_index=True, height=min(560, 45 + 35 * len(pb)))
        st.markdown("**Value frequencies** - 10 most and 10 least frequent per column, per file")
        for c in setup.canon:
            if c not in freq or "A" not in freq[c]:
                continue
            with st.expander(f"**{c}**{' · key' if c in setup.keys else ''} - {ia.at[c, 'Type']} · "
                             f"{NA}: {ia.at[c, 'Distinct']:,} distinct · {NB}: {ib.at[c, 'Distinct']:,} distinct"):
                fa, fb = st.columns(2)
                for slot, which, name in ((fa, "A", NA), (fb, "B", NB)):
                    top, bottom = freq[c][which]
                    with slot:
                        st.caption(name)
                        t1, t2 = st.columns(2)
                        t1.markdown("Most frequent")
                        t1.dataframe(top, width="stretch", hide_index=True)
                        t2.markdown("Least frequent")
                        t2.dataframe(bottom, width="stretch", hide_index=True)

# ---- Compare ------------------------------------------------------------------
st.subheader("Compare")
if not setup.compare:
    status_strip(strip, files_cell, cols_cell, key_cell, "none", "not run", {"Compare": "warn"})
    st.warning("Tick **Compare** on at least one column in the table.")
    st.stop()
d1, d2, d3 = st.columns([1, 1, 2])
display_rows = d1.number_input("Rows to display per section", 100, 10_000, 1000, step=100,
                               key="disp_rows", help="Downloads always contain everything.")
auto_rerun = d2.checkbox("Re-run on every change", value=False, key="auto_rerun",
                         help="Off: press Compare when you are ready - the last result stays "
                              "on screen and is marked stale. On: every change re-runs.")
go = d3.button("Compare", type="primary", width="stretch", key="go")

try:
    both_f, left_f, right_f = build_filters(filter_rows, NA, NB)
    filter_error = None
except ValueError as exc:
    both_f, left_f, right_f, filter_error = {}, {}, {}, str(exc)

column_rules = {s.canon: {"type": "number", **({"tolerance": s.tolerance} if s.tolerance else {})}
                for s in setup.specs if s.kind == "number" and s.canon in setup.compare}
pending = {
    "name": (A.label.rsplit(".", 1)[0] or "comparison").replace(" ", "_"),
    "mode": mode, "keys": setup.keys, "specs": [asdict(s) for s in setup.specs],
    "compare_columns": setup.compare, "only_a": list(setup.only_a), "only_b": list(setup.only_b),
    "trim": trim, "empty_as_null": empty_as_null,
    "ignore_case": ignore_case, "tolerance": float(tolerance), "column_rules": column_rules,
    "filters": both_f, "left_filters": left_f, "right_filters": right_f,
    "display_rows": int(display_rows), "null_tokens": st.session_state.get("null_tokens", NULL_TOKENS_DEFAULT),
}
sig = signature(A, B, pending)
run = st.session_state.result
stale = bool(run) and run.get("signature") != sig
auto_go = st.session_state.pop("auto_go", False)

if go or auto_go or (stale and auto_rerun):
    if filter_error:
        st.error(filter_error)
    else:
        try:
            with st.status("Comparing…", expanded=True) as box:
                t0 = time.perf_counter()
                new_run = run_comparison(A, B, pending, OPTS, sig, previous=run, progress=box.write)
                box.update(label=f"Compared in {time.perf_counter() - t0:.1f}s", state="complete",
                           expanded=False)
            if new_run["result"].error:
                st.error(f"The engine reported: {new_run['result'].error}"
                         + (" - the previous result is still shown below." if run else ""))
                discard_run(new_run)
            else:
                st.session_state.result, previous = new_run, run
                run, stale = new_run, False
                discard_run(previous)              # only now is it safe to drop the old files
        except (duckdb.Error, RuntimeError, ValueError, KeyError) as exc:
            st.error(f"The comparison failed: {exc}" + (" - the previous result is still shown below."
                                                        if run else ""))

if not run:
    status_strip(strip, files_cell, cols_cell, key_cell, f"{len(setup.compare)} columns",
                 "press Compare", {"Result": "warn", "Key": "" if setup.keys else "warn"})
    st.stop()
if filter_error:
    st.error(filter_error)

res = run["result"]
tone, _ = ui_results.verdict(run, NA, NB, stale)
orphans = res.only_left + res.only_right
status_strip(strip, files_cell, cols_cell, key_cell, f"{len(setup.compare)} columns",
             ("identical" if tone == "ok" else f"{res.diff_rows:,} differ · {orphans:,} one-sided")
             + (" · stale" if stale else ""),
             {"Result": "warn" if stale else tone, "Key": "" if setup.keys else "warn"})
if stale:
    st.warning("Settings have changed since this comparison ran - the result below is from "
               "the previous settings. Press **Compare** to bring it up to date.")
st.markdown("---")
ui_results.render(run, A, B, NA, NB, stale)
