"""The house style. Every colour, font and limit is here and nowhere else - and the app's name.

This is the Crosshire apps theme: the same tokens the web apps carry as --fs-* variables,
in three flavours, each with a light and a dark mode. `paper` (warm paper, burnt amber accent,
Fraunces headlines on IBM Plex) is the default and opens light; `aurora` (warm dark, amber accent)
and `violet` (cool dark, indigo accent, Inter throughout) open dark. The page's Light / Dark
button flips the mode; with no choice saved it follows the system setting, as the report does.
Pick a flavour with an environment variable before starting; anything unknown falls back to paper:

    set COMPARE_THEME=violet                     (Windows)
    export COMPARE_THEME=violet                  (macOS / Linux)

The name is the other thing you are likely to change per deployment. Either edit APP_NAME
below, or leave the code alone and set an environment variable before starting:

    set COMPARE_APP_NAME=Employee Table Check    (Windows)
    export COMPARE_APP_NAME="Employee Table Check"   (macOS / Linux)

It shows in the browser tab, the sidebar mark, the page header and the report.

What the rest of the app reads from here: THEME (the active token dict), THEMES (paper, aurora and violet), THEME_LIGHT (the active one's light mode),
tokens_css() (the :root block that puts the tokens on the page), FONTS (the Google Fonts
URL), esc(), APP_NAME, APP_TAGLINE and CELL_BUDGET.
"""
from __future__ import annotations

import os
from typing import Any

APP_NAME = os.environ.get("COMPARE_APP_NAME", "CrossHire Compare").strip() or "CrossHire Compare"
APP_TAGLINE = os.environ.get("COMPARE_APP_TAGLINE", "Tables, side by side").strip()
CELL_BUDGET = 150_000        # the report shows at most this many cells per row table, whatever the row cap


# Self-contained files (the report and the page) load the fonts from Google: paper's below, the
# older flavours' in _OLD_FONTS.
_OLD_FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;"
         "0,9..144,600;1,9..144,300;1,9..144,400&family=Inter:ital,wght@0,300;0,400;0,500;0,600;1,400"
         "&family=JetBrains+Mono:ital,wght@0,400;0,500;1,400&display=swap")

_SHARED = {                  # the same in both themes
    "r_sm": "6px", "r_md": "12px", "r_lg": "18px",
    "body": '"Inter", system-ui, -apple-system, sans-serif',
    "mono": '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
}

PAPER_FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;"
               "1,9..144,400&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap")

_SHARED_PAPER = {
    "r_sm": "6px", "r_md": "10px", "r_lg": "18px",
    "body": '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif',
    "mono": '"IBM Plex Mono", ui-monospace, Menlo, monospace',
    "display": '"Fraunces", Georgia, serif',
}

PAPER_LIGHT: dict[str, Any] = {            # the default look: warm paper, burnt amber accent
    **_SHARED_PAPER,
    "bg": "#F6F4EF", "panel": "#FFFFFF", "surface": "#FAF8F4", "surface2": "#F0ECE3",
    "line": "#E4DFD5", "border": "#EDE9E0", "border2": "#CFC8BA",
    "text": "#1B1915", "text2": "#4B463D", "text3": "#6E675B", "text4": "#9A9385",
    "accent": "#9A5A1A", "accent_h": "#7A4712",
    "accent_dim": "rgba(154,90,26,0.12)", "accent_subtle": "rgba(154,90,26,0.06)",
    "accent_border": "rgba(154,90,26,0.28)", "accent_line": "rgba(154,90,26,0.32)",
    "pos": "#1E6B3E", "neg": "#B6412E", "warn": "#9A6B13",
    # the report's existing diff classes: left = side A, right = side B, both on the diff tint
    "diff_left_bg": "#FFF1E0", "diff_left_fg": "#1D4F91",
    "diff_right_bg": "#FFF1E0", "diff_right_fg": "#8F4A12",
    # new keys
    "accent_fill": "#F2B277", "accent_edge": "#DE9450", "accent_bg": "#FBEBDC",
    "side_a": "#1D4F91", "side_a_bg": "#E6EEF8", "side_a_edge": "#B9CCE8",
    "side_b": "#8F4A12", "side_b_bg": "#FBEBDC", "side_b_edge": "#EFCBA2",
    "pos_bg": "#E6F3EA", "pos_dot": "#2E8B57", "neg_bg": "#FBE9E5",
    "warn_bg": "#FBF2DC", "warn_dot": "#D4A24C",
    "diff_bg": "#FFF1E0", "diff_edge": "#F3D9B4",
    "bar_ok": "#3F9D6B", "bar_good": "#7FB069", "bar_warn": "#E0A24A",
    "out_full": "#3F9D6B", "out_diff": "#E0A24A", "out_a": "#3B6FC0", "out_b": "#8E5B3A",
    "on_fill": "#1B1915", "on_badge": "#FFFFFF",      # text on the accent fill, on the A / B badges
    # shadows, the drawer's backdrop, a count on a dark or an accent button
    "shadow": "rgba(0,0,0,0.12)", "shadow_lg": "rgba(0,0,0,0.14)", "scrim": "rgba(0,0,0,0.22)",
    "count_dark": "rgba(127,127,127,0.25)", "count_fill": "rgba(27,25,21,0.12)",
}

