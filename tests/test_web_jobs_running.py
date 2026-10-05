"""A running job is never lost: not to Clear the Log, not to the Log's size limit, not to a
second job of its kind."""
import re
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tablecmp.web import jobs, runs
from tablecmp.web.app import create_app
from tablecmp.web.workspace import Workspace


def held(ws, kind="Fetch", page="Compare"):
    """A job that stays running until the test lets it go."""
    go = threading.Event()
    e = jobs.start(ws, kind, "Working…", lambda ctx: go.wait(10), page=page)
    return e, go


def test_clearing_the_log_keeps_a_running_job_findable():
    app = create_app()
    c = TestClient(app, headers={"X-Compare": "1"})
    ws = app.state.workspaces.get(c.get("/api/workspace").json()["id"])
    e, go = held(ws)
    try:
        jobs.note(ws, "Note", "done thing", ["x"])
        body = c.delete("/api/log").json()
        assert [x["id"] for x in body["entries"]] == [e["id"]]
        assert body["last"]["Compare"]["id"] == e["id"]
        assert c.get(f"/api/jobs/{e['id']}").json()["state"] == "running"
    finally:
        go.set()


def test_the_trim_never_drops_a_running_job():
    ws = Workspace(id="w")
    e, go = held(ws)
    try:
        for i in range(jobs.LOG_MAX + 5):
            jobs.note(ws, "Note", f"n{i}", [])
        assert e in ws.log and len(ws.log) <= jobs.LOG_MAX
        assert jobs.find(ws, e["id"]) is e
    finally:
        go.set()


def test_a_second_job_of_the_same_kind_and_page_is_refused_while_one_runs():
    ws = Workspace(id="w")
    e, go = held(ws, "Profile", "Compare")
    try:
        with pytest.raises(HTTPException) as x:
            jobs.start(ws, "Profile", "Profiling…", lambda ctx: None, page="Compare")
        assert x.value.status_code == 409 and "running already" in x.value.detail
        jobs.start(ws, "Profile", "Profiling…", lambda ctx: None, page="Profiling", wait=True)
        jobs.start(ws, "Key search", "Looking…", lambda ctx: None, page="Compare", wait=True)
    finally:
        go.set()


def test_a_job_that_ended_lets_the_next_one_start():
    ws = Workspace(id="w")
    jobs.start(ws, "Fetch", "Fetching…", lambda ctx: None, wait=True)
    assert jobs.start(ws, "Fetch", "Fetching…", lambda ctx: None, wait=True)["state"] == "done"
    assert not ws.running


def test_running_sees_a_job_the_log_no_longer_holds():
    ws = Workspace(id="w")
    e, go = held(ws, "Compare", "Compare")
    try:
        ws.log.clear()
        assert runs.running(ws)
    finally:
        go.set()


def test_a_time_in_the_label_is_only_a_trailing_one():
    ws = Workspace(id="w")
    e = jobs.start(ws, "Profile", "Profile ready - key: q2s", lambda ctx: None, wait=True)
    assert re.search(r"key: q2s in \d+\.\ds$", e["label"])


def test_fetch_a_and_fetch_b_do_not_refuse_each_other():
    ws = Workspace(id="w")
    go = threading.Event()
    jobs.start(ws, "Fetch", "Fetching…", lambda ctx: go.wait(10), page="Compare", slot="A")
    try:
        jobs.start(ws, "Fetch", "Fetching…", lambda ctx: None, page="Compare", slot="B")
        with pytest.raises(HTTPException):
            jobs.start(ws, "Fetch", "Fetching…", lambda ctx: None, page="Compare", slot="A")
    finally:
        go.set()
