"""After the switch: no Streamlit anywhere - not imported, not required, not locked - none of the
modules that went with it imported in any form, and every module under tablecmp/ imports with
Streamlit blocked."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve()
SOURCES = [ROOT / "compare_app.py", *(ROOT / "tablecmp").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]
GONE = [
    re.compile(r"^\s*(import|from)\s+streamlit\b", re.M),
    re.compile(r"\bstreamlit\.(testing|web|runtime|config)\b"),
    re.compile(r"^\s*from\s+(tablecmp|\.)\s+import\s+[^\n]*\b(ui_[a-z]+|state)\b", re.M),
    re.compile(r"^\s*from\s+(tablecmp\.|\.)(ui_[a-z]+|state)\s+import\b", re.M),
    re.compile(r"\btablecmp\.(ui_[a-z]+|state)\b"),
    re.compile(r"\btests\.test_(apptest|ui_log|ui_results|bootstrap)\b"),
    re.compile(r"\bAppTest\.from_file\b"),
    re.compile(r"\.style\.apply\b|\bStyler\b"),          # pandas' Styler needs jinja2, which only Streamlit brought
]


def test_the_streamlit_modules_are_gone():
    left = sorted(p.name for p in (ROOT / "tablecmp").glob("ui_*.py")) + \
        (["state.py"] if (ROOT / "tablecmp" / "state.py").exists() else [])
    assert left == [], left


def test_nothing_imports_them_in_any_form():
    hits = []
    for p in SOURCES:
        if p == HERE or "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        hits += [f"{p.relative_to(ROOT)}: {rx.pattern}" for rx in GONE if rx.search(text)]
    assert hits == [], "\n".join(hits)


def test_streamlit_is_not_required_or_locked():
    for name in ("requirements.txt", "requirements.lock", "requirements-dev.txt"):
        lines = (ROOT / name).read_text(encoding="utf-8").lower().splitlines()
        assert not [ln for ln in lines if ln.strip().startswith("streamlit")], name


def test_every_module_imports_without_streamlit():
    code = ("import sys, importlib, pkgutil\n"
            "sys.modules['streamlit'] = None\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import tablecmp, compare_app\n"
            "for m in pkgutil.walk_packages(tablecmp.__path__, 'tablecmp.'):\n"
            "    importlib.import_module(m.name)\n"
            "print('ok')\n")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert proc.stdout.strip().endswith("ok"), proc.stderr


def test_the_theme_keeps_the_tokens_and_drops_the_streamlit_half():
    from tablecmp import theme
    for gone in ("STREAMLIT_THEME", "MODE_JS", "css", "status_strip"):
        assert not hasattr(theme, gone), gone
    assert "upload_mb" not in theme.THEME
    assert "--fs-bg:" in theme.tokens_css() and theme.FONTS.startswith("https://fonts.googleapis.com/")