PAPER_DARK: dict[str, Any] = {             # the same design on aurora's dark ground
    **_SHARED_PAPER,
    "bg": "#0E0D0B", "panel": "#17150F", "surface": "#1F1C14", "surface2": "#2A261C",
    "line": "#2A261C", "border": "#221F17", "border2": "#3A3527",
    "text": "#F4EAD6", "text2": "#B8AD94", "text3": "#9A8F74", "text4": "#5C5440",
    "accent": "#F4B87C", "accent_h": "#F6C48D",
    "accent_dim": "rgba(244,184,124,0.12)", "accent_subtle": "rgba(244,184,124,0.06)",
    "accent_border": "rgba(244,184,124,0.25)", "accent_line": "rgba(244,184,124,0.28)",
    "pos": "#7FB069", "neg": "#E08A7C", "warn": "#D4A24C",
    "diff_left_bg": "rgba(224,162,74,0.16)", "diff_left_fg": "#8FB4EC",
    "diff_right_bg": "rgba(224,162,74,0.16)", "diff_right_fg": "#F0B48A",
    "accent_fill": "#F4B87C", "accent_edge": "#E39A55", "accent_bg": "rgba(244,184,124,0.14)",
    "side_a": "#8FB4EC", "side_a_bg": "rgba(61,111,192,0.18)", "side_a_edge": "rgba(61,111,192,0.40)",
    "side_b": "#F0B48A", "side_b_bg": "rgba(201,116,58,0.18)", "side_b_edge": "rgba(201,116,58,0.40)",
    "pos_bg": "rgba(127,176,105,0.16)", "pos_dot": "#7FB069", "neg_bg": "rgba(201,112,100,0.16)",
    "warn_bg": "rgba(212,162,76,0.16)", "warn_dot": "#D4A24C",
    "diff_bg": "rgba(224,162,74,0.16)", "diff_edge": "rgba(224,162,74,0.35)",
    "bar_ok": "#3F9D6B", "bar_good": "#7FB069", "bar_warn": "#E0A24A",
    "out_full": "#3F9D6B", "out_diff": "#E0A24A", "out_a": "#5A8DE0", "out_b": "#B07A4F",
    "on_fill": "#1B1915", "on_badge": "#FFFFFF",
    "shadow": "rgba(0,0,0,0.40)", "shadow_lg": "rgba(0,0,0,0.50)", "scrim": "rgba(0,0,0,0.55)",
    "count_dark": "rgba(127,127,127,0.25)", "count_fill": "rgba(27,25,21,0.12)",
}

# the paper tokens the older flavours lacked, as CSS custom properties
EXTRA_VARS = (
    ("accent_fill", "--fs-accent-fill"), ("accent_edge", "--fs-accent-edge"), ("accent_bg", "--fs-accent-bg"),
    ("side_a", "--fs-side-a"), ("side_a_bg", "--fs-side-a-bg"), ("side_a_edge", "--fs-side-a-edge"),
    ("side_b", "--fs-side-b"), ("side_b_bg", "--fs-side-b-bg"), ("side_b_edge", "--fs-side-b-edge"),
    ("pos_bg", "--fs-pos-bg"), ("pos_dot", "--fs-pos-dot"), ("neg_bg", "--fs-neg-bg"),
    ("warn_bg", "--fs-warn-bg"), ("warn_dot", "--fs-warn-dot"),
    ("diff_bg", "--fs-diff-bg"), ("diff_edge", "--fs-diff-edge"),
    ("bar_ok", "--fs-bar-ok"), ("bar_good", "--fs-bar-good"), ("bar_warn", "--fs-bar-warn"),
    ("out_full", "--fs-out-full"), ("out_diff", "--fs-out-diff"), ("out_a", "--fs-out-a"), ("out_b", "--fs-out-b"),
    ("on_fill", "--fs-on-fill"), ("on_badge", "--fs-on-badge"),
    ("shadow", "--fs-shadow"), ("shadow_lg", "--fs-shadow-lg"), ("scrim", "--fs-scrim"),
    ("count_dark", "--fs-count-dark"), ("count_fill", "--fs-count-fill"),
)

