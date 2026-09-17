# tests/test_ui_log.py
"""The run disc and the Log panel: every run is an entry with its lines and its time, the
disc stays on the page once the run is done - on the page it ran on - the panel is the last
thing on the page, the log is capped. The pure parts run without an app - the page's
st.empty() stood in for."""
import re

import pytest
import streamlit

from tablecmp import ui_log
from tests.test_apptest import EX, _boot, _load_path, _ok

AT = re.compile(r"^\d\d:\d\d:\d\d$")


# ---- the app --------------------------------------------------------------------
def _auto(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    for tag, f in (("A", "hr_employees.csv"), ("B", "payroll_employees.csv")):
        _load_path(at, tag, EX / f)
    _ok(at.button(key="auto_btn").click().run())
    return _ok(at.run())                           # the auto_go rerun: Compare


def _log_labels(at) -> list[str]:
    return [e.label for e in at.main.expander if e.label.startswith("Log - ")]


def test_auto_and_compare_land_in_the_log(monkeypatch, tmp_path):
    at = _auto(monkeypatch, tmp_path)
    log = at.session_state["log"]
    kinds = [e["kind"] for e in log]
    assert kinds.index("Auto") < kinds.index("Auto decisions") < kinds.index("Compare") == len(log) - 1
    assert all(AT.match(e["at"]) for e in log), [e["at"] for e in log]
    auto, decided, compared = (next(e for e in log if e["kind"] == k) for k in ("Auto", "Auto decisions", "Compare"))
    assert auto["state"] == "done" and auto["seconds"] > 0 and auto["lines"]
    assert auto["label"].startswith("Worked out in ") and "key: emp_id" in auto["label"]
    assert decided["state"] == "done" and decided["seconds"] is None
    assert decided["lines"] == at.session_state["auto_notes"] and len(decided["lines"]) > 0
    assert decided["label"] == f"{len(decided['lines'])} decisions - every one a cell in the column table"
    assert compared["state"] == "done" and compared["seconds"] > 0 and compared["lines"]
    assert compared["label"].startswith("Compared in ") and compared["label"].endswith("s")
    assert at.session_state["last_run"] == {"Compare": compared}
    # the page: no Auto expander any more, one Log expander and it comes last, the done disc at the top
    assert not [e for e in at.expander if e.label.startswith("What Auto decided")]
    assert _log_labels(at) == ["Log - 3 entries"] and at.main.expander[-1].label == "Log - 3 entries"
    discs = [m.value for m in at.main.markdown if 'class="runbox' in m.value]
    assert len(discs) == 1 and 'class="runbox done"' in discs[0], discs
    assert "✓" in discs[0] and compared["label"] in discs[0]
    book = next(m.value for m in at.main.markdown if 'class="logbook"' in m.value)
    assert book.index("Compare</span>") < book.index("Auto decisions</span>") < book.index(">Auto</span>")
    assert not re.search(r"in \d+\.\ds · \d", book), book       # the label says how long; once
    # the run that compares draws its disc at the Compare button too, far down the page
    _ok(at.button(key="go").click().run())
    discs = [m.value for m in at.main.markdown if 'class="runbox' in m.value]
    assert len(discs) == 2 and discs[0] == discs[1] and 'class="runbox done"' in discs[0], discs
    at = _ok(at.run())                             # a later rerun: the top disc alone
    assert len([m for m in at.main.markdown if 'class="runbox' in m.value]) == 1
    # a plain profile run is logged with the time put on its label
    _ok(at.button(key="do_profile").click().run())
    prof = at.session_state["log"][-1]
    assert prof["kind"] == "Profile" and prof["state"] == "done" and prof["lines"]
    assert re.fullmatch(r"Profile ready in \d+\.\ds", prof["label"]), prof["label"]
    assert _log_labels(at) == ["Log - 5 entries"]
    # Clear empties the log and takes the disc with it
    _ok(at.button(key="log_clear").click().run())
    assert at.session_state["log"] == [] and "last_run" not in at.session_state
    assert _log_labels(at) == ["Log - empty"]
    assert not [m for m in at.main.markdown if 'class="runbox' in m.value]


def test_log_panel_is_there_before_anything_is_loaded(monkeypatch, tmp_path):
    at = _boot(monkeypatch, tmp_path)
    assert _log_labels(at) == ["Log - empty"] and at.main.expander[-1].label == "Log - empty"
    assert not [m for m in at.main.markdown if 'class="runbox' in m.value]


# ---- the pure parts ----------------------------------------------------------------
class _Slot:
    """Stands in for the st.empty() the page mounts: keeps every disc drawn into it."""

    def __init__(self):
        self.drawn = []

    def markdown(self, html, unsafe_allow_html=False):
        assert unsafe_allow_html
        self.drawn.append(html)


def _bare(monkeypatch):
    """No app: session state is a dict, the mounted slot a recorder on the Compare page."""
    state = {}
    monkeypatch.setattr(streamlit, "session_state", state)
    slot = _Slot()
    ui_log.mount(slot, "Compare")
    return state, slot


def test_running_draws_the_disc_and_writes_the_entry(monkeypatch):
    state, slot = _bare(monkeypatch)
    with ui_log.running("Comparing…", "Compare") as box:
        assert slot.drawn[-1] == ('<div class="runbox running"><span class="disc"></span>'
                                  '<div class="rl"><b>Comparing…</b><span class="m"></span></div></div>')
        box.write("Reading <Left>…")
        assert '<span class="m">Reading &lt;Left&gt;…</span>' in slot.drawn[-1]
        box.update(label="Compared in 3.2s", state="complete")
    e = state["log"][-1]
    assert e["kind"] == "Compare" and e["state"] == "done" and e["label"] == "Compared in 3.2s"
    assert e["lines"] == ["Reading <Left>…"] and 0 <= e["seconds"] < 5 and AT.match(e["at"])
    assert slot.drawn[-1] == ('<div class="runbox done"><span class="disc">✓</span>'
                              '<div class="rl"><b>Compared in 3.2s</b><span class="m"></span></div></div>')
    assert ui_log.last_run_html("Compare") == slot.drawn[-1] and state["last_run"] == {"Compare": e}
    assert ui_log.last_run_html("Profiling") == ""   # the other page shows no disc for it
    assert len(slot.drawn) == 3                    # enter, the line, the finish - nothing after


def test_a_run_started_far_down_the_page_draws_where_it_starts_too(monkeypatch):
    state, slot = _bare(monkeypatch)
    here = []
    monkeypatch.setattr(streamlit, "empty", lambda: here.append(_Slot()) or here[-1])
    with ui_log.running("Comparing…", "Compare", here=True) as box:
        box.write("Reading…")
    assert len(here) == 1 and here[0].drawn == slot.drawn and len(slot.drawn) == 3
    assert 'class="runbox done"' in slot.drawn[-1]


def test_a_label_without_a_time_gets_one(monkeypatch):
    state, slot = _bare(monkeypatch)
    with ui_log.running("Profiling…", "Profile") as box:
        box.update(label="Profile ready", state="complete")
    assert re.fullmatch(r"Profile ready in \d+\.\ds", state["log"][-1]["label"])
    with ui_log.running("Looking for keys…", "Key search"):
        pass                                       # no update at all: the running label, its dots gone
    assert re.fullmatch(r"Looking for keys in \d+\.\ds", state["log"][-1]["label"])
    with ui_log.running("Fetching…", "Fetch") as box:
        box.update(label="Fetched 3,000 rows in 0.4s", state="complete")
    assert state["log"][-1]["label"] == "Fetched 3,000 rows in 0.4s"


def test_an_exception_marks_the_run_and_goes_on_up(monkeypatch):
    state, slot = _bare(monkeypatch)
    with pytest.raises(RuntimeError, match="boom"):
        with ui_log.running("Profiling…", "Profile") as box:
            box.write("Counting…")
            raise RuntimeError("boom")
    e = state["log"][-1]
    assert e["state"] == "error" and e["label"] == "Profiling" and e["seconds"] is not None
    assert slot.drawn[-1] == ('<div class="runbox error"><span class="disc"></span>'
                              '<div class="rl"><b>Profiling</b><span class="m">could not finish</span></div></div>')
    # the call site's own update(state="error") is kept, and a finish is final - Auto's st.rerun()
    # raises a BaseException through the block after it (KeyboardInterrupt stands in here)
    with pytest.raises(KeyboardInterrupt):
        with ui_log.running("Working it out…", "Auto") as box:
            box.update(state="error")
            raise KeyboardInterrupt
    assert state["log"][-1]["state"] == "error" and state["log"][-1]["label"] == "Working it out"
    assert 'Working it out · <span class="bad">could not finish</span>' in ui_log._logbook_html(state["log"])
    with pytest.raises(KeyboardInterrupt):
        with ui_log.running("Working it out…", "Auto") as box:
            box.update(label="Worked out in 1.0s", state="complete")
            raise KeyboardInterrupt
    assert state["log"][-1]["state"] == "done" and state["log"][-1]["label"] == "Worked out in 1.0s"


def test_note_and_clear(monkeypatch):
    state, slot = _bare(monkeypatch)
    with ui_log.running("Working it out…", "Auto"):
        pass
    ui_log.note("Auto decisions", "2 decisions - every one a cell in the column table", ["a", "b"])
    e = state["log"][-1]
    assert e == {"at": e["at"], "kind": "Auto decisions", "label": "2 decisions - every one a cell in the column table",
                 "state": "done", "seconds": None, "lines": ["a", "b"]}
    assert state["last_run"]["Compare"] is state["log"][0]    # a note is not a run
    ui_log.clear()
    assert state["log"] == [] and "last_run" not in state and ui_log.last_run_html("Compare") == ""


def test_log_is_capped(monkeypatch):
    state, slot = _bare(monkeypatch)
    for i in range(ui_log.LOG_MAX + 5):
        with ui_log.running(f"Run {i}…", "Test") as box:
            box.write("one line")
    log = state["log"]
    assert len(log) == ui_log.LOG_MAX == 50
    assert log[0]["label"].startswith("Run 5 in ") and log[-1]["label"].startswith(f"Run {ui_log.LOG_MAX + 4} in ")
    assert state["last_run"]["Compare"] is log[-1]


def test_a_slot_from_another_run_is_not_drawn_into(monkeypatch):
    state, slot = _bare(monkeypatch)
    fresh = []
    monkeypatch.setattr(ui_log, "_stamp", lambda: object())       # every call: another run
    monkeypatch.setattr(streamlit, "empty", lambda: fresh.append(_Slot()) or fresh[-1])
    with ui_log.running("Comparing…", "Compare"):
        pass
    assert not slot.drawn and len(fresh) == 1 and 'class="runbox done"' in fresh[0].drawn[-1]
