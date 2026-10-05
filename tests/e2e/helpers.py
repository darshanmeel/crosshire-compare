"""What the browser runs share: why they would skip, and loading a file the way a person does."""
from __future__ import annotations

import re
from pathlib import Path

INSTALL = "pip install -r requirements-dev.txt, then once: python -m playwright install chromium"
EX = Path(__file__).resolve().parents[2] / "examples"
FAKE_PW = "example-not-a-real-password"


def browser_missing() -> str:
    """'' when Playwright and its Chromium are both here, else the sentence the skip shows."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return f"Playwright is not installed - {INSTALL}"
    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
    except Exception as exc:                     # the driver itself would not start
        return f"Playwright could not start ({type(exc).__name__}: {exc}) - {INSTALL}"
    if not Path(exe).exists():
        return "The Playwright Chromium is not downloaded - run: python -m playwright install chromium"
    return ""


def load_path(page, panel: str, path: Path) -> None:
    """Path on disk in one side panel, the path typed, Load pressed, the loaded line waited for."""
    from playwright.sync_api import expect
    box = page.get_by_role("region", name=panel, exact=True)
    box.get_by_label("Path on disk").check()
    box.get_by_label("Path to CSV or JSON").fill(str(path))
    box.get_by_role("button", name=re.compile(r"^Load")).click()
    expect(box.get_by_text(path.name).first).to_be_visible(timeout=60_000)