THEMES: dict[str, dict[str, Any]] = {
    "paper": PAPER_DARK,     # the same design on a dark ground; its light mode (the default) is LIGHT["paper"]
    "aurora": {              # warm dark, amber accent
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
        "diff_left_bg": "#3a2330", "diff_left_fg": "#f3cdc4",
        "diff_right_bg": "#e6c3cf", "diff_right_fg": "#3a2330",
    },
}

# each flavour's light mode: the same accent family, darkened until it reads on paper
LIGHT: dict[str, dict[str, Any]] = {
    "paper": PAPER_LIGHT,
    "aurora": {              # warm paper, burnt amber
        "bg": "#faf6ee", "panel": "#f3ecdf", "surface": "#ebe2d0", "surface2": "#e0d5bf",
        "line": "#ddd1b9",
        "text": "#1f1a10", "text2": "#4a4130", "text3": "#7a6e55", "text4": "#a89a7c",
        "accent": "#a85a17", "accent_h": "#8f4c12",
        "accent_dim": "rgba(168,90,23,0.12)", "accent_subtle": "rgba(168,90,23,0.06)",
        "accent_border": "rgba(168,90,23,0.28)", "accent_line": "rgba(168,90,23,0.32)",
        "border": "rgba(168,90,23,0.12)", "border2": "rgba(168,90,23,0.2)",
        "pos": "#3f7a32", "neg": "#b0473b", "warn": "#94650f",
        "diff_left_bg": "#f6d9d3", "diff_left_fg": "#5a1f18",
        "diff_right_bg": "#5a2a24", "diff_right_fg": "#f8e3dc",
    },
    "violet": {              # cool paper, deep indigo
        "bg": "#f7f7fb", "panel": "#efeff7", "surface": "#e6e6f2", "surface2": "#dadaeb",
        "line": "#d6d6e8",
        "text": "#16162a", "text2": "#3e3e60", "text3": "#6a6a90", "text4": "#9a9abb",
        "accent": "#5443cf", "accent_h": "#4536b3",
        "accent_dim": "rgba(84,67,207,0.12)", "accent_subtle": "rgba(84,67,207,0.06)",
        "accent_border": "rgba(84,67,207,0.28)", "accent_line": "rgba(84,67,207,0.32)",
        "border": "rgba(84,67,207,0.12)", "border2": "rgba(84,67,207,0.2)",
        "pos": "#2f7d55", "neg": "#b0473b", "warn": "#866611",
        "diff_left_bg": "#f3d8dc", "diff_left_fg": "#4a1f2a",
        "diff_right_bg": "#4a2a36", "diff_right_fg": "#f6e2e8",
    },
}

# aurora and violet predate the paper tokens (the side colours, tints, bars): they borrow paper's
for _name in ("aurora", "violet"):
    for _k, _ in EXTRA_VARS:
        THEMES[_name].setdefault(_k, PAPER_DARK[_k])
        LIGHT[_name].setdefault(_k, PAPER_LIGHT[_k])

DEFAULT_MODE = {"paper": "light", "aurora": "dark", "violet": "dark"}   # the mode a flavour opens in

THEME_NAME = os.environ.get("COMPARE_THEME", "paper").strip().lower()
if THEME_NAME not in THEMES:
    THEME_NAME = "paper"
THEME = THEMES[THEME_NAME]   # the active tokens (the dark mode) - everything else reads from this
THEME_LIGHT = {**THEME, **LIGHT[THEME_NAME]}     # the light mode: the same fonts, other colours
MODE = DEFAULT_MODE[THEME_NAME]
FONTS = PAPER_FONTS if THEME_NAME == "paper" else _OLD_FONTS

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
) + EXTRA_VARS


def _vars(t: dict[str, Any]) -> str:
    return ";".join(f"{var}:{t[key]}" for key, var in _CSS_VARS)


def tokens_css(theme: dict[str, Any] | None = None, light_when: str = "", dark_when: str = "") -> str:
    """The :root block that puts the active tokens on a page - the app and the report both start
    with it. The flavour's own mode (MODE: light for paper, dark for the others) is the default;
    `light_when` / `dark_when` are the selectors under which each mode's tokens take over: the page
    marks its <html data-fs-mode>, the report passes "media" to follow the reader's system setting."""
    if theme is not None:
        return ":root{" + _vars(theme) + "}"
    out = ":root{" + _vars(THEME_LIGHT if MODE == "light" else THEME) + "}"
    for when, t, scheme in ((light_when, THEME_LIGHT, "light"), (dark_when, THEME, "dark")):
        if when == "media":
            out += f"@media (prefers-color-scheme: {scheme})" + "{:root{" + _vars(t) + "}}"
        elif when:
            out += when + "{" + _vars(t) + "}"
    return out


def esc(x: Any) -> str:
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
