"""The side panels over HTTP: upload, path, folder, Browse, Load, preview, fetch, config."""
import json
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp import loading
from tablecmp.web.app import create_app
from tablecmp.web.sides import panel
from tablecmp.web.workspace import COOKIE

W = {"X-Compare": "1"}
EX = Path(__file__).resolve().parent.parent / "examples"
HR = EX / "hr_employees.csv"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    client = TestClient(create_app())
    client.get("/api/workspace")
    return client


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


def wait(c, entry, seconds=60):
    """A job's entry once it has ended (or after `seconds`)."""
    t0 = time.time()
    while True:
        e = c.get(f"/api/jobs/{entry['id']}").json()
        if e["state"] != "running" or time.time() - t0 > seconds:
            return e
        time.sleep(0.05)


def test_the_sides_start_empty(c):
    b = c.get("/api/sources").json()
    assert [b["sides"][t]["loaded"] for t in "ABP"] == [False, False, False]
    assert b["defaults"] == {"A": "Left", "B": "Right", "P": "Table"} and "contains" in b["quick_ops"]
    assert b["config"] is None and "parquet" in b["upload_types"]
    assert c.post("/api/sources/X/schema", json={}, headers=W).status_code == 404


def test_an_upload_is_streamed_to_the_work_folder_and_picked(c, tmp_path):
    data = HR.read_bytes()
    r = c.post("/api/sources/A/upload?filename=hr.csv", content=data, headers=W)
    assert r.status_code == 200 and r.json()["staged"] == "hr.csv"
    first = panel(ws_of(c), "A").staged
    assert Path(first).parent == tmp_path / "work" and Path(first).read_bytes() == data
    s = c.post("/api/sources/A/schema", json={"how": "upload"}, headers=W).json()
    assert s["label"] == "hr.csv" and [x["name"] for x in s["columns"]][:2] == ["emp_id", "first_name"]
    c.post("/api/sources/A/upload?filename=again.csv", content=data, headers=W)
    assert not Path(first).exists()                   # replaced, and nothing had loaded it


def test_an_upload_has_no_size_cap(c):
    chunk = b"x," * 32768 + b"\n"

    def body():
        yield b"a,b\n"
        for _ in range(100):                          # ~6.5 MB, sent piece by piece
            yield chunk
    r = c.post("/api/sources/B/upload?filename=big.csv", content=body(), headers=W)
    assert r.status_code == 200
    assert Path(panel(ws_of(c), "B").staged).stat().st_size == 4 + 100 * len(chunk)


def test_an_upload_of_another_kind_or_a_failed_write_is_refused(c, tmp_path, monkeypatch):
    r = c.post("/api/sources/A/upload?filename=run.exe", content=b"MZ", headers=W)
    assert r.status_code == 400 and ".parquet" in r.json()["detail"]
    c.post("/api/sources/A/upload?filename=hr.csv", content=HR.read_bytes(), headers=W)
    kept = panel(ws_of(c), "A").staged
    monkeypatch.setattr(loading, "upload_path", lambda tag, name: tmp_path)     # a folder: the write fails
    r = c.post("/api/sources/A/upload?filename=hr2.csv", content=b"a\n1\n", headers=W)
    assert r.status_code == 400 and r.json()["detail"].startswith("The upload did not finish")
    assert panel(ws_of(c), "A").staged == kept and Path(kept).exists()


def test_a_path_on_disk_and_what_is_said_about_it(c, tmp_path, monkeypatch):
    s = c.post("/api/sources/A/schema", json={"how": "path", "path": f'  "{HR}" '}, headers=W).json()
    assert s["error"] == "" and s["kind"] == "csv" and len(s["columns"]) == 7      # "Copy as path" quotes dropped
    missing = c.post("/api/sources/A/schema", json={"how": "path", "path": str(tmp_path / "no.csv")}, headers=W)
    assert missing.json()["error"] == "File not found."
    monkeypatch.setenv("COMPARE_DATA_DIR", str(tmp_path))
    outside = c.post("/api/sources/A/schema", json={"how": "path", "path": str(HR)}, headers=W).json()
    assert "COMPARE_DATA_DIR" in outside["error"] and outside["columns"] == []
    junk = tmp_path / "junk.parquet"
    junk.write_bytes(b"not parquet")
    s = c.post("/api/sources/A/schema", json={"how": "path", "path": str(junk)}, headers=W).json()
    assert s["error"].startswith("Could not read the parquet file:")
    blank = c.post("/api/sources/A/schema", json={"how": "path", "path": ""}, headers=W).json()
    assert blank == {"label": "", "kind": "csv", "columns": [], "error": ""}


