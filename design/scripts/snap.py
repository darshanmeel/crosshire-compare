#!/usr/bin/env python3
"""Screenshot the real app in the states the mockups show, for a side-by-side with
design/mockups/screenshots/. Run from the repo root after `npm run build`:

    python design/scripts/snap.py                 # -> design/progress/<nn>-<name>.png
    python design/scripts/snap.py --url http://127.0.0.1:8501   # against a server you started

Needs pytest-playwright's Chromium (python -m playwright install chromium). Starts its own server
on a free port with temp folders (like tests/e2e/conftest.py) unless --url is given, loads the
example pair through the API with the browser's own cookie, runs Auto, then Profile, and clicks
through the screens by their accessible names. A screen it cannot reach is reported, not fatal:
the redesign is built one screen at a time, so early runs will skip most of them."""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "examples"
OUT = ROOT / "design" / "progress"
W = {"X-Compare": "1"}
WIDTH, HEIGHT = 1440, 900


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(tmp: Path) -> tuple[subprocess.Popen, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("COMPARE_CONN") and k not in ("COMPARE_DATA_DIR", "COMPARE_WEB_PORT")}
    env.update({
        "COMPARE_WORK_DIR": str(tmp / "work"), "COMPARE_OUT_DIR": str(tmp / "out"),
        "COMPARE_CONNECTIONS": str(tmp / "connections.json"),
        "COMPARE_CONN_SAMPLE": "duckdb:///" + (EX / "sample.duckdb").as_posix(),
    })
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "tablecmp.web", "--no-browser", "--port", str(port)],
                            env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while True:
        if proc.poll() is not None or time.time() - t0 > 60:
            raise SystemExit("the server did not start - is the page built? (cd web && npm run build)")
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1).close()
            return proc, url
        except OSError:
            time.sleep(0.1)


