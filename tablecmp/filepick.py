"""Browse for a file on disk with the system's own file dialog - for a file too big to upload.

The dialog is Tk's, run in a process of its own: Tk wants the main thread, and a Streamlit
script runs in another one. It opens on the machine the app runs on, so it is offered only
where that machine has a screen - Windows, macOS, a Linux desktop - and not in a container,
where the path is typed instead.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

FILE_TYPES = [("Data files", "*.csv *.txt *.tsv *.dat *.json *.jsonl *.ndjson *.parquet"), ("All files", "*.*")]
WAIT = 600          # seconds the dialog may stay open

_DIALOG = """
import json, sys, tkinter, tkinter.filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
path = tkinter.filedialog.askopenfilename(parent=root, title="Choose a CSV, JSON or Parquet file",
                                          initialdir=sys.argv[1] or None, filetypes=[tuple(t) for t in json.loads(sys.argv[2])])
sys.stdout.write(path or "")
"""


def available() -> bool:
    """Is there a screen here to open a dialog on, and Tk to draw it?"""
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return importlib.util.find_spec("tkinter") is not None


def pick_file(start: str = "") -> str:
    """The path chosen, or '' when the dialog was cancelled. RuntimeError when it could not open."""
    start = start if start and os.path.isdir(start) else ""
    try:
        r = subprocess.run([sys.executable, "-c", _DIALOG, start, json.dumps(FILE_TYPES)],
                           capture_output=True, text=True, encoding="utf-8", timeout=WAIT,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})   # a path in any script
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        raise RuntimeError("The file dialog could not open: " + (r.stderr.strip().splitlines() or ["no reason given"])[-1])
    return os.path.normpath(r.stdout.strip()) if r.stdout.strip() else ""
