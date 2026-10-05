# tests/webflow.py
"""What the API flow tests share - in place of tests/test_apptest.py's helpers: a client on temp
folders that keeps every response body, the sample counts, the fake password and the grep for
it, and one helper per thing a person does on the page.

ROUTES names the route behind each helper; phases 3-5 built them. If one moves, change ROUTES
(and the reading in run() / profile()) - never a test. A route with {run_id} in it is called for
the run on the page: Flow.call fills the id in from GET /api/compare."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.loading import DEFAULT_NAMES
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
W = {"X-Compare": "1"}
FAKE_PW = "example-not-a-real-password"
COUNTS = dict(t.split("=") for t in (ROOT / "tests/COUNTS.md").read_text(encoding="utf-8").split()
              if "=" in t)            # matched=... only_left=... only_right=... diff_rows=... cells=... key=...
COUNT_KEYS = ("matched", "only_left", "only_right", "diff_rows", "cells")
OUTPUT_SUFFIXES = ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "report.html", "diff.html", "profile.csv")
_SUMMARY_KEY = {"matched": "matched_rows", "only_left": "only_left", "only_right": "only_right",
                "diff_rows": "diff_rows", "cells": "cell_diffs"}     # COUNT_KEYS in summary.json's "result"

ROUTES: dict[str, tuple[str, str]] = {
    # phase 3 (routes_setup.py, prefix /api/setup)
    "columns":      ("GET",  "/api/setup"),                       # the column table: rows, specs, rev
    "names":        ("PUT",  "/api/setup/names"),                 # NamesIn: A, B (the Name boxes)
    "settings":     ("PUT",  "/api/setup/settings"),              # SettingsIn: trim, empty_as_null, ignore_case, ...
    "step":         ("POST", "/api/setup/steps"),                 # StepsIn: canon, which, action, step{op, params}
    "filters":      ("PUT",  "/api/setup/filters"),               # FiltersIn: rows (the "Apply to"... aliases)
    "keys":         ("GET",  "/api/setup/keys"),                  # the Key section: keys, formats, ...
    "mapping":      ("POST", "/api/setup/mapping"),               # MappingIn: text (a mapping.json)
    "profile_both": ("GET",  "/api/setup/profile"),               # Profile both files, as held
    # phase 4 (routes_compare.py, routes_results.py, routes_downloads.py)
    "state":        ("GET",  "/api/compare"),                     # gate, strip, settings, stale, run{id, pair, keys...}
    "page_settings": ("PUT", "/api/compare/settings"),            # display_rows, auto_rerun, out_fmt, auto_profile
    "auto":         ("POST", "/api/auto"),                        # Auto (a job, then Compare)
    "compare":      ("POST", "/api/compare"),                     # Compare (a job)
    "summary":      ("GET",  "/api/results/{run_id}/summary"),    # Summary: counts, ledger{columns, rows}, tones
    "columns_view": ("GET",  "/api/results/{run_id}/columns"),    # Columns & values
    "files":        ("GET",  "/api/results/{run_id}/files"),      # Downloads: files, paired, zip, save_folder
    "paired":       ("POST", "/api/results/{run_id}/paired"),     # Downloads, write the paired rows
    "zip":          ("POST", "/api/results/{run_id}/zip"),        # Downloads, the zip
    "parquet":      ("POST", "/api/results/{run_id}/parquet"),    # Downloads, Parquet copies
    "save":         ("POST", "/api/results/{run_id}/save"),       # SaveIn: what (report|config|all), folder
    # phase 5 (routes_profiling.py, prefix /api/profiling)
    "profile":      ("POST", "/api/profiling/run"),               # NameIn: name; a job
    "profile_view": ("GET",  "/api/profiling"),                   # {"profile": {...} | None, "stale", "made", ...}
    "profile_defaults": ("GET", "/api/profiling/defaults"),       # ?name= -> {"csv_name", "save_folder"}
    # phase 2 (routes_sources.py)
    "config":       ("POST", "/api/sources/config"),              # ConfigIn: path | text; a job
}


class Flow:
    """A TestClient that keeps every response body, so a test can grep them all for a secret."""

    def __init__(self, client: TestClient):
        self.c = client
        self.bodies: list[str] = []

    def _keep(self, r):
        self.bodies.append(r.text)
        return r

    def get(self, url: str, **params):
        return self._keep(self.c.get(url, params=params or None))

    def send(self, method: str, url: str, body: dict | None = None):
        return self._keep(self.c.request(method, url, json=body, headers=W))

    def run_id(self) -> str:
        run = self.get("/api/compare").json()["run"]
        assert run is not None, "no run on the page"
        return run["id"]

    def call(self, name: str, body: dict | None = None, **path_args):
        method, url = ROUTES[name]
        if "{run_id}" in url and "run_id" not in path_args:
            path_args["run_id"] = self.run_id()
        url = url.format(**path_args)
        return self.get(url) if method == "GET" else self.send(method, url, body)

    def ws(self):
        return self.c.app.state.workspaces.get(self.c.cookies.get(COOKIE))


def boot(monkeypatch, tmp_path) -> Flow:
    """A fresh page on temp folders: the sample DuckDB as SAMPLE, a connection whose URI holds the
    fake password as FAKE, and nothing of the user's own connections read or written."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    monkeypatch.delenv("COMPARE_TABLE_FORMATS", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    monkeypatch.setenv(cx.ENV_PREFIX + "SAMPLE", "duckdb:///" + (EX / "sample.duckdb").as_posix())
    monkeypatch.setenv(cx.ENV_PREFIX + "FAKE", f"postgresql://u:{FAKE_PW}@nowhere:5432/db")
    f = Flow(TestClient(create_app()))
    f.get("/api/workspace")
    return f


