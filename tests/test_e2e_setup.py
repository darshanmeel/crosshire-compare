"""The browser runs skip, with the command to fix it, when Playwright or its Chromium is missing."""
import sys
import types


def test_without_playwright_the_reason_names_the_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)     # import fails
    from tests.e2e.helpers import browser_missing
    why = browser_missing()
    assert why.startswith("Playwright is not installed") and "pip install -r requirements-dev.txt" in why


def test_without_its_chromium_the_reason_names_the_download(monkeypatch, tmp_path):
    class Fake:
        def __enter__(self):
            return types.SimpleNamespace(chromium=types.SimpleNamespace(executable_path=str(tmp_path / "none.exe")))

        def __exit__(self, *exc):
            return False
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = Fake
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    from tests.e2e.helpers import browser_missing
    assert "python -m playwright install chromium" in browser_missing()


def test_with_both_there_is_nothing_to_say(monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")

    class Fake:
        def __enter__(self):
            return types.SimpleNamespace(chromium=types.SimpleNamespace(executable_path=str(exe)))

        def __exit__(self, *exc):
            return False
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = Fake
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    from tests.e2e.helpers import browser_missing
    assert browser_missing() == ""
