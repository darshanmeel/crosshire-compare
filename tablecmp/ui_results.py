"""The results: verdict, summary, columns and values, report, downloads."""
from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import streamlit as st

from .columns import key_chips_html, PAINTED_ROWS, row_css
from .compare import (bucket_profile, column_ledger, ledger_counts, Outcome, differing_rows,
                      diffs_by_key_value, near_match, paired_path, side_labels, style_pairs,
                      value_pairs)
from .outputs import default_save_folder, save_target, table_formats, verdict_of, write_parquet_copies, zip_run
from .report import build_report
from .sources import Side
from .theme import THEME, esc
from .values import ColSpec


COLUMN_CARDS = 12       # compared columns opened without being asked for - the worst first


def verdict(run: dict, NA: str, NB: str, stale: bool) -> tuple[str, str]:
    """(tone, html) for the banner above the tabs - the verdict is the run's own."""
    res: Outcome = run["result"]
    keys = list(res.keys or run["cfg"]["keys"]) if run["mode"] == "key" else []
    pct = round(res.diff_rows / res.matched_rows * 100, 2) if res.matched_rows else 0.0
    v = run.get("verdict") or verdict_of(res, run["mode"])
    tone = v.tone
    if run["mode"] == "hash":
        how = f"<b>{res.matched_rows:,}</b> identical rows found by hashing {len(res.columns_compared)} columns"
    elif keys:
        how = f"<b>{res.matched_rows:,}</b> rows matched on <b>{esc(' + '.join(keys))}</b>"
    else:
        how = f"<b>{res.matched_rows:,}</b> rows paired by position"
    html = (f'<div class="verdict {tone}"><span class="t">Result{" · stale - settings changed since" if stale else ""}</span>'
            + f"<b>{esc(v.word)}</b> · " + how + f" · <b>{len(res.columns_compared)}</b> columns compared · "
            + (f"<b>{res.diff_rows:,}</b> rows ({pct}%) differ in <b>{res.cell_diffs:,}</b> cells"
               if res.diff_rows else ("<b>no differences</b> on the matched rows" if run["mode"] != "hash"
                                      else "identical rows are identical by construction"))
            + f" · <b>{res.only_left:,}</b> only in {esc(NA)} · <b>{res.only_right:,}</b> only in {esc(NB)}"
            + f'<span style="color:{THEME["text3"]}"> · {run["seconds"]:.1f}s at {run["at"]}</span></div>')
    return tone, html


def render(run: dict, A: Side, B: Side, NA: str, NB: str, stale: bool, limit: int | None = None) -> None:
    """`limit` is the Rows to display box as it stands - display-only, so a run made under
    another value is shown with this one rather than marked stale."""
    res: Outcome = run["result"]
    cfg = run["cfg"]
    mode = run["mode"]
    keys = list(res.keys or cfg["keys"]) if mode == "key" else []
    cols = list(res.columns_compared or cfg["compare_columns"])
    specs = {d["canon"]: ColSpec(**d) for d in cfg["specs"]}
    limit = int(limit or cfg["display_rows"])
    _, html = verdict(run, NA, NB, stale)
    st.markdown(html, unsafe_allow_html=True)

    # one view at a time, not four tabs: Streamlit builds every tab on every rerun, so with
    # tabs each click on the page rebuilt the report and read every result file into memory
    view = st.radio("View", ["Summary", "Columns & values", "Report", "Downloads"],
                    horizontal=True, key="res_view", label_visibility="collapsed")
    try:
        if view == "Summary":
            summary_tab(run, res, NA, NB, keys, cols, specs, mode)
        elif view == "Columns & values":
            columns_tab(run, res, NA, NB, keys, cols, specs, mode, limit)
        elif view == "Report":
            report_tab(run, A, B, NA, NB, limit)
        else:
            downloads_tab(run, A, B, NA, NB, limit)
    except (duckdb.Error, KeyError, ValueError, OSError) as exc:
        st.error(f"Could not build the {view} view: {exc}")


