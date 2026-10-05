"""The page is built by npm into tablecmp/web_dist, which is committed - so a Python-only user
never needs Node. This fails when web/ changed after the last build: run `npm run build` in web/."""
import hashlib
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tablecmp.web.app import DIST, create_app

WEB = Path(__file__).resolve().parent.parent / "web"
_TOP = ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json")


def source_hash(root: Path) -> str:
    """The same sha256 web/scripts/source-hash.mjs writes after a build: the top files and what git
    tracks under src/, so a scratch file there changes nothing."""
    out = subprocess.run(["git", "ls-files", "-z", "--", "src"], cwd=root, capture_output=True, check=True).stdout
    tracked = [n for n in out.decode("utf-8").split("\0") if n]
    h = hashlib.sha256()
    for rel in sorted([*_TOP, *tracked]):
        h.update((rel + "\n").encode())
        h.update((root / rel).read_bytes().decode("utf-8").replace("\r\n", "\n").encode())
        h.update(b"\n")
    return h.hexdigest()


def test_the_committed_build_is_from_the_current_sources():
    said = (DIST / "source-hash.txt").read_text(encoding="utf-8").strip()
    assert said == source_hash(WEB), "web/ changed since the last build - run `npm run build` in web/"


def test_an_untracked_file_under_src_does_not_change_the_hash():
    before = source_hash(WEB)
    scratch = WEB / "src" / "scratch-not-tracked.ts"
    scratch.write_text("export const x = 1\n", encoding="utf-8")
    try:
        assert source_hash(WEB) == before
    finally:
        scratch.unlink()


def test_the_page_is_served_at_the_root():
    r = TestClient(create_app()).get("/")
    assert r.status_code == 200 and '<div id="root">' in r.text


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_index_html_is_never_cached_but_the_hashed_assets_are_left_alone(path):
    c = TestClient(create_app())
    assert c.get(path).headers["cache-control"] == "no-cache"
    asset = next((DIST / "assets").glob("*.js")).name
    assert "no-cache" not in c.get(f"/assets/{asset}").headers.get("cache-control", "")


def test_without_a_build_the_root_says_how_to_make_one(tmp_path, monkeypatch):
    import tablecmp.web.app as appmod
    monkeypatch.setattr(appmod, "DIST", tmp_path / "none")
    r = TestClient(appmod.create_app()).get("/")
    assert r.status_code == 503 and "npm run build" in r.text
