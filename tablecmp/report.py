"""The report: one self-contained HTML file in the house style."""
from __future__ import annotations

import json
import time

import pandas as pd

from .compare import (bucket_profile, column_ledger, ledger_counts, Outcome, differing_rows, diffs_by_key_value,
                      value_pairs)
from .outputs import summary_payload
from .sources import Side
from .theme import APP_NAME, CELL_BUDGET, FONTS, esc, tokens_css
from .values import ColSpec

# the section anchors, in page order; a section that is not emitted leaves its id unused
IDS = ["setup", "counts", "columns", "by-key", "rows", "only-a", "only-b"]
OP_WORDS = {"eq": "=", "ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<=", "in": "in", "not_in": "not in",
            "between": "between", "like": "like", "is_null": "is null", "not_null": "is not null"}

# The palette and fonts come from theme.py as --fs-* / --font-* / --diff-* variables (tokens_css()
# opens the <style> block); these rules only ever point at them. Left rows sit on bg with text
# ("black"), Right rows on text with bg ("cream"), everywhere the two sides are shown together.
CSS = """
:root{--pad:clamp(20px,5vw,64px)}
*{box-sizing:border-box}
body{margin:0;background:var(--fs-bg);color:var(--fs-text2);font-family:var(--font-sans);font-weight:400;
font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.main{max-width:1500px;margin:0 auto;padding:0 var(--pad) 100px}
.hero{padding:clamp(40px,7vw,80px) 0 clamp(30px,4vw,44px);border-bottom:1px solid var(--fs-line)}
.eyebrow{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--fs-text3);margin-bottom:22px}
.eyebrow span{color:var(--fs-accent)}
h1{font-family:var(--font-display);font-weight:300;font-size:clamp(32px,5vw,54px);line-height:1.06;letter-spacing:-.018em;color:var(--fs-text);margin:0 0 20px;max-width:22ch}
h1 em{font-style:italic;color:var(--fs-accent)}
.lede{max-width:70ch;font-size:16.5px;color:var(--fs-text2);margin:0}
.lede b{font-weight:500;color:var(--fs-text)}
.pills{display:flex;flex-wrap:wrap;gap:7px;margin-top:26px}
.pill{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.06em;padding:5px 11px;border:1px solid var(--fs-line);border-radius:100px;color:var(--fs-text3)}
.sec{padding:clamp(34px,4vw,56px) 0;border-bottom:1px solid var(--fs-border)}
.sec-head{display:grid;grid-template-columns:64px 1fr;gap:0 22px;margin-bottom:22px}
.sec-num{font-family:var(--font-mono);font-size:11px;letter-spacing:.1em;color:var(--fs-accent);padding-top:9px}
.sec-h{font-family:var(--font-display);font-weight:300;font-size:clamp(24px,3vw,34px);line-height:1.16;letter-spacing:-.012em;color:var(--fs-text);margin:0}
.sec-h em{font-style:italic;color:var(--fs-accent)}
.sec-sub{font-family:var(--font-mono);font-size:11.5px;color:var(--fs-text3);margin-top:8px}
.body{margin-left:86px}
@media(max-width:760px){.sec-head{grid-template-columns:1fr}.body{margin-left:0}}
p{margin:0 0 14px;max-width:70ch}
code{font-family:var(--font-mono);font-size:.88em;background:var(--fs-surface);border:1px solid var(--fs-border);padding:1px 5px;border-radius:3px;color:var(--fs-accent-h)}
.note{margin:18px 0;padding:14px 18px;border-left:2px solid var(--fs-accent-line);background:var(--fs-panel);border-radius:0 var(--r-sm) var(--r-sm) 0;max-width:80ch}
.note-t{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--fs-accent);margin-bottom:6px}
.note.ok{border-left-color:var(--fs-pos)}.note.ok .note-t{color:var(--fs-pos)}
.note.bad{border-left-color:var(--fs-neg)}.note.bad .note-t{color:var(--fs-neg)}
.note p{margin:0;font-size:14.5px}
.note b{font-family:var(--font-display);font-weight:400;font-size:1.25rem;color:var(--fs-text)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.m{border:1px solid var(--fs-line);border-radius:var(--r-sm);background:var(--fs-panel);padding:12px 14px}
.m .k{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--fs-text3)}
.m .v{font-family:var(--font-display);font-weight:300;font-size:30px;color:var(--fs-text);line-height:1.1;margin-top:6px}
.m .v.bad{color:var(--fs-neg)}.m .v.ok{color:var(--fs-pos)}
.card{border:1px solid var(--fs-line);border-radius:var(--r-sm);background:var(--fs-panel);overflow:hidden;margin:16px 0}
.card .row{display:grid;grid-template-columns:12rem 1fr;gap:0 14px;padding:10px 16px;border-bottom:1px solid var(--fs-border);font-size:14px}
.card .row:last-child{border-bottom:0}
.card .k{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--fs-accent);padding-top:3px}
.card .v{color:var(--fs-text);overflow-wrap:anywhere}
.tw{overflow-x:auto;margin:14px 0 22px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-family:var(--font-mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--fs-text3);font-weight:400;padding:0 14px 8px 0;border-bottom:1px solid var(--fs-line);white-space:nowrap}
td{padding:8px 14px 8px 0;border-bottom:1px solid var(--fs-border);vertical-align:top;line-height:1.5;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num{text-align:right;font-family:var(--font-mono);font-size:12px}
th.num{text-align:right}
.bar{display:inline-block;height:6px;background:var(--fs-warn);border-radius:3px;vertical-align:middle;margin-right:8px}
tr.a td{background:var(--fs-bg);color:var(--fs-text)}
tr.b td{background:var(--fs-text);color:var(--fs-bg);border-bottom-color:var(--fs-text2)}
td.side{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--fs-text3)}
tr.b td.side{color:var(--fs-text4)}
tr.b td.key{color:var(--fs-text4)}  /* text4, not warn: warn on the cream row is 1.9:1 */
tr.a td.diff{background:var(--diff-left-bg)!important;color:var(--diff-left-fg);font-weight:500}
tr.b td.diff{background:var(--diff-right-bg)!important;color:var(--diff-right-fg);font-weight:500}
.legend{display:flex;gap:14px;margin:0 0 10px;font-family:var(--font-mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase}
.legend span{padding:3px 10px;border-radius:3px;border:1px solid var(--fs-line)}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin:12px 0 18px}
.pcard{border:1px solid var(--fs-line);border-radius:var(--r-sm);padding:10px 12px;background:var(--fs-panel)}
.pcard .k{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--fs-accent);margin-bottom:6px}
.pcard table{font-size:12px}
.legend .la{background:var(--fs-bg);color:var(--fs-text)}.legend .lb{background:var(--fs-text);color:var(--fs-bg)}
.side-a td{background:var(--fs-bg);color:var(--fs-text)}
.side-b td{background:var(--fs-text);color:var(--fs-bg);border-bottom-color:var(--fs-text2)}
.side-b th{color:var(--fs-text3)}
td.key{font-family:var(--font-mono);font-size:12px;color:var(--fs-accent-h)}
tr.gap td{padding:0;height:6px;background:var(--fs-bg);border:0}
.small{font-family:var(--font-mono);font-size:10.5px;color:var(--fs-text3);margin-top:6px}
.foot{padding:36px 0 0;color:var(--fs-text3);font-size:12.5px}
.note.warn{border-left-color:var(--fs-warn)}.note.warn .note-t{color:var(--fs-warn)}
.pill a{color:inherit;text-decoration:none}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:baseline;border:1px solid var(--fs-line);border-radius:var(--r-sm);background:var(--fs-panel);padding:14px 18px;margin-top:22px}
.verdict .w{font-family:var(--font-display);font-weight:300;font-size:26px;color:var(--fs-text)}
.verdict.ok .w{color:var(--fs-pos)}.verdict.warn .w{color:var(--fs-warn)}.verdict.bad .w{color:var(--fs-neg)}
.verdict .r{font-family:var(--font-mono);font-size:11px;color:var(--fs-text3)}
.vp{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin:14px 0 4px}
.vp .pcard .k{display:flex;justify-content:space-between}
.vp .pcard .k span{color:var(--fs-neg)}
details{margin-top:8px}summary{cursor:pointer;font-family:var(--font-mono);font-size:11px;color:var(--fs-text3)}
details pre{font-family:var(--font-mono);font-size:11px;white-space:pre-wrap;color:var(--fs-text2);background:var(--fs-surface);padding:12px;border-radius:var(--r-sm);max-height:420px;overflow:auto}
@media print{:root{--fs-bg:#fff;--fs-panel:#fff;--fs-surface:#f3f1ec;--fs-line:#d8d3c8;--fs-text:#111;--fs-text2:#333;--fs-text3:#666;--fs-text4:#888;--fs-accent:#8a5a1e;--fs-accent-h:#8a5a1e;--fs-border:#e2ddd2;--diff-left-bg:#f6d9d2;--diff-left-fg:#4a2521;--diff-right-bg:#f6d9d2;--diff-right-fg:#4a2521}
body{font-size:11px}.main{max-width:none;padding:0}td,th{white-space:normal}.tw{overflow:visible}.card,.m,.note,.pcard,tr{break-inside:avoid}
tr.a td{background:#fff;color:#111}tr.b td{background:#eee;color:#111}tr.b td.side,tr.b td.key{color:#555}.side-b td{background:#eee;color:#111}.legend .lb{background:#eee;color:#111}details{display:none}}
"""