def test_a_folder_lists_its_files_and_a_file_is_picked_by_name(c, tmp_path):
    root = tmp_path / "exports"
    (root / "sub").mkdir(parents=True)
    shutil.copy(HR, root / "hr.csv")
    shutil.copy(EX / "payroll_employees.csv", root / "sub" / "payroll.csv")
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(root)))
    assert c.get("/api/sources/folders").json() == [{"name": "DATA", "host": str(root)}]
    files = c.get("/api/sources/folders/DATA/files").json()
    assert files["files"] == ["hr.csv", "sub/payroll.csv"] and files["note"] is None
    s = c.post("/api/sources/B/schema", json={"how": "path", "folder": "DATA", "file": "sub/payroll.csv"},
               headers=W).json()
    assert s["label"] == "payroll.csv" and s["columns"][0]["name"] == "EmployeeId"
    assert c.get("/api/sources/folders/GONE/files").status_code == 404
    s = c.post("/api/sources/B/schema", json={"how": "path", "folder": "GONE", "file": "x.csv"}, headers=W).json()
    assert s["error"] == "No folder connection called GONE - pick another."


def test_browse_opens_the_dialog_here_and_names_a_folder_file(c, tmp_path, monkeypatch):
    from tablecmp import filepick
    monkeypatch.setattr(filepick, "available", lambda: False)
    assert c.post("/api/sources/browse", json={}, headers=W).status_code == 409
    monkeypatch.setattr(filepick, "available", lambda: True)
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(tmp_path)))
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(filepick, "pick_file", lambda start="": seen.append(start) or str(tmp_path / "a.csv"))
    assert c.post("/api/sources/browse", json={"folder": "DATA"}, headers=W).json() == {"path": "", "file": "a.csv"}
    assert seen == [str(tmp_path)]
    assert c.post("/api/sources/browse", json={"start": str(HR)}, headers=W).json() == \
        {"path": str(tmp_path / "a.csv"), "file": ""}
    assert seen[-1] == str(HR.parent)

    def boom(start=""):
        raise RuntimeError("The file dialog could not open: no display")
    monkeypatch.setattr(filepick, "pick_file", boom)
    r = c.post("/api/sources/browse", json={}, headers=W)
    assert r.status_code == 400 and "could not open" in r.json()["detail"]


def load(c, tag="A", **kw):
    return c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(HR), **kw}, headers=W)


def test_load_reads_the_rows_with_the_cut(c):
    r = load(c, name="HR", where="department = 'Finance'", order_by=["hire_date", "gone"], desc=True, limit=100)
    assert r.status_code == 200
    s = r.json()["side"]
    assert s["loaded"] and s["name"] == "HR" and s["rows"] == 100 and s["snapshot"]
    assert s["cut"] == "WHERE department = 'Finance' · ORDER BY hire_date DESC · TOP 100"
    assert s["caption"].startswith(":green[**✓ HR**] · hr_employees.csv · 100 rows × 7 columns")
    assert r.json()["warnings"] == [] and s["notes"] == []
    assert c.get("/api/sources").json()["sides"]["A"]["rows"] == 100


def test_the_preview_is_the_first_rows_as_the_page_names_them(c):
    assert c.get("/api/sources/A/preview").status_code == 409
    r = load(c, column_names="id, first").json()
    assert r["warnings"][0].startswith("You gave 2 names but the file has 7 columns")
    p = c.get("/api/sources/A/preview?n=3").json()
    assert p["columns"][:3] == ["id", "first", "last_name"] and len(p["rows"]) == 3
    assert p["rows"][0][0] == "E10001"


def test_nothing_picked_and_a_bad_cut_are_sentences(c):
    r = c.post("/api/sources/A/load", json={"how": "path", "path": ""}, headers=W)
    assert r.status_code == 400 and r.json()["detail"] == "Nothing to load - pick a file, or fetch a table, first."
    r = load(c, where="no_such_column = 1")
    assert r.status_code == 400 and r.json()["detail"].startswith("Could not read the rows:")