def summary_tab(run, res: Outcome, NA, NB, keys, cols, specs, mode) -> None:
    st.markdown("#### Key")
    if mode == "key":
        st.markdown(key_chips_html(keys), unsafe_allow_html=True)
        st.markdown(f"Rows are matched on **{' + '.join(keys)}** - **{res.matched_rows:,}** rows matched")
        if res.duplicate_keys_left or res.duplicate_keys_right:
            st.warning(f"The key **{' + '.join(keys)}** is not unique: **{res.duplicate_keys_left:,}** rows in "
                       f"{NA} and **{res.duplicate_keys_right:,}** in {NB} share their key with an earlier row. "
                       "Rows with the same key were paired in file order - first with first, second with "
                       "second - so a difference reported under a repeated key may be two rows swapped rather "
                       "than a changed value. Add a column to the key to make it unique (Suggest keys helps).")
    elif mode == "hash":
        st.markdown(f"No key - rows were matched by hashing the {len(cols)} compared columns")
    else:
        st.markdown("No key - rows were paired by position, line 1 against line 1")

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
    # the rows in the column table's colours: a key green, a column that took no part red -
    # past PAINTED_ROWS the Role column carries them, a style per cell being slow to draw
    painted = ledger.style.apply(row_css, axis=1) if len(ledger) <= PAINTED_ROWS else ledger
    st.dataframe(painted, width="stretch", hide_index=True,
                 height=min(640, 45 + 35 * len(ledger)), column_config=config)
    where_they_sit(run, res, NA, NB, keys, cols)



def columns_tab(run, res: Outcome, NA, NB, keys, cols, specs, mode, limit) -> None:
    if mode == "hash":
        st.caption("With hashing there are no matched-but-different rows: a row is either "
                   "identical on the other side or one-sided. The one-sided rows are below.")
        return
    cells_path = run["files"].get(f"{run['pair']}__cell_diffs.csv")
    pairs = value_pairs(run, 10)                 # one DuckDB pass over cd, every column at once
    differing = sorted([c for c in cols if res.diffs_by_column.get(c, 0)],
                       key=lambda c: (-res.diffs_by_column.get(c, 0), c))
    agreeing = sorted(c for c in cols if not res.diffs_by_column.get(c, 0))
    # the columns that differ are what the page opens with - a wide pair drawing a card per
    # column, each with its own tables, is what makes the page slow to answer a click
    order = differing + agreeing
    shown = (differing or order)[:COLUMN_CARDS]
    rest = [c for c in order if c not in shown]
    st.caption(f"Each compared column on the **{res.matched_rows:,} rows that paired"
               f"{' on ' + ' + '.join(keys) if keys else ' by position'}**. Columns that "
               "differ come first, worst first"
               + (f" - the first {len(shown)} of {len(order)} are open; the rest are under "
                  "*Other columns*." if rest else ".")
               + " What each column holds across a set of rows is counted in one place: "
                 "*Profile by bucket* on the Summary.")
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
    if rest:
        with st.expander(f"Other columns - {len(rest)} not open", expanded=False):
            extra = st.multiselect("Columns to open", rest, default=[], key="col_cards",
                                   label_visibility="collapsed",
                                   placeholder="pick the columns to look at",
                                   help="Each one adds the value pairs behind its count.")
        shown = shown + [c for c in order if c in extra]
    for col in shown:
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
            pair = pairs.get(col) if n else None
            if pair is not None and len(pair):
                pair = pair[["a", "b", "n", "pct"]].copy()
                pair.columns = [f"{NA} · {col}", f"{NB} · {col}", "Count", "%"]
                pair["%"] = pair["%"].astype(float).round(2)
                st.markdown("**Where they differ** - the value pairs behind the count")
                st.dataframe(pair, width="stretch", hide_index=True,
                             column_config={"Count": st.column_config.NumberColumn("Count", format="localized")})
    if cells_path:
        with st.expander("Near-match analysis - is it formatting or real data?"):
            st.caption("High similarity means the two values are nearly the same text - "
                       "formatting, padding or casing rather than data.")
            if st.button("Run near-match analysis", key="nearmatch"):
                st.dataframe(near_match(str(cells_path)), width="stretch", hide_index=True)


