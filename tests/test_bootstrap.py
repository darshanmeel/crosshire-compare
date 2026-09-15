# tests/test_bootstrap.py
"""`python compare_app.py`: the settings it starts the server with - the upload cap, usage stats,
the theme and the STREAMLIT_* variables - are applied before the server is built."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Runs the real __main__ block; only bootstrap.run is stubbed, to report what the server would
# have been built with instead of building it.
STUB = """
import json, runpy, sys
from streamlit import config
from streamlit.web import bootstrap
def fake_run(path, is_hello, args, flag_options, **kw):
    keys = ("server.maxUploadSize", "browser.gatherUsageStats", "server.headless", "server.port",
            "server.address", "logger.level", "theme.primaryColor", "theme.base", "client.allowedOrigins")
    print("SETTINGS " + json.dumps({k: [config.get_option(k), config.get_where_defined(k)] for k in keys}))
bootstrap.run = fake_run
try:
    runpy.run_path(sys.argv[1], run_name="__main__")
except SystemExit:
    pass
"""


def _start(env: dict) -> dict:
    proc = subprocess.run([sys.executable, "-c", STUB, str(ROOT / "compare_app.py")],
                          env={**os.environ, **env}, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("SETTINGS ")]
    assert lines, proc.stdout + proc.stderr
    return json.loads(lines[-1][len("SETTINGS "):])


def test_python_start_applies_the_settings():
    got = _start({"COMPARE_UPLOAD_MB": "4096", "STREAMLIT_SERVER_HEADLESS": "true",
                  "STREAMLIT_SERVER_PORT": "8597", "STREAMLIT_LOGGER_LEVEL": "warning",
                  "STREAMLIT_CLIENT_ALLOWED_ORIGINS": "https://a.example https://b.example"})
    flag = "command-line argument or environment variable"
    assert got["server.maxUploadSize"] == [4096, flag]        # not Streamlit's 200 MB default
    assert got["browser.gatherUsageStats"] == [False, flag]
    assert got["theme.primaryColor"][1] == flag and got["theme.base"] == ["dark", flag]
    assert got["server.headless"] == [True, flag]              # typed as the `streamlit` command types them
    assert got["server.port"] == [8597, flag]
    assert got["logger.level"] == ["warning", flag]
    assert got["client.allowedOrigins"] == [["https://a.example", "https://b.example"], flag]


def test_python_start_default_cap_and_env_absent():
    env = {k: v for k, v in os.environ.items() if not k.startswith("STREAMLIT_") and k != "COMPARE_UPLOAD_MB"}
    proc = subprocess.run([sys.executable, "-c", STUB, str(ROOT / "compare_app.py")],
                          env=env, capture_output=True, text=True, timeout=120)
    got = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("SETTINGS ")][-1][9:])
    assert got["server.maxUploadSize"][0] == 4096              # THEME["upload_mb"]
    assert got["server.port"][1] == "<default>" and got["logger.level"][1] == "<default>"