def _fmt(v, null: str = '<span style="color:var(--fs-text3)">∅</span>') -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return null                       # ∅ for a null data value; "" where a cell simply doesn't apply
    return esc(v)


def _table(df: pd.DataFrame, numeric: set[str] | None = None, bar: str | None = None,
           bar_max: float = 100.0, null: str = '<span style="color:var(--fs-text3)">∅</span>') -> str:
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


def _source_row(nm: str, s: Side, n: int, path: str) -> str:
    """One side of the Sources row: what it is, where it came from, how many rows - never a URI."""
    text = f"{esc(nm)} - {esc(s.origin or s.label) if s.is_database else esc(s.label)}"
    if s.is_database:
        text += f" · connection <code>{esc(s.conn)}</code>"
    elif path:
        text += f" · {esc(path)}"
    if s.cut:
        text += f" ({esc(s.cut)})"
    if s.cache_path:
        text += " · Parquet snapshot"
    text += f" - {n:,} rows"
    if s.is_database:
        text += f" · fetched {esc(s.fetched_at)}"
    if s.capped:
        text += f" · capped at {s.cap:,}"
    if s.is_database and s.query:
        text += f'<div class="small">{esc(s.query)}</div>'
    return text


def _key_row(res: Outcome, keys: list[str], name_a: str, name_b: str, notes: list[str]) -> str:
    """The Key row: the columns, whether they are unique, the match rate, and why Auto chose them -
    only when the key that ran is the one Auto chose; a key picked by hand carries no reason."""
    text = esc(" + ".join(keys))
    if res.duplicate_keys_left or res.duplicate_keys_right:
        text += (f" - {res.duplicate_keys_left:,} rows in {esc(name_a)} and {res.duplicate_keys_right:,} in "
                 f"{esc(name_b)} share their key with an earlier row")
    else:
        text += " - unique on both sides"
    floor = min(res.rows_left, res.rows_right)
    rate = res.matched_rows / floor * 100 if floor else 0.0
    text += f" · {res.matched_rows:,} of {floor:,} matched ({rate:.1f}%)"
    why = next((n for n in notes if n.startswith("key:")), "")
    named, _, reason = why[len("key:"):].partition(" - ")     # "key: a + b - <reason>"
    if reason and set(named.strip().split(" + ")) == set(keys):
        text += " · " + esc(reason)
    if notes:
        text += (f"<details><summary>How this was worked out - {len(notes)} "
                 f"{'decision' if len(notes) == 1 else 'decisions'}</summary><pre>"
                 + "\n".join(esc(n) for n in notes) + "</pre></details>")
    return text