def where_they_sit(run, res: Outcome, NA, NB, keys, cols) -> None:
    """Top values per column for each bucket of unhappy rows - the profile of what went wrong."""
    buckets = []
    label_a, label_b = side_labels(NA, NB)       # the radio picks by label: two SAMPLEs stay apart
    if res.matched_rows and keys:
        buckets.append(("matched", f"Keys matched ({res.matched_rows:,})"))
    if res.diff_rows and keys:
        buckets.append(("differ", f"Matched but different ({res.diff_rows:,})"))
    if res.only_left:
        buckets.append(("left", f"Only in {label_a} ({res.only_left:,})"))
    if res.only_right:
        buckets.append(("right", f"Only in {label_b} ({res.only_right:,})"))
    if not buckets:
        return
    st.markdown("#### Profile by bucket")
    st.caption("Pick a bucket - keys matched, matched but different, only in one file - and see the "
               "top values for those rows. The key columns are counted; any other column is counted "
               "when you add it, so a wide pair does not count hundreds of columns nobody asked to "
               "see. For paired rows each value is counted on both sides, so a non-key column shows "
               "what it held in each file.")
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
    others = [c for c in cols if c not in keys]
    shown = list(keys) if keys else others[:3]
    if others:
        with st.expander(f"Other columns - {len(others)} to add", expanded=False):
            extra = st.multiselect("Columns to count", others, default=[],
                                   key=f"bucket_cols_{bucket}", label_visibility="collapsed",
                                   placeholder="pick the columns to count for these rows")
        shown = shown + [c for c in others if c in extra]
    with st.spinner("Profiling…"):
        prof = bucket_profile(run, keys, cols, bucket, only=shown)
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


def default_save_dir(tag: str = "A") -> str:
    """Next to file A - or the profiled table, P - when it was given as a path; otherwise
    the user's Downloads folder."""
    import tempfile
    a = st.session_state.get(tag)
    tmp = Path(tempfile.gettempdir()).resolve()
    if a is not None and a.csv_path:
        folder = Path(a.csv_path).resolve().parent
        if tmp not in folder.parents and folder != tmp:
            return str(folder)
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


def save_row(files: dict[str, bytes | Path], label: str, key: str, run: dict, tag: str = "A",
             prepare=None) -> None:
    """A folder box and a button that writes the given files there - no browser involved,
    which is the reliable route for big results. The default is a folder per run,
    <base>/<pair>__<run_id>, where <base> is COMPARE_OUT_DIR when it is set, else the folder
    of the last save, else next to file A (`tag` names another side - the Profiling page's
    table) or Downloads. Under COMPARE_OUT_DIR every save must stay inside it. `prepare` is
    called on the click and returns files to add - what the run writes only when asked for."""
    per_run = f"{run['pair']}__{run['run_id']}"
    base = Path(st.session_state.get("save_dir") or default_save_dir(tag))
    box = f"{key}_dir"
    # a keyed text box keeps whatever it holds, whatever `value` says - so when a new run arrives
    # the box is set through session state, once, and then left to the user. Streamlit drops the
    # box's state on a rerun that does not draw it - Write Parquet copies, or another results
    # view - so what it held is kept alongside and put back, and only a new run resets it
    same_run = st.session_state.get(f"{box}_for") == run["run_id"]
    if not same_run or box not in st.session_state:
        typed = st.session_state.get(f"{box}_kept") if same_run else None
        st.session_state[box] = typed or str(default_save_folder(run, base))
        st.session_state[f"{box}_for"] = run["run_id"]
    c1, c2 = st.columns([3, 1])
    with c1:
        folder = st.text_input("Save to folder", key=box, label_visibility="collapsed",
                               placeholder=r"C:\data\compare_out")
        st.session_state[f"{box}_kept"] = folder
    with c2:
        go = st.button(label, key=key, width="stretch")
    if go:
        if not (folder or "").strip():
            st.error("Type a folder to save into.")
            return
        if prepare is not None:
            files = {**files, **prepare()}
        try:
            target = save_target(folder, run)
            target.mkdir(parents=True, exist_ok=True)
            written = []
            for fname, data in files.items():
                if isinstance(data, Path):
                    shutil.copyfile(data, target / fname)
                else:
                    (target / fname).write_bytes(data)
                written.append(fname)
            # remember the base, so the next run's default is its own folder beside this one
            st.session_state["save_dir"] = str(target.parent if target.name == per_run else target)
            st.success(f"Saved {len(written)} file{'s' if len(written) != 1 else ''} to "
                       f"`{target}`: " + ", ".join(written))
        except ValueError as exc:
            st.error(str(exc))
        except OSError as exc:
            st.error(f"Could not write to `{folder}`: {exc}")


