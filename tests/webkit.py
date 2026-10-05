# tests/webkit.py
"""What the compare, results and downloads API tests share - not a test file itself: a client on
a fresh work folder, a job waited for, the sample pair loaded, a column table seeded, a run made
by Auto."""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.runconfig import column_table
from tablecmp.setup import seed_key
from tablecmp.web.app import create_app
from tablecmp.web.sides import side
from tablecmp.web.workspace import COOKIE

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
W = {"X-Compare": "1"}
COLS = [{"a": "emp_id", "b": "EmployeeId", "name": "emp_id", "type": "text", "key": True, "compare": False},
        {"a": "department", "b": "Dept", "name": "department", "type": "text", "key": False, "compare": True}]
COUNTS = dict(x.split("=") for x in (ROOT / "tests/COUNTS.md").read_text().split())
FAKE_PW = "example-not-a-real-password"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    monkeypatch.setenv(cx.ENV_PREFIX + "FAKE", f"postgresql://u:{FAKE_PW}@nowhere:5432/db")
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


def wait(c, entry, seconds=180):
    """A job's entry once it has ended (or after `seconds`)."""
    t0 = time.time()
    while True:
        e = c.get(f"/api/jobs/{entry['id']}").json()
        if e["state"] != "running" or time.time() - t0 > seconds:
            return e
        time.sleep(0.05)


def newest(c, kind):
    return next(e for e in c.get("/api/log").json()["entries"] if e["kind"] == kind)


def load_pair(c):
    for tag, fname, name in (("A", "hr_employees.csv", "Left"), ("B", "payroll_employees.csv", "Right")):
        r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(EX / fname), "name": name}, headers=W)
        assert r.status_code == 200, r.text


def seed_table(c, cols=COLS):
    """The column table phase 3 would hold - two pairs, from a config's columns."""
    ws = ws_of(c)
    A, B = side(ws, "A"), side(ws, "B")
    ws.data.update(cmap=column_table({"columns": cols}, A, B), cmap_seed=seed_key(A, B))


def state(c):
    return c.get("/api/compare").json()


def compare(c):
    r = c.post("/api/compare", headers=W)
    assert r.status_code == 200, r.text
    return wait(c, r.json())


def auto_run(c):
    """Both sides loaded, Auto pressed, and the Compare it starts waited for - the state after it."""
    load_pair(c)
    e = wait(c, c.post("/api/auto", headers=W).json())
    assert e["state"] == "done", e
    done = wait(c, newest(c, "Compare"))
    assert done["state"] == "done", done
    return state(c)