def test_what_is_said_under_the_loaded_side(c, tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    s = load(c, path=str(empty)).json()["side"]
    assert s["rows"] == 0 and {"tone": "warning", "text": "The file has no rows."} in s["notes"]
    rowish = tmp_path / "rows.csv"
    rowish.write_text("1,2026-01-01,3.5\n2,2026-01-02,4.5\n", encoding="utf-8")
    s = load(c, path=str(rowish)).json()["side"]
    assert any("look like a data row" in n["text"] for n in s["notes"])
    r = load(c, path=str(rowish), header=False, column_names="a, b, c, d").json()
    assert r["side"]["columns"] == ["a", "b", "c"] and r["warnings"][0].startswith("You gave 4 names")


def test_a_new_side_drops_what_was_worked_out_from_the_old(c):
    load(c)
    ws = ws_of(c)
    ws.data.update(cmap="x", result={"run_id": "y"}, profile_P="z")
    old_snap = panel(ws, "A").side.cache_path
    load(c, where="department = 'Finance'")
    assert "cmap" not in ws.data and "result" not in ws.data and ws.data["profile_P"] == "z"
    assert old_snap and not Path(old_snap).exists()
    load(c, "P")
    assert "profile_P" not in ws.data


def test_add_to_filter(c):
    r = c.post("/api/sources/quick-clause",
               json={"column": "department", "op": "contains", "value": "Fin", "where": "salary > 0 "}, headers=W)
    assert r.json()["where"] == "salary > 0\nAND \"department\" ILIKE '%Fin%'"
    bad = c.post("/api/sources/quick-clause", json={"column": "x", "op": "drop table"}, headers=W)
    assert bad.status_code == 400


FAKE_PW = "example-not-a-real-password"
TABLE = {"connection": "SAMPLE", "mode": "table", "table": "hr.employees", "cap": 0}


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setenv("COMPARE_CONN_SAMPLE", "duckdb:///" + (EX / "sample.duckdb").as_posix())


def test_the_plan_for_a_table_and_for_sql(c, sample):
    plan = c.post("/api/sources/A/db", json={**TABLE, "cap": 1000}, headers=W).json()
    assert plan == {"sql": 'SELECT * FROM "hr"."employees"', "error": "", "warning": loading.CAP_WARNING,
                    "held": None, "password": "none"}
    ordered = c.post("/api/sources/A/db", json={"connection": "SAMPLE", "mode": "sql",
                                               "sql": "SELECT * FROM hr.employees ORDER BY emp_id", "cap": 10},
                     headers=W).json()
    assert ordered["warning"] == ""
    assert c.post("/api/sources/A/db", json={"connection": "NOPE"}, headers=W).status_code == 400


def test_fetch_is_a_job_and_load_reads_it(c, sample):
    e = c.post("/api/sources/A/fetch", json=TABLE, headers=W).json()
    assert e["kind"] == "Fetch" and e["label"] == "Fetching from SAMPLE…" and "result" not in e
    done = wait(c, e)
    assert done["state"] == "done" and done["label"].startswith("Fetched 3,000 rows in ")
    assert c.post("/api/sources/A/db", json=TABLE, headers=W).json()["held"]["rows"] == 3000
    r = c.post("/api/sources/A/load", json={"how": "database", "db": TABLE, "name": "Left"}, headers=W).json()
    s = r["side"]
    assert s["name"] == "SAMPLE" and s["origin"] == "DuckDB file · hr.employees" and s["is_database"]
    assert s["label"] == "SAMPLE.parquet" and s["rows"] == 3000 and not s["snapshot"]
    assert c.get("/api/log").json()["last"]["Compare"]["id"] == e["id"]


def test_a_fetch_for_the_profiling_page_lights_its_disc(c, sample):
    e = wait(c, c.post("/api/sources/P/fetch", json=TABLE, headers=W).json())
    assert c.get("/api/log").json()["last"]["Profiling"]["id"] == e["id"]


def test_only_a_read_is_sent(c, sample):
    r = c.post("/api/sources/A/fetch", json={"connection": "SAMPLE", "mode": "sql", "sql": "DELETE FROM hr.employees"},
               headers=W)
    assert r.status_code == 400 and "Only SELECT or WITH" in r.json()["detail"]
    blank = c.post("/api/sources/A/fetch", json={"connection": "SAMPLE", "mode": "sql", "sql": "  "}, headers=W)
    assert blank.status_code == 400 and blank.json()["detail"] == "Give a table, or write the SQL, first."


def test_a_typed_password_is_held_and_never_shown(c, monkeypatch):
    monkeypatch.setenv("COMPARE_CONN_FAKE", f"postgresql://u:{FAKE_PW}@127.0.0.1:1/db")
    cx.save(cx.Connection(name="PG", kind="postgresql", host="127.0.0.1", port=1, database="db", user="u"))
    q = {"connection": "PG", "mode": "sql", "sql": "SELECT 1", "cap": 0}
    assert c.post("/api/sources/A/db", json=q, headers=W).json()["password"] == "asked"
    no = c.post("/api/sources/A/fetch", json=q, headers=W)
    assert no.status_code == 400 and no.json()["detail"] == "Type the password above first."
    e = wait(c, c.post("/api/sources/A/fetch", json={**q, "password": "typed-secret"}, headers=W).json())
    assert e["state"] == "error"                       # nothing listens on port 1, or no driver
    assert ws_of(c).passwords["PG"] == "typed-secret"
    assert c.post("/api/sources/A/db", json=q, headers=W).json()["password"] == "held"
    f = wait(c, c.post("/api/sources/B/fetch", json={**q, "connection": "FAKE"}, headers=W).json())
    assert f["state"] == "error"
    blob = c.get("/api/log").text + c.get("/api/sources").text
    assert "typed-secret" not in blob and FAKE_PW not in blob


def test_fetch_again_keeps_the_file_the_loaded_side_reads(c, sample):
    wait(c, c.post("/api/sources/A/fetch", json=TABLE, headers=W).json())
    first = panel(ws_of(c), "A").fetched.path
    c.post("/api/sources/A/load", json={"how": "database", "db": TABLE}, headers=W)
    c.delete("/api/sources/A/fetch", headers=W)
    assert Path(first).exists() and panel(ws_of(c), "A").fetched is None       # the loaded side reads it
    wait(c, c.post("/api/sources/A/fetch", json=TABLE, headers=W).json())
    second = panel(ws_of(c), "A").fetched.path
    assert second != first
    c.post("/api/sources/A/load", json={"how": "database", "db": TABLE}, headers=W)
    assert not Path(first).exists() and Path(second).exists()                  # nothing reads the first now
    c.delete("/api/sources/A/fetch", headers=W)
    assert Path(second).exists()


def _conf(tmp_path, a=None, b=None):
    conf = {"kind": "crosshire-compare config", "version": 1,
            "sides": {"A": a or {"name": "HR", "path": str(HR)},
                      "B": b or {"name": "PR", "path": str(EX / "payroll_employees.csv")}},
            "columns": [{"a": "emp_id", "b": "EmployeeId", "name": "emp_id", "type": "text", "key": True,
                         "compare": False},
                        {"a": "department", "b": "Dept", "name": "department", "type": "text", "key": False,
                         "compare": True}],
            "settings": {"trim": True, "tolerance": 0.25, "mode": "hash"},
            "filters": [{"Apply to": "Both", "Column": "department", "Operator": "=", "Value": "Finance",
                         "Type": "auto"}]}
    path = tmp_path / "hr_compare_pr__config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    return conf, path


def test_a_config_by_path_loads_both_sides_and_the_column_table(c, tmp_path):
    _, path = _conf(tmp_path)
    e = wait(c, c.post("/api/sources/config", json={"path": f'"{path}"'}, headers=W).json())
    assert e["state"] == "done" and e["kind"] == "Config"
    body = c.get("/api/sources").json()
    assert body["sides"]["A"]["name"] == "HR" and body["sides"]["B"]["rows"] == 2985
    cfg = body["config"]
    assert cfg["n"] == 1 and cfg["said"] == [{"tone": "success", "text": "Loaded - HR against PR, 2 pairs; comparing"}]
    assert cfg["boxes"]["A"]["how"] == "path" and cfg["boxes"]["settings"]["nokey_mode"] == "hash"
    ws = ws_of(c)
    assert list(ws.data["cmap"]["Common name"][:2]) == ["emp_id", "department"]
    assert ws.data["settings"]["tolerance"] == 0.25
    assert ws.data["filter_rows"].iloc[0]["Value"] == "Finance"
    assert "looks_like" in ws.data              # sampled by the config job: the setup page need not wait for the Compare
    wait(c, next(e for e in c.get("/api/log").json()["entries"] if e["kind"] == "Compare"))


def test_a_config_as_text_and_its_sentences(c, tmp_path):
    conf, _ = _conf(tmp_path, a={"name": "HR", "path": str(tmp_path / "gone.csv"), "uploaded": True})
    wait(c, c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W).json())
    body = c.get("/api/sources").json()
    said = body["config"]["said"]
    assert said[0]["tone"] == "error" and "file not found" in said[0]["text"] and "it was an upload" in said[0]["text"]
    assert said[-1] == {"tone": "info", "text": loading.CONFIG_PARTLY}
    assert body["sides"]["B"]["loaded"] is True and "cmap" not in ws_of(c).data
    bad = c.post("/api/sources/config", json={"text": "{not json"}, headers=W)
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Not loaded: not JSON")
    gone = c.post("/api/sources/config", json={"path": str(tmp_path / "nope.json")}, headers=W)
    assert gone.status_code == 400 and gone.json()["detail"].startswith("Could not read it")
    none = c.post("/api/sources/config", json={}, headers=W)
    assert none.status_code == 400 and none.json()["detail"] == "Give the config file, or its path."


