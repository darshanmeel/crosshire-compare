"""One workspace per browser, kept by a cookie - and a stale cookie gets a fresh one."""
from fastapi.testclient import TestClient

from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE


def test_the_cookie_keeps_the_same_workspace():
    c = TestClient(create_app())
    first = c.get("/api/workspace").json()["id"]
    assert c.cookies.get(COOKIE) == first
    assert c.get("/api/workspace").json()["id"] == first


def test_two_browsers_two_workspaces():
    app = create_app()
    a, b = TestClient(app), TestClient(app)
    assert a.get("/api/workspace").json()["id"] != b.get("/api/workspace").json()["id"]


def test_a_cookie_from_before_a_restart_gets_a_fresh_workspace():
    c = TestClient(create_app())
    c.cookies.set(COOKIE, "from-an-old-server", domain="testserver.local")
    r = c.get("/api/workspace")
    assert r.status_code == 200
    new = r.json()["id"]
    assert new != "from-an-old-server" and c.cookies.get(COOKIE) == new
