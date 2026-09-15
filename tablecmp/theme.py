"""The house style. Every colour, font and limit is here and nowhere else - and the app's name.

This is the Crosshire apps theme: the same tokens the web apps carry as --fs-* variables,
in two flavours. `aurora` (warm dark, amber accent, Fraunces headlines) is the default;
`violet` (cool dark, indigo accent, Inter throughout) is the other. Pick one with an
environment variable before starting; anything unknown falls back to aurora:

    set COMPARE_THEME=violet                     (Windows)
    export COMPARE_THEME=violet                  (macOS / Linux)

The name is the other thing you are likely to change per deployment. Either edit APP_NAME
below, or leave the code alone and set an environment variable before starting:

    set COMPARE_APP_NAME=Employee Table Check    (Windows)
    export COMPARE_APP_NAME="Employee Table Check"   (macOS / Linux)

It shows in the browser tab, the sidebar mark, the page header and the report.

What the rest of the app reads from here: THEME (the active token dict), THEMES (both),
tokens_css() (the :root block that puts the tokens on the page), FONTS (the Google Fonts
URL), css() (the app's styling on top of Streamlit) and STREAMLIT_THEME (what Streamlit
itself draws with).
"""
from __future__ import annotations

import os
from typing import Any

APP_NAME = os.environ.get("COMPARE_APP_NAME", "CrossHire Compare").strip() or "CrossHire Compare"
APP_TAGLINE = os.environ.get("COMPARE_APP_TAGLINE", "Tables, side by side").strip()
CELL_BUDGET = 150_000        # the report shows at most this many cells per row table, whatever the row cap


def brand_html() -> str:
    """The sidebar mark: last word in italic accent, the rest upright - "CrossHire <em>Compare</em>"."""
    words = APP_NAME.split()
    if len(words) < 2:
        return f"<em>{esc(APP_NAME)}</em>"
    return esc(" ".join(words[:-1])) + f" <em>{esc(words[-1])}</em>"


# Self-contained files (the report) load the fonts from Google; the app does the same via css().
FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;"
         "0,9..144,600;1,9..144,300;1,9..144,400&family=Inter:ital,wght@0,300;0,400;0,500;0,600;1,400"
         "&family=JetBrains+Mono:ital,wght@0,400;0,500;1,400&display=swap")

_SHARED = {                  # the same in both themes
    "r_sm": "6px", "r_md": "12px", "r_lg": "18px",
    "body": '"Inter", system-ui, -apple-system, sans-serif',
    "mono": '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
    "upload_mb": 4096,       # upload limit when started with `python compare_app.py`
}

THEMES: dict[str, dict[str, Any]] = {
    "aurora": {              # warm dark, amber accent - the default
        **_SHARED,
        "bg": "#0e0d0b", "panel": "#17150f", "surface": "#1f1c14", "surface2": "#2a261c",
        "line": "#2a261c",
        "text": "#f4ead6", "text2": "#b8ad94", "text3": "#7a7159", "text4": "#4d4128",
        "accent": "#f4b87c", "accent_h": "#f6c48d",
        "accent_dim": "rgba(244,184,124,0.12)", "accent_subtle": "rgba(244,184,124,0.06)",
        "accent_border": "rgba(244,184,124,0.25)", "accent_line": "rgba(244,184,124,0.28)",
        "border": "rgba(244,184,124,0.08)", "border2": "rgba(244,184,124,0.15)",
        "pos": "#7fb069", "neg": "#c97064", "warn": "#d4a24c",
        "display": '"Fraunces", Georgia, serif',
        "heading_font": "Fraunces, serif",                     # Streamlit's own headings
        # side-by-side rows: Left on bg with text ("black"), Right on text with bg ("cream");
        # the differing cells on each, built from neg
        "diff_left_bg": "#4a2521", "diff_left_fg": "#f3cdc4",
        "diff_right_bg": "#ebc2b7", "diff_right_fg": "#4a2521",
    },
    "violet": {              # cool dark, indigo accent; the sans doubles as the display face
        **_SHARED,
        "bg": "#0d0d12", "panel": "#11111a", "surface": "#18182a", "surface2": "#222238",
        "line": "#22223a",
        "text": "#e8e8f2", "text2": "#a0a0c0", "text3": "#6868a0", "text4": "#404070",
        "accent": "#8b7cf6", "accent_h": "#a394fa",
        "accent_dim": "rgba(139,124,246,0.12)", "accent_subtle": "rgba(139,124,246,0.06)",
        "accent_border": "rgba(139,124,246,0.25)", "accent_line": "rgba(139,124,246,0.28)",
        "border": "rgba(139,124,246,0.08)", "border2": "rgba(139,124,246,0.15)",
        "pos": "#6ab187", "neg": "#c97064", "warn": "#c9a85a",
        "display": '"Inter", system-ui, sans-serif',
        "heading_font": "Inter, sans-serif",
        "diff_left_bg": "#3a2330", "diff_left_fg": "#f3cdc4",
        "diff_right_bg": "#e6c3cf", "diff_right_fg": "#3a2330",
    },
}

