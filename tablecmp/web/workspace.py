"""A workspace is what st.session_state was: everything one browser has loaded and set. It lives
in this process's memory - the engine's objects (Side, the column table, a run with its DuckDB
connection) never go to the browser. A cookie names it; a cookie the server does not know (it
was restarted) gets a fresh workspace and a new cookie, never an error."""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request, Response

COOKIE = "cmp_ws"


@dataclass
class Workspace:
    id: str
    passwords: dict[str, str] = field(default_factory=dict, repr=False)   # typed, unsaved - never written anywhere
    log: list[dict] = field(default_factory=list)               # newest last; jobs and notes
    last_run: dict[str, dict] = field(default_factory=dict)     # page -> its last job entry
    running: dict[str, dict] = field(default_factory=dict)      # id -> the job entries still running, whatever the Log holds
    data: dict[str, Any] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class Workspaces:
    def __init__(self) -> None:
        self._all: dict[str, Workspace] = {}
        self._lock = threading.Lock()

    def get(self, wid: str | None) -> Workspace | None:
        return self._all.get(wid or "")

    def new(self) -> Workspace:
        with self._lock:
            ws = Workspace(id=secrets.token_urlsafe(18))
            self._all[ws.id] = ws
            return ws


def workspace(request: Request, response: Response) -> Workspace:
    store: Workspaces = request.app.state.workspaces
    ws = store.get(request.cookies.get(COOKIE))
    if ws is None:
        ws = store.new()
        response.set_cookie(COOKIE, ws.id, httponly=True, samesite="strict")
    return ws
