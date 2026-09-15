"""The results: verdict, summary, columns and values, report, downloads."""
from __future__ import annotations

import io
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from .compare import (bucket_profile, column_ledger, ledger_counts, Outcome, differing_rows, diffs_by_key_value, load_csv, matched_values,
                      near_match, paired_frame, style_pairs, top_values)
from .report import build_report
from .sources import Side
from .theme import THEME, esc
from .values import ColSpec


def verdict(run: dict, NA: str, NB: str, stale: bool) -> tuple[str, str]:
    """(tone, html) for the banner above the tabs."""
    res: Outcome = run["result"]
    keys = list(res.keys or run["cfg"]["keys"]) if run["mode"] == "key" else []
    pct = round(res.diff_rows / res.matched_rows * 100, 2) if res.matched_rows else 0.0
    orphans = res.only_left + res.only_right
    tone = "ok" if not res.diff_rows and not orphans else "warn" if pct < 5 and orphans <= res.matched_rows else "bad"
    if run["mode"] == "hash":
        how = f"<b>{res.matched_rows:,}</b> identical rows found by hashing {len(res.columns_compared)} columns"
    elif keys:
        how = f"<b>{res.matched_rows:,}</b> rows matched on <b>{esc(' + '.join(keys))}</b>"
    else:
        how = f"<b>{res.matched_rows:,}</b> rows paired by position"
    html = (f'<div class="verdict {tone}"><span class="t">Result{" · stale - settings changed since" if stale else ""}</span>'
            + how + f" · <b>{len(res.columns_compared)}</b> columns compared · "
            + (f"<b>{res.diff_rows:,}</b> rows ({pct}%) differ in <b>{res.cell_diffs:,}</b> cells"
               if res.diff_rows else ("<b>no differences</b> on the matched rows" if run["mode"] != "hash"
                                      else "identical rows are identical by construction"))
            + f" · <b>{res.only_left:,}</b> only in {esc(NA)} · <b>{res.only_right:,}</b> only in {esc(NB)}"
            + f'<span style="color:{THEME["text3"]}"> · {run["seconds"]:.1f}s at {run["at"]}</span></div>')
    return tone, html


def render(run: dict, A: Side, B: Side, NA: str, NB: str, stale: bool) -> None:
    res: Outcome = run["result"]
    cfg = run["cfg"]
    mode = run["mode"]
    keys = list(res.keys or cfg["keys"]) if mode == "key" else []
    cols = list(res.columns_compared or cfg["compare_columns"])
    specs = {d["canon"]: ColSpec(**d) for d in cfg["specs"]}
    limit = cfg["display_rows"]
    _, html = verdict(run, NA, NB, stale)
    st.markdown(html, unsafe_allow_html=True)

    view = st.tabs(["Summary", "Columns & values", "Report", "Downloads"])
    with view[0]:
        try:
            summary_tab(run, res, NA, NB, keys, cols, specs, mode)
        except (duckdb.Error, KeyError, ValueError) as exc:
            st.error(f"Could not build part of the summary: {exc}")
    with view[1]:
        try:
            columns_tab(run, res, NA, NB, keys, cols, specs, mode, limit)
        except (duckdb.Error, KeyError, ValueError) as exc:
            st.error(f"Could not build part of this view: {exc}")
    with view[2]:
        try:
            report_tab(run, A, B, NA, NB, limit)
        except (duckdb.Error, KeyError, ValueError) as exc:
            st.error(f"Could not build the report: {exc}")
    with view[3]:
        downloads_tab(run, res, NA, NB, keys, cols, mode)


