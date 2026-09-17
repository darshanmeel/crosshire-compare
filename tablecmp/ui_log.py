"""The run disc and the Log panel - every long run reports to one place.

A run (Auto, profiling, the key search, a database fetch, Compare) draws a big red disc with
its label while it works, pulsing, the latest progress line under it; when it is done the
disc holds a check mark and the label carries the elapsed time. Each run, and Auto's
decisions, is an entry in st.session_state["log"] - newest last, at most LOG_MAX of them -
and the Log expander at the foot of the page shows them newest first. The last run of each
page is st.session_state["last_run"][page], so the page can draw its disc again after a rerun.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Iterator

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from .theme import esc

LOG_MAX = 50
_HAS_TIME = re.compile(r"\d(\.\d+)?s\b")         # "in 3.2s" - a label that already says how long


def _stamp():
    """Something new on every script run - a slot from an earlier run must not be drawn into."""
    ctx = get_script_run_ctx(suppress_warning=True)
    return ctx.cursors if ctx else None


def mount(slot, page: str) -> None:
    """The st.empty() under the status strip that every run of this script run draws into,
    and the page it is on - a run's disc comes back on the page it ran on, not the other."""
    st.session_state["_run_slot"] = (slot, page, _stamp())


def _mounted():
    """(slot, page) when the mount was made this run - else a fresh slot where the run is."""
    held = st.session_state.get("_run_slot")
    if held and held[2] is _stamp():
        return held[0], held[1]
    return st.empty(), ""


def _log() -> list[dict]:
    return st.session_state.setdefault("log", [])


def _add(kind: str, label: str, state: str, lines=()) -> dict:
    entry = {"at": time.strftime("%H:%M:%S"), "kind": kind, "label": label, "state": state,
             "seconds": None, "lines": list(lines)}
    log = _log()
    log.append(entry)
    del log[:-LOG_MAX]                           # the oldest go first
    return entry


def _disc_html(e: dict) -> str:
    state = e["state"]
    sub = ("could not finish" if state == "error"
           else e["lines"][-1] if state == "running" and e["lines"] else "")
    return (f'<div class="runbox {state}"><span class="disc">{"✓" if state == "done" else ""}</span>'
            f'<div class="rl"><b>{esc(e["label"])}</b><span class="m">{esc(sub)}</span></div></div>')


class _Box:
    """What a run holds while it works: its log entry, the slots its disc is in, its clock.
    write() and update() have the shape st.status gave them, so a worker's progress
    callback is box.write and the call sites read as they did."""

    def __init__(self, entry: dict, slots: list) -> None:
        self.entry, self.slots, self.t0 = entry, slots, time.perf_counter()

    def draw(self) -> None:
        html = _disc_html(self.entry)
        for slot in self.slots:
            slot.markdown(html, unsafe_allow_html=True)

    def write(self, msg: str) -> None:
        self.entry["lines"].append(str(msg))
        self.draw()

    def update(self, label: str | None = None, state: str | None = None) -> None:
        if state in ("complete", "error"):
            self.finish("done" if state == "complete" else "error", label)
        elif label:
            self.entry["label"] = label
            self.draw()

    def finish(self, state: str, label: str | None = None) -> None:
        """Close the entry once: the elapsed time, the label it ends with, the last disc."""
        e = self.entry
        if e["state"] != "running":
            return
        e["state"] = state
        e["seconds"] = time.perf_counter() - self.t0
        e["label"] = (label or e["label"]).rstrip("…")      # the running label's dots: it runs no more
        if state == "done" and not _HAS_TIME.search(e["label"]):
            e["label"] += f" in {e['seconds']:.1f}s"
        self.draw()


@contextmanager
def running(label: str, kind: str, here: bool = False) -> Iterator[_Box]:
    """A long run: the pulsing disc while it works, the check mark and the elapsed time when
    it is done, "could not finish" when it raises - and the exception goes on up. The disc
    is drawn under the status strip; with `here` also where the run starts, for a run
    pressed far down the page."""
    slot, page = _mounted()
    entry = _add(kind, label, "running")
    st.session_state.setdefault("last_run", {})[page] = entry
    box = _Box(entry, [slot, st.empty()] if here else [slot])
    box.draw()
    try:
        yield box
    except BaseException:                        # a stop or rerun mid-way is one too
        box.finish("error")
        raise
    box.finish("done")


def last_run_html(page: str) -> str:
    """The disc of the page's last run, to draw again on a later rerun - empty when there is none."""
    e = st.session_state.get("last_run", {}).get(page)
    return _disc_html(e) if e else ""


def note(kind: str, label: str, lines: list[str]) -> None:
    """A log entry that is not a run - Auto's decisions."""
    _add(kind, label, "done", lines)


def clear() -> None:
    st.session_state["log"] = []
    st.session_state.pop("last_run", None)


def _logbook_html(log: list[dict]) -> str:
    out = []
    for e in reversed(log):                      # a finished run's label carries its time
        head = (f'<span class="at">{esc(e["at"])}</span> · <span class="kind">{esc(e["kind"])}</span> · '
                + esc(e["label"]))
        if e["state"] == "error":
            head += ' · <span class="bad">could not finish</span>'
        lines = "".join(f'<div class="l">{esc(line)}</div>' for line in e["lines"])
        out.append(f'<div class="e">{head}{lines}</div>')
    return f'<div class="logbook">{"".join(out)}</div>'


def panel() -> None:
    """The Log expander - the last thing on the page: every run and Auto's decisions, newest first."""
    log = st.session_state.get("log") or []
    n = len(log)
    with st.expander(f"Log - {n} {'entry' if n == 1 else 'entries'}" if log else "Log - empty",
                     expanded=False):
        if log:
            st.markdown(_logbook_html(log), unsafe_allow_html=True)
        if st.button("Clear", key="log_clear", disabled=not log):
            clear()
            st.rerun()
