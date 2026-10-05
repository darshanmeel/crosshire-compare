"""The Connections manager over HTTP - and never a password in a response."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.web.app import create_app

W = {"X-Compare": "1"}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client


PG = {"kind": "postgresql", "host": "db.local", "port": 5432, "database": "hr", "user": "me"}


def test_save_list_and_edit_without_a_password_coming_back(c):
    r = c.put("/api/connections/PG", json={**PG, "password": "hunter2", "save_password": True}, headers=W)
    assert r.status_code == 200
    rows = c.get("/api/connections").json()
    assert rows == [{"name": "PG", "kind": "postgresql", "label": "Postgres", "where": rows[0]["where"],
                     "source": "file", "origin_file": "", "is_folder": False, "editable": True,
                     "password": "saved"}]
    form = c.get("/api/connections/PG").json()
    assert form["has_password"] is True and "hunter2" not in json.dumps(form)
    assert "hunter2" not in c.get("/api/connections").text


def test_a_blank_password_on_save_keeps_the_saved_one(c):
    c.put("/api/connections/PG", json={**PG, "password": "hunter2", "save_password": True}, headers=W)
    c.put("/api/connections/PG", json={**PG, "database": "hr2", "password": "", "save_password": True}, headers=W)
    stored = cx.stored_as_written()["PG"]
    assert stored.database == "hr2" and stored.password == "hunter2"


def test_an_env_reference_is_kept_and_shown_as_written(c, monkeypatch):
    monkeypatch.setenv("PG_PW", "s3cret")
    c.put("/api/connections/PG", json={**PG, "password": "${PG_PW}", "save_password": True}, headers=W)
    c.put("/api/connections/PG", json={**PG, "host": "db2", "password": None, "save_password": True}, headers=W)
    raw = (cx.store_path()).read_text(encoding="utf-8")
    assert "${PG_PW}" in raw and "s3cret" not in raw


def test_an_unsaved_password_lives_in_the_workspace_only(c):
    c.put("/api/connections/PG", json={**PG, "password": "typed", "save_password": False}, headers=W)
    assert cx.stored_as_written()["PG"].password is None
    assert "typed" not in cx.store_path().read_text(encoding="utf-8")
    assert c.get("/api/connections").json()[0]["password"] == "session"


def test_a_secret_extra_is_never_returned(c):
    body = {"kind": "databricks", "host": "h", "schema": "s", "extra": {"http_path": "/sql/x", "token": "t0k"},
            "save_password": True}
    c.put("/api/connections/DBX", json=body, headers=W)
    form = c.get("/api/connections/DBX").json()
    assert form["extra"].get("token", "") == "" and form["extra"]["http_path"] == "/sql/x"
    assert "t0k" not in c.get("/api/connections/DBX").text


def test_test_a_folder_and_delete(c, tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
    folder = {"kind": "folder", "host": str(tmp_path)}
    r = c.post("/api/connections/test", json={**folder, "name": "DATA"}, headers=W).json()
    assert r["ok"] and "data file" in r["message"]
    c.put("/api/connections/DATA", json=folder, headers=W)
    assert c.get("/api/connections").json()[0]["password"] == "folder"
    assert c.delete("/api/connections/DATA", headers=W).json() == {"deleted": "DATA"}
    assert c.get("/api/connections").json() == []


def test_a_bad_save_is_a_sentence(c):
    r = c.put("/api/connections/bad name", json=PG, headers=W)
    assert r.status_code == 400 and r.json()["detail"]


def test_import_preview_import_and_export(c):
    text = "PG: {kind: postgresql, host: h, password: lit}\nDATA: {kind: folder, path: D:/x}\nSF: {kind: snowflake, host: a, password: '${SF_PW}'}\n"
    prev = c.post("/api/connections/import/preview", json={"text": text, "filename": "team.yml"}, headers=W).json()
    assert [p["name"] for p in prev] == ["PG", "DATA", "SF"] and not any(p["replaces"] for p in prev)
    r = c.post("/api/connections/import", json={"text": text, "filename": "team.yml", "keep_passwords": False},
               headers=W).json()
    assert r["names"] == ["PG", "DATA", "SF"]
    stored = cx.stored_as_written()
    assert stored["PG"].password is None and stored["SF"].password == "${SF_PW}"
    out = c.get("/api/connections/export")
    assert "connections.yml" in out.headers["content-disposition"] and "lit" not in out.text
    bad = c.post("/api/connections/import/preview", json={"text": "X: {kind: mysql}", "filename": "x.yml"}, headers=W)
    assert bad.status_code == 400 and "not one of" in bad.json()["detail"]