def summary_tab(run, res: Outcome, NA, NB, keys, cols, specs, mode) -> None:
    st.markdown("#### Row counts")
    m = st.columns(6)
    m[0].metric(f"Rows {NA}", f"{res.rows_left_read:,}")
    m[1].metric(f"Rows {NB}", f"{res.rows_right_read:,}")
    m[2].metric("Matched on key" if mode == "key" else "Identical rows" if mode == "hash"
                else "Paired by position", f"{res.matched_rows:,}")
    m[3].metric(f"Only in {NA}", f"{res.only_left:,}")
    m[4].metric(f"Only in {NB}", f"{res.only_right:,}")
    m[5].metric("Rows that differ", f"{res.diff_rows:,}",
                help="Matched rows where at least one compared column differs")
    if mode == "key" and (res.duplicate_keys_left or res.duplicate_keys_right):
        st.warning(f"The key **{' + '.join(keys)}** is not unique: **{res.duplicate_keys_left:,}** rows in "
                   f"{NA} and **{res.duplicate_keys_right:,}** in {NB} share their key with an earlier row. "
                   "Rows with the same key were paired in file order - first with first, second with "
                   "second - so a difference reported under a repeated key may be two rows swapped rather "
                   "than a changed value. Add a column to the key to make it unique (Suggest keys helps).")
    if res.filter_left or res.filter_right:
        st.info(f"Filter applied - comparing **{res.rows_left:,}** of {res.rows_left_read:,} "
                f"{NA} rows and **{res.rows_right:,}** of {res.rows_right_read:,} {NB} rows.")
    if res.sample_unmatched_left or res.sample_unmatched_right:
        st.error(
            f"Only {res.matched_rows:,} rows matched on {' + '.join(keys)}. If that looks "
            "wrong, the key values are spelled differently on the two sides - give the key "
            "column a Type or a transform step:\n\n"
            + "\n".join([f"- {NA}: `{v}`" for v in res.sample_unmatched_left]
                        + [f"- {NB}: `{v}`" for v in res.sample_unmatched_right]))

    st.markdown("#### Columns")
    ledger = column_ledger(run, NA, NB)
    counts = ledger_counts(ledger, NA, NB)
    c = st.columns(5)
    for i, (k, v) in enumerate(counts.items()):
        c[i].metric(k.capitalize() if i < 3 else k[0].upper() + k[1:], f"{v:,}")
    missing = [k for k, v in counts.items() if k.startswith("only in") and v]
    if missing:
        names = {k: ledger.loc[ledger["Role"] == k, "Column"].tolist() for k in missing}
        st.warning("Columns present on one side only, so not compared: "
                   + " · ".join(f"**{k}**: {', '.join(v[:12])}{' …' if len(v) > 12 else ''}"
                                for k, v in names.items()))
    if mode == "hash":
        st.caption("Distinct values present on one side only, per compared column - the "
                   "columns with the most are where the one-sided rows differ.")
    else:
        fully = res.matched_rows - res.diff_rows
        o1, o2, o3 = st.columns(3)
        o1.metric("Overall match %", f"{round(fully / res.matched_rows * 100, 2) if res.matched_rows else 0.0}%")
        o2.metric("Fully matched rows", f"{fully:,}")
        o3.metric("Rows with differences", f"{res.diff_rows:,}")
        st.caption(f"Match figures are measured on the {res.matched_rows:,} rows that paired. "
                   "Key columns are identical by construction; one-sided columns have no partner.")
    config = {"Match %": st.column_config.ProgressColumn("Match %", format="%.2f%%",
                                                        min_value=0, max_value=100)}
    for col in ("Matched", "Mismatched", f"Values only in {NA}", f"Values only in {NB}"):
        if col in ledger.columns:
            config[col] = st.column_config.NumberColumn(col, format="localized")
    st.dataframe(ledger, width="stretch", hide_index=True, height=min(640, 45 + 35 * len(ledger)),
                 column_config=config)
    where_they_sit(run, res, NA, NB, keys, cols)



def columns_tab(run, res: Outcome, NA, NB, keys, cols, specs, mode, limit) -> None:
    if mode == "hash":
        st.caption("With hashing there are no matched-but-different rows: a row is either "
                   "identical on the other side or one-sided. The one-sided rows are below.")
        return
    cells_path = run["files"].get(f"{run['cfg']['name']}__cell_diffs.csv")
    cells = load_csv(str(cells_path)) if cells_path else pd.DataFrame(
        columns=["column_name", "left_value", "right_value"])
    sample = matched_values(run, cols)
    differing = sorted([c for c in cols if res.diffs_by_column.get(c, 0)],
                       key=lambda c: (-res.diffs_by_column.get(c, 0), c))
    agreeing = sorted(c for c in cols if not res.diffs_by_column.get(c, 0))
    st.caption(f"Each compared column on the **{res.matched_rows:,} rows that paired"
               f"{' on ' + ' + '.join(keys) if keys else ' by position'}**. Columns that "
               "differ come first, worst first.")
    if differing:
        st.error(f"**{len(differing)} column(s) differ**: "
                 + ", ".join(f"{c} ({res.diffs_by_column[c]:,})" for c in differing[:10])
                 + (" …" if len(differing) > 10 else ""))
    if keys and res.diff_rows:
        with st.expander(f"Rows that differ - {NA} above {NB}, differing cells marked · "
                         f"first {min(limit, res.diff_rows):,} of {res.diff_rows:,}", expanded=True):
            df, marks = differing_rows(run, keys, cols, limit)
            if len(df):
                st.dataframe(style_pairs(df, marks), width="stretch", hide_index=True,
                             height=min(600, 40 + 35 * len(df)))
    for col in differing + agreeing:
        n = res.diffs_by_column.get(col, 0)
        pct = round(n / res.matched_rows * 100, 2) if res.matched_rows else 0.0
        read_as = specs[col].describe() if col in specs else "text"
        head = (f"**{col}** · {read_as} - all {res.matched_rows:,} matched rows agree" if not n
                else f":red[**{col}** · {read_as} - {n:,} {'mismatch' if n == 1 else 'mismatches'} ({pct}%)]")
        with st.expander(head, expanded=False):
            if n and res.matched_rows and n >= 0.99 * res.matched_rows:
                st.warning("Every matched row differs on this column - usually two different "
                           "fields paired by mistake, or a value that converts on one side "
                           "only. Check the column in the transform section.")
            sub = cells[cells["column_name"] == col] if n else cells.iloc[0:0]
            if n:
                pair = (sub.groupby([sub["left_value"].fillna("∅ null"), sub["right_value"].fillna("∅ null")])
                        .size().reset_index(name="Count").sort_values("Count", ascending=False).head(10))
                pair.columns = [f"{NA} · {col}", f"{NB} · {col}", "Count"]
                pair["%"] = (pair["Count"] / max(n, 1) * 100).round(2)
                st.markdown("**Where they differ** - the value pairs behind the count")
                st.dataframe(pair, width="stretch", hide_index=True)
            if f"a_{col}" in sample.columns:
                st.markdown("**Distribution across the matched rows**")
                m1, m2 = st.columns(2)
                m1.caption(NA)
                m1.dataframe(top_values(sample[f"a_{col}"], len(sample)), width="stretch", hide_index=True)
                m2.caption(NB)
                m2.dataframe(top_values(sample[f"b_{col}"], len(sample)), width="stretch", hide_index=True)
    if cells_path:
        with st.expander("Near-match analysis - is it formatting or real data?"):
            st.caption("High similarity means the two values are nearly the same text - "
                       "formatting, padding or casing rather than data.")
            if st.button("Run near-match analysis", key="nearmatch"):
                st.dataframe(near_match(str(cells_path)), width="stretch", hide_index=True)


