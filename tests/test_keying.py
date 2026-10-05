"""The Key section and Profile both files, with no page attached - what the Streamlit page and
the React server both call."""

import pandas as pd
import pytest

from tablecmp import keying as kg
from tablecmp import loading as ld
from tablecmp.columns import build_table, specs_from
from tablecmp.keys import MAX_KEY_COLS, key_uniqueness
from tablecmp.profile import profile_tables
from tablecmp.sources import file_stamp, source_schema
from tablecmp.values import ReadOptions, steps_from_json

OPTS = ReadOptions()


def _side(tag, path, name="Left"):
    schema = source_schema(str(path), "csv", ",", True, file_stamp(str(path)))
    return ld.build_side(tag, ld.ReadAsked(name=name, label=path.name, path=str(path), snapshot=False), schema)


@pytest.fixture
def codes(tmp_path, monkeypatch):
    """emp_code written 'AB 7' on A and 'AB7' on B; ref carries a prefix on A only."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("emp_code,ref,salary\n" + "".join(f"AB {i},R-{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    b.write_text("emp_code,ref,salary\n" + "".join(f"AB{i},{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    A, B = _side("A", a), _side("B", b, "Right")
    return A, B, build_table(A, B, {})


def test_the_columns_that_read_like_a_key(codes):
    A, B, cmap = codes
    specs = specs_from(cmap)
    assert kg.key_like(A, B, [], specs) == ["emp_code", "ref"]
    assert kg.key_like(A, B, ["salary"], specs) == ["salary"]


def test_a_simple_fix_goes_in_and_a_guess_waits(codes):
    A, B, cmap = codes
    new, found = kg.check_formats(A, B, cmap, ["emp_code", "ref"], OPTS)
    assert [(fx.canon, done) for fx, done in found] == [("emp_code", True), ("ref", False)]
    row = new.set_index("Common name")
    assert steps_from_json(row.at["emp_code", "A steps"]) == [{"op": "remove spaces", "params": {}}]
    assert cmap.set_index("Common name").at["emp_code", "A steps"] == "[]"         # the old one untouched
    said = kg.formats_said(["emp_code", "ref"], found)
    assert said[0][0] == "success" and said[0][1].startswith(":green[**Applied**] · emp_code: ")
    assert said[1][0] == "warning" and "your call" in said[1][1]
    fixed = kg.with_fix(new, found[1][0])
    assert steps_from_json(fixed.set_index("Common name").at["ref", "A steps"])[0]["op"] == "regex replace"
    assert kg.formats_said(["salary"], []) == [
        ("caption", "Key formats checked (salary): the two sides write them alike.")]


def test_a_fix_for_a_column_no_longer_paired_is_none(codes):
    A, B, cmap = codes
    _, found = kg.check_formats(A, B, cmap, ["ref"], OPTS)
    unpaired = cmap[cmap["Common name"] != "ref"]
    assert kg.with_fix(unpaired, found[0][0]) is None


def test_the_key_picked_from_suggestions():
    assert kg.chosen_key([["a"], ["a", "b"], ["c"]], [1, 0, 2, 9]) == ["a", "b", "c"]
    assert kg.best_label([["emp_id"], ["x"]]) == "Best key: emp_id" and kg.best_label([]) == "No key found"
    cmap = pd.DataFrame({"A column": ["a", "b", "c"], "B column": ["a", "b", ""], "Common name": ["a", "b", "c"],
                         "Key": [True, False, False]})
    ticked = kg.with_key(cmap, ["b", "c"])
    assert list(ticked["Key"]) == [False, True, False] and list(cmap["Key"]) == [True, False, False]


def test_what_is_said_about_suggestions_and_a_checked_key(codes):
    A, B, cmap = codes
    table = pd.DataFrame([{"Key columns": "emp_code", "Unique on both": "yes"}])
    assert kg.suggestions_said(table, "Found fast") == (
        "success", "1 combination(s) identify a single row on both sides - best: **emp_code**. Found fast.")
    tone, text = kg.suggestions_said(pd.DataFrame(columns=["Key columns", "Unique on both"]), "None")
    assert tone == "warning" and f"Nothing up to {MAX_KEY_COLS} columns" in text
    salary = kg.with_key(cmap, ["salary"])
    report = key_uniqueness(A, B, specs_from(salary), ["salary"], "Left", "Right", OPTS)
    assert kg.report_said(report, ["salary"]) == ("success", "**salary** identifies a single row on both sides.")
    dup = pd.DataFrame([{"Side": "Left", "Rows": 4, "Distinct keys": 2, "Duplicate rows": 1, "Null keys": 1,
                         "Unique": "no"}])
    tone, text = kg.report_said(dup, ["k"])
    assert tone == "warning" and text.startswith("This key is null on 1 rows of Left - those rows cannot match.")
    assert "not unique on Left (1 duplicate rows)" in text


def test_the_profile_key_and_the_both_sides_table(codes):
    A, B, cmap = codes
    specs = specs_from(cmap)
    key = kg.profile_key_for(A, B, specs, OPTS)
    assert key == kg.profile_key_for(A, B, specs_from(cmap.copy()), OPTS)
    assert key != kg.profile_key_for(A, B, specs, ReadOptions(trim=False))
    prof = profile_tables(A, B, specs, OPTS)
    both = kg.both_table(prof, [s.canon for s in specs], "Left", "Right")
    assert list(both.columns)[:4] == ["Column", "Type", "Null % Left", "Null % Right"]
    assert set(both["Column"]) == {"emp_code", "ref", "salary"}
    assert kg.freq_columns(prof, ["emp_code", "gone"]) == ["emp_code"]
    assert kg.freq_title(prof, "emp_code", ["emp_code"], "Left", "Right") == \
        "**emp_code** · key - text · Left: 40 distinct · Right: 40 distinct"
