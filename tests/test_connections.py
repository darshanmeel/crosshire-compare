# tests/test_connections.py
import json
import os
import stat

import pytest
from tablecmp import connections as cx


def test_uri_round_trip_snowflake():
    c = cx.Connection(name="prod", kind="snowflake", host="xy12345.eu-west-1", database="ANALYTICS",
                      schema="HR", user="DSINGH", password="p@ss/word",
                      extra={"warehouse": "WH_SMALL", "role": "ANALYST"})
    uri = cx.to_uri(c)
    assert uri.startswith("snowflake://DSINGH:p%40ss%2Fword@xy12345.eu-west-1/ANALYTICS/HR?")
    back = cx.from_uri("prod", uri)
    assert back == c


@pytest.mark.parametrize("uri", [
    "databricks://token:dapi123@adb-1.azuredatabricks.net/?http_path=/sql/1.0/warehouses/abc&catalog=main&schema=hr",
    "mssql://svc:pw@sql01.corp:1433/Payroll",
    "oracle://hr_ro:pw@ora01:1521/?service_name=HRPDB",
    "postgresql://reporter:pw@pg01:5432/hr",
    "duckdb:///C:/data/sample.duckdb",
])
def test_uri_round_trip_other_kinds(uri):
    c = cx.from_uri("x", uri)
    assert cx.to_uri(c) == uri


def test_duckdb_uri_is_a_path():
    c = cx.from_uri("s", "duckdb:///C:/data/sample.duckdb")
    assert c.kind == "duckdb" and c.host == "C:/data/sample.duckdb"


def test_host_keeps_its_case():
    c = cx.from_uri("p", "snowflake://U:pw@XY12345.EU-WEST-1/DB/SCH?warehouse=WH")
    assert c.host == "XY12345.EU-WEST-1"


def test_from_uri_rejects_unknown_kind():
    with pytest.raises(ValueError):
        cx.from_uri("x", "mysql://u:p@h/db")


def test_save_load_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "c" / "connections.json"))
    monkeypatch.delenv("COMPARE_CONN_PROD", raising=False)
    cx.save(cx.Connection(name="prod", kind="postgresql", host="pg", port=5432, database="hr",
                          user="u", password="secret"))
    cx.save(cx.Connection(name="dev", kind="postgresql", host="pg", port=5432, database="hr",
                          user="u", password=None))
    raw = json.loads((tmp_path / "c" / "connections.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    by = {c["name"]: c for c in raw["connections"]}
    assert by["prod"]["password"] == "secret" and "password" not in by["dev"]
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "c" / "connections.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "c").stat().st_mode) == 0o700
    got = cx.load_all()
    assert got["prod"].password == "secret" and got["dev"].password is None
    assert got["prod"].source == "file"
    cx.delete("prod")
    assert "prod" not in cx.load_all()


def test_store_file_is_lf_and_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="a", kind="duckdb", host="x.duckdb"))
    cx.save(cx.Connection(name="b", kind="duckdb", host="y.duckdb"))
    raw = (tmp_path / "connections.json").read_bytes()
    assert b"\r\n" not in raw
    assert sorted(p.name for p in tmp_path.iterdir()) == ["connections.json"]


def test_save_rejects_bad_name_and_kind(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    with pytest.raises(ValueError):
        cx.save(cx.Connection(name="bad name", kind="postgresql", host="pg"))
    with pytest.raises(ValueError):
        cx.save(cx.Connection(name="ok", kind="mysql", host="pg"))
    assert not (tmp_path / "connections.json").exists()


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="prod", kind="postgresql", host="old", database="hr", user="u"))
    monkeypatch.setenv("COMPARE_CONN_prod", "postgresql://u:pw@new:5432/hr")
    got = cx.load_all()
    assert got["prod"].host == "new" and got["prod"].source == "env"


def test_env_connection_that_is_new_keeps_its_name(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.setenv("COMPARE_CONN_SAMPLE", "duckdb:///examples/sample.duckdb")
    monkeypatch.setenv("COMPARE_CONN_BROKEN", "nosuchkind://u:p@h/db")
    got = cx.load_all()
    assert got["SAMPLE"].kind == "duckdb" and got["SAMPLE"].host == "examples/sample.duckdb"
    assert got["SAMPLE"].source == "env"
    assert "BROKEN" not in got


def test_env_connection_is_never_written_to_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.setenv("COMPARE_CONN_ENVONLY", "postgresql://u:pw@h:5432/db")
    cx.save(cx.Connection(name="filed", kind="duckdb", host="x.duckdb"))
    raw = json.loads((tmp_path / "connections.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in raw["connections"]] == ["filed"]
    assert "pw" not in (tmp_path / "connections.json").read_text(encoding="utf-8")


def test_resolve_asks_for_a_missing_password(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="dev", kind="postgresql", host="pg", database="hr", user="u"))
    with pytest.raises(cx.PasswordNeeded) as e:
        cx.resolve("dev", {})
    assert e.value.name == "dev"
    assert cx.resolve("dev", {"dev": "typed"}).password == "typed"


def test_resolve_duckdb_needs_no_password(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    cx.save(cx.Connection(name="f", kind="duckdb", host="x.duckdb"))
    assert cx.resolve("f", {}).password is None
    with pytest.raises(KeyError):
        cx.resolve("nope", {})


def test_redact():
    s = ("postgresql://u:secret@h/db password=secret pwd=secret token=abc "
         "Authorization: Bearer xyz")
    r = cx.redact(s)
    for word in ("secret", "abc", "xyz"):
        assert word not in r
    assert "postgresql://u:***@h/db" in r


def test_redact_json_shaped_driver_message():
    s = ('{"headers": {"Authorization": "Bearer dapi123"}, "password": "hunter2", '
         'api_key: sk-1, secret: s3} at snowflake://svc:p%40ss@acct/DB')
    r = cx.redact(s)
    for word in ("dapi123", "hunter2", "sk-1", "s3}", "p%40ss"):
        assert word not in r
    assert "snowflake://svc:***@acct/DB" in r


def test_redact_leaves_plain_text_alone():
    s = "relation \"employees\" does not exist at host pg01:5432, user reporter"
    assert cx.redact(s) == s


def test_where_never_shows_a_credential():
    c = cx.Connection(name="p", kind="snowflake", host="acct", database="DB", schema="HR",
                      user="me", password="hidden", extra={"warehouse": "WH"})
    w = c.where
    assert "hidden" not in w and "me" not in w.split()
    assert "acct" in w and "DB.HR" in w and "WH" in w
    assert cx.Connection(name="d", kind="duckdb", host="C:/x.duckdb").where == "C:/x.duckdb"
