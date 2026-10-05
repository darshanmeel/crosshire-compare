"""The `paper` flavour for tablecmp/theme.py - phase 0.1 of design/PLAN.md.

How to apply (keep aurora and violet as they are; they become the dark looks people can still pick):

1. Paste PAPER_DARK into THEMES as THEMES["paper"] and PAPER_LIGHT into LIGHT as LIGHT["paper"].
   Both carry _SHARED's keys already, so no ** _SHARED is needed; the new keys are listed in
   EXTRA_VARS - append those tuples to _CSS_VARS so tokens_css() emits them. aurora and violet
   need the same keys: add DARK_EXTRA_FALLBACK / LIGHT_EXTRA_FALLBACK to them (one line each:
   THEMES["aurora"].update(...)) so their :root blocks stay complete.
2. FONTS -> PAPER_FONTS. The report inherits it.
3. Default flavour: THEME_NAME falls back to "paper", not "aurora".
4. Default mode: paper is light-first. Replace tokens_css() with tokens_css_v2() below (same
   signature plus `default_mode`), and in app.py serve
       theme.tokens_css_v2(light_when=':root[data-fs-mode="light"]', dark_when=':root[data-fs-mode="dark"]')
   The page's ModeToggle reads the starting mode from /api/meta ("mode": DEFAULT_MODE[THEME_NAME])
   instead of assuming "dark". The report keeps `light_when="media"` semantics: for paper it is
   light by default and dark under `prefers-color-scheme: dark`.
5. tests: tests/test_web_meta.py and tests/test_no_streamlit.py grep /theme.css for `--fs-bg:`
   and the light selector - both still hold. Add one assertion that `--fs-side-a:` is present.
"""
from __future__ import annotations

from typing import Any

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
}

# Append to theme._CSS_VARS so the new keys reach the page.
EXTRA_VARS = (
    ("accent_fill", "--fs-accent-fill"), ("accent_edge", "--fs-accent-edge"), ("accent_bg", "--fs-accent-bg"),
    ("side_a", "--fs-side-a"), ("side_a_bg", "--fs-side-a-bg"), ("side_a_edge", "--fs-side-a-edge"),
    ("side_b", "--fs-side-b"), ("side_b_bg", "--fs-side-b-bg"), ("side_b_edge", "--fs-side-b-edge"),
    ("pos_bg", "--fs-pos-bg"), ("pos_dot", "--fs-pos-dot"), ("neg_bg", "--fs-neg-bg"),
    ("warn_bg", "--fs-warn-bg"), ("warn_dot", "--fs-warn-dot"),
    ("diff_bg", "--fs-diff-bg"), ("diff_edge", "--fs-diff-edge"),
    ("bar_ok", "--fs-bar-ok"), ("bar_good", "--fs-bar-good"), ("bar_warn", "--fs-bar-warn"),
    ("out_full", "--fs-out-full"), ("out_diff", "--fs-out-diff"), ("out_a", "--fs-out-a"), ("out_b", "--fs-out-b"),
)

# aurora / violet lack the new keys: give them sensible values so every flavour emits a full block.
DARK_EXTRA_FALLBACK = {k: PAPER_DARK[k] for k, _ in EXTRA_VARS}
LIGHT_EXTRA_FALLBACK = {k: PAPER_LIGHT[k] for k, _ in EXTRA_VARS}

DEFAULT_MODE = {"paper": "light", "aurora": "dark", "violet": "dark"}


def tokens_css_v2(theme_dark: dict[str, Any], theme_light: dict[str, Any], css_vars, *,
                  default_mode: str = "light", light_when: str = "", dark_when: str = "") -> str:
    """Like theme.tokens_css(): the :root block plus the other mode under its selector - but the
    default mode is a parameter. `css_vars` is theme._CSS_VARS (+ EXTRA_VARS). For the report pass
    light_when="media" / dark_when="media" to follow the reader's system setting."""
    def block(t: dict[str, Any]) -> str:
        return ";".join(f"{var}:{t[key]}" for key, var in css_vars)

    first, other = (theme_light, theme_dark) if default_mode == "light" else (theme_dark, theme_light)
    other_when = dark_when if default_mode == "light" else light_when
    scheme = "dark" if default_mode == "light" else "light"
    out = ":root{" + block(first) + "}"
    if other_when == "media":
        out += f"@media (prefers-color-scheme: {scheme})" + "{:root{" + block(other) + "}}"
    elif other_when:
        out += other_when + "{" + block(other) + "}"
    return out
