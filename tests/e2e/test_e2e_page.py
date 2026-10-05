"""The whole page in a real browser, three times: the sample pair compared, one table profiled,
and the Compare settings kept across the Compare | Profiling switch. Each test gets its own
browser context - its own cookie, so its own workspace."""
import re
from pathlib import Path

import pytest

pytest.importorskip("pytest_playwright", reason="pip install -r requirements-dev.txt")

from playwright.sync_api import Page, expect  # noqa: E402

from tests.e2e.helpers import EX, FAKE_PW, load_path  # noqa: E402

# The counts come from tests/COUNTS.md, so this module stands on its own.
_COUNTS_FILE = Path(__file__).resolve().parents[1] / "COUNTS.md"
COUNTS = dict(line.split("=") for line in _COUNTS_FILE.read_text().split() if "=" in line)

LONG = 600_000          # ms: Auto with its profile on a slow machine


STEP_LINK = re.compile(r"^(Add a step to|Steps for) ")


def _open_how(page: Page) -> None:
    """How values are read sits in the values editor, reached from a pair's Transform link in the
    column table - from the results, Edit setup first. The view outlives the page switch, so the
    editor may already be on screen."""
    if page.get_by_label("Ignore case in values").is_visible():
        return
    edit = page.get_by_role("button", name="Edit setup")
    if edit.is_visible():
        edit.click()
    page.get_by_role("button", name=STEP_LINK).first.click()
    expect(page.get_by_role("group", name="How values are read")).to_be_visible()


def _pair(page: Page) -> None:
    load_path(page, "File A", EX / "hr_employees.csv")
    load_path(page, "File B", EX / "payroll_employees.csv")
    page.get_by_role("button", name="Figure it all out and compare").click()


def test_the_sample_pair_compared_in_the_browser(page: Page, server):
    page.goto(server["url"])
    _pair(page)
    expect(page.locator(".verdict")).to_contain_text(
        f"{int(COUNTS['matched']):,} rows matched on {COUNTS['key']}", timeout=LONG)
    assert FAKE_PW not in page.content()


def test_one_table_profiled_in_the_browser(page: Page, server):
    page.goto(server["url"])
    page.get_by_role("radiogroup", name="Page").get_by_label("Profiling").check()
    load_path(page, "File", EX / "hr_employees.csv")
    page.get_by_role("button", name="Profile", exact=True).click()
    expect(page.get_by_text("3,000 rows × 7 columns · key: emp_id").first).to_be_visible(timeout=LONG)
    for fold in ("Outliers", "Patterns", "Dependencies"):
        expect(page.get_by_text(fold, exact=True).first).to_be_visible()
    assert FAKE_PW not in page.content()


def test_settings_survive_the_profiling_page(page: Page, server):
    page.goto(server["url"])
    page.get_by_role("region", name="File A", exact=True).get_by_label("Name").fill("HR")
    _pair(page)
    expect(page.locator(".verdict")).to_be_visible(timeout=LONG)
    _open_how(page)
    # a switch that lives on the server: it flips after the round trip, so click, then wait for it
    page.get_by_label("Ignore case in values").click()
    expect(page.get_by_label("Ignore case in values")).to_be_checked()
    switch = page.get_by_role("radiogroup", name="Page")
    switch.get_by_label("Profiling").check()
    expect(page.get_by_role("region", name="File", exact=True)).to_be_visible()
    switch.get_by_label("Compare").check()
    _open_how(page)
    expect(page.get_by_label("Ignore case in values")).to_be_checked()
    steps = page.get_by_role("navigation", name="Steps")
    steps.get_by_role("button", name="Columns").click()      # the rail, back to the setup
    expect(page.get_by_role("region", name="File A", exact=True).get_by_label("Name")).to_have_value("HR")
    steps.get_by_role("button", name="Results").click()
    expect(page.locator(".verdict")).to_be_visible()