def test_a_database_side_in_a_config_is_fetched_and_held(c, tmp_path, sample):
    sql = "SELECT * FROM payroll.employees"
    conf, _ = _conf(tmp_path, b={"name": "PR", "connection": "SAMPLE", "query": sql, "cap": 0})
    e = wait(c, c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W).json())
    assert e["state"] == "done"
    B = c.get("/api/sources").json()["sides"]["B"]
    assert B["is_database"] and B["rows"] == 2985 and B["fetched"]["rows"] == 2985
    plan = c.post("/api/sources/B/db", json={"connection": "SAMPLE", "mode": "sql", "sql": sql, "cap": 0},
                  headers=W).json()
    assert plan["held"]["rows"] == 2985


def test_a_config_needing_a_password_says_so(c, tmp_path):
    cx.save(cx.Connection(name="PG", kind="postgresql", host="127.0.0.1", port=1, user="u"))
    conf, _ = _conf(tmp_path, b={"name": "PR", "connection": "PG", "query": "SELECT 1", "cap": 0})
    wait(c, c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W).json())
    said = c.get("/api/sources").json()["config"]["said"]
    assert said[0] == {"tone": "warning", "text": "B: type the password for **PG**, then Fetch and Load"}


# ---- final review, group D ------------------------------------------------------------------
def _run_config(c, conf):
    return wait(c, c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W).json())


