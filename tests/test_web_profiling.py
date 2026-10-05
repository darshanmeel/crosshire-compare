"""The Profiling page over HTTP: Profile as a job, the profile as rows, frequencies, profile.csv, the save."""
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp import profiling
from tablecmp.keys import KEY_COLS
from tablecmp.observe import CORR_COLS, DEP_COLS, OUTLIER_COLS, PATTERN_COLS
from tablecmp.profile import STATS_COLS
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

W = {"X-Compare": "1"}
EX = Path(__file__).resolve().parent.parent / "examples"
HR = EX / "hr_employees.csv"


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
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


def wait(c, entry, seconds=120):
    t0 = time.time()
    while True:
        e = c.get(f"/api/jobs/{entry['id']}").json()
        if e["state"] != "running" or time.time() - t0 > seconds:
            return e
        time.sleep(0.05)


def load_p(c, path, name="Table"):
    r = c.post("/api/sources/P/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
    assert r.status_code == 200, r.text


def profile(c, name="Table"):
    r = c.post("/api/profiling/run", json={"name": name}, headers=W)
    assert r.status_code == 200, r.text
    return wait(c, r.json())


def test_nothing_to_show_before_a_profile(c):
    assert c.get("/api/profiling").json()["profile"] is None
    r = c.post("/api/profiling/run", json={"name": "Table"}, headers=W)
    assert r.status_code == 409 and r.json()["detail"] == "Load a table in the sidebar first."
    assert c.get("/api/profiling/freq", params={"column": "x"}).json()["detail"] == "Profile the table first."
    assert c.post("/api/profiling/run", json={"name": "Table"}).status_code == 403      # a write needs the header


def test_profile_runs_as_a_job_and_the_page_gets_it_as_rows(c, tmp_path):
    ws_of(c).passwords["PG"] = "s3cret-pw"                  # a typed password: in no response, ever
    load_p(c, HR, "HR")
    e = profile(c, "HR")
    assert e["state"] == "done" and e["kind"] == "Profile" and e["page"] == "Profiling"
    assert e["label"].startswith("Profile ready - key: emp_id in ")
    assert e["lines"][0] == "Looking at the values…" and "Looking for keys…" in e["lines"]
    log = c.get("/api/log").json()
    noted = log["entries"][0]                              # newest first: the notes, then the run
    v = c.get("/api/profiling").json()
    p = v["profile"]
    assert noted["kind"] == "Profile notes" and noted["lines"] == p["notes"]
    assert noted["label"] == f"{len(p['notes'])} things stand out"
    assert log["last"]["Profiling"]["id"] == e["id"]
    assert p["headline"].startswith("3,000 rows × 7 columns · key: emp_id")
    assert p["keys"]["tone"] == "success" and p["keys"]["text"].startswith("Key: **emp_id** - unique on every row. ")
    assert p["keys"]["table"]["columns"] == KEY_COLS and p["keys"]["table"]["rows"][0][0] == "emp_id"
    assert p["stats"]["columns"] == STATS_COLS and len(p["stats"]["rows"]) == 7
    assert p["notes"][0] == "key: emp_id - unique on every row"
    assert p["outliers"]["columns"] == OUTLIER_COLS and len(p["outliers"]["rows"]) == 2
    assert p["patterns"]["columns"] == PATTERN_COLS
    assert p["deps"]["columns"] == DEP_COLS and p["corr"]["columns"] == CORR_COLS
    assert p["freq"]["columns"] == ["emp_id", "first_name", "last_name", "department", "salary", "hire_date", "active"]
    assert p["freq"]["picked"] == ["emp_id"]
    assert p["freq"]["titles"]["emp_id"] == "**emp_id** - text · 3,000 distinct · 0.0% null"
    d = c.get("/api/profiling/defaults", params={"name": "HR"}).json()
    assert v["stale"] is False and d["csv_name"] == "HR__profile.csv"
    assert d["save_folder"] == str(tmp_path / "out" / f"HR__{v['made']}")
    f = c.get("/api/profiling/freq", params={"column": "department"}).json()
    assert f["top"]["columns"] == ["Value", "Count", "%"] and f["top"]["rows"][0] == ["Support", 412, 13.73]
    for text in (str(v), str(f), str(log), c.get("/api/sources").text):
        assert "s3cret-pw" not in text


def test_a_column_with_an_odd_name_has_its_frequencies(c, tmp_path):
    p = tmp_path / "odd.csv"
    p.write_text("a/b %,id\nx,1\ny,2\nx,3\n", encoding="utf-8")
    load_p(c, p)
    assert profile(c)["state"] == "done"
    f = c.get("/api/profiling/freq", params={"column": "a/b %"}).json()
    assert f["column"] == "a/b %" and f["top"]["rows"] == [["x", 2, 66.67], ["y", 1, 33.33]]
    assert f["title"] == "**a/b %** - text · 2 distinct · 0.0% null"
    r = c.get("/api/profiling/freq", params={"column": "nope"})
    assert r.status_code == 404 and r.json()["detail"] == "No column called nope in this profile."


def test_no_key_and_an_empty_table_still_come_as_rows(c, tmp_path):
    rows = ["dept,grade,flag"] + [f"{'Sales' if i % 3 else 'Ops'},G{i % 4},{'Y' if i % 2 else 'N'}" for i in range(24)]
    (tmp_path / "nokey.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    load_p(c, tmp_path / "nokey.csv")
    assert profile(c)["label"].startswith("Profile ready - no key in ")
    p = c.get("/api/profiling").json()["profile"]
    assert p["keys"]["tone"] == "warning"
    assert p["keys"]["text"].startswith("Nothing up to 5 columns is unique - the closest are below. ")
    assert p["freq"]["picked"] == [] and p["outliers"]["rows"] == []
    (tmp_path / "empty.csv").write_text("id,name\n", encoding="utf-8")
    load_p(c, tmp_path / "empty.csv")
    assert profile(c)["state"] == "done"
    p = c.get("/api/profiling").json()["profile"]
    assert p["notes"] == [] and p["keys"]["text"].startswith("Nothing up to 5 columns is unique. ")
    assert p["stats"]["rows"][0][-3:] == [None, None, None]      # no lengths on an empty column: null, not NaN


def test_profile_csv_and_the_six_file_save(c, tmp_path):
    load_p(c, HR)
    profile(c, "HR")
    r = c.get("/api/profiling/profile.csv", params={"name": "HR"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="HR__profile.csv"' in r.headers["content-disposition"]
    assert r.text.startswith("Column,Type,Rows,Nulls,Null %,")
    folder = c.get("/api/profiling/defaults", params={"name": "HR"}).json()["save_folder"]
    s = c.post("/api/profiling/save", json={"name": "HR", "folder": folder}, headers=W)
    assert s.status_code == 200
    names = ["HR__profile.csv", "HR__keys.csv", "HR__notes.txt", "HR__outliers.csv", "HR__patterns.csv",
             "HR__dependencies.csv"]
    assert s.json()["text"] == f"Saved 6 files to `{Path(folder).resolve()}`: " + ", ".join(names)
    assert sorted(p.name for p in Path(folder).iterdir()) == sorted(names)
    assert ws_of(c).data["save_dir"] == str((tmp_path / "out").resolve())
    blank = c.post("/api/profiling/save", json={"name": "HR", "folder": "  "}, headers=W)
    assert blank.status_code == 400 and blank.json()["detail"] == "Type a folder to save into."
    out = c.post("/api/profiling/save", json={"name": "HR", "folder": str(tmp_path / "elsewhere")}, headers=W)
    assert out.status_code == 400 and out.json()["detail"].startswith("Saves must stay under")
    assert not (tmp_path / "elsewhere").exists()


def test_stale_after_the_values_options_change_and_gone_when_the_table_is_loaded_again(c):
    load_p(c, HR)
    profile(c)
    assert c.get("/api/profiling").json()["stale"] is False
    ws_of(c).data["settings"] = {"trim": False}            # How values are read, changed on the Compare page
    v = c.get("/api/profiling").json()
    assert v["stale"] is True and v["profile"] is not None
    load_p(c, HR)                                          # the same file, loaded again: a new table
    assert c.get("/api/profiling").json()["profile"] is None


def test_a_failed_profile_says_why_and_keeps_the_last_one(c, monkeypatch):
    load_p(c, HR)
    profile(c)
    made = c.get("/api/profiling").json()["made"]

    def boom(*_args, **_kwargs):
        raise OverflowError("date value out of range")
    monkeypatch.setattr(profiling, "profile_single", boom)
    e = profile(c)
    assert e["state"] == "error" and e["lines"][-1] == "date value out of range"
    assert e["label"] == "Profiling - could not finish"
    v = c.get("/api/profiling").json()
    assert v["profile"] is not None and v["made"] == made


def test_typing_a_name_does_not_rebuild_the_profile(c, monkeypatch):
    from tablecmp.web import routes_profiling as rp
    load_p(c, HR)
    profile(c, "HR")
    built = []
    real = rp.profile_view
    monkeypatch.setattr(rp, "profile_view", lambda prof: built.append(1) or real(prof))
    first = c.get("/api/profiling").json()
    for name in ("C", "Cu", "Customers"):
        d = c.get("/api/profiling/defaults", params={"name": name}).json()
        assert d["csv_name"] == f"{name}__profile.csv" and d["save_folder"].endswith(f"{name}__{first['made']}")
    again = c.get("/api/profiling").json()
    assert len(built) == 1 and again["profile"] == first["profile"]
    profile(c, "HR")                                       # a new profile is built again
    c.get("/api/profiling")
    assert len(built) == 2


def test_a_save_that_stops_part_way_says_which_files_were_written(c, tmp_path, monkeypatch):
    import os as _os
    load_p(c, HR)
    profile(c, "HR")
    folder = str(tmp_path / "out" / "pick")
    real = _os.replace
    def locked(src, dst):
        if str(dst).endswith("HR__outliers.csv"):
            raise PermissionError(13, "Permission denied", str(dst))
        return real(src, dst)
    monkeypatch.setattr("tablecmp.results.os.replace", locked)
    r = c.post("/api/profiling/save", json={"name": "HR", "folder": folder}, headers=W)
    assert r.status_code == 400
    msg = r.json()["detail"]
    assert msg.startswith("Could not write HR__outliers.csv - it may be open in another program. Saved before that: ")
    assert "HR__profile.csv" in msg and "Errno" not in msg and "Permission denied" not in msg
    assert not list(Path(folder).glob("*.part"))
