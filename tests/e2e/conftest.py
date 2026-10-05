"""The browser runs: one real server on a free port with temp folders, and a clean skip when
Playwright or its Chromium is not installed (see helpers.INSTALL)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from tests.e2e.helpers import EX, FAKE_PW, browser_missing

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def _need_a_browser():
    why = browser_missing()
    if why:
        pytest.skip(why)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """The page in its own process, so its environment cannot leak into the tests that run after it."""
    tmp = tmp_path_factory.mktemp("e2e")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("COMPARE_CONN") and k not in ("COMPARE_DATA_DIR", "COMPARE_WEB_PORT")}
    env.update({
        "COMPARE_WORK_DIR": str(tmp / "work"),
        "COMPARE_OUT_DIR": str(tmp / "out"),
        "COMPARE_CONNECTIONS": str(tmp / "connections.json"),
        "COMPARE_CONN_SAMPLE": "duckdb:///" + (EX / "sample.duckdb").as_posix(),
        "COMPARE_CONN_FAKE": f"postgresql://u:{FAKE_PW}@nowhere:5432/db",
    })
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "tablecmp.web", "--no-browser", "--port", str(port)],
                            env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while True:
            assert proc.poll() is None and time.time() - t0 < 60, "the server did not start"
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        yield {"url": f"http://127.0.0.1:{port}", "out": tmp / "out", "work": tmp / "work"}
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
