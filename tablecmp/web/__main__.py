"""python -m tablecmp.web [--port N] [--host H] [--no-browser] - the page, on 127.0.0.1:8501 unless
told otherwise. `python compare_app.py` starts the same thing."""
from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
import threading
import webbrowser

try:
    import uvicorn
except ModuleNotFoundError:                      # said in one sentence by main
    uvicorn = None

from .. import outputs

DEFAULT_PORT = 8501


def _env_port() -> int:
    try:
        return int(os.environ.get("COMPARE_WEB_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _probe_host(host: str) -> str:
    """The address a browser on this machine uses for a server bound to host."""
    if host in ("", "0.0.0.0", "localhost"):
        return "127.0.0.1"
    if host in ("::", "::0"):
        return "::1"
    return host


def port_free(host: str, port: int) -> bool:
    """True when nothing listens on host:port - so a second app there is one sentence, not a traceback.
    A connect probe catches a listener on the wildcard address, which Windows lets a second socket
    bind past; the bind probe catches the rest."""
    try:
        socket.create_connection((_probe_host(host), port), timeout=0.5).close()
        return False
    except OSError:
        pass
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # TIME_WAIT after a restart is not "in use"
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def shown_url(host: str, port: int) -> str:
    """The address to print and open: the guard answers on this machine's own names only."""
    shown = _probe_host(host)
    return f"http://[{shown}]:{port}" if ":" in shown else f"http://{shown}:{port}"


def _ignored_settings() -> str:
    """One line naming settings of the old Streamlit page that nothing reads any more."""
    old = sorted(k for k in os.environ if k.startswith("STREAMLIT_") or k == "COMPARE_UPLOAD_MB")
    if not old:
        return ""
    return (f"Not read any more: {', '.join(old)}. Use --port or COMPARE_WEB_PORT, and --host; "
            f"uploads have no size cap.")


def main(argv: list[str] | None = None, prog: str = "python -m tablecmp.web") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__)
    ap.add_argument("--port", type=int, default=_env_port())
    ap.add_argument("--host", default="127.0.0.1", help="only change this in a container or behind a trusted proxy")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    if uvicorn is None or importlib.util.find_spec("fastapi") is None:
        print("The page needs FastAPI and uvicorn, which are not installed here - "
              "run: pip install -r requirements.txt", file=sys.stderr)
        return 1
    if not port_free(args.host, args.port):
        print(f"Port {args.port} is in use - stop the other app on it, or start this one with --port N "
              f"or COMPARE_WEB_PORT.", file=sys.stderr)
        return 1
    note = _ignored_settings()
    if note:
        print(note, file=sys.stderr)
    try:
        outputs.sweep_work_dir()                 # old runs, fetches and snapshots go once per start
    except ValueError:
        print(f"COMPARE_KEEP_HOURS is {os.environ.get('COMPARE_KEEP_HOURS')!r} - set it to a number of hours, "
              f"like 24, or leave it out.", file=sys.stderr)
        return 1
    except OSError:
        pass
    url = shown_url(args.host, args.port)
    print(f"CrossHire Compare at {url} - Ctrl+C stops it")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, [url]).start()
    uvicorn.run("tablecmp.web.app:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
