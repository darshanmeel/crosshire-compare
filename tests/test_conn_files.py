# tests/test_conn_files.py
"""Many connections from one JSON or YAML file, ${NAME} from the environment, shared files
read-only, import and export - and the folder connection a Path on disk side picks from."""
import json

import pytest
import yaml

from tablecmp import connections as cx
from tablecmp import databases as db
from tablecmp.sources import folder_files, in_folder

YAML = """
connections:
  - name: PROD
    type: snowflake
    account: xy12345.eu-west-1
    user: ANALYST
    password: ${SNOW_PW}
    database: HR
    schema: PUBLIC
    warehouse: WH_S
    role: READER
  - name: PG
    kind: postgresql
    server: db.local
    port: 5433
    db: hr
    username: me
  - name: DATA
    kind: folder
    path: D:/exports
  - name: SAMPLE
    uri: duckdb:///examples/sample.duckdb
"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    for k in [k for k in __import__("os").environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    return tmp_path


def test_a_yaml_file_holds_many_connections_by_their_usual_names(monkeypatch):
    monkeypatch.setenv("SNOW_PW", "s3cret")
    conns = cx.parse_connections(YAML, "team.yml")
    assert list(conns) == ["PROD", "PG", "DATA", "SAMPLE"]
    p = conns["PROD"]
    assert (p.kind, p.host, p.user, p.password, p.database, p.schema) == \
           ("snowflake", "xy12345.eu-west-1", "ANALYST", "s3cret", "HR", "PUBLIC")
    assert p.extra == {"warehouse": "WH_S", "role": "READER"}
    g = conns["PG"]
    assert (g.host, g.port, g.database, g.user, g.password) == ("db.local", 5433, "hr", "me", None)
    assert conns["DATA"].is_folder and conns["DATA"].host == "D:/exports"
    assert conns["SAMPLE"].kind == "duckdb" and conns["SAMPLE"].host == "examples/sample.duckdb"


def test_every_shape_of_file_reads_the_same(monkeypatch):
    rec = {"kind": "postgresql", "host": "h", "database": "d", "user": "u"}
    shapes = [json.dumps({"connections": [dict(rec, name="X")]}), json.dumps({"connections": {"X": rec}}),
              json.dumps([dict(rec, name="X")]), json.dumps({"X": rec}), yaml.safe_dump({"X": rec}),
              "X: postgresql://u@h/d"]
    for text in shapes:
        c = cx.parse_connections(text)["X"]
        assert (c.kind, c.host, c.database, c.user) == ("postgresql", "h", "d", "u"), text


@pytest.mark.parametrize("text, said", [
    ("X: {kind: mysql}", "not one of"), ("- {kind: postgresql}", "no name"),
    ("'bad name': {kind: folder, path: x}", "letters, digits"), ("X: {kind: mssql, port: abc}", "not a number"),
    ("X: [1, 2]", "not a mapping"), ("{not json", "not a valid"), ("42", "a list of connections")])
def test_a_bad_file_is_refused_naming_what_is_wrong(text, said):
    with pytest.raises(ValueError, match=said):
        cx.parse_connections(text, "team.yml")


def test_a_databricks_token_is_its_password():
    c = cx.parse_connections("DB: {kind: databricks, host: h, token: t0k, http_path: /sql/x}")["DB"]
    assert c.password == "t0k" and c.extra["http_path"] == "/sql/x"


def test_shared_files_are_read_only_and_the_store_and_env_win(store, monkeypatch):
    shared = store / "team.yml"
    shared.write_text("A: {kind: folder, path: /team/a}\nB: {kind: folder, path: /team/b}\n"
                      "C: {kind: folder, path: /team/c}\n", encoding="utf-8")
    monkeypatch.setenv(cx.FILES_ENV, str(shared))
    cx.save(cx.Connection(name="B", kind="folder", host="/mine/b"))
    monkeypatch.setenv("COMPARE_CONN_C", "folder:///env/c")
    conns = cx.load_all()
    assert (conns["A"].host, conns["A"].source, conns["A"].origin_file) == ("/team/a", "shared", str(shared))
    assert (conns["B"].host, conns["B"].source) == ("/mine/b", "file")
    assert (conns["C"].host, conns["C"].source) == ("env/c", "env")
    # saving another connection never copies a shared one into the store
    cx.save(cx.Connection(name="D", kind="folder", host="/mine/d"))
    assert set(cx.parse_connections((store / "connections.json").read_text(encoding="utf-8"))) == {"B", "D"}


def test_an_env_reference_is_never_written_out_as_its_secret(store, monkeypatch):
    monkeypatch.setenv("PG_PW", "hunter2")
    (store / "connections.json").write_text(json.dumps({"connections": [
        {"name": "PG", "kind": "postgresql", "host": "h", "user": "u", "password": "${PG_PW}", "port": "${PG_PORT}"}]}),
        encoding="utf-8")
    monkeypatch.setenv("PG_PORT", "6543")
    c = cx.resolve("PG")
    assert c.password == "hunter2" and c.port == 6543
    cx.save(cx.Connection(name="OTHER", kind="folder", host="/x"))       # rewrites the store
    text = (store / "connections.json").read_text(encoding="utf-8")
    assert "hunter2" not in text and "${PG_PW}" in text and "${PG_PORT}" in text
    monkeypatch.delenv("PG_PW")
    with pytest.raises(cx.PasswordNeeded):                               # unset: asked for, like no password
        cx.resolve("PG")


def test_import_adds_to_the_store_and_export_holds_no_password(store, monkeypatch):
    cx.save(cx.Connection(name="PG", kind="postgresql", host="old", password="keep"))
    found = cx.parse_connections(YAML, expand=False)
    names = cx.import_connections(found.values())
    assert names == ["PROD", "PG", "DATA", "SAMPLE"]
    conns = cx.load_all()
    assert conns["PG"].host == "db.local" and conns["DATA"].is_folder
    raw = (store / "connections.json").read_text(encoding="utf-8")
    assert "${SNOW_PW}" in raw                                         # kept as written
    out = cx.dump_connections(conns.values(), yaml_out=True)
    again = cx.parse_connections(out, "x.yml", expand=False)
    assert set(again) == set(conns) and all(c.password is None for c in again.values())
    assert again["PROD"].extra == {"warehouse": "WH_S", "role": "READER"}


def test_import_without_passwords_drops_them(store):
    cx.import_connections(cx.parse_connections("PG: {kind: postgresql, host: h, password: pw}").values(),
                          passwords=False)
    assert cx.load_all()["PG"].password is None


def test_a_yaml_store_is_read_and_written_as_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "conns.yml"))
    cx.save(cx.Connection(name="DATA", kind="folder", host="D:/exports"))
    text = (tmp_path / "conns.yml").read_text(encoding="utf-8")
    assert yaml.safe_load(text)["connections"][0] == {"name": "DATA", "kind": "folder", "host": "D:/exports"}
    assert cx.load_all()["DATA"].host == "D:/exports"


def test_a_folder_connection_round_trips_and_needs_no_password(store, tmp_path):
    c = cx.from_uri("DATA", "folder:///D:/exports/hr")
    assert c.is_folder and c.host == "D:/exports/hr" and cx.to_uri(c) == "folder:///D:/exports/hr"
    assert cx.needs_no_password(c) and c.where == "D:/exports/hr"
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(tmp_path)))
    assert list(cx.folders()) == ["DATA"] and cx.resolve("DATA").password is None
    ok = db.test(cx.Connection(name="DATA", kind="folder", host=str(tmp_path)))
    assert ok.ok and "data file" in ok.message
    assert not db.test(cx.Connection(name="X", kind="folder", host=str(tmp_path / "gone"))).ok


def test_a_folder_lists_its_data_files_with_subfolders(tmp_path):
    (tmp_path / "2026-10").mkdir()
    (tmp_path / ".hidden").mkdir()
    for f in ("b.csv", "a.parquet", "notes.docx", "2026-10/hr.json", ".hidden/x.csv"):
        (tmp_path / f).write_text("x", encoding="utf-8")
    assert folder_files(str(tmp_path)) == ["a.parquet", "b.csv", "2026-10/hr.json"]
    assert folder_files(str(tmp_path), limit=2) == ["a.parquet", "b.csv"]
    assert folder_files(str(tmp_path / "gone")) == []
    assert in_folder(str(tmp_path), "2026-10/hr.json") == str(tmp_path / "2026-10/hr.json")
    assert in_folder(str(tmp_path), str(tmp_path / "b.csv")) == str(tmp_path / "b.csv")