def _case_bit(cfg: dict) -> str:
    """'case ignored' or 'case matters', then the columns whose own Case overrides the switch:
    'case matters · <b>ignored on: city</b>'."""
    ignore = bool(cfg.get("ignore_case"))
    rules = cfg.get("column_rules") or {}
    against = sorted(c for c, r in rules.items() if isinstance(r, dict)
                     and r.get("ignore_case") is not None and bool(r["ignore_case"]) != ignore)
    text = "<b>case ignored</b>" if ignore else "case matters"
    if against:
        text += f" · <b>{'exact' if ignore else 'ignored'} on: {esc(', '.join(against))}</b>"
    return text


def _values_row(cfg: dict) -> str:
    """How values were read before comparing; anything off the default in bold."""
    tol = cfg.get("tolerance") or 0
    tokens = cfg.get("null_tokens") or []            # the app keeps the typed text, scripts a list
    if isinstance(tokens, str):
        tokens = [t.strip() for t in tokens.split(",") if t.strip()]
    bits = ["trim spaces" if cfg.get("trim", True) else "<b>keep spaces</b>",
            "empty is null" if cfg.get("empty_as_null", True) else "<b>empty is a value</b>",
            _case_bit(cfg),
            f"<b>tolerance {tol}</b>" if tol else f"tolerance {tol}",
            "null tokens: " + (esc(", ".join(str(t) for t in tokens)) or "none")]
    return " · ".join(bits)