def ensure_report(run: dict, A: Side, B: Side, NA: str, NB: str, limit: int) -> str:
    """The report HTML for this run. compare_app builds it as the run finishes and leaves it in
    run["_report"]; that copy is reused unless the row limit it was built with differs. Whatever
    the route, <pair>__report.html sits in the run folder and is listed in run["files"]."""
    key = ("report", run["at"], limit)
    path = Path(run["folder"]) / f"{run['pair']}__report.html"
    if not run.get("_report") or run.get("_report_key") != key:
        with st.spinner("Building the report…"):
            prof = st.session_state.get("profile")
            run["_report"] = build_report(run, A, B, NA, NB, limit=min(limit, 2000),
                                          notes=run["cfg"].get("notes") or [],
                                          profile=prof[1] if prof else None)
            run["_report_key"] = key
        path.write_text(run["_report"], encoding="utf-8", newline="\n")
    elif not path.exists():
        path.write_text(run["_report"], encoding="utf-8", newline="\n")
    run["files"][path.name] = path
    return run["_report"]


def report_tab(run, A, B, NA, NB, limit) -> None:
    html = ensure_report(run, A, B, NA, NB, limit)
    report_name = f"{run['pair']}__report.html"
    h1, h2 = st.columns([4, 1])
    with h1:
        st.markdown("#### Report")
        st.caption("One self-contained HTML file in the house style - sources, setup, counts, column "
                   "by column with the value pairs behind each count, differences by key value, the "
                   "rows that differ with the cells marked, the one-sided rows. Open it anywhere, "
                   "attach it to a ticket.")
    with h2:
        # on_click="ignore": the click must not rerun the page, or the browser's fetch of the
        # file can race the rerun and the button is left stuck in its disabled "downloading" state
        st.download_button("Download report", html.encode("utf-8"), file_name=report_name,
                           mime="text/html", type="primary", width="stretch",
                           key=f"dl_report_{run['at']}", on_click="ignore")
        engine = run["files"].get(f"{run['pair']}__diff.html")
        if engine and not engine.exists():
            engine = None
            st.caption("the engine's report file is no longer on disk - run Compare again")
        if engine:
            st.download_button("Download engine report", engine.read_bytes(), file_name=engine.name,
                               mime="text/html", width="stretch",
                               key=f"dl_engine_{run['at']}", on_click="ignore")
            st.caption("the engine's own HTML, as it produces it")
    save_row({report_name: html.encode("utf-8")}, "Save report to folder", key="save_report", run=run)
    height = st.select_slider("Viewer height", [600, 820, 1000, 1400], value=820,
                              key="rep_h", label_visibility="collapsed")
    path = run["files"][report_name]
    if hasattr(st, "iframe"):
        st.iframe(path, height=height)
    else:
        from streamlit.components.v1 import html as st_html
        st_html(html, height=height, scrolling=True)


# what each file in the run folder is called on the Downloads tab, in the order the buttons appear
DOWNLOAD_LABELS = [("cell_diffs.csv", "Cell differences"), ("left_only.csv", "Rows only in {NA}"),
                   ("right_only.csv", "Rows only in {NB}"), ("paired.csv", "Paired rows"),
                   ("columns.csv", "Columns"), ("profile.csv", "Profile"), ("summary.csv", "Summary"),
                   ("summary.json", "Settings and result"), ("report.html", "Report"),
                   ("diff.html", "Engine report")]
MIME = {".csv": "text/csv", ".json": "application/json", ".html": "text/html",
        ".parquet": "application/vnd.apache.parquet"}


def have_paired(run) -> bool:
    p = run["files"].get(f"{run['pair']}__paired.csv")
    return bool(p and p.exists())


def paired_row(run, NA: str, NB: str) -> None:
    """The one file a run does not write as it goes: every matched row with both sides beside
    each other. On a wide pair it takes longer to write than the comparison itself takes to
    run, and most runs are read here and never downloaded - so it is offered, not assumed.
    Zip, Save everything and the Parquet copies write it too: those say the whole run."""
    if have_paired(run):
        return
    p1, p2 = st.columns([2, 1])
    with p1:
        st.caption(f"**Paired rows** - every matched row with {NA} beside {NB} - are written when "
                   "you ask for them. On a wide pair that file takes longer than the comparison "
                   "did, and most runs are read here rather than downloaded.")
    with p2:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button("Write the paired rows", key="write_paired_btn", width="stretch"):
            with st.spinner("Writing the paired rows…"):
                paired_path(run)
            st.rerun()          # the offer is drawn before the click is known: redraw without it


