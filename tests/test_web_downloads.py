# tests/test_web_downloads.py
"""The run's files over HTTP: the report for the viewer and to download, every file by name and
nothing else, the paired rows, the zip and the Parquet copies on request, and saves to a folder."""
import io
import json
import os
import zipfile
from pathlib import Path

from tests.webkit import W, auto_run, c, state, ws_of  # noqa: F401


def test_the_files_of_a_run_and_their_links(c):
    run = auto_run(c)["run"]
    rid, pair = run["id"], run["pair"]
    f = c.get(f"/api/results/{rid}/files").json()
    assert f["config"]["name"] == f"{pair}__config.json" and f["paired"] is False and f["zip"] is None
    labels = [x["label"] for x in f["files"]]
    assert labels[:3] == ["Cell differences", "Rows only in Left", "Rows only in Right"] and "Report" in labels
    assert not any(label.startswith("Config") for label in labels) and f["engine"]["name"] == f"{pair}__diff.html"
    assert f["report"] == f"{pair}__report.html" and f["out_fmt"] == "csv" and f["parquet"] is False
    assert f["save_folder"] == str(Path(os.environ["COMPARE_OUT_DIR"]) / f"{pair}__{rid}")
    r = c.get(f"/api/results/{rid}/file/{pair}__summary.json")
    assert r.status_code == 200 and json.loads(r.content)["pair"] == pair
    assert "attachment" in r.headers["content-disposition"]
    for bad in ("..%5C..%5Csecret.txt", "nope.csv", f"{pair}__paired.csv"):
        assert c.get(f"/api/results/{rid}/file/{bad}").status_code == 404, bad
    assert c.get(f"/api/results/19990101-000000/files").status_code == 404


def test_the_report_for_the_viewer_and_to_download(c):
    run = auto_run(c)["run"]
    r = c.get(f"/api/results/{run['id']}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "script-src 'none'" in r.headers["content-security-policy"]
    assert "attachment" not in r.headers.get("content-disposition", "")
    d = c.get(f"/api/results/{run['id']}/report", params={"limit": 500, "download": 1})
    assert d.headers["content-disposition"] == f'attachment; filename="{run["pair"]}__report.html"'
    assert ws_of(c).data["result"]["_report_key"][2] == 500


def test_paired_rows_zip_and_parquet_on_request(c):
    run = auto_run(c)["run"]
    rid, pair = run["id"], run["pair"]
    folder = Path(ws_of(c).data["result"]["folder"])
    f = c.post(f"/api/results/{rid}/paired", headers=W).json()
    assert f["paired"] is True and "Paired rows" in [x["label"] for x in f["files"]]
    (folder / f"{pair}__paired.csv").unlink()                 # swept, or removed by hand
    f = c.post(f"/api/results/{rid}/zip", headers=W).json()
    assert f["zip"]["name"] == f"{pair}__{rid}.zip" and (folder / f"{pair}__paired.csv").exists()
    z = c.get(f"/api/results/{rid}/file/{f['zip']['name']}")
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        assert {f"{pair}__paired.csv", f"{pair}__report.html", f"{pair}__summary.json"} <= set(zf.namelist())
    c.put("/api/compare/settings", json={"out_fmt": "parquet"}, headers=W)
    assert state(c)["stale"] is False                          # the format is not a setting
    f = c.get(f"/api/results/{rid}/files").json()
    assert f["out_fmt"] == "parquet" and f["parquet"] is False
    f = c.post(f"/api/results/{rid}/parquet", headers=W).json()
    assert f["parquet"] is True and f["zip"] is None and "paired (Parquet)" in [x["label"] for x in f["files"]]


def test_saves_land_in_the_run_folder_under_the_out_dir(c, tmp_path):
    run = auto_run(c)["run"]
    rid, pair = run["id"], run["pair"]
    target = tmp_path / "out" / f"{pair}__{rid}"
    r = c.post(f"/api/results/{rid}/save", json={"what": "all", "folder": str(target)}, headers=W)
    assert r.status_code == 200 and r.json()["tone"] == "success"
    on_disk = {p.name for p in target.iterdir()}
    assert {f"{pair}__paired.csv", f"{pair}__summary.json", f"{pair}__report.html", f"{pair}__config.json"} <= on_disk
    assert r.json()["text"].startswith(f"Saved {len(on_disk)} files to `") and r.json()["files"]["paired"] is True
    (target / f"{pair}__report.html").unlink()
    r = c.post(f"/api/results/{rid}/save", json={"what": "report", "folder": str(target)}, headers=W)
    assert r.json()["text"].startswith("Saved 1 file to") and (target / f"{pair}__report.html").exists()
    assert c.post(f"/api/results/{rid}/save", json={"what": "config", "folder": str(target)},
                  headers=W).status_code == 200
    bad = c.post(f"/api/results/{rid}/save", json={"what": "all", "folder": str(tmp_path / "elsewhere")}, headers=W)
    assert bad.status_code == 400 and bad.json()["detail"].startswith("Saves must stay under")
    assert not (tmp_path / "elsewhere").exists()
    blank = c.post(f"/api/results/{rid}/save", json={"what": "all", "folder": "  "}, headers=W)
    assert blank.status_code == 400 and blank.json()["detail"] == "Type a folder to save into."
    assert c.post(f"/api/results/{rid}/save", json={"what": "all", "folder": str(target)}).status_code == 403


def test_a_file_of_a_swept_run_says_the_run_is_gone(c):
    import shutil
    run = auto_run(c)["run"]
    rid, pair = run["id"], run["pair"]
    shutil.rmtree(ws_of(c).data["result"]["folder"])
    r = c.get(f"/api/results/{rid}/file/{pair}__summary.json")
    assert r.status_code == 410 and "Press **Compare**" in r.json()["detail"]