def _filter_lines(filters: dict, where: str) -> list[str]:
    """The user's filters as typed: 'department in Sales, Finance · both sides'."""
    lines = []
    for col, spec in (filters or {}).items():
        for k, v in (spec or {}).items():
            if k == "type":
                continue
            val = "" if k in ("is_null", "not_null") else \
                ", ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)
            lines.append(esc(" ".join(p for p in (str(col), OP_WORDS.get(k, k), val) if p)) + f" · {esc(where)}")
    return lines


def _filters_row(res: Outcome, cfg: dict, A: Side, B: Side, name_a: str, name_b: str) -> str:
    lines = (_filter_lines(cfg.get("filters"), "both sides") + _filter_lines(cfg.get("left_filters"), name_a)
             + _filter_lines(cfg.get("right_filters"), name_b))
    for nm, s in ((name_a, A), (name_b, B)):
        if s.cut:
            lines.append(f"{esc(nm)}: {esc(s.cut)}")
    sql = [esc(x) for x in dict.fromkeys(x for x in (res.filter_left, res.filter_right) if x)]
    if not lines and not sql:
        return "none"
    return "<br>".join(lines) + "".join(f'<div class="small">{x}</div>' for x in sql)


def _value_pairs(pairs: dict[str, pd.DataFrame], res: Outcome, top: int = 15) -> str:
    """Per differing column, worst first: the most frequent left → right pairs."""
    if not pairs:
        return ""
    order = sorted(pairs, key=lambda c: (-res.diffs_by_column.get(c, 0), c))[:top]
    cards = []
    for col in order:
        n = res.diffs_by_column.get(col, int(pairs[col]["n"].sum()))
        rows = "".join(f'<tr><td>{esc(r["a"])} → {esc(r["b"])}</td>'
                       f'<td class="num">{int(r["n"]):,} · {float(r["pct"]):.0f}%</td></tr>'
                       for _, r in pairs[col].iterrows())
        note = ('<div class="small">every matched row differs on this column - two fields paired by mistake, '
                'or a value that converts on one side only</div>'
                if res.matched_rows and n >= 0.99 * res.matched_rows else "")
        cards.append(f'<div class="pcard"><div class="k"><code>{esc(col)}</code><span>{n:,} differ</span></div>'
                     f'<table>{rows}</table>{note}</div>')
    return '<div class="vp">' + "".join(cards) + "</div>"


