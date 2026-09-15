"""The report: one self-contained HTML file in the house style."""
from __future__ import annotations

import time

import pandas as pd

from .compare import bucket_profile, column_ledger, ledger_counts, Outcome, differing_rows, diffs_by_key_value, load_csv
from .sources import Side
from .theme import APP_NAME, THEME, esc
from .values import ColSpec

FONTS = THEME["fonts"]

CSS = """
:root{--ink:#0e0d0b;--ink-2:#151310;--ink-3:#1c1916;--rule:#2b2620;--rule-soft:#211d19;
--paper:#f2efe9;--paper-2:#cdc6ba;--muted:#918878;--brass:#c8a45c;--brass-dim:#8a713c;
--ice:#8fb3c4;--sage:#94ab8e;--rose:#c98f7f;
--display:"Newsreader",Georgia,serif;--body:"IBM Plex Sans",system-ui,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;--pad:clamp(20px,5vw,64px)}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--paper-2);font-family:var(--body);font-weight:300;
font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.main{max-width:1500px;margin:0 auto;padding:0 var(--pad) 100px}
.hero{padding:clamp(40px,7vw,80px) 0 clamp(30px,4vw,44px);border-bottom:1px solid var(--rule)}
.eyebrow{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:22px}
.eyebrow span{color:var(--brass)}
h1{font-family:var(--display);font-weight:300;font-size:clamp(32px,5vw,54px);line-height:1.06;letter-spacing:-.018em;color:var(--paper);margin:0 0 20px;max-width:22ch}
h1 em{font-style:italic;color:var(--brass)}
.lede{max-width:70ch;font-size:16.5px;color:var(--paper-2);margin:0}
.lede b{font-weight:500;color:var(--paper)}
.pills{display:flex;flex-wrap:wrap;gap:7px;margin-top:26px}
.pill{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;padding:5px 11px;border:1px solid var(--rule);border-radius:100px;color:var(--muted)}
.sec{padding:clamp(34px,4vw,56px) 0;border-bottom:1px solid var(--rule-soft)}
.sec-head{display:grid;grid-template-columns:64px 1fr;gap:0 22px;margin-bottom:22px}
.sec-num{font-family:var(--mono);font-size:11px;letter-spacing:.1em;color:var(--brass);padding-top:9px}
.sec-h{font-family:var(--display);font-weight:300;font-size:clamp(24px,3vw,34px);line-height:1.16;letter-spacing:-.012em;color:var(--paper);margin:0}
.sec-h em{font-style:italic;color:var(--brass)}
.sec-sub{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-top:8px}
.body{margin-left:86px}
@media(max-width:760px){.sec-head{grid-template-columns:1fr}.body{margin-left:0}}
p{margin:0 0 14px;max-width:70ch}
code{font-family:var(--mono);font-size:.88em;background:var(--ink-3);border:1px solid var(--rule-soft);padding:1px 5px;border-radius:3px;color:var(--ice)}
.note{margin:18px 0;padding:14px 18px;border-left:2px solid var(--brass-dim);background:var(--ink-2);border-radius:0 4px 4px 0;max-width:80ch}
.note-t{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--brass);margin-bottom:6px}
.note.ok{border-left-color:var(--sage)}.note.ok .note-t{color:var(--sage)}
.note.bad{border-left-color:var(--rose)}.note.bad .note-t{color:var(--rose)}
.note p{margin:0;font-size:14.5px}
.note b{font-family:var(--display);font-weight:400;font-size:1.25rem;color:var(--paper)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.m{border:1px solid var(--rule);border-radius:5px;background:var(--ink-2);padding:12px 14px}
.m .k{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.m .v{font-family:var(--display);font-weight:300;font-size:30px;color:var(--paper);line-height:1.1;margin-top:6px}
.m .v.bad{color:var(--rose)}.m .v.ok{color:var(--sage)}
.card{border:1px solid var(--rule);border-radius:5px;background:var(--ink-2);overflow:hidden;margin:16px 0}
.card .row{display:grid;grid-template-columns:12rem 1fr;gap:0 14px;padding:10px 16px;border-bottom:1px solid var(--rule-soft);font-size:14px}
.card .row:last-child{border-bottom:0}
.card .k{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--brass);padding-top:3px}
.card .v{color:var(--paper);overflow-wrap:anywhere}
.tw{overflow-x:auto;margin:14px 0 22px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:400;padding:0 14px 8px 0;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:8px 14px 8px 0;border-bottom:1px solid var(--rule-soft);vertical-align:top;line-height:1.5;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num{text-align:right;font-family:var(--mono);font-size:12px}
th.num{text-align:right}
.bar{display:inline-block;height:6px;background:var(--brass-dim);border-radius:3px;vertical-align:middle;margin-right:8px}
tr.a td{background:var(--ink);color:var(--paper)}
tr.b td{background:var(--paper);color:var(--ink);border-bottom-color:var(--paper-2)}
td.side{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
tr.b td.side{color:var(--brass-dim)}
tr.b td.key{color:#3f6f86}
tr.a td.diff{background:#4a1f22!important;color:#f2c9c0;font-weight:500}
tr.b td.diff{background:#e9c4bb!important;color:#4a1f22;font-weight:500}
.legend{display:flex;gap:14px;margin:0 0 10px;font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase}
.legend span{padding:3px 10px;border-radius:3px;border:1px solid var(--rule)}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin:12px 0 18px}
.pcard{border:1px solid var(--rule);border-radius:4px;padding:10px 12px;background:var(--ink-2)}
.pcard .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--brass);margin-bottom:6px}
.pcard table{font-size:12px}
.legend .la{background:var(--ink);color:var(--paper)}.legend .lb{background:var(--paper);color:var(--ink)}
.side-a td{background:var(--ink);color:var(--paper)}
.side-b td{background:var(--paper);color:var(--ink);border-bottom-color:var(--paper-2)}
.side-b th{color:var(--muted)}
td.key{font-family:var(--mono);font-size:12px;color:var(--ice)}
tr.gap td{padding:0;height:6px;background:var(--ink);border:0}
.small{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:6px}
.foot{padding:36px 0 0;color:var(--muted);font-size:12.5px}
"""


