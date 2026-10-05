"""What the page needs before anything else: the names, the theme's tokens, the connection form."""
from fastapi.testclient import TestClient

from tablecmp.connections import KINDS
from tablecmp.web.app import create_app


def test_theme_css_holds_both_modes_and_the_fonts():
    r = TestClient(create_app()).get("/theme.css")
    assert r.headers["content-type"].startswith("text/css")
    css = r.text
    assert css.startswith("@import url(") and "--fs-bg:" in css and ':root[data-fs-mode="light"]' in css
    assert ':root[data-fs-mode="dark"]' in css and css.count("--fs-side-a:") == 3     # the default, light, dark


def test_paper_opens_light_and_every_flavour_has_the_paper_tokens():
    from tablecmp import theme
    assert theme.THEME_NAME == "paper" and theme.MODE == "light" and "IBM+Plex+Sans" in theme.FONTS
    for name in theme.THEMES:
        for t in (theme.THEMES[name], {**theme.THEMES[name], **theme.LIGHT[name]}):
            assert all(k in t for k, _ in theme._CSS_VARS), name
    report = theme.tokens_css(light_when="media", dark_when="media")
    assert report.startswith(":root{--fs-bg:#F6F4EF") and "@media (prefers-color-scheme: dark)" in report


def test_meta_gives_names_kinds_and_the_form():
    m = TestClient(create_app()).get("/api/meta").json()
    assert m["app_name"] and m["kinds"] == KINDS
    assert m["form"]["fields"]["folder"] == ["host"] and "token" in m["form"]["secret_extras"]
    assert m["form"]["host_label"]["folder"] == "Folder path" and isinstance(m["filepick"], bool)
    assert m["mode"] == "light" and m["examples"]["A"].endswith("hr_employees.csv")