def where_they_sit(run, res: Outcome, NA, NB, keys, cols) -> None:
    """Top values per column for each bucket of unhappy rows - the profile of what went wrong."""
    buckets = []
    if res.matched_rows and keys:
        buckets.append(("matched", f"Keys matched ({res.matched_rows:,})"))
    if res.diff_rows and keys:
        buckets.append(("differ", f"Matched but different ({res.diff_rows:,})"))
    if res.only_left:
        buckets.append(("left", f"Only in {NA} ({res.only_left:,})"))
    if res.only_right:
        buckets.append(("right", f"Only in {NB} ({res.only_right:,})"))
    if not buckets:
        return
    st.markdown("#### Profile by bucket")
    st.caption("Pick a bucket - keys matched, matched but different, only in one file - and see the "
               "top values of every column for those rows, key columns first. For paired rows each "
               "value is counted on both sides, so a non-key column shows what it held in each file.")
    default = next((i for i, b in enumerate(buckets) if b[0] == "differ"), 0)
    label = st.radio("Bucket", [b[1] for b in buckets], horizontal=True, key="bucket_pick",
                     index=default, label_visibility="collapsed")
    bucket = next(b[0] for b in buckets if b[1] == label)
    if bucket == "differ":
        st.markdown(f"**By key value** - the {res.diff_rows:,} rows that paired on **{' + '.join(keys)}** "
                    "but disagree on a compared column, grouped by each key column. The key is identical "
                    "on both sides for these rows, so this is *where* the differences sit.")
        by_val = diffs_by_key_value(run, keys)
        kcols = st.columns(min(len(by_val), 2) or 1)
        for i, (k, tbl) in enumerate(by_val.items()):
            with kcols[i % len(kcols)]:
                st.markdown(f"**{k}** - top {len(tbl)} values by rows that differ")
                st.dataframe(tbl, width="stretch", hide_index=True, height=min(420, 45 + 35 * len(tbl)))
        st.markdown("**Every column across these rows** - top values, counted on each side")
    with st.spinner("Profiling…"):
        prof = bucket_profile(run, keys, cols, bucket)
    if not prof:
        st.caption("Nothing to profile for this bucket.")
        return
    grid = st.columns(3)
    for i, (col, df) in enumerate(prof.items()):
        with grid[i % 3]:
            st.markdown(f"**{col}**" + (" · key" if col in keys else ""))
            cfg = {c: st.column_config.NumberColumn(c, format="localized")
                   for c in df.columns if c.startswith("Rows")}
            st.dataframe(df, width="stretch", hide_index=True, column_config=cfg,
                         height=min(400, 45 + 35 * len(df)))


def default_save_dir() -> str:
    """Next to file A when it was given as a path; otherwise the user's Downloads folder."""
    import tempfile
    a = st.session_state.get("A")
    tmp = Path(tempfile.gettempdir()).resolve()
    if a is not None and a.csv_path:
        folder = Path(a.csv_path).resolve().parent
        if tmp not in folder.parents and folder != tmp:
            return str(folder)
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