def _fmt(v, null: str = '<span style="color:var(--muted)">∅</span>') -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return null                       # ∅ for a null data value; "" where a cell simply doesn't apply
    return esc(v)


def _table(df: pd.DataFrame, numeric: set[str] | None = None, bar: str | None = None,
           bar_max: float = 100.0, null: str = '<span style="color:var(--muted)">∅</span>') -> str:
    if df is None or not len(df):
        return '<p class="small">nothing to show</p>'
    numeric = numeric or set()
    head = "".join(f'<th class="{"num" if c in numeric else ""}">{esc(c)}</th>' for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if c == bar:
                blank = v is None or (isinstance(v, float) and pd.isna(v))
                try:
                    w = 0.0 if blank else max(0.0, min(100.0, float(v) / max(bar_max, 1e-9) * 100))
                except (TypeError, ValueError):
                    w = 0.0
                cells.append('<td class="num"></td>' if blank else
                             f'<td class="num"><span class="bar" style="width:{w * 0.6:.0f}px"></span>{float(v):.2f}</td>')
            elif c in numeric:
                cells.append(f'<td class="num">{_fmt(v, null)}</td>')
            else:
                cells.append(f"<td>{_fmt(v, null)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tw"><table><tr>{head}</tr>{"".join(body)}</table></div>'


def _pairs_table(df: pd.DataFrame, marks: dict[int, set[str]], keys: list[str],
                 name_a: str, name_b: str) -> str:
    if df is None or not len(df):
        return '<p class="small">none</p>'
    cols = [c for c in df.columns if c != "Side"]
    head = "<th></th>" + "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = []
    for i, (_, r) in enumerate(df.iterrows()):
        changed = marks.get(i - (i % 2), set())
        side = "a" if r["Side"] == "A" else "b"
        cells = [f'<td class="side">{esc(name_a if side == "a" else name_b)}</td>']
        for c in cols:
            cls = "key" if c in keys else ("diff" if c in changed else "")
            cells.append(f'<td class="{cls}">{_fmt(r[c])}</td>')
        body.append(f'<tr class="{side}">{"".join(cells)}</tr>')
        if side == "b":
            body.append(f'<tr class="gap"><td colspan="{len(cols) + 1}"></td></tr>')
    return f'<div class="tw"><table><tr>{head}</tr>{"".join(body)}</table></div>'


def _profile_grid(prof: dict, keys: list[str], top: int = 6) -> str:
    if not prof:
        return ""
    cards = []
    for col, df in prof.items():
        numeric = {c for c in df.columns if c.startswith("Rows") or c == "%"}
        cards.append(f'<div class="pcard"><div class="k">{esc(col)}{" · key" if col in keys else ""}</div>'
                     f'{_table(df.head(top), numeric=numeric)}</div>')
    return '<div class="pgrid">' + "".join(cards) + "</div>"


def build_report(run: dict, A: Side, B: Side, name_a: str, name_b: str, limit: int = 500) -> str:
    res: Outcome = run["result"]
    cfg = run["cfg"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys = list(res.keys or cfg["keys"]) if run["mode"] == "key" else []
    cols = list(res.columns_compared or cfg["compare_columns"])
    by_key = run["mode"] == "key"
    pct = round(res.diff_rows / res.matched_rows * 100, 2) if res.matched_rows else 0.0
    orphans = res.only_left + res.only_right
    tone = "ok" if not res.diff_rows and not orphans else "bad" if (pct >= 5 or orphans > res.matched_rows) else ""
    n_sec = iter(range(1, 20))
    sec = lambda: f"{next(n_sec):02d}"     # noqa: E731

    if run["mode"] == "hash":
        how = f"<b>{res.matched_rows:,}</b> identical rows matched by hashing {len(cols)} columns"
    elif by_key:
        how = f"<b>{res.matched_rows:,}</b> rows matched on <b>{esc(' + '.join(keys))}</b>"
    else:
        how = f"<b>{res.matched_rows:,}</b> rows paired by position"
    verdict = (how + f" · <b>{len(cols)}</b> columns compared · "
               + (f"<b>{res.diff_rows:,}</b> rows ({pct}%) differ in <b>{res.cell_diffs:,}</b> cells"
                  if res.diff_rows else "<b>no differences</b> on the matched rows")
               + f" · <b>{res.only_left:,}</b> only in {esc(name_a)} · <b>{res.only_right:,}</b> only in {esc(name_b)}")

    # settings card
    steps_rows = [f"<div><code>{esc(s.canon)}</code> {esc(s.describe())}</div>"
                  for s in specs if s.canon in keys + cols and (s.a_steps or s.b_steps or s.kind != 'text')]
    settings = "".join(
        f'<div class="row"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in [
            ("Files", f"{esc(name_a)}: {esc(A.label)} - {res.rows_left_read:,} rows"
                      + (f" ({esc(A.cut)})" if A.cut else "")
                      + f"<br>{esc(name_b)}: {esc(B.label)} - {res.rows_right_read:,} rows"
                      + (f" ({esc(B.cut)})" if B.cut else "")),
            ("Rows paired", ("on the key " + esc(" + ".join(keys))) if by_key else
                            "by hashing the compared columns" if run["mode"] == "hash" else "by position"),
            ("Columns compared", esc(", ".join(cols))),
            ("Read as", "".join(steps_rows) or "all text"),
            ("Filters", esc(res.filter_left or "-") + (f"<br>{esc(res.filter_right)}"
                        if res.filter_right and res.filter_right != res.filter_left else "")),
        ])

    # every column, one sheet
    stats = column_ledger(run, name_a, name_b)
    counts = ledger_counts(stats, name_a, name_b)
    col_line = " · ".join(f"<b>{v}</b> {esc(k)}" for k, v in counts.items())
    missing = [k for k, v in counts.items() if k.startswith("only in") and v]
    missing_note = ""
    if missing:
        names = {k: stats.loc[stats["Role"] == k, "Column"].tolist() for k in missing}
        missing_note = ('<div class="note"><div class="note-t">Not compared</div><p>Present on one side only: '
                        + " · ".join(f"<b>{esc(k)}</b>: {esc(', '.join(v))}" for k, v in names.items())
                        + "</p></div>")
    for c in ("Matched", "Mismatched", f"Values only in {name_a}", f"Values only in {name_b}"):
        if c in stats.columns:
            stats[c] = stats[c].map(lambda v: None if v is None or pd.isna(v) else f"{int(v):,}")

    parts = [f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg['name'])} - {esc(APP_NAME)} report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="{FONTS}" rel="stylesheet">
<style>{CSS}</style></head><body><main class="main">
<header class="hero">
  <div class="eyebrow">{esc(APP_NAME)} · <span>{esc(name_a)} against {esc(name_b)}</span> · {esc(time.strftime('%d %b %Y %H:%M'))}</div>
  <h1>{esc(name_a)} against {esc(name_b)}, <em>every difference.</em></h1>
  <p class="lede">{verdict}</p>
  <div class="pills"><span class="pill">{esc(A.label)}</span><span class="pill">{esc(B.label)}</span>
  <span class="pill">{'key ' + esc(' + '.join(keys)) if by_key else run['mode']}</span><span class="pill">{len(cols)} columns</span></div>
</header>
<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">The <em>setup.</em></h2></div></div>
<div class="body"><div class="card">{settings}</div></div></section>
<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Row <em>counts.</em></h2></div></div>
<div class="body"><div class="grid">
  <div class="m"><div class="k">Rows {esc(name_a)}</div><div class="v">{res.rows_left_read:,}</div></div>
  <div class="m"><div class="k">Rows {esc(name_b)}</div><div class="v">{res.rows_right_read:,}</div></div>
  <div class="m"><div class="k">{'Matched on key' if by_key else 'Identical rows' if run['mode'] == 'hash' else 'Paired by position'}</div><div class="v">{res.matched_rows:,}</div></div>
  <div class="m"><div class="k">Only in {esc(name_a)}</div><div class="v {'bad' if res.only_left else ''}">{res.only_left:,}</div></div>
  <div class="m"><div class="k">Only in {esc(name_b)}</div><div class="v {'bad' if res.only_right else ''}">{res.only_right:,}</div></div>
  <div class="m"><div class="k">Rows that differ</div><div class="v {'bad' if res.diff_rows else 'ok'}">{res.diff_rows:,}</div></div>
</div>
<div class="note {tone}"><div class="note-t">Result</div><p>{verdict}</p></div></div></section>
<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Every <em>column.</em></h2>
<div class="sec-sub">{col_line} · {'match figures measured on the ' + f'{res.matched_rows:,}' + ' rows that paired' if run['mode'] != 'hash' else 'distinct values present on one side only'}</div></div></div>
<div class="body">{missing_note}{_table(stats, numeric={"Matched", "Mismatched", "Match %", f"Values only in {name_a}", f"Values only in {name_b}"}, bar="Match %" if run['mode'] != 'hash' else None, null="")}</div></section>"""]

    if by_key and res.diff_rows:
        by_val = diffs_by_key_value(run, keys)
        blocks = "".join(f"<h3 class='sec-sub' style='margin-top:18px'>{esc(k)}</h3>"
                         + _table(t, numeric={"Matched rows", "Rows that differ", "% of those rows", "Cells that differ"})
                         for k, t in by_val.items())
        dup_note = ""
        if res.duplicate_keys_left or res.duplicate_keys_right:
            dup_note = (f'<div class="note warn"><div class="note-t">Key not unique</div><p>{res.duplicate_keys_left:,} rows in '
                        f'{esc(name_a)} and {res.duplicate_keys_right:,} in {esc(name_b)} share their key with an earlier row. '
                        f'Rows with the same key were paired in file order - first with first, second with second - so a '
                        f'difference under a repeated key may be two rows swapped rather than a changed value.</p></div>')
        prof = _profile_grid(bucket_profile(run, keys, cols, "differ"), keys)
        parts.append(f"""<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Differences by <em>key value.</em></h2>
<div class="sec-sub">the key is identical on both sides for these rows - this is where the differences sit, not what they are</div></div></div>
<div class="body">{dup_note}{blocks}
<h3 class="sec-sub" style="margin-top:26px">Every column across the {res.diff_rows:,} rows that differ - top values, counted on each side</h3>{prof}</div></section>""")
        df, marks = differing_rows(run, keys, cols, limit)
        parts.append(f"""<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Rows that <em>differ.</em></h2>
<div class="sec-sub">{esc(name_a)} above {esc(name_b)} · {min(res.diff_rows, limit):,} of {res.diff_rows:,} rows · differing cells marked</div></div></div>
<div class="body"><div class="legend"><span class="la">{esc(name_a)} · black</span><span class="lb">{esc(name_b)} · cream</span></div>{_pairs_table(df, marks, keys, name_a, name_b)}</div></section>""")

    for tag, name, total in (("left_only", name_a, res.only_left), ("right_only", name_b, res.only_right)):
        path = run["files"].get(f"{cfg['name']}__{tag}.csv")
        if not path or not total:
            continue
        frame = load_csv(str(path)).head(limit)
        parts.append(f"""<section class="sec"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Only in <em>{esc(name)}.</em></h2>
<div class="sec-sub">{min(total, limit):,} of {total:,} rows · no partner on the other side</div></div></div>
<div class="body"><h3 class="sec-sub">Top values by column - the key columns are why these rows did not pair</h3>
{_profile_grid(bucket_profile(run, keys, cols, "left" if tag == "left_only" else "right"), keys)}
<h3 class="sec-sub" style="margin-top:20px">The rows</h3>
<div class="{"side-a" if tag == "left_only" else "side-b"}">{_table(frame)}</div></div></section>""")

    parts.append(f"""<div class="foot">Built {esc(run['at'])} in {run['seconds']:.1f}s · rows shown are capped at {limit:,} per section; the CSV downloads hold everything · values are the canonical form both sides were compared on.</div>
</main></body></html>""")
    return "".join(parts)
