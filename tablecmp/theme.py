"""The house style. Every colour, font and limit is here and nowhere else - and the app's name.

The name is the one thing you are likely to change per deployment. Either edit APP_NAME below,
or leave the code alone and set an environment variable before starting:

    set COMPARE_APP_NAME=Acme Table Check        (Windows)
    export COMPARE_APP_NAME="Acme Table Check"   (macOS / Linux)

It shows in the browser tab, the sidebar mark, the page header and the report.
"""
from __future__ import annotations

import os
from typing import Any

APP_NAME = os.environ.get("COMPARE_APP_NAME", "CrossHire Compare").strip() or "CrossHire Compare"
APP_TAGLINE = os.environ.get("COMPARE_APP_TAGLINE", "Tables, side by side").strip()


def brand_html() -> str:
    """The sidebar mark: last word in italic brass, the rest upright - "CrossHire <em>Compare</em>"."""
    words = APP_NAME.split()
    if len(words) < 2:
        return f"<em>{esc(APP_NAME)}</em>"
    return esc(" ".join(words[:-1])) + f" <em>{esc(words[-1])}</em>"


THEME = {
    "ink": "#0e0d0b", "ink2": "#151310", "ink3": "#1c1916",       # surfaces, darkest first
    "rule": "#2b2620", "rule_soft": "#211d19",                    # hairlines
    "paper": "#f2efe9", "paper2": "#cdc6ba", "muted": "#918878",  # text, secondary, quiet
    "brass": "#c8a45c", "brass_dim": "#8a713c",                   # the accent
    "ice": "#8fb3c4", "sage": "#94ab8e", "rose": "#c98f7f",       # code · good · trouble
    "display": '"Newsreader", Georgia, serif',
    "body": '"IBM Plex Sans", system-ui, -apple-system, sans-serif',
    "mono": '"IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace',
    "fonts": ("https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;"
              "0,6..72,400;0,6..72,500;1,6..72,300;1,6..72,400&family=IBM+Plex+Sans:ital,wght@"
              "0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:ital,wght@0,400;0,500;1,400"
              "&display=swap"),
    "upload_mb": 4096,       # upload limit when started with `python compare_app.py`
}

STREAMLIT_THEME = {          # what Streamlit itself draws with: grids, menus, focus rings
    "theme.base": "dark",
    "theme.primaryColor": THEME["brass"],
    "theme.backgroundColor": THEME["ink"],
    "theme.secondaryBackgroundColor": THEME["ink2"],
    "theme.textColor": THEME["paper"],
    "theme.font": "IBM Plex Sans, sans-serif",
    "theme.codeFont": "IBM Plex Mono, monospace",
    "theme.headingFont": "Newsreader, serif",
    "theme.borderColor": THEME["rule"],
    "theme.baseRadius": "4px",
}


