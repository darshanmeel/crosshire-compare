"""The READMEs describe the page as it is: started with python compare_app.py
on 8501, built with FastAPI and React, tested over HTTP and in a browser - no Streamlit left."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_no_streamlit_left_in_the_docs():
    for name in ("README.md", "README.html"):
        text = _read(name)
        assert not re.search(r"streamlit|AppTest|_stcore|COMPARE_UPLOAD_MB|session_state", text, re.I), name


def test_both_readmes_say_how_to_start_and_test():
    for name in ("README.md", "README.html"):
        text = _read(name)
        for must in ("python compare_app.py", "8501", "COMPARE_WEB_PORT", "COMPARE_ALLOWED_HOSTS",
                     "requirements-dev.txt", "python -m playwright install chromium", "npm run build",
                     "/api/health", "tests/webflow.py"):
            assert must in text, (name, must)