def test_a_config_cannot_get_around_the_data_folder(c, tmp_path, monkeypatch):
    conf, path = _conf(tmp_path)                       # both files lie in examples/, outside the data folder
    monkeypatch.setenv("COMPARE_DATA_DIR", str(tmp_path))
    _run_config(c, conf)
    body = c.get("/api/sources").json()
    assert not body["sides"]["A"]["loaded"] and not body["sides"]["B"]["loaded"]
    assert "COMPARE_DATA_DIR" in body["config"]["said"][0]["text"]
    assert c.get("/api/sources/A/preview").status_code == 409
    gone = _conf(tmp_path, a={"name": "HR", "path": str(tmp_path.parent / "no_such_file.csv")})[0]
    _run_config(c, gone)                               # outside the folder, a missing file is not told apart
    assert "COMPARE_DATA_DIR" in c.get("/api/sources").json()["config"]["said"][0]["text"]
    other = tmp_path.parent / "elsewhere.json"
    other.write_text(json.dumps(conf), encoding="utf-8")
    r = c.post("/api/sources/config", json={"path": str(other)}, headers=W)
    assert r.status_code == 400 and "COMPARE_DATA_DIR" in r.json()["detail"]
    r = c.post("/api/sources/config", json={"path": str(path)}, headers=W)           # inside the folder: read
    assert r.status_code == 200


