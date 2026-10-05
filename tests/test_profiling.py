"""The Profiling page with no page attached - what the Streamlit page and the React server both call."""
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from tablecmp import profiling as pf
from tablecmp.keys import KEY_COLS
from tablecmp.observe import OUTLIER_COLS
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions()


def _side(path: Path, rows: int) -> Side:
    s = Side(name="t", label=path.name, csv_path=str(path), kind="csv", rows=rows)
    s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


@pytest.fixture(scope="module")
def hr():
    lines: list[str] = []
    return pf.make_profile(_side(EX / "hr_employees.csv", 3000), "HR", OPTS, lines.append), lines


@pytest.fixture
def nokey(tmp_path):
    rows = ["dept,grade,flag"] + [f"{'Sales' if i % 3 else 'Ops'},G{i % 4},{'Y' if i % 2 else 'N'}" for i in range(24)]
    p = tmp_path / "nokey.csv"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return pf.make_profile(_side(p, 24), "T", OPTS, lambda _m: None)


def test_the_key_says_what_the_profile_was_measured_on():
    s = _side(EX / "hr_employees.csv", 3000)
    assert pf.profile_key(s, OPTS) == json.dumps([s.read_key, OPTS.tokens, OPTS.trim], default=str)
    assert pf.profile_key(s, ReadOptions(trim=False)) != pf.profile_key(s, OPTS)


def test_a_profile_and_the_lines_said_about_it(hr):
    prof, lines = hr
    assert lines[0] == "Looking at the values…" and "Looking for keys…" in lines
    assert pf.best_key(prof) == ["emp_id"]
    assert pf.ready_label(prof) == "Profile ready - key: emp_id"
    assert pf.keys_line(prof) == ("success", f"Key: **emp_id** - unique on every row. {prof['keys'][2]}.")
    assert pf.fold_title(prof["stats"], "emp_id") == "**emp_id** - text · 3,000 distinct · 0.0% null"


def test_no_key_and_nothing_to_measure(nokey):
    assert pf.best_key(nokey) is None and pf.ready_label(nokey) == "Profile ready - no key"
    assert pf.keys_line(nokey) == (
        "warning", f"Nothing up to 5 columns is unique - the closest are below. {nokey['keys'][2]}.")
    empty = {"keys": (pd.DataFrame(columns=KEY_COLS), [], "n")}
    assert pf.keys_line(empty) == ("warning", "Nothing up to 4 columns is unique. n.")   # MAX_KEY_COLS when the profile says none
    files = pf.profile_files(nokey, "T")
    assert files["T__outliers.csv"] == (",".join(OUTLIER_COLS) + "\n").encode("utf-8")
    deps = files["T__dependencies.csv"].decode("utf-8").splitlines()
    assert deps == [",".join(pf.DEP_FILE_COLS), "grade,flag,many-to-one,4,"]


def test_the_counts_in_words():
    assert pf.notes_label([]) == "0 things stand out"
    assert pf.notes_label(["a"]) == "1 thing stands out"
    assert pf.notes_label(["a", "b"]) == "2 things stand out"


def test_the_six_files_are_named_after_the_table(hr):
    prof, _ = hr
    assert pf.file_stem("My table!") == "My_table" and pf.file_stem("  ") == "Table" and pf.file_stem("***") == "Table"
    files = pf.profile_files(prof, "HR")
    assert list(files) == ["HR__profile.csv", "HR__keys.csv", "HR__notes.txt", "HR__outliers.csv",
                           "HR__patterns.csv", "HR__dependencies.csv"]
    assert files["HR__profile.csv"].decode("utf-8").startswith("Column,Type,Rows,Nulls,Null %,")
    assert files["HR__keys.csv"].decode("utf-8").startswith("Key columns,Distinct,Unique,")
    assert files["HR__notes.txt"].decode("utf-8") == prof["headline"] + "\n\n" + "\n".join(prof["notes"]) + "\n"
    assert b"\r\n" not in b"".join(files.values())


def test_a_save_writes_the_files_and_stays_under_the_out_folder(hr, tmp_path, monkeypatch):
    prof, _ = hr
    monkeypatch.delenv("COMPARE_OUT_DIR", raising=False)
    run = {"pair": "HR", "run_id": "20261004-120000"}
    target, written = pf.save_files(pf.profile_files(prof, "HR"), str(tmp_path / "HR__20261004-120000"), run)
    assert target == (tmp_path / "HR__20261004-120000").resolve()
    assert sorted(p.name for p in target.iterdir()) == sorted(written) and len(written) == 6
    assert pf.saved_line(target, written) == f"Saved 6 files to `{target}`: " + ", ".join(written)
    assert pf.saved_line(target, ["a"]) == f"Saved 1 file to `{target}`: a"
    assert pf.save_base_after(target, run) == str(target.parent)            # the per-run folder: its parent
    assert pf.save_base_after(tmp_path / "mine", run) == str(tmp_path / "mine")
    with pytest.raises(ValueError, match="Type a folder to save into."):
        pf.save_files({"x.txt": b"x"}, "   ", run)
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    with pytest.raises(ValueError, match="Saves must stay under"):
        pf.save_files({"x.txt": b"x"}, str(tmp_path / "other"), run)
    assert not (tmp_path / "other").exists()


def test_the_default_save_base():
    downloads = Path.home() / "Downloads"
    want = str(downloads if downloads.exists() else Path.home())
    assert pf.default_save_base(Side(csv_path=str(EX / "hr_employees.csv"))) == str(EX)
    assert pf.default_save_base(Side()) == want and pf.default_save_base(None) == want
    in_temp = Path(tempfile.gettempdir()) / "cmp_P_1_hr.csv"          # an upload: not a place to save next to
    assert pf.default_save_base(Side(csv_path=str(in_temp))) == want


def test_fold_titles_one_index_for_every_column():
    import pandas as pd
    n = 3000
    stats = pd.DataFrame({"Column": [f"c{i}" for i in range(n)], "Type": "text", "Distinct": range(n), "Null %": 0.0})
    import time
    t0 = time.perf_counter()
    titles = pf.fold_titles(stats, list(stats["Column"]))
    assert time.perf_counter() - t0 < 1.0
    assert titles["c7"] == pf.fold_title(stats, "c7") == "**c7** - text · 7 distinct · 0.0% null"
