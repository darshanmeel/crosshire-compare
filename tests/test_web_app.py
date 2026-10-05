"""The web server: the guard every request passes, and the health route."""
from fastapi.testclient import TestClient

from tablecmp.web.app import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_health_answers():
    assert client().get("/api/health").json() == {"ok": True}


def test_a_write_without_the_header_is_refused():
    c = client()
    r = c.post("/api/health")
    assert r.status_code == 403 and "X-Compare" in r.json()["detail"]


def test_a_write_with_the_header_reaches_the_route():
    r = client().post("/api/health", headers={"X-Compare": "1"})
    assert r.status_code == 405             # past the guard: the route only takes GET


def test_a_foreign_host_is_refused(monkeypatch):
    monkeypatch.delenv("COMPARE_ALLOWED_HOSTS", raising=False)
    r = client().get("/api/health", headers={"Host": "evil.example:8501"})
    assert r.status_code == 400


def test_an_allowed_host_from_the_environment(monkeypatch):
    monkeypatch.setenv("COMPARE_ALLOWED_HOSTS", "box.local")
    r = client().get("/api/health", headers={"Host": "box.local:8501"})
    assert r.status_code == 200
