"""Long work as a job: a thread runs it under the workspace's lock (the engine's DuckDB
connections are not shared between threads), its progress lines are kept on its Log entry, and
the page polls GET /api/jobs/{id}. The same entry shape the Streamlit Log used:
{at, kind, label, state: running|done|error, seconds, lines}."""
from __future__ import annotations

import re
import secrets
import threading
import time
from typing import Any, Callable

from fastapi import HTTPException

from ..connections import known_secrets, redact
from .workspace import Workspace

LOG_MAX = 50
_HAS_TIME = re.compile(r" in \d+(\.\d+)?s\b")    # a time said as " in 3.2s" - a key named q2s is not one
_starting = threading.Lock()
BUSY = "That is running already - wait for it to finish."


def _secrets(ws: Workspace | None) -> list[str]:
    """Every secret value the workspace holds or the store saves, to blank out of any line."""
    return known_secrets(ws.passwords.values() if ws else ())


class JobCtx:
    def __init__(self, entry: dict, ws: Workspace | None = None) -> None:
        self._entry = entry
        self._ws = ws
        self.label = entry["label"]

    def say(self, line: str) -> None:
        self._entry["lines"].append(redact(str(line), _secrets(self._ws)))


def _add(ws: Workspace, entry: dict) -> dict:
    ws.log.append(entry)
    over = len(ws.log) - LOG_MAX
    if over > 0:                                   # the oldest finished entries go; a running one stays
        drop = {id(e) for e in [e for e in ws.log if e["state"] != "running"][:over]}
        ws.log[:] = [e for e in ws.log if id(e) not in drop]
    return entry


def _entry(kind: str, label: str, state: str, page: str = "", slot: str = "") -> dict:
    return {"id": secrets.token_hex(6), "at": time.strftime("%H:%M:%S"), "kind": kind, "label": label,
            "state": state, "seconds": None, "lines": [], "page": page, "slot": slot, "result": None}


def start(ws: Workspace, kind: str, label: str, fn: Callable[[JobCtx], Any], page: str = "Compare",
          wait: bool = False, slot: str = "") -> dict:
    with _starting:                                # a second job of this kind on this page waits for the first
        if any((e["kind"], e["page"], e["slot"]) == (kind, page, slot) for e in list(ws.running.values())):
            raise HTTPException(409, BUSY)
        entry = _add(ws, _entry(kind, label, "running", page, slot))
        ws.running[entry["id"]] = entry
        ws.last_run[page] = entry
    ctx = JobCtx(entry, ws)

    def run() -> None:
        t0 = time.perf_counter()
        try:
            with ws.lock:
                entry["result"] = fn(ctx)
            ws.running.pop(entry["id"], None)       # out of the running set before it says done
            entry["seconds"] = round(time.perf_counter() - t0, 1)
            label_now = ctx.label
            entry["label"] = label_now if _HAS_TIME.search(label_now) else f"{label_now.rstrip('…')} in {entry['seconds']}s"
            entry["state"] = "done"
        except Exception as exc:                   # the job's own failure, said on its entry
            ws.running.pop(entry["id"], None)
            entry["seconds"] = round(time.perf_counter() - t0, 1)
            entry["lines"].append(redact(str(exc).strip() or type(exc).__name__, _secrets(ws)))
            entry["label"] = f"{ctx.label.rstrip('…')} - could not finish"
            entry["state"] = "error"
        finally:                                   # a BaseException must not leave the entry "running"
            if entry["state"] == "running":
                entry["seconds"] = round(time.perf_counter() - t0, 1)
                entry["lines"].append("The job was stopped before it finished.")
                entry["label"] = f"{ctx.label.rstrip('…')} - could not finish"
                entry["state"] = "error"
            ws.running.pop(entry["id"], None)

    t = threading.Thread(target=run, daemon=True, name=f"job-{kind}")
    t.start()
    if wait:
        t.join()
    return entry


def note(ws: Workspace, kind: str, label: str, lines: list[str]) -> dict:
    e = _entry(kind, label, "done")
    e["lines"] = [redact(str(x), _secrets(ws)) for x in lines]
    return _add(ws, e)


def public(entry: dict) -> dict:
    out = dict(entry)                              # one copy; the job thread may still be writing the entry
    out.pop("result", None)
    return out


def find(ws: Workspace, job_id: str) -> dict | None:
    return ws.running.get(job_id) or next((e for e in reversed(ws.log) if e["id"] == job_id), None)