def wait(f: Flow, entry: dict, seconds: float = 600) -> dict:
    """A job's entry once it has ended."""
    t0 = time.time()
    while True:
        e = f.get(f"/api/jobs/{entry['id']}").json()
        if e["state"] != "running":
            return e
        assert time.time() - t0 < seconds, f"{e['kind']} still running after {seconds}s"
        time.sleep(0.05)


def settle(f: Flow, seconds: float = 600) -> None:
    """Until no job in the Log runs - Auto starts Compare when it is done, a config starts both."""
    t0 = time.time()
    while any(e["state"] == "running" for e in f.get("/api/log").json()["entries"]):
        assert time.time() - t0 < seconds, "a job is still running"
        time.sleep(0.05)


def load_path(f: Flow, tag: str, path: Path, **kw) -> dict:
    """Load a file as the page does: the Name box says what it holds - its default when untouched."""
    body = {"how": "path", "path": str(path), "name": DEFAULT_NAMES[tag], **kw}
    r = f.send("POST", f"/api/sources/{tag}/load", body)
    assert r.status_code == 200, r.text
    return r.json()


def fetch_and_load(f: Flow, tag: str, conn: str, table: str, **kw) -> dict:
    db = {"connection": conn, "mode": "table", "table": table}
    done = wait(f, f.send("POST", f"/api/sources/{tag}/fetch", db).json())
    assert done["state"] == "done", done
    body = {"how": "database", "db": db, "name": DEFAULT_NAMES[tag], **kw}
    r = f.send("POST", f"/api/sources/{tag}/load", body)
    assert r.status_code == 200, r.text
    return r.json()


def run(f: Flow) -> dict:
    """The run on the page now, in one shape: the pair, its folder, its keys, the five counts
    (read from the run's own summary.json) and the run as the Compare state says it."""
    state = f.call("state").json()
    body = state["run"]
    assert body is not None, state
    folder = Path(f.ws().data["result"]["folder"])
    res = json.loads((folder / f"{body['pair']}__summary.json").read_text(encoding="utf-8"))["result"]
    return {"pair": body["pair"], "folder": folder, "keys": list(body["keys"]),
            "counts": {k: int(res[_SUMMARY_KEY[k]]) for k in COUNT_KEYS}, "body": body}


def auto(f: Flow, profile: bool = False) -> dict:
    """Auto, with or without its profile tick, through to the Compare it starts."""
    f.call("page_settings", {"auto_profile": profile})
    r = f.call("auto")
    assert r.status_code == 200, r.text
    assert wait(f, r.json())["state"] == "done"
    settle(f)
    return run(f)


def compare(f: Flow) -> dict:
    r = f.call("compare")
    assert r.status_code == 200, r.text
    assert wait(f, r.json())["state"] == "done"
    return run(f)


def expected_counts() -> dict[str, int]:
    return {k: int(COUNTS[k]) for k in COUNT_KEYS}


def rows(frame: dict) -> list[dict]:
    """A table as the server sends it ({"columns": [...], "rows": [[...]]}) as one dict per row."""
    return [dict(zip(frame["columns"], r)) for r in frame["rows"]]


def profile(f: Flow) -> dict:
    """Profile the P table and wait; the profile phase 5 serves for it (headline, keys, stats, notes...)."""
    r = f.call("profile", {"name": ""})
    assert r.status_code == 200, r.text
    done = wait(f, r.json())
    assert done["state"] == "done", done
    return f.call("profile_view").json()["profile"]


def no_secret(f: Flow, *folders: Path) -> None:
    """The grep: the fake password is in no response this flow got and no file it wrote."""
    f.get("/api/log")
    blob = "\n".join(f.bodies)
    for d in folders:
        for p in Path(d).rglob("*"):
            if p.is_file() and p.suffix in (".csv", ".json", ".html", ".txt", ".yml"):
                blob += "\n" + p.read_text(encoding="utf-8", errors="ignore")
    assert FAKE_PW not in blob and "example-not" not in blob