def css() -> str:
    t = THEME
    return f"""
<style>
    @import url('{t['fonts']}');
    :root {{
        --ink:{t['ink']}; --ink-2:{t['ink2']}; --ink-3:{t['ink3']};
        --rule:{t['rule']}; --rule-soft:{t['rule_soft']};
        --paper:{t['paper']}; --paper-2:{t['paper2']}; --muted:{t['muted']};
        --brass:{t['brass']}; --brass-dim:{t['brass_dim']};
        --ice:{t['ice']}; --sage:{t['sage']}; --rose:{t['rose']};
        --display:{t['display']}; --body:{t['body']}; --mono:{t['mono']};
    }}
    html, body, .stApp {{
        background: var(--ink); color: var(--paper-2);
        font-family: var(--body); font-weight: 300; font-size: 15.5px; line-height: 1.6;
        letter-spacing: .005em; -webkit-font-smoothing: antialiased; font-variant-numeric: tabular-nums;
    }}
    .stApp *:not(code):not(pre):not(kbd):not(pre *):not(code *):not(svg *)
        :not([data-testid*="Icon"]):not([data-testid*="Icon"] *):not([class*="material"]) {{ font-family: var(--body) !important; }}
    [data-testid*="Icon"], [data-testid*="Icon"] *, [class*="material-symbols"] {{ font-family: "Material Symbols Rounded" !important; }}
    [data-testid="stHeader"] {{ background: var(--ink); }}
    .block-container {{ padding-top: 2.4rem; padding-bottom: 7rem; max-width: 1500px; counter-reset: sec; }}
    ::selection {{ background: var(--brass-dim); color: var(--paper); }}

    /* type */
    .eyebrow {{ font-family: var(--mono) !important; font-size: 10.5px; letter-spacing: .16em;
        text-transform: uppercase; color: var(--muted); margin: 0 0 1.1rem; }}
    .eyebrow span {{ color: var(--brass); }}
    h1, .hero-h {{ font-family: var(--display) !important; font-weight: 300 !important;
        font-size: clamp(34px, 4.6vw, 56px); line-height: 1.06; letter-spacing: -.018em;
        color: var(--paper); margin: 0 0 .9rem; max-width: 22ch; }}
    h1 em, .hero-h em {{ font-style: italic; color: var(--brass); }}
    .lede {{ max-width: 68ch; font-size: 17px; line-height: 1.66; color: var(--paper-2); margin: 0 0 1.2rem; }}
    strong {{ font-weight: 500; color: var(--paper); }}
    .block-container h3 {{
        font-family: var(--display) !important; font-weight: 300 !important;
        font-size: clamp(25px, 3vw, 34px); line-height: 1.16; letter-spacing: -.012em;
        color: var(--paper); margin: 2.4rem 0 .5rem; padding-top: 2.2rem;
        border-top: 1px solid var(--rule-soft); counter-increment: sec; }}
    .block-container h3::before {{
        content: counter(sec, decimal-leading-zero); display: block;
        font-family: var(--mono) !important; font-size: 11px; letter-spacing: .1em;
        color: var(--brass); margin-bottom: .55rem; }}
    .block-container h3 em {{ font-style: italic; color: var(--brass); }}
    h2 {{ font-family: var(--display) !important; font-weight: 300 !important; color: var(--paper);
        font-size: 1.6rem; letter-spacing: -.012em; }}
    h4, [data-testid="stMarkdownContainer"] h4, .stMarkdown h4 {{ font-family: var(--mono) !important;
        font-weight: 400 !important; font-size: 10.5px !important; letter-spacing: .14em; text-transform: uppercase;
        color: var(--brass) !important; margin: 1.4rem 0 .5rem; padding: 0; }}
    p, li, label {{ color: var(--paper-2); }}
    [data-testid="stCaptionContainer"] p {{ color: var(--muted); font-size: 13.5px; line-height: 1.62; max-width: 92ch; }}
    label[data-testid="stWidgetLabel"] p {{ font-size: 13px; color: var(--paper-2); }}
    hr {{ border: 0; border-top: 1px solid var(--rule-soft); margin: 1.5rem 0; }}
    a {{ color: var(--paper); text-decoration: none; border-bottom: 1px solid var(--brass-dim); }}
    a:hover {{ border-bottom-color: var(--brass); }}
    code {{ font-family: var(--mono) !important; font-size: .88em; background: var(--ink-3);
        border: 1px solid var(--rule-soft); padding: 1px 5px; border-radius: 3px; color: var(--ice); }}
    [data-testid="stCode"] pre, pre {{ background: var(--ink-2) !important; border: 1px solid var(--rule); border-radius: 5px; }}
    [data-testid="stCode"] code, pre code {{ background: none; border: 0; color: var(--paper-2); }}

    /* sidebar: the rail */
    section[data-testid="stSidebar"] {{ background: var(--ink); border-right: 1px solid var(--rule-soft); }}
    section[data-testid="stSidebar"] > div {{ padding-top: 2.6rem; }}
    .rail-mark {{ font-family: var(--display) !important; font-size: 21px; color: var(--paper); letter-spacing: .01em; }}
    .rail-mark em {{ font-style: italic; color: var(--brass); }}
    .rail-sub {{ font-family: var(--mono) !important; font-size: 10.5px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--muted); margin: .2rem 0 1.6rem; }}
    section[data-testid="stSidebar"] hr {{ margin: 1.2rem 0; }}

    /* widgets */
    div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"],
    div[data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] {{
        background: var(--ink-2) !important; border-color: var(--rule) !important;
        border-radius: 4px !important; color: var(--paper) !important; }}
    div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
    div[data-baseweb="select"] > div:focus-within, [data-testid="stNumberInputContainer"]:focus-within {{
        border-color: var(--brass-dim) !important; box-shadow: none !important; }}
    input, textarea {{ color: var(--paper) !important; font-weight: 300; }}
    ::placeholder {{ color: var(--muted) !important; opacity: 1; }}
    ul[data-baseweb="menu"] {{ background: var(--ink-2) !important; border: 1px solid var(--rule); }}
    ul[data-baseweb="menu"] li {{ color: var(--paper-2) !important; }}
    ul[data-baseweb="menu"] li[aria-selected="true"], ul[data-baseweb="menu"] li:hover {{ background: var(--ink-3) !important; color: var(--paper) !important; }}
    label[data-baseweb="checkbox"] > span:first-of-type {{ border-radius: 3px !important; border-color: var(--rule) !important; background: var(--ink-2) !important; }}
    label[data-baseweb="checkbox"]:has(input:checked) > span:first-of-type {{ background: var(--brass) !important; border-color: var(--brass) !important; }}
    label[data-baseweb="radio"] > div:first-of-type {{ border-color: var(--rule) !important; background: var(--ink-2) !important; }}
    label[data-baseweb="radio"]:has(input:checked) > div:first-of-type {{ border-color: var(--brass) !important; }}
    label[data-baseweb="radio"]:has(input:checked) > div:first-of-type > div {{ background: var(--brass) !important; }}
    span[data-baseweb="tag"] {{ background: var(--ink-3) !important; color: var(--brass) !important;
        border: 1px solid var(--brass-dim) !important; border-radius: 100px !important; }}
    span[data-baseweb="tag"] span {{ font-family: var(--mono) !important; font-size: 11px !important; color: var(--brass) !important; }}
    span[data-baseweb="tag"] svg {{ fill: var(--brass) !important; color: var(--brass) !important; }}
    [data-baseweb="slider"] [role="slider"] {{ background: var(--brass) !important; border-color: var(--brass) !important; }}
    [data-testid="stSliderThumbValue"] {{ color: var(--brass) !important; }}
    [data-testid="stFileUploaderDropzone"] {{ background: var(--ink-2) !important;
        border: 1px dashed var(--rule) !important; border-radius: 5px !important; }}
    [data-testid="stFileUploaderDropzone"] small, [data-testid="stFileUploaderDropzone"] span {{ color: var(--muted) !important; }}

    /* buttons: the reference's pills */
    .stButton > button, .stDownloadButton > button, [data-testid="stFileUploaderDropzone"] button {{
        font-family: var(--mono) !important; font-size: 10.5px !important; letter-spacing: .12em;
        text-transform: uppercase; border-radius: 100px !important; border: 1px solid var(--rule) !important;
        background: transparent !important; color: var(--paper-2) !important; min-height: 0;
        padding: .5rem 1rem; transition: border-color .15s, color .15s; }}
    .stButton > button:hover, .stDownloadButton > button:hover {{ border-color: var(--brass) !important; color: var(--paper) !important; }}
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
        background: var(--brass) !important; border-color: var(--brass) !important; color: var(--ink) !important; font-weight: 500 !important; }}
    .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {{
        background: var(--paper) !important; border-color: var(--paper) !important; }}
    .stButton > button:disabled, .stDownloadButton > button:disabled {{ opacity: .35; }}

    /* metrics, tabs, expanders, tables */
    [data-testid="stMetric"] {{ background: var(--ink-2); border: 1px solid var(--rule); border-radius: 5px; padding: .85rem 1rem; }}
    [data-testid="stMetricLabel"] p {{ font-family: var(--mono) !important; font-size: 10px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--muted); }}
    [data-testid="stMetricValue"] {{ font-family: var(--display) !important; font-weight: 300 !important;
        font-size: 2rem; color: var(--paper); letter-spacing: -.01em; }}
    .stTabs [data-baseweb="tab"] {{ font-family: var(--mono) !important; font-size: 10.5px !important;
        letter-spacing: .13em; text-transform: uppercase; color: var(--muted) !important; padding-bottom: .6rem; }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{ color: var(--paper) !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background: var(--brass); height: 1px; }}
    .stTabs [data-baseweb="tab-border"] {{ background: var(--rule); }}
    [data-testid="stExpander"] {{ border: 1px solid var(--rule); border-radius: 5px; background: var(--ink-2); }}
    [data-testid="stExpander"] summary {{ background: var(--ink-3); }}
    [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{ font-weight: 500; font-size: 14px; color: var(--paper); }}
    [data-testid="stExpander"] summary:hover p {{ color: var(--brass); }}
    div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{ border: 1px solid var(--rule); border-radius: 5px; overflow: hidden; }}
    [data-testid="stStatusWidget"], [data-testid="stSpinner"] {{ color: var(--muted); }}
    [data-testid="stProgress"] > div > div > div {{ background: var(--brass) !important; }}

    /* alerts as the reference's notes */
    [data-testid="stAlert"], [data-testid="stAlert"] > div {{ background: var(--ink-2) !important;
        border-radius: 0 4px 4px 0 !important; color: var(--paper-2) !important; }}
    [data-testid="stAlert"] {{ border: 1px solid var(--rule-soft); border-left: 2px solid var(--brass-dim) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{ border-left-color: var(--rose) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{ border-left-color: var(--brass) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color: var(--sage) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) {{ border-left-color: var(--ice) !important; }}
    [data-testid="stAlert"] p {{ font-size: 14px; line-height: 1.6; color: var(--paper-2) !important; }}
    [data-testid="stAlert"] svg {{ display: none; }}

    /* run sheet panels: the status strip, the setup card, the verdict */
    .strip {{ display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid var(--rule);
        border-radius: 5px; background: var(--ink-2); margin: 1.4rem 0 2rem; overflow: hidden; }}
    .strip > div {{ padding: .85rem 1.1rem; border-right: 1px solid var(--rule-soft); min-width: 0; }}
    .strip > div:last-child {{ border-right: 0; }}
    .strip .k, .card .k {{ font-family: var(--mono) !important; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--brass); }}
    .strip .v {{ font-size: 14px; color: var(--paper); margin-top: .3rem; font-weight: 400; overflow-wrap: anywhere; }}
    .ok {{ color: var(--sage) !important; }} .warn {{ color: var(--brass) !important; }} .bad {{ color: var(--rose) !important; }}
    .card {{ border: 1px solid var(--rule); border-radius: 5px; background: var(--ink-2); margin: .6rem 0 1.2rem; overflow: hidden; }}
    .card .row {{ display: grid; grid-template-columns: 11rem 1fr; gap: 0 1rem; padding: .7rem 1.1rem;
        border-bottom: 1px solid var(--rule-soft); font-size: 14px; }}
    .card .row:last-child {{ border-bottom: 0; }}
    .card .row .v {{ color: var(--paper); overflow-wrap: anywhere; }}
    .card .row .v code {{ font-size: 12px; }}
    .card .row .m {{ color: var(--muted); }}
    .verdict {{ border-left: 2px solid var(--brass-dim); background: var(--ink-2); padding: 1rem 1.2rem;
        border-radius: 0 4px 4px 0; margin: .4rem 0 1.4rem; font-size: 14.5px; color: var(--paper-2); line-height: 1.7; }}
    .verdict .t {{ display: block; font-family: var(--mono) !important; font-size: 10px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--brass); margin-bottom: .45rem; }}
    .verdict.ok {{ border-left-color: var(--sage); }} .verdict.ok .t {{ color: var(--sage); }}
    .verdict.warn {{ border-left-color: var(--brass); }}
    .verdict.bad {{ border-left-color: var(--rose); }} .verdict.bad .t {{ color: var(--rose); }}
    .verdict b {{ font-family: var(--display) !important; font-weight: 400; font-size: 1.3rem; color: var(--paper); }}
    .steps {{ font-family: var(--mono) !important; font-size: 12px; color: var(--paper-2); line-height: 1.9; }}
    .steps .n {{ color: var(--brass-dim); margin-right: .6rem; }}
    .steps .arrow {{ color: var(--muted); margin: 0 .5rem; }}
    @media (max-width: 900px) {{ .strip {{ grid-template-columns: 1fr 1fr; }} .card .row {{ grid-template-columns: 1fr; }} }}
</style>
"""


def esc(x: Any) -> str:
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def status_strip(slot, files: str, columns: str, key: str, compare: str, result: str,
                 tones: dict[str, str] | None = None) -> None:
    """The five-cell strip under the title: where the comparison stands, at a glance."""
    tones = tones or {}
    cells = [("Files", files), ("Columns", columns), ("Key", key), ("Compare", compare),
             ("Result", result)]
    html = "".join(f'<div><div class="k">{k}</div><div class="v {tones.get(k, "")}">{esc(v)}</div></div>'
                   for k, v in cells)
    slot.markdown(f'<div class="strip">{html}</div>', unsafe_allow_html=True)


def card(rows: list[tuple[str, str]]) -> str:
    """A run-sheet style card: label on the left, value (already HTML) on the right."""
    body = "".join(f'<div class="row"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
                   for k, v in rows)
    return f'<div class="card">{body}</div>'