class Shooter:
    def __init__(self, page, url: str):
        self.page, self.url, self.taken, self.missed = page, url, [], []

    # --- API through the browser's cookie -------------------------------------------------
    def api(self, method: str, path: str, body: dict | None = None) -> dict:
        r = self.page.request.fetch(self.url + path, method=method, data=body, headers=W)
        if not r.ok:
            raise RuntimeError(f"{method} {path} -> {r.status}: {r.text()[:200]}")
        return r.json() if r.text() else {}

    def wait_job(self, entry: dict, seconds: float = 600) -> dict:
        t0 = time.time()
        while True:
            e = self.api("GET", f"/api/jobs/{entry['id']}")
            if e["state"] != "running":
                return e
            if time.time() - t0 > seconds:
                raise RuntimeError(f"{e['kind']} still running after {seconds}s")
            time.sleep(0.1)

    def settle(self) -> None:
        while any(e["state"] == "running" for e in self.api("GET", "/api/log")["entries"]):
            time.sleep(0.1)

    # --- browser ---------------------------------------------------------------------------
    def goto(self, path: str = "/") -> None:
        self.page.goto(self.url + path)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(300)

    def shot(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        self.page.wait_for_timeout(200)
        self.page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        self.taken.append(name)
        print("  shot", name)

    def click(self, name: str | re.Pattern, roles=("tab", "link", "button", "radio")) -> bool:
        for role in roles:
            loc = self.page.get_by_role(role, name=name)
            if loc.count():
                loc.first.click()
                self.page.wait_for_timeout(400)
                return True
        return False

    def screen(self, name: str, how) -> None:
        try:
            ok = how()
            if ok is False:
                raise RuntimeError("control not found")
            self.shot(name)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            self.missed.append((name, f"{type(exc).__name__}: {exc}"))
            print("  skip", name, "-", exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="a running server; otherwise one is started on a free port")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    proc = None
    tmp = Path(tempfile.mkdtemp(prefix="snap-"))
    url = args.url
    if not url:
        proc, url = start_server(tmp)
    print("app at", url)
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            s = Shooter(page, url)

            # 01 home
            s.goto("/")
            s.shot("01-home")

            # 17 run from config (from the header)
            s.screen("17-run-from-config", lambda: s.click(re.compile(r"run from (a )?config", re.I)))
            s.goto("/")

            # 02 connections drawer
            s.screen("02-connections", lambda: s.click(re.compile(r"^connections", re.I)))
            s.goto("/")

            # 04 loaded + auto (the API, with the page's cookie), then the page re-read
            s.api("POST", "/api/sources/A/load", {"how": "path", "path": str(EX / "hr_employees.csv"), "name": "HR"})
            s.api("POST", "/api/sources/B/load", {"how": "path", "path": str(EX / "payroll_employees.csv"), "name": "Payroll"})
            s.api("PUT", "/api/compare/settings", {"auto_profile": False})
            s.wait_job(s.api("POST", "/api/auto"))
            s.settle()
            # Auto pairs last_name with FullName but leaves the split to the person (README walkthrough):
            # add "part 2 split by space" on the Payroll side so the counts match tests/COUNTS.md.
            try:
                s.api("POST", "/api/setup/steps", {"canon": "last_name", "which": "B", "action": "add",
                                                   "step": {"op": "part N split by S", "params": {"s": " ", "n": "2"}}})
                s.wait_job(s.api("POST", "/api/compare"))
                s.settle()
            except Exception as exc:  # noqa: BLE001
                print("  note: could not add the split step -", exc)
            s.goto("/")
            s.shot("04-loaded")

            # 05 transform editor - a transform summary link or the Values step
            s.screen("05-transform", lambda: s.click(re.compile(r"split by|remove thousands|transform", re.I)))
            s.goto("/")
            # 06 rows editor
            s.screen("06-rows", lambda: s.click(re.compile(r"^edit rows|^rows$", re.I)))
            s.goto("/")

            # 08-12 results tabs
            s.screen("08-results-summary", lambda: s.click(re.compile(r"^results|^summary", re.I)))
            s.screen("09-results-diffs", lambda: s.click(re.compile(r"differing rows", re.I)))
            s.screen("10-results-onesided", lambda: s.click(re.compile(r"one-sided rows", re.I)))
            s.screen("11-results-report", lambda: s.click(re.compile(r"^report$", re.I)))
            s.screen("12-results-downloads", lambda: s.click(re.compile(r"^downloads$", re.I)))

            # 13 log
            s.screen("13-log", lambda: s.click(re.compile(r"^log\b", re.I)))
            s.goto("/")

            # 03 side B from the sample DuckDB (connection SAMPLE from the environment)
            def db_side():
                db = {"connection": "SAMPLE", "mode": "table", "table": "payroll.employees"}
                s.wait_job(s.api("POST", "/api/sources/B/fetch", db))
                s.api("POST", "/api/sources/B/load", {"how": "database", "db": db, "name": "Payroll"})
                s.goto("/")
            s.screen("03-source-database", db_side)

            # 14-16 profile
            s.goto("/")
            s.screen("14-profile-home", lambda: s.click(re.compile(r"^profil(e|ing)$", re.I), roles=("radio", "tab", "link", "button")))
            def profile_result():
                s.api("POST", "/api/sources/P/load", {"how": "path", "path": str(EX / "hr_employees.csv"), "name": "HR"})
                s.wait_job(s.api("POST", "/api/profiling/run", {"name": ""}))
                s.goto("/")
                s.click(re.compile(r"^profil(e|ing)$", re.I), roles=("radio", "tab", "link", "button"))
            s.screen("15-profile-result", profile_result)
            s.screen("16-profile-column", lambda: s.click(re.compile(r"^salary$", re.I)))

            b.close()
    finally:
        if proc:
            proc.terminate()
    print(f"\n{len(s.taken)} screenshots in {OUT}")
    if s.missed:
        print("not reached yet (expected while the redesign is in progress):")
        for name, why in s.missed:
            print(f"  {name}: {why}")
    print("07-running is not captured: the sample compare finishes in under a second.")


if __name__ == "__main__":
    main()