def test_a_config_that_cannot_be_read_or_has_a_bad_value_is_a_sentence(c, tmp_path):
    latin = tmp_path / "latin.json"
    latin.write_bytes(b'{"name": "caf\xe9"}')
    r = c.post("/api/sources/config", json={"path": str(latin)}, headers=W)
    assert r.status_code == 400 and r.json()["detail"].startswith("Could not read it")
    conf, path = _conf(tmp_path, a={"name": "HR", "path": str(HR), "limit": "ten"})
    r = c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W)
    assert r.status_code == 400 and r.json()["detail"].startswith("Not loaded:")
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + json.dumps(_conf(tmp_path)[0]).encode())
    assert c.post("/api/sources/config", json={"path": str(bom)}, headers=W).status_code == 200


def test_an_upload_name_is_clean_for_windows(c, tmp_path):
    p = loading.upload_path("A", 'a.csv:x<>|?*".csv')
    assert p.name.startswith("cmp_A_") and not set(':<>|?*"') & set(p.name)
    assert loading.upload_path("A", "../../evil.csv").parent == p.parent
    r = c.post("/api/sources/A/upload?filename=report%3Astream.csv", content=b"a,b\n1,2\n", headers=W)
    assert r.status_code == 200
    assert ":" not in Path(panel(ws_of(c), "A").staged).name


def test_a_config_waits_while_a_compare_runs(c, tmp_path):
    from tablecmp.web import runs
    conf, _ = _conf(tmp_path)
    ws_of(c).running["x"] = {"id": "x", "kind": "Compare", "page": "Compare", "slot": "", "state": "running", "lines": []}
    r = c.post("/api/sources/config", json={"text": json.dumps(conf)}, headers=W)
    assert r.status_code == 409 and r.json()["detail"] == runs.BUSY


def test_a_config_keeps_the_pages_own_switches(c, tmp_path):
    conf, _ = _conf(tmp_path)
    ws_of(c).data["settings"] = {"display_rows": 500, "auto_rerun": True, "auto_profile": True}
    _run_config(c, conf)
    s = ws_of(c).data["settings"]
    assert s["display_rows"] == 500 and s["auto_rerun"] is True and s["auto_profile"] is True
    assert s["tolerance"] == 0.25                                    # what the config sets still wins
    wait(c, next(e for e in c.get("/api/log").json()["entries"] if e["kind"] == "Compare"))
    conf["settings"]["display_rows"] = 200
    _run_config(c, conf)
    assert ws_of(c).data["settings"]["display_rows"] == 200


def test_a_config_database_side_has_its_real_capped_flag_and_drops_the_old_fetch(c, tmp_path, sample):
    sql = "SELECT * FROM payroll.employees ORDER BY 1"
    first = wait(c, c.post("/api/sources/B/fetch", json={"connection": "SAMPLE", "mode": "sql", "sql": sql, "cap": 10},
                           headers=W).json())
    assert first["state"] == "done"
    old = panel(ws_of(c), "B").fetched.path
    conf, _ = _conf(tmp_path, b={"name": "PR", "connection": "SAMPLE", "query": sql, "cap": 10})
    _run_config(c, conf)
    B = c.get("/api/sources").json()["sides"]["B"]
    assert B["fetched"]["capped"] is True and B["rows"] == 10
    assert not Path(old).exists()


def test_an_edited_connection_does_not_offer_its_old_fetch(c, tmp_path):
    first = tmp_path / "one.duckdb"
    shutil.copy(EX / "sample.duckdb", first)
    cx.save(cx.Connection(name="D1", kind="duckdb", host=str(first)))
    q = {"connection": "D1", "mode": "table", "table": "hr.employees", "cap": 0}
    assert wait(c, c.post("/api/sources/A/fetch", json=q, headers=W).json())["state"] == "done"
    assert c.post("/api/sources/A/db", json=q, headers=W).json()["held"]
    second = tmp_path / "two.duckdb"
    shutil.copy(first, second)
    cx.save(cx.Connection(name="D1", kind="duckdb", host=str(second)))
    assert c.post("/api/sources/A/db", json=q, headers=W).json()["held"] is None