def save_row(files: dict[str, bytes], label: str, key: str) -> None:
    """A folder box and a button that writes the given files there - no browser involved,
    which is the reliable route for big results."""
    c1, c2 = st.columns([3, 1])
    with c1:
        folder = st.text_input("Save to folder", value=st.session_state.get("save_dir")
                               or default_save_dir(), key=f"{key}_dir",
                               label_visibility="collapsed",
                               placeholder=r"C:\\data\\compare_out")
    with c2:
        go = st.button(label, key=key, width="stretch")
    if go:
        try:
            target = Path(folder).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            written = []
            for fname, data in files.items():
                (target / fname).write_bytes(data)
                written.append(fname)
            st.session_state["save_dir"] = str(target)
            st.success(f"Saved {len(written)} file{'s' if len(written) != 1 else ''} to "
                       f"`{target}`: " + ", ".join(written))
        except OSError as exc:
            st.error(f"Could not write to `{folder}`: {exc}")


def report_tab(run, A, B, NA, NB, limit) -> None:
    key = ("report", run["at"], limit)
    if run.get("_report_key") != key:
        with st.spinner("Building the report…"):
            run["_report"] = build_report(run, A, B, NA, NB, limit=min(limit, 2000))
            run["_report_key"] = key
    html = run["_report"]
    h1, h2 = st.columns([4, 1])
    with h1:
        st.markdown("#### Report")
        st.caption("One self-contained HTML file in the house style - setup, counts, column "
                   "by column, differences by key value, the rows that differ with the cells "
                   "marked, the one-sided rows. Open it anywhere, attach it to a ticket.")
    report_name = f"{run['cfg']['name']}__report.html"
    with h2:
        # on_click="ignore": the click must not rerun the page, or the browser's fetch of the
        # file can race the rerun and the button is left stuck in its disabled "downloading" state
        st.download_button("Download report", html.encode("utf-8"), file_name=report_name,
                           mime="text/html", type="primary", width="stretch",
                           key=f"dl_report_{run['at']}", on_click="ignore")
        engine = run["files"].get(f"{run['cfg']['name']}__diff.html")
        if engine and not engine.exists():
            engine = None
            st.caption("the engine's report file is no longer on disk - run Compare again")
        if engine:
            st.download_button("Download engine report", engine.read_bytes(), file_name=engine.name,
                               mime="text/html", width="stretch",
                               key=f"dl_engine_{run['at']}", on_click="ignore")
            st.caption("the engine's own HTML, as it produces it")
    save_row({report_name: html.encode("utf-8")}, "Save report to folder", key="save_report")
    height = st.select_slider("Viewer height", [600, 820, 1000, 1400], value=820,
                              key="rep_h", label_visibility="collapsed")
    path = run["folder"] / f"{run['cfg']['name']}__report.html"
    path.write_text(html, encoding="utf-8")
    if hasattr(st, "iframe"):
        st.iframe(path, height=height)
    else:
        from streamlit.components.v1 import html as st_html
        st_html(html, height=height, scrolling=True)


def downloads_tab(run, res: Outcome, NA, NB, keys, cols, mode) -> None:
    st.markdown("#### Downloads")
    st.caption("Complete results, not just the rows displayed. Values are the canonical form "
               "both sides were compared on.")
    name = run["cfg"]["name"]
    labels = {f"{name}__cell_diffs.csv": "Cell differences",
              f"{name}__left_only.csv": f"Rows only in {NA}",
              f"{name}__right_only.csv": f"Rows only in {NB}",
              f"{name}__summary.csv": "Summary", f"{name}__summary.json": "Settings and result"}
    grid = st.columns(5)
    for i, (fname, label) in enumerate(labels.items()):
        path = run["files"].get(fname)
        if not path:
            continue
        if not path.exists():
            continue
        with grid[i % 5]:
            st.download_button(label, path.read_bytes(), file_name=fname, width="stretch",
                               mime="application/json" if fname.endswith("json") else "text/csv",
                               key=f"dl_{fname}_{run['at']}", on_click="ignore")
    everything = {f: p.read_bytes() for f, p in run["files"].items() if p.exists()}
    if run.get("_report"):
        everything[f"{name}__report.html"] = run["_report"].encode("utf-8")
    save_row(everything, "Save everything to folder", key="save_all")
    if mode != "hash":
        with st.expander("Export the side-by-side view"):
            n = st.number_input("Max rows", 100, 1_000_000, 50_000, step=1000, key="exp_rows")
            if st.button("Build export", key="build_exp"):
                df = paired_frame(run, keys, cols, int(n))
                buf = io.StringIO()
                df.to_csv(buf, index=False)
                st.download_button("Download paired rows CSV", buf.getvalue(),
                                   file_name=f"{name}__paired.csv", mime="text/csv",
                                   key=f"dl_paired_{run['at']}", on_click="ignore")
