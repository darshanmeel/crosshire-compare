"""A job runs in a thread, says how it is going, and lands in the Log - as the run disc did."""
import re

import pytest

from fastapi.testclient import TestClient

from tablecmp.web import jobs
from tablecmp.web.app import create_app
from tablecmp.web.workspace import Workspace


def test_a_job_says_its_lines_and_ends_done_with_its_time():
    ws = Workspace(id="w")

    def work(ctx):
        ctx.say("Reading A…")
        ctx.say("Matching on emp_id")
        return 42

    e = jobs.start(ws, "Compare", "Comparing…", work, wait=True)
    assert e["state"] == "done" and e["result"] == 42
    assert e["lines"] == ["Reading A…", "Matching on emp_id"]
    assert re.search(r" in \d+\.\ds$", e["label"])
    assert ws.last_run["Compare"] is e and ws.log[-1] is e


def test_a_label_with_a_time_is_left_as_it_is():
    ws = Workspace(id="w")

    def work(ctx):
        ctx.label = "Compared in 3.2s"

    assert jobs.start(ws, "Compare", "Comparing…", work, wait=True)["label"] == "Compared in 3.2s"


def test_a_job_that_raises_is_an_error_with_the_password_blanked():
    ws = Workspace(id="w")

    def work(ctx):
        raise RuntimeError("could not log in to postgresql://me:hunter2@db/hr")

    e = jobs.start(ws, "Fetch", "Fetching…", work, wait=True)
    assert e["state"] == "error" and "hunter2" not in " ".join(e["lines"])
    assert "could not finish" in e["label"]
    assert e["lines"][-1].startswith("could not log in") and "RuntimeError" not in e["lines"][-1]


def test_an_errored_job_is_still_served():
    app = create_app()
    c = TestClient(app)
    ws = app.state.workspaces.get(c.get("/api/workspace").json()["id"])

    def work(ctx):
        raise RuntimeError("boom")

    e = jobs.start(ws, "Fetch", "Fetching…", work, wait=True)
    r = c.get(f"/api/jobs/{e['id']}")
    assert r.status_code == 200 and r.json()["state"] == "error" and "result" not in r.json()


def test_polling_public_while_a_job_finishes_never_raises():
    import threading
    ws = Workspace(id="w")
    go = threading.Event()

    def work(ctx):
        go.wait(2)
        return {"x": 1}

    e = jobs.start(ws, "Compare", "Comparing…", work)
    go.set()
    while e["state"] == "running":
        assert "result" not in jobs.public(e)
    assert "result" not in jobs.public(e) and e["result"] == {"x": 1}


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the interrupt is meant to escape the thread
def test_a_base_exception_does_not_leave_a_job_running():
    ws = Workspace(id="w")

    def work(ctx):
        raise KeyboardInterrupt()

    e = jobs.start(ws, "Compare", "Comparing…", work, wait=True)
    assert e["state"] == "error"


def test_the_log_is_capped_and_notes_go_in_it():
    ws = Workspace(id="w")
    for i in range(jobs.LOG_MAX + 5):
        jobs.note(ws, "Auto decisions", f"note {i}", [])
    assert len(ws.log) == jobs.LOG_MAX and ws.log[0]["label"] == "note 5"


def test_the_log_routes_hide_results_and_clear():
    app = create_app()
    c = TestClient(app)
    wid = c.get("/api/workspace").json()["id"]
    ws = app.state.workspaces.get(wid)
    e = jobs.start(ws, "Profile", "Profiling…", lambda ctx: {"big": "thing"}, page="Profiling", wait=True)
    body = c.get("/api/log").json()
    assert body["entries"][0]["id"] == e["id"] and "result" not in body["entries"][0]
    assert body["last"]["Profiling"]["id"] == e["id"]
    assert c.get(f"/api/jobs/{e['id']}").json()["state"] == "done"
    assert c.get("/api/jobs/nope").status_code == 404
    assert c.delete("/api/log", headers={"X-Compare": "1"}).json() == {"entries": [], "last": {}}
