"""`python compare_app.py` and `python -m tablecmp.web`: what they start uvicorn with, the sweep at
start, a busy port, the wrong way in, and the Docker image."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from tablecmp.web import __main__ as start
from tablecmp.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent

# Runs compare_app.py's real __main__ block; only uvicorn.run is stubbed, to report what the
# server would have been started with.
STUB = """
import json, runpy, sys
import uvicorn
def fake_run(app, **kw):
    print("UVICORN " + json.dumps({"app": app, "host": kw.get("host"), "port": kw.get("port")}))
uvicorn.run = fake_run
path = sys.argv[1]
sys.argv = [path] + sys.argv[2:]
runpy.run_path(path, run_name="__main__")
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(tmp_path, *args, env=None, stub=STUB):
    e = {k: v for k, v in os.environ.items() if k != "COMPARE_WEB_PORT"}
    e.update({"COMPARE_WORK_DIR": str(tmp_path / "work"), **(env or {})})
    return subprocess.run([sys.executable, "-c", stub, str(ROOT / "compare_app.py"), *args],
                          env=e, capture_output=True, text=True, timeout=120)


def _started(proc) -> dict:
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("UVICORN ")]
    assert lines, proc.stdout + proc.stderr
    return json.loads(lines[-1][len("UVICORN "):])


def test_python_compare_app_starts_the_page(tmp_path):
    port = _free_port()
    proc = _start(tmp_path, "--no-browser", env={"COMPARE_WEB_PORT": str(port)})
    assert proc.returncode == 0, proc.stderr
    assert _started(proc) == {"app": "tablecmp.web.app:app", "host": "127.0.0.1", "port": port}
    assert f"at http://127.0.0.1:{port}" in proc.stdout


def test_the_port_flag_wins_and_8501_is_the_default(tmp_path):
    port = _free_port()
    proc = _start(tmp_path, "--no-browser", "--port", str(port), env={"COMPARE_WEB_PORT": "1"})
    assert _started(proc)["port"] == port
    assert start.DEFAULT_PORT == 8501


def test_a_busy_port_is_one_sentence(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        proc = _start(tmp_path, "--no-browser", "--port", str(port))
    assert proc.returncode == 1 and "UVICORN" not in proc.stdout
    assert f"Port {port} is in use" in proc.stderr and "COMPARE_WEB_PORT" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_a_listener_on_all_interfaces_is_a_busy_port(tmp_path):
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        s.listen()
        port = s.getsockname()[1]
        assert not start.port_free("127.0.0.1", port) and not start.port_free("0.0.0.0", port)
        proc = _start(tmp_path, "--no-browser", "--port", str(port))
    assert proc.returncode == 1 and "UVICORN" not in proc.stdout and f"Port {port} is in use" in proc.stderr
    assert start.port_free("127.0.0.1", port)


@pytest.mark.skipif(os.name == "nt", reason="TIME_WAIT only blocks a plain bind on POSIX")
def test_a_port_in_time_wait_after_a_restart_is_free():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    cli = socket.create_connection(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.close()                                  # the server closes first, so it keeps the TIME_WAIT
    cli.close()
    srv.close()
    assert start.port_free("127.0.0.1", port)


@pytest.mark.parametrize("host, shown", [
    ("127.0.0.1", "http://127.0.0.1:8501"), ("localhost", "http://127.0.0.1:8501"),
    ("0.0.0.0", "http://127.0.0.1:8501"), ("::", "http://[::1]:8501"), ("::1", "http://[::1]:8501"),
])
def test_the_printed_address_is_one_the_guard_answers(host, shown):
    assert start.shown_url(host, 8501) == shown


def test_host_0000_prints_the_loopback_address(tmp_path):
    proc = _start(tmp_path, "--no-browser", "--host", "0.0.0.0", "--port", str(_free_port()))
    assert "at http://127.0.0.1:" in proc.stdout and "0.0.0.0:" not in proc.stdout


def test_without_fastapi_it_is_one_sentence(tmp_path):
    blocked = "import sys\nsys.modules['fastapi'] = None\n" + STUB
    proc = _start(tmp_path, "--no-browser", env={"COMPARE_WEB_PORT": str(_free_port())}, stub=blocked)
    assert proc.returncode == 1 and "UVICORN" not in proc.stdout
    assert "pip install -r requirements.txt" in proc.stderr and "Traceback" not in proc.stderr


def test_a_bad_keep_hours_is_one_sentence(tmp_path):
    proc = _start(tmp_path, "--no-browser", env={"COMPARE_WEB_PORT": str(_free_port()), "COMPARE_KEEP_HOURS": "1d"})
    assert proc.returncode == 1 and "UVICORN" not in proc.stdout
    assert "COMPARE_KEEP_HOURS" in proc.stderr and "Traceback" not in proc.stderr


def test_old_streamlit_settings_are_named_as_no_longer_read(tmp_path):
    port = _free_port()
    proc = _start(tmp_path, "--no-browser", env={"COMPARE_WEB_PORT": str(port), "STREAMLIT_SERVER_PORT": "8600",
                                                 "COMPARE_UPLOAD_MB": "500"})
    assert proc.returncode == 0 and _started(proc)["port"] == port
    assert "Not read any more: COMPARE_UPLOAD_MB, STREAMLIT_SERVER_PORT" in proc.stderr
    quiet = _start(tmp_path, "--no-browser", env={"COMPARE_WEB_PORT": str(port)})
    assert "Not read any more" not in quiet.stderr


def test_old_files_in_the_work_folder_go_at_start(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    old = work / "cmp_A_1.parquet"
    old.write_text("x", encoding="utf-8")
    two_days = time.time() - 48 * 3600
    os.utime(old, (two_days, two_days))
    monkeypatch.setenv("COMPARE_WORK_DIR", str(work))
    monkeypatch.setattr(start.uvicorn, "run", lambda *a, **k: None)
    assert start.main(["--no-browser", "--port", str(_free_port())]) == 0
    assert not old.exists()


def test_without_the_tablecmp_folder_it_says_what_to_do(tmp_path):
    shutil.copy(ROOT / "compare_app.py", tmp_path / "compare_app.py")
    (tmp_path / "theme.py").write_text("", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(tmp_path / "compare_app.py"), "--no-browser"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0 and "needs the folder" in proc.stderr and "theme.py" in proc.stderr


def test_under_streamlit_run_it_says_how_to_start(tmp_path):
    under = "import sys, types\nsys.modules['streamlit'] = types.ModuleType('streamlit')\n" + STUB
    proc = _start(tmp_path, env={"COMPARE_WEB_PORT": str(_free_port())}, stub=under)
    assert proc.returncode == 1 and "UVICORN" not in proc.stdout
    assert "no longer a Streamlit app" in proc.stderr and "python compare_app.py" in proc.stderr


def test_the_docker_image_starts_the_page():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "STREAMLIT" not in docker and "_stcore" not in docker
    assert 'CMD ["python", "compare_app.py", "--host", "0.0.0.0", "--no-browser"]' in docker
    assert "EXPOSE 8501" in docker and "${COMPARE_WEB_PORT:-8501}/api/health" in docker
    assert '"8501:8501"' in compose


def test_the_docker_health_check_and_a_host_browser_pass_the_guard():
    c = TestClient(create_app())
    assert c.get("/api/health", headers={"Host": "127.0.0.1:8501"}).json() == {"ok": True}
    assert c.get("/api/health", headers={"Host": "localhost:8501"}).status_code == 200