def build_report(run: dict, A: Side, B: Side, name_a: str, name_b: str, limit: int = 500,
                 notes: list[str] | None = None, profile: dict | None = None) -> str:
    """The whole report as one HTML string. `notes` are Auto's decisions when Auto ran; `profile`
    is the profile that ran, accepted so callers can hand it over (the report does not draw it)."""
    res: Outcome = run["result"]
    cfg = run["cfg"]
    notes = list(notes or [])
    v = run["verdict"]
    specs = [ColSpec(**d) for d in cfg["specs"]]
    keys = list(res.keys or cfg["keys"]) if run["mode"] == "key" else []
    cols = list(res.columns_compared or cfg["compare_columns"])
    by_key = run["mode"] == "key"
    pct = round(res.diff_rows / res.matched_rows * 100, 2) if res.matched_rows else 0.0
    pairs = value_pairs(run)
    payload = summary_payload(run, A, B, name_a, name_b, notes)     # before write_summary: tolerated
    cap = min(limit, max(50, CELL_BUDGET // (len(cols) + len(keys) + 1)))
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

    # which sections the page will have, in page order - the pills link to them
    have = {"setup", "counts", "columns"}
    if by_key and res.diff_rows:
        have |= {"by-key", "rows"}
    if res.only_left and run["files"].get(f"{cfg['name']}__left_only.csv"):
        have.add("only-a")
    if res.only_right and run["files"].get(f"{cfg['name']}__right_only.csv"):
        have.add("only-b")
    present = [i for i in IDS if i in have]

    # settings card
    steps_rows = [f"<div><code>{esc(s.canon)}</code> {esc(s.describe())}</div>"
                  for s in specs if s.canon in keys + cols
                  and (s.a_steps or s.b_steps or s.kind != 'text' or s.case_rule() is not None)]
    rows = [("Sources", _source_row(name_a, A, res.rows_left_read, payload["sources"]["A"]["path"]) + "<br>"
                        + _source_row(name_b, B, res.rows_right_read, payload["sources"]["B"]["path"]))]
    if by_key:
        rows.append(("Key", _key_row(res, keys, name_a, name_b, notes)))
    rows += [
        ("Rows paired", ("on the key " + esc(" + ".join(keys))) if by_key else
                        "by hashing the compared columns" if run["mode"] == "hash" else "by position"),
        ("Columns compared", esc(", ".join(cols))),
        ("Read as", "".join(steps_rows) or "all text"),
        ("Values", _values_row(cfg)),
        ("Filters", _filters_row(res, cfg, A, B, name_a, name_b)),
    ]
    settings = "".join(f'<div class="row"><div class="k">{k}</div><div class="v">{val}</div></div>' for k, val in rows)

    # every column, one sheet
    stats = column_ledger(run, name_a, name_b)
    counts = ledger_counts(stats, name_a, name_b)
    col_line = " · ".join(f"<b>{val}</b> {esc(k)}" for k, val in counts.items())
    missing = [k for k, val in counts.items() if k.startswith("only in") and val]
    missing_note = ""
    if missing:
        names = {k: stats.loc[stats["Role"] == k, "Column"].tolist() for k in missing}
        missing_note = ('<div class="note"><div class="note-t">Not compared</div><p>Present on one side only: '
                        + " · ".join(f"<b>{esc(k)}</b>: {esc(', '.join(val))}" for k, val in names.items())
                        + "</p></div>")
    for c in ("Matched", "Mismatched", f"Values only in {name_a}", f"Values only in {name_b}"):
        if c in stats.columns:
            stats[c] = stats[c].map(lambda x: None if x is None or pd.isna(x) else f"{int(x):,}")

    after_filter = ""
    if res.rows_left != res.rows_left_read:
        after_filter += (f'<div class="m"><div class="k">Rows after filter {esc(name_a)}</div>'
                         f'<div class="v">{res.rows_left:,}</div></div>')
    if res.rows_right != res.rows_right_read:
        after_filter += (f'<div class="m"><div class="k">Rows after filter {esc(name_b)}</div>'
                         f'<div class="v">{res.rows_right:,}</div></div>')
    dup_note = ""
    if res.duplicate_keys_left or res.duplicate_keys_right:
        dup_note = (f'<div class="note warn"><div class="note-t">Key not unique</div><p>{res.duplicate_keys_left:,} rows in '
                    f'{esc(name_a)} and {res.duplicate_keys_right:,} in {esc(name_b)} share their key with an earlier row. '
                    f'Rows with the same key were paired in file order - first with first, second with second - so a '
                    f'difference under a repeated key may be two rows swapped rather than a changed value.</p></div>')

    pills = (f'<span class="pill">{esc(name_a)} · {esc(A.origin.split(" · ")[0]) if A.is_database else esc(A.label)}</span>'
             f'<span class="pill">{esc(name_b)} · {esc(B.origin.split(" · ")[0]) if B.is_database else esc(B.label)}</span>'
             f'<span class="pill">{"key " + esc(" + ".join(keys)) if by_key else run["mode"]}</span>'
             f'<span class="pill">{len(cols)} columns</span>'
             + "".join(f'<span class="pill"><a href="#{i}">{i}</a></span>' for i in present))

    parts = [f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg['name'])} - {esc(APP_NAME)} report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="{FONTS}" rel="stylesheet">
<style>{tokens_css()}{CSS}</style></head><body><main class="main">
<header class="hero">
  <div class="eyebrow">{esc(APP_NAME)} · <span>{esc(name_a)} against {esc(name_b)}</span> · {esc(time.strftime('%d %b %Y %H:%M'))}</div>
  <h1>{esc(name_a)} against {esc(name_b)}, <em>every difference.</em></h1>
  <p class="lede">{verdict}</p>
  <div class="pills">{pills}</div>
  <div class="verdict {esc(v.tone)}"><div class="w">{esc(v.word)}</div><div class="r">judged by: {esc(v.rule)}</div></div>
</header>
<section class="sec" id="setup"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">The <em>setup.</em></h2></div></div>
<div class="body"><div class="card">{settings}</div></div></section>
<section class="sec" id="counts"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Row <em>counts.</em></h2></div></div>
<div class="body"><div class="grid">
  <div class="m"><div class="k">Rows {esc(name_a)}</div><div class="v">{res.rows_left_read:,}</div></div>
  <div class="m"><div class="k">Rows {esc(name_b)}</div><div class="v">{res.rows_right_read:,}</div></div>
  <div class="m"><div class="k">{'Matched on key' if by_key else 'Identical rows' if run['mode'] == 'hash' else 'Paired by position'}</div><div class="v">{res.matched_rows:,}</div></div>
  <div class="m"><div class="k">Only in {esc(name_a)}</div><div class="v {'bad' if res.only_left else ''}">{res.only_left:,}</div></div>
  <div class="m"><div class="k">Only in {esc(name_b)}</div><div class="v {'bad' if res.only_right else ''}">{res.only_right:,}</div></div>
  <div class="m"><div class="k">Rows that differ</div><div class="v {'bad' if res.diff_rows else 'ok'}">{res.diff_rows:,}</div></div>
  {after_filter}
</div>
<div class="note {esc(v.tone)}"><div class="note-t">Result</div><p>{verdict}</p></div>{dup_note}</div></section>
<section class="sec" id="columns"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Every <em>column.</em></h2>
<div class="sec-sub">{col_line} · {'match figures measured on the ' + f'{res.matched_rows:,}' + ' rows that paired' if run['mode'] != 'hash' else 'distinct values present on one side only'}</div></div></div>
<div class="body">{missing_note}{_table(stats, numeric={"Matched", "Mismatched", "Match %", f"Values only in {name_a}", f"Values only in {name_b}"}, bar="Match %" if run['mode'] != 'hash' else None, null="")}
{_value_pairs(pairs, res)}</div></section>"""]

    if "by-key" in present:
        by_val = diffs_by_key_value(run, keys)
        blocks = "".join(f"<h3 class='sec-sub' style='margin-top:18px'>{esc(k)}</h3>"
                         + _table(t, numeric={"Matched rows", "Rows that differ", "% of those rows", "Cells that differ"})
                         for k, t in by_val.items())
        prof = _profile_grid(bucket_profile(run, keys, cols, "differ"), keys)
        parts.append(f"""<section class="sec" id="by-key"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Differences by <em>key value.</em></h2>
<div class="sec-sub">the key is identical on both sides for these rows - this is where the differences sit, not what they are</div></div></div>
<div class="body">{blocks}
<h3 class="sec-sub" style="margin-top:26px">Every column across the {res.diff_rows:,} rows that differ - top values, counted on each side</h3>{prof}</div></section>""")
        df, marks = differing_rows(run, keys, cols, cap)
        parts.append(f"""<section class="sec" id="rows"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Rows that <em>differ.</em></h2>
<div class="sec-sub">{esc(name_a)} above {esc(name_b)} · {min(res.diff_rows, cap):,} of {res.diff_rows:,} rows · capped at {limit:,} rows or {CELL_BUDGET:,} cells · differing cells marked</div></div></div>
<div class="body"><div class="legend"><span class="la">{esc(name_a)} · black</span><span class="lb">{esc(name_b)} · cream</span></div>{_pairs_table(df, marks, keys, name_a, name_b)}</div></section>""")

    for tag, sid, name, total in (("left_only", "only-a", name_a, res.only_left),
                                  ("right_only", "only-b", name_b, res.only_right)):
        if sid not in present:
            continue
        path = run["files"][f"{cfg['name']}__{tag}.csv"]
        frame = pd.read_csv(str(path), nrows=cap, dtype=str, keep_default_na=False, na_values=[""])
        parts.append(f"""<section class="sec" id="{sid}"><div class="sec-head"><div class="sec-num">{sec()}</div><div><h2 class="sec-h">Only in <em>{esc(name)}.</em></h2>
<div class="sec-sub">{min(total, cap):,} of {total:,} rows · capped at {limit:,} rows or {CELL_BUDGET:,} cells · no partner on the other side</div></div></div>
<div class="body"><h3 class="sec-sub">Top values by column - the key columns are why these rows did not pair</h3>
{_profile_grid(bucket_profile(run, keys, cols, "left" if tag == "left_only" else "right"), keys)}
<h3 class="sec-sub" style="margin-top:20px">The rows</h3>
<div class="{"side-a" if tag == "left_only" else "side-b"}">{_table(frame)}</div></div></section>""")

    as_json = esc(json.dumps({k: payload[k] for k in ("sources", "settings")}, indent=1, default=str))
    parts.append(f"""<div class="foot">Built {esc(run['at'])} in {run['seconds']:.1f}s · run {esc(run['run_id'])} · rows shown are capped at {limit:,} per section and {CELL_BUDGET:,} cells; the downloads hold everything · values are the canonical form both sides were compared on · self-contained apart from the web fonts, which fall back when offline
<details><summary>Settings as JSON</summary><pre>{as_json}</pre></details></div>
</main></body></html>""")
    return "".join(parts)
