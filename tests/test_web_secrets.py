"""The final review's secrets and redaction findings, over HTTP."""
import os

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp import databases as db
from tablecmp.web import jobs
from tablecmp.web.app import create_app
from tablecmp.web.workspace import Workspace

W = {"X-Compare": "1"}
PG = {"kind": "postgresql", "host": "db.local", "port": 5432, "database": "hr", "user": "me"}
SF = {"kind": "snowflake", "host": "acct", "user": "me", "extra": {"private_key_file": "k.p8"}}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client


def held(c):
    return next(iter(c.app.state.workspaces._all.values())).passwords


def test_the_export_holds_no_secret_and_no_expanded_env_value(c, monkeypatch):
    monkeypatch.setenv("SFPW", "envsecret123")
    c.put("/api/connections/sf", json={**SF, "extra": {**SF["extra"], "private_key_pwd": "passphrase-literal"},
                                       "save_password": True}, headers=W)
    c.put("/api/connections/sf2", json={**SF, "extra": {**SF["extra"], "private_key_pwd": "${SFPW}"},
                                        "save_password": True}, headers=W)
    c.put("/api/connections/pg", json={**PG, "password": "${SFPW}", "save_password": True}, headers=W)
    c.put("/api/connections/pg2", json={**PG, "password": "literalpw", "save_password": True}, headers=W)
    c.put("/api/connections/dbx", json={"kind": "databricks", "host": "h", "extra": {"token": "dapiTOKEN"},
                                        "save_password": True}, headers=W)
    text = c.get("/api/connections/export").text
    for bad in ("passphrase-literal", "envsecret123", "literalpw", "dapiTOKEN"):
        assert bad not in text
    assert "${SFPW}" in text


def test_a_databricks_token_with_save_unticked_is_held_for_the_session(c, monkeypatch):
    seen = {}

    def fake_test(conn, secrets=()):
        seen["pw"] = conn.password
        return db.TestResult(True, "ok", 0.1)
    monkeypatch.setattr(db, "test", fake_test)
    body = {"kind": "databricks", "host": "h", "extra": {"token": "dapiSECRET"}, "save_password": False}
    assert c.post("/api/connections/test", json={**body, "name": "dbx"}, headers=W).json()["ok"] is True
    assert seen["pw"] == "dapiSECRET"
    c.put("/api/connections/dbx", json=body, headers=W)
    assert "dapiSECRET" not in cx.store_path().read_text(encoding="utf-8")
    assert c.get("/api/connections").json()[0]["password"] == "session"


def test_a_passphrase_with_save_unticked_stays_out_of_the_file_and_reaches_resolve(c):
    c.put("/api/connections/sf", json={**SF, "extra": {**SF["extra"], "private_key_pwd": "pass-phrase-1"},
                                       "save_password": False}, headers=W)
    assert "pass-phrase-1" not in cx.store_path().read_text(encoding="utf-8")
    assert cx.resolve("sf", held(c)).extra["private_key_pwd"] == "pass-phrase-1"


def test_a_broken_connections_file_says_the_line_number_only(c):
    bad = "prod:\n  kind: postgresql\n  password: Hunter2: [oops\n"
    cx.store_path().write_text(bad, encoding="utf-8")
    for path in ("/api/connections", "/api/connections/export"):
        r = c.get(path)
        assert r.status_code == 400 and "Hunter2" not in r.text and "line" in r.json()["detail"]
    p = c.post("/api/connections/import/preview", json={"text": bad, "filename": "c.yml"}, headers=W)
    assert p.status_code == 400 and "Hunter2" not in p.text and "c.yml" in p.json()["detail"]


def test_forgetting_a_held_password_and_editing_or_deleting_drop_it(c):
    c.put("/api/connections/PG", json={**PG, "password": "typed", "save_password": False}, headers=W)
    assert held(c) == {"PG": "typed"}
    assert c.delete("/api/connections/PG/password", headers=W).json() == {"ok": True}
    assert held(c) == {}
    c.put("/api/connections/PG", json={**PG, "password": "typed", "save_password": False}, headers=W)
    c.put("/api/connections/PG", json={**PG, "host": "other", "save_password": False}, headers=W)
    assert held(c) == {}                                   # another host: the old password is not carried
    c.put("/api/connections/PG", json={**PG, "password": "typed", "save_password": False}, headers=W)
    c.delete("/api/connections/PG", headers=W)
    assert held(c) == {}
    assert c.delete("/api/connections/PG/password").status_code == 403


def test_redact_blanks_known_secrets_and_leaves_no_partial_secret():
    for text, secret in [("password=my secret here", "my secret here"), ('invalid password "s3cr3t"', "s3cr3t"),
                         ("bad login (hunter2)", "hunter2"), ("PWD={a b};", "a b")]:
        assert secret not in cx.redact(text, [secret])
    assert cx.redact("postgresql://bob:p@ss@db") == "postgresql://bob:***@db"
    assert "secretpw" not in cx.redact("mssql://:secretpw@host")
    assert "b c" not in cx.redact('password="a b c"') and "b c" not in cx.redact("PWD={a b c};")
    assert cx.redact("user x ok", ["ab"]) == "user x ok"   # too short to be worth blanking


def test_a_422_never_echoes_the_body(c):
    r = c.put("/api/connections/x", json={"password": "S3cretPW", "host": "h"}, headers=W)
    assert r.status_code == 422 and "S3cretPW" not in r.text
    assert r.json()["errors"][0]["loc"] == ["body", "kind"]


def test_options_needs_the_header_too(c):
    assert c.options("/api/connections/PG").status_code == 403
    assert c.options("/api/connections/PG", headers=W).status_code == 405


def test_a_job_line_blanks_the_workspaces_typed_password():
    ws = Workspace(id="w", passwords={"PG": "my secret here"})

    def boom(ctx):
        ctx.say("trying my secret here")
        raise RuntimeError("bad login my secret here")
    e = jobs.start(ws, "t", "T", boom, wait=True)
    assert "my secret here" not in " ".join(e["lines"]) and "***" in e["lines"][-1]
    assert "my secret here" not in " ".join(jobs.note(ws, "n", "N", ["pw my secret here"])["lines"])


def test_a_password_with_a_space_is_blanked_whole_in_the_test_message_and_a_configs_line(monkeypatch):
    from tablecmp import loading, runconfig
    pw = "my secret here"

    def bad(c):
        raise RuntimeError(f"password={pw} rejected")
    monkeypatch.setattr(db, "connect", bad)
    r = db.test(cx.Connection(name="p", kind="postgresql", host="h", user="u", password=pw), [pw])
    assert "secret" not in r.message and "here" not in r.message

    def no_login(block, tag, passwords, say):
        raise RuntimeError(f"bad login {pw}")
    monkeypatch.setattr(runconfig, "open_side", no_login)
    _, said = loading.open_config_sides({"sides": {"A": {}, "B": {}}}, {"pg": pw})
    assert said and all(pw not in text and "secret" not in text for _, text in said)


def test_a_databricks_token_given_as_a_reference_stays_in_the_file(c):
    body = {"kind": "databricks", "host": "h", "extra": {"token": "${DBX_TOKEN}"}, "save_password": False}
    assert c.put("/api/connections/dbx", json=body, headers=W).status_code == 200
    assert "${DBX_TOKEN}" in cx.store_path().read_text(encoding="utf-8")