def paired_first(run) -> dict[str, Path]:
    """The paired rows, written now if they are not on disk - what a save of everything adds."""
    if have_paired(run):
        return {}
    with st.spinner("Writing the paired rows…"):
        p = paired_path(run)
    return {p.name: p} if p else {}


def downloads_tab(run, A, B, NA, NB, limit) -> None:
    st.markdown("#### Downloads")
    st.caption("Complete results, not just the rows displayed. Values are the canonical form "
               "both sides were compared on.")
    ensure_report(run, A, B, NA, NB, limit)
    name = run["pair"]
    paired_row(run, NA, NB)
    buttons = [(f"{name}__{suffix}", label.format(NA=NA, NB=NB)) for suffix, label in DOWNLOAD_LABELS]
    buttons += [(p.name, f"{p.name[len(name) + 2:-len('.parquet')]} (Parquet)")
                for p in sorted(run["files"].values()) if p.suffix == ".parquet"]
    present = [(f, label) for f, label in buttons if f in run["files"] and run["files"][f].exists()]
    # a browser download holds the whole file in memory, and Streamlit fills every download
    # button on every rerun - so one file is picked and only that one is read
    labels = {f"{label} · {run['files'][f].stat().st_size / 1e6:,.1f} MB": f for f, label in present}
    d1, d2 = st.columns([2, 1])
    with d1:
        pick = st.selectbox("File to download", list(labels), key=f"dl_pick_{run['run_id']}",
                            help="Every file of this run is in the folder already - this is the "
                                 "browser route for one of them.")
    with d2:
        st.markdown('<div style="height:28px"></div>', unsafe_allow_html=True)
        if pick:
            fname = labels[pick]
            path = run["files"][fname]
            st.download_button(f"Download {fname}", path.read_bytes(), file_name=fname,
                               width="stretch", mime=MIME.get(path.suffix, "application/octet-stream"),
                               key=f"dl_{fname}_{run['run_id']}", on_click="ignore")
    if st.button("Zip the whole run", key="zip_run_btn",
                 help="Every file of this run in one archive - the paired rows written first when "
                      "they are not on disk yet - next to the run folder"):
        wrote = not have_paired(run)
        with st.spinner("Writing the paired rows and zipping…" if wrote else "Zipping the run folder…"):
            paired_path(run)
            zip_run(run)
        if wrote:
            st.rerun()      # the offer and the picker above were drawn without the file
    z = run.get("zip")
    if z and z.exists():
        st.download_button(f"Download {z.name} · {z.stat().st_size / 1e6:,.1f} MB", z.read_bytes(),
                           file_name=z.name, mime="application/zip", type="primary",
                           key=f"dl_zip_{run['run_id']}", on_click="ignore")
    env = table_formats()                        # COMPARE_TABLE_FORMATS, or csv
    st.session_state.setdefault("out_fmt", "both" if {"csv", "parquet"} <= env else
                                "parquet" if "parquet" in env else "csv")
    fmt = st.radio("Tables as", ["csv", "parquet", "both"], horizontal=True, key="out_fmt",
                   format_func={"csv": "CSV", "parquet": "Parquet", "both": "both"}.get,
                   help="Parquet: typed counts, a fraction of the size, straight into DuckDB, pandas or a "
                        "warehouse. Applies to the next run; COMPARE_TABLE_FORMATS sets the default.")
    if fmt in ("parquet", "both") and not any(p.suffix == ".parquet" for p in run["files"].values()):
        if st.button("Write Parquet copies for this run", key="write_pq"):
            with st.spinner("Writing Parquet…"):
                paired_path(run)                  # a table of the run like any other
                write_parquet_copies(run)         # drops the zip too, so it is rebuilt with them
            st.rerun()
    everything = {p.name: p for p in run["files"].values() if p.exists()}
    save_row(everything, "Save everything to folder", key="save_all", run=run,
             prepare=lambda: paired_first(run))