THEME_NAME = os.environ.get("COMPARE_THEME", "aurora").strip().lower()
if THEME_NAME not in THEMES:
    THEME_NAME = "aurora"
THEME = THEMES[THEME_NAME]   # the active tokens - everything else reads from this

# token -> CSS custom property, in the order the web apps declare them
_CSS_VARS = (
    ("bg", "--fs-bg"), ("panel", "--fs-panel"), ("surface", "--fs-surface"), ("surface2", "--fs-surface2"),
    ("line", "--fs-line"), ("text", "--fs-text"), ("text2", "--fs-text2"), ("text3", "--fs-text3"),
    ("text4", "--fs-text4"), ("accent", "--fs-accent"), ("accent_h", "--fs-accent-h"),
    ("accent_dim", "--fs-accent-dim"), ("accent_subtle", "--fs-accent-subtle"),
    ("accent_border", "--fs-accent-border"), ("accent_line", "--fs-accent-line"),
    ("border", "--fs-border"), ("border2", "--fs-border2"),
    ("pos", "--fs-pos"), ("neg", "--fs-neg"), ("warn", "--fs-warn"),
    ("r_sm", "--r-sm"), ("r_md", "--r-md"), ("r_lg", "--r-lg"),
    ("display", "--font-display"), ("body", "--font-sans"), ("mono", "--font-mono"),
    ("diff_left_bg", "--diff-left-bg"), ("diff_left_fg", "--diff-left-fg"),
    ("diff_right_bg", "--diff-right-bg"), ("diff_right_fg", "--diff-right-fg"),
)


def tokens_css(theme: dict[str, Any] | None = None) -> str:
    """The :root block that puts the active tokens on a page - the app and the report both start with it."""
    t = theme or THEME
    return ":root{" + ";".join(f"{var}:{t[key]}" for key, var in _CSS_VARS) + "}"


STREAMLIT_THEME = {          # what Streamlit itself draws with: grids, menus, focus rings
    "theme.base": "dark",
    "theme.primaryColor": THEME["accent"],
    "theme.backgroundColor": THEME["bg"],
    "theme.secondaryBackgroundColor": THEME["panel"],
    "theme.textColor": THEME["text"],
    "theme.font": "Inter, sans-serif",
    "theme.codeFont": "JetBrains Mono, monospace",
    "theme.headingFont": THEME["heading_font"],
    "theme.borderColor": THEME["line"],
    "theme.codeBackgroundColor": THEME["surface"],           # inline code and code blocks Streamlit draws itself
    "theme.codeTextColor": THEME["accent_h"],
    "theme.dataframeHeaderBackgroundColor": THEME["panel"],  # st.dataframe / data_editor headers
    "theme.dataframeBorderColor": THEME["line"],
    "theme.baseRadius": THEME["r_sm"],
}


