# tests/conftest.py
"""What every API test shares: the sample paths and counts, the fake password, a page on temp
folders that reads none of the user's own env (isolated_env), its workspace (ws_of) and a plain
client `c`. webkit and webflow build their clients on isolated_env and add their connections."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
W = {"X-Compare": "1"}
FAKE_PW = "example-not-a-real-password"
COUNTS = dict(t.split("=") for t in (ROOT / "tests/COUNTS.md").read_text(encoding="utf-8").split()
              if "=" in t)            # matched=... only_left=... only_right=... diff_rows=... cells=... key=...


def isolated_env(monkeypatch, tmp_path):
    """Work, output and connections under tmp_path, and no COMPARE_* setting of the developer's."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


@pytest.fixture
def c(tmp_path, monkeypatch):
    isolated_env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client
