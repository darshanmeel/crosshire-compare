# tests/test_run_console.py
"""python -m tablecmp.run on a console that cannot print every character (Windows cp1252):
the result line still prints and the exit code says what the comparison found, never an
encoding accident."""
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_runconfig import EX, _config

ROOT = Path(__file__).resolve().parent.parent


def _cli(tmp_path, *args):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0",
           "COMPARE_WORK_DIR": str(tmp_path / "work"), "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-m", "tablecmp.run", *args], cwd=tmp_path, env=env,
                          capture_output=True, timeout=300)


def test_a_cp1252_console_gets_the_result_line_and_the_right_exit_code(tmp_path, monkeypatch):
    conf, _, _ = _config(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(conf), encoding="utf-8")
    p = _cli(tmp_path, str(path), "-q")                       # the example pair: differences
    out, err = p.stdout.decode("cp1252"), p.stderr.decode("cp1252")
    assert "Traceback" not in err and "UnicodeEncodeError" not in err, err
    assert p.returncode == 1                                  # a difference, said by the comparison
    assert "[1/1]" in out and "Differences" in out and "matched" in out and "only right" in out
    # a pair that cannot run: 2, the ✗ line printed as best the console can
    p = _cli(tmp_path, str(path), "--left", str(tmp_path / "nowhere.csv"),
             "--right", str(EX / "payroll_employees.csv"), "-q")
    err = p.stderr.decode("cp1252")
    assert "Traceback" not in err, err
    assert p.returncode == 2 and "file not found" in p.stdout.decode("cp1252")


def test_csvdiff_on_a_cp1252_console_prints_a_file_name_it_cannot_spell(tmp_path):
    left = tmp_path / "hr→jan.csv"
    left.write_text("id,v\n1,a\n2,b\n", encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    p = subprocess.run([sys.executable, str(ROOT / "csvdiff.py"), "file", str(left), str(left), "--key", "id",
                        "--out", str(tmp_path / "out")], cwd=tmp_path, env=env, capture_output=True, timeout=300)
    err = p.stderr.decode("cp1252")
    assert "Traceback" not in err, err
    assert p.returncode == 0                                  # identical, said by the comparison
    assert "comparing hr?jan" in p.stdout.decode("cp1252")
    assert (tmp_path / "out").is_dir()                        # the reports keep the real name, in UTF-8