def css() -> str:
    return f"""
<style>
    @import url('{FONTS}');
    {tokens_css()}
    html, body, .stApp {{
        background: var(--fs-bg); color: var(--fs-text2);
        font-family: var(--font-sans); font-weight: 400; font-size: 15.5px; line-height: 1.6;
        letter-spacing: .005em; -webkit-font-smoothing: antialiased; font-variant-numeric: tabular-nums;
    }}
    /* the sans everywhere Streamlit would use its own face; :where() keeps this rule's specificity
       at .stApp alone, so the display and mono rules below win on the elements they name */
    .stApp :where(*:not(code):not(pre):not(kbd):not(pre *):not(code *):not(svg *):not([data-testid*="Icon"]):not([data-testid*="Icon"] *):not([class*="material"])) {{ font-family: var(--font-sans) !important; }}
    /* Streamlit wraps the text of headings, metrics, tabs and buttons in its own span or p; those take
       the face and colour of the element the rules below style (the display face, the mono, the button's
       ink on the accent), not the sans above - same specificity, later in the sheet, so this one wins.
       The colour half is deliberate: a heading's own colour rule beats it, an unstyled child inherits. */
    .stApp :where(h1 *, .hero-h *, .rail-mark *, .eyebrow *, .steps *, h3 *, h4 *, [data-testid="stMetricValue"] *, [data-baseweb="tab"] *,
        .stButton button *, .stDownloadButton button *) {{ font-family: inherit !important; color: inherit; }}
    [data-testid*="Icon"], [data-testid*="Icon"] *, [class*="material-symbols"] {{ font-family: "Material Symbols Rounded" !important; }}
    [data-testid="stHeader"] {{ background: var(--fs-bg); }}
    .block-container {{ padding-top: 2.4rem; padding-bottom: 7rem; max-width: 1500px; counter-reset: sec; }}
    ::selection {{ background: var(--fs-accent-line); color: var(--fs-text); }}

    /* type */
    .eyebrow {{ font-family: var(--font-mono) !important; font-size: 10.5px; letter-spacing: .16em;
        text-transform: uppercase; color: var(--fs-text3); margin: 0 0 1.1rem; }}
    .eyebrow span {{ color: var(--fs-accent); }}
    h1, .hero-h {{ font-family: var(--font-display) !important; font-weight: 300 !important;
        font-size: clamp(34px, 4.6vw, 56px); line-height: 1.06; letter-spacing: -.018em;
        color: var(--fs-text) !important; margin: 0 0 .9rem; max-width: 22ch; }}
    h1 em, .hero-h em {{ font-style: italic; color: var(--fs-accent) !important; }}
    .hero-h [data-testid="stHeaderActionElements"] {{ display: none; }}   /* Streamlit's anchor icon would wrap the headline */
    .lede {{ max-width: 68ch; font-size: 17px; line-height: 1.66; color: var(--fs-text2); margin: 0 0 1.2rem; }}
    strong {{ font-weight: 500; color: var(--fs-text); }}
    .block-container h3 {{
        font-family: var(--font-display) !important; font-weight: 300 !important;
        font-size: clamp(25px, 3vw, 34px); line-height: 1.16; letter-spacing: -.012em;
        color: var(--fs-text); margin: 2.4rem 0 .5rem; padding-top: 2.2rem;
        border-top: 1px solid var(--fs-border); counter-increment: sec; }}
    .block-container h3::before {{
        content: counter(sec, decimal-leading-zero); display: block;
        font-family: var(--font-mono) !important; font-size: 11px; letter-spacing: .1em;
        color: var(--fs-accent); margin-bottom: .55rem; }}
    .block-container h3 em {{ font-style: italic; color: var(--fs-accent); }}
    h2 {{ font-family: var(--font-display) !important; font-weight: 300 !important; color: var(--fs-text);
        font-size: 1.6rem; letter-spacing: -.012em; }}
    h4, [data-testid="stMarkdownContainer"] h4, .stMarkdown h4 {{ font-family: var(--font-mono) !important;
        font-weight: 400 !important; font-size: 10.5px !important; letter-spacing: .14em; text-transform: uppercase;
        color: var(--fs-accent) !important; margin: 1.4rem 0 .5rem; padding: 0; }}
    p, li, label {{ color: var(--fs-text2); }}
    [data-testid="stCaptionContainer"] p {{ color: var(--fs-text3); font-size: 13.5px; line-height: 1.62; max-width: 92ch; }}
    label[data-testid="stWidgetLabel"] p {{ font-size: 13px; color: var(--fs-text2); }}
    hr {{ border: 0; border-top: 1px solid var(--fs-border); margin: 1.5rem 0; }}
    a {{ color: var(--fs-text); text-decoration: none; border-bottom: 1px solid var(--fs-accent-line); }}
    a:hover {{ border-bottom-color: var(--fs-accent); }}
    code {{ font-family: var(--font-mono) !important; font-size: .88em; background: var(--fs-surface);
        border: 1px solid var(--fs-border); padding: 1px 5px; border-radius: 3px; color: var(--fs-accent-h); }}
    [data-testid="stCode"] pre, pre {{ background: var(--fs-panel) !important; border: 1px solid var(--fs-line); border-radius: var(--r-sm); }}
    [data-testid="stCode"] code, pre code {{ background: none; border: 0; color: var(--fs-text2); }}

    /* sidebar: the rail */
    section[data-testid="stSidebar"] {{ background: var(--fs-bg); border-right: 1px solid var(--fs-border); }}
    section[data-testid="stSidebar"] > div {{ padding-top: 2.6rem; }}
    .rail-mark {{ font-family: var(--font-display) !important; font-size: 21px; color: var(--fs-text); letter-spacing: .01em; }}
    .rail-mark em {{ font-style: italic; color: var(--fs-accent); }}
    .rail-sub {{ font-family: var(--font-mono) !important; font-size: 10.5px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--fs-text3); margin: .2rem 0 1.6rem; }}
    section[data-testid="stSidebar"] hr {{ margin: 1.2rem 0; }}

    /* widgets */
    div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"],
    div[data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] {{
        background: var(--fs-panel) !important; border-color: var(--fs-line) !important;
        border-radius: var(--r-sm) !important; color: var(--fs-text) !important; }}
    div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
    div[data-baseweb="select"] > div:focus-within, [data-testid="stNumberInputContainer"]:focus-within {{
        border-color: var(--fs-accent-line) !important; box-shadow: none !important; }}
    input, textarea {{ color: var(--fs-text) !important; font-weight: 400; }}
    ::placeholder {{ color: var(--fs-text3) !important; opacity: 1; }}
    ul[data-baseweb="menu"] {{ background: var(--fs-panel) !important; border: 1px solid var(--fs-line); }}
    ul[data-baseweb="menu"] li {{ color: var(--fs-text2) !important; }}
    ul[data-baseweb="menu"] li[aria-selected="true"], ul[data-baseweb="menu"] li:hover {{ background: var(--fs-surface) !important; color: var(--fs-text) !important; }}
    label[data-baseweb="checkbox"] > span:first-of-type {{ border-radius: 3px !important; border-color: var(--fs-line) !important; background: var(--fs-panel) !important; }}
    label[data-baseweb="checkbox"]:has(input:checked) > span:first-of-type {{ background: var(--fs-accent) !important; border-color: var(--fs-accent) !important; }}
    label[data-baseweb="radio"] > div:first-of-type {{ border-color: var(--fs-line) !important; background: var(--fs-panel) !important; }}
    label[data-baseweb="radio"]:has(input:checked) > div:first-of-type {{ border-color: var(--fs-accent) !important; }}
    label[data-baseweb="radio"]:has(input:checked) > div:first-of-type > div {{ background: var(--fs-accent) !important; }}
    span[data-baseweb="tag"] {{ background: var(--fs-surface) !important; color: var(--fs-accent) !important;
        border: 1px solid var(--fs-accent-line) !important; border-radius: 100px !important; }}
    span[data-baseweb="tag"] span {{ font-family: var(--font-mono) !important; font-size: 11px !important; color: var(--fs-accent) !important; }}
    span[data-baseweb="tag"] svg {{ fill: var(--fs-accent) !important; color: var(--fs-accent) !important; }}
    [data-baseweb="slider"] [role="slider"] {{ background: var(--fs-accent) !important; border-color: var(--fs-accent) !important; }}
    [data-testid="stSliderThumbValue"] {{ color: var(--fs-accent) !important; }}
    [data-testid="stFileUploaderDropzone"] {{ background: var(--fs-panel) !important;
        border: 1px dashed var(--fs-line) !important; border-radius: var(--r-sm) !important; }}
    [data-testid="stFileUploaderDropzone"] small, [data-testid="stFileUploaderDropzone"] span {{ color: var(--fs-text3) !important; }}

    /* buttons: the reference's pills - descendant selectors, since a button with help= sits inside a tooltip wrapper */
    .stButton button, .stDownloadButton button, [data-testid="stFileUploaderDropzone"] button {{
        font-family: var(--font-mono) !important; font-size: 10.5px !important; letter-spacing: .12em;
        text-transform: uppercase; border-radius: 100px !important; border: 1px solid var(--fs-line) !important;
        background: transparent !important; color: var(--fs-text2) !important; min-height: 0;
        padding: .5rem 1rem; transition: border-color .15s, color .15s; }}
    .stButton button:hover, .stDownloadButton button:hover {{ border-color: var(--fs-accent) !important; color: var(--fs-text) !important; }}
    .stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {{
        background: var(--fs-accent) !important; border-color: var(--fs-accent) !important; color: var(--fs-bg) !important; font-weight: 500 !important; }}
    .stButton button[kind="primary"]:hover, .stDownloadButton button[kind="primary"]:hover {{
        background: var(--fs-text) !important; border-color: var(--fs-text) !important; }}
    .stButton button:disabled, .stDownloadButton button:disabled {{ opacity: .35; }}
    .stButton [data-testid="stTooltipIcon"], .stButton [data-testid="stTooltipHoverTarget"] {{ width: 100%; }}   /* a button with help= still fills its column */
    .stButton button p, .stDownloadButton button p {{ word-break: normal; overflow-wrap: normal; }}

    /* metrics, tabs, expanders, tables */
    [data-testid="stMetric"] {{ background: var(--fs-panel); border: 1px solid var(--fs-line); border-radius: var(--r-sm); padding: .85rem 1rem; }}
    [data-testid="stMetricLabel"] p {{ font-family: var(--font-mono) !important; font-size: 10px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--fs-text3); }}
    [data-testid="stMetricValue"] {{ font-family: var(--font-display) !important; font-weight: 300 !important;
        font-size: 2rem; color: var(--fs-text); letter-spacing: -.01em; }}
    .stTabs [data-baseweb="tab"] {{ font-family: var(--font-mono) !important; font-size: 10.5px !important;
        letter-spacing: .13em; text-transform: uppercase; color: var(--fs-text3) !important; padding-bottom: .6rem; }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{ color: var(--fs-text) !important; }}
    .stTabs [data-baseweb="tab-highlight"] {{ background: var(--fs-accent); height: 1px; }}
    .stTabs [data-baseweb="tab-border"] {{ background: var(--fs-line); }}
    [data-testid="stExpander"] {{ border: 1px solid var(--fs-line); border-radius: var(--r-sm); background: var(--fs-panel); }}
    [data-testid="stExpander"] summary {{ background: var(--fs-surface); }}
    [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{ font-weight: 500; font-size: 14px; color: var(--fs-text); }}
    [data-testid="stExpander"] summary:hover p {{ color: var(--fs-accent); }}
    div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{ border: 1px solid var(--fs-line); border-radius: var(--r-sm); overflow: hidden; }}
    [data-testid="stStatusWidget"], [data-testid="stSpinner"] {{ color: var(--fs-text3); }}
    [data-testid="stProgress"] > div > div > div {{ background: var(--fs-accent) !important; }}

    /* alerts as the reference's notes */
    [data-testid="stAlert"], [data-testid="stAlert"] > div {{ background: var(--fs-panel) !important;
        border-radius: 0 var(--r-sm) var(--r-sm) 0 !important; color: var(--fs-text2) !important; }}
    [data-testid="stAlert"] {{ border: 1px solid var(--fs-border); border-left: 2px solid var(--fs-accent-line) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{ border-left-color: var(--fs-neg) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{ border-left-color: var(--fs-accent) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{ border-left-color: var(--fs-pos) !important; }}
    [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) {{ border-left-color: var(--fs-accent-h) !important; }}
    [data-testid="stAlert"] p {{ font-size: 14px; line-height: 1.6; color: var(--fs-text2) !important; }}
    [data-testid="stAlert"] svg {{ display: none; }}

    /* run sheet panels: the status strip, the setup card, the verdict */
    .strip {{ display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid var(--fs-line);
        border-radius: var(--r-sm); background: var(--fs-panel); margin: 1.4rem 0 2rem; overflow: hidden; }}
    .strip > div {{ padding: .85rem 1.1rem; border-right: 1px solid var(--fs-border); min-width: 0; }}
    .strip > div:last-child {{ border-right: 0; }}
    .strip .k, .card .k {{ font-family: var(--font-mono) !important; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--fs-accent); }}
    .strip .v {{ font-size: 14px; color: var(--fs-text); margin-top: .3rem; font-weight: 400; overflow-wrap: anywhere; }}
    .ok {{ color: var(--fs-pos) !important; }} .warn {{ color: var(--fs-accent) !important; }} .bad {{ color: var(--fs-neg) !important; }}
    .card {{ border: 1px solid var(--fs-line); border-radius: var(--r-sm); background: var(--fs-panel); margin: .6rem 0 1.2rem; overflow: hidden; }}
    .card .row {{ display: grid; grid-template-columns: 11rem 1fr; gap: 0 1rem; padding: .7rem 1.1rem;
        border-bottom: 1px solid var(--fs-border); font-size: 14px; }}
    .card .row:last-child {{ border-bottom: 0; }}
    .card .row .v {{ color: var(--fs-text); overflow-wrap: anywhere; }}
    .card .row .v code {{ font-size: 12px; }}
    .card .row .m {{ color: var(--fs-text3); }}
    .verdict {{ border-left: 2px solid var(--fs-accent-line); background: var(--fs-panel); padding: 1rem 1.2rem;
        border-radius: 0 var(--r-sm) var(--r-sm) 0; margin: .4rem 0 1.4rem; font-size: 14.5px; color: var(--fs-text2); line-height: 1.7; }}
    .verdict .t {{ display: block; font-family: var(--font-mono) !important; font-size: 10px; letter-spacing: .14em;
        text-transform: uppercase; color: var(--fs-accent); margin-bottom: .45rem; }}
    .verdict.ok {{ border-left-color: var(--fs-pos); }} .verdict.ok .t {{ color: var(--fs-pos); }}
    .verdict.warn {{ border-left-color: var(--fs-accent); }}
    .verdict.bad {{ border-left-color: var(--fs-neg); }} .verdict.bad .t {{ color: var(--fs-neg); }}
    .verdict b {{ font-family: var(--font-display) !important; font-weight: 400; font-size: 1.3rem; color: var(--fs-text); }}
    .steps {{ font-family: var(--font-mono) !important; font-size: 12px; color: var(--fs-text2); line-height: 1.9; }}
    .steps .n {{ color: var(--fs-warn); margin-right: .6rem; }}
    .steps .arrow {{ color: var(--fs-text3); margin: 0 .5rem; }}
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
