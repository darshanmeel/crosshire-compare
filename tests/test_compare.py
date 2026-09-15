# tests/test_compare.py
"""The Rows filters as the engine gets them, and what makes a run stale."""
import pandas as pd
import pytest

from tablecmp.compare import (ENGINE_HTML_ROWS, build_filters, date_texts, number_texts, run_comparison,
                              side_labels, signature)
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ColSpec, ReadOptions

SPECS = [ColSpec(canon="emp_id", a_src="emp_id", b_src="EmployeeId", kind="text"),
         ColSpec(canon="active", a_src="active", b_src="IsActive", kind="boolean"),
         ColSpec(canon="hire_date", a_src="hire_date", b_src="HireDate", kind="date"),
         ColSpec(canon="seen", a_src="seen", b_src="seen", kind="timestamp"),
         ColSpec(canon="salary", a_src="salary", b_src="Salary", kind="number")]


def _rows(*rows):
    return pd.DataFrame([{"Apply to": where, "Column": col, "Operator": op, "Value": val, "Type": kind}
                         for col, op, val, where, kind in rows],
                        columns=["Apply to", "Column", "Operator", "Value", "Type"])


def test_boolean_filter_values_are_spelled_like_the_column():
    """A boolean column holds true / false; True, Yes, y, 1 and their opposites are typed freely."""
    both, left, right = build_filters(_rows(("active", "=", "True", "Left", "auto"),
                                            ("active", "in", "Yes, n, 1", "Right", "auto"),
                                            ("active", "!=", "F", "Both", "string")), "Left", "Right", SPECS)
    assert left == {"active": {"eq": "true"}}
    assert right == {"active": {"in": ["true", "false", "true"]}}
    assert both == {"active": {"type": "string", "ne": "false"}}
    # a value that is not a boolean word stays as typed, and a like pattern is never touched
    both, _, _ = build_filters(_rows(("active", "=", "maybe", "Both", "auto"),
                                     ("active", "like", "T%", "Both", "auto")), "Left", "Right", SPECS)
    assert both == {"active": {"eq": "maybe", "like": "T%"}}
    # without the specs nothing is known about the column: the value goes through verbatim
    assert build_filters(_rows(("active", "=", "True", "Both", "auto")), "Left", "Right")[0] == {"active": {"eq": "True"}}


def test_date_filter_values_are_read_like_the_column():
    both, _, _ = build_filters(_rows(("hire_date", ">=", "05/01/2024", "Both", "auto"),
                                     ("hire_date", "between", "2024-01-01, 2024-12-31", "Both", "date"),
                                     ("seen", ">", "2024-01-05", "Both", "auto")), "Left", "Right", SPECS)
    assert both["hire_date"] == {"ge": "2024-01-05", "type": "date", "between": ["2024-01-01", "2024-12-31"]}
    assert both["seen"] == {"gt": "2024-01-05 00:00:00"}          # a timestamp column keeps the time
    # Type date on any column: a value with a time of day keeps it, the engine compares as timestamps
    both, _, _ = build_filters(_rows(("emp_id", "=", "2024-01-05T10:11:12", "Both", "date")), "Left", "Right", SPECS)
    assert both == {"emp_id": {"type": "date", "eq": "2024-01-05 10:11:12"}}
    assert date_texts("x", [], full=False) == []


def test_date_filter_values_follow_the_columns_own_format():
    """A column read with a to date / to timestamp format reads its filter values with it too:
    05/01/2024 is May on an m/d column and January on a d/m one, ISO still works, and the
    format is the one of the side the filter applies to."""
    us = {"op": "to date", "params": {"fmt": "%m/%d/%Y"}}
    uk = {"op": "to date", "params": {"fmt": "%d/%m/%Y"}}
    specs = [ColSpec(canon="hire_date", a_src="hire_date", b_src="HireDate", kind="date", a_steps=[us], b_steps=[us]),
             ColSpec(canon="seen", a_src="seen", b_src="seen", kind="timestamp",
                     b_steps=[{"op": "trim"}, {"op": "to timestamp", "params": {"fmt": "%d/%m/%Y %H:%M"}}]),
             ColSpec(canon="code", a_src="code", b_src="code", kind="text", a_steps=[{"op": "to date", "params": {"fmt": "%d.%m.%Y"}}])]
    both, left, right = build_filters(_rows(("hire_date", "=", "05/01/2024", "Both", "auto"),
                                            ("hire_date", "in", "2024-01-05, 05/13/2024", "Left", "auto"),
                                            ("seen", ">", "05/01/2024 10:11", "Right", "auto"),
                                            ("code", ">=", "27.08.2026", "Both", "date")), "Left", "Right", specs)
    assert both == {"hire_date": {"eq": "2024-05-01"}, "code": {"type": "date", "ge": "2026-08-27"}}
    assert left == {"hire_date": {"in": ["2024-01-05", "2024-05-13"]}}
    assert right == {"seen": {"gt": "2024-01-05 10:11:00"}}
    # the two sides read the spelling as different days: refused with both readings when the
    # filter is on both, read each side's way when it is on one
    mixed = [ColSpec(canon="hire_date", a_src="hire_date", b_src="HireDate", kind="date", a_steps=[uk], b_steps=[us])]
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("hire_date", "=", "05/01/2024", "Both", "auto")), "Left", "Right", mixed)
    assert str(exc.value) == ("filter on 'hire_date': '05/01/2024' is 2024-01-05 to Left (%d/%m/%Y) "
                              "and 2024-05-01 to Right (%m/%d/%Y) - spell it 2024-01-05 or 2024-05-01")
    both, left, right = build_filters(_rows(("hire_date", "=", "05/13/2024", "Both", "auto"),
                                            ("hire_date", "=", "05/01/2024", "Left", "auto"),
                                            ("hire_date", "=", "05/01/2024", "Right", "auto")), "Left", "Right", mixed)
    assert (both, left, right) == ({"hire_date": {"eq": "2024-05-13"}}, {"hire_date": {"eq": "2024-01-05"}},
                                   {"hire_date": {"eq": "2024-05-01"}})
    # a format DuckDB cannot read is our sentence, not its exception
    bad = [ColSpec(canon="hire_date", a_src="hire_date", b_src="HireDate", kind="date",
                   a_steps=[{"op": "to date", "params": {"fmt": "%Q"}}])]
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("hire_date", "=", "2024-05-01", "Both", "auto")), "Left", "Right", bad)
    assert str(exc.value).startswith("filter on 'hire_date': the column's date format cannot be read - ")


@pytest.mark.parametrize("value,kind", [("not-a-date", "date"), ("2024-13-45", "date"), ("", "date"),
                                        ("not-a-date", "auto")])
def test_date_filter_refuses_what_is_not_a_date(value, kind):
    """A sentence from us, not DuckDB's ConversionException out of the engine."""
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("hire_date", ">=", value, "Both", kind)), "Left", "Right", SPECS)
    assert str(exc.value) == f"filter on 'hire_date': {value!r} is not a date"
    # a date value on a text column is only checked when the filter's Type says date
    assert build_filters(_rows(("emp_id", ">=", value, "Both", "auto")), "Left", "Right", SPECS)[0] == {"emp_id": {"ge": value}}


def test_number_filter_values_compare_as_numbers():
    """A number column carries type number under auto - the sides hold every value as text, so
    without it 10 > 9 is false - and the value is spelled the way the column is."""
    both, left, _ = build_filters(_rows(("salary", ">", "10000", "Both", "auto"),
                                        ("salary", "in", "10.50, 1e3, -3", "Left", "auto"),
                                        ("emp_id", "<=", "007", "Left", "number")), "Left", "Right", SPECS)
    assert both == {"salary": {"type": "number", "gt": "10000"}}
    assert left == {"salary": {"type": "number", "in": ["10.5", "1000", "-3"]},
                    "emp_id": {"type": "number", "le": "7"}}
    # Type string keeps the text comparison; like and the null checks never touch the value
    both, _, _ = build_filters(_rows(("salary", ">", "9", "Both", "string"),
                                     ("salary", "like", "1%", "Both", "auto"),
                                     ("salary", "is null", "", "Both", "auto")), "Left", "Right", SPECS)
    assert both == {"salary": {"type": "string", "gt": "9", "like": "1%", "is_null": True}}
    # a number on a text column is text unless the filter's Type says number
    assert build_filters(_rows(("emp_id", ">", "9", "Both", "auto")), "Left", "Right", SPECS)[0] == {"emp_id": {"gt": "9"}}
    assert number_texts("x", []) == []


@pytest.mark.parametrize("value,kind", [("abc", "auto"), ("", "auto"), ("nan", "auto"),
                                        ("inf", "number"), ("9,5", "number")])
def test_number_filter_refuses_what_is_not_a_number(value, kind):
    """One sentence from us on both paths - the engine's and filter_sql's - never DuckDB's Binder
    Error, and nothing but a number is ever spliced into the SQL."""
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("salary", ">=", value, "Both", kind)), "Left", "Right", SPECS)
    assert str(exc.value) == f"filter on 'salary': {value!r} is not a number"
    # the same value on a text column is only checked when the filter's Type says number
    assert build_filters(_rows(("emp_id", ">=", value, "Both", "auto")), "Left", "Right", SPECS)[0] == {"emp_id": {"ge": value}}


def _side(path, name, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    s = Side(name=name, label=path.name, csv_path=str(path))
    s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


@pytest.mark.parametrize("mode", ["key", "hash"])
def test_number_filter_on_a_key_or_uncompared_column_runs_as_numbers(tmp_path, monkeypatch, mode):
    """id > 9 on a number id keeps 10 and 100, not 100 alone (text order), whether id is the key
    (never compared, so it has no column rule) or the run pairs by hashing (no engine, filter_sql)."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    text = "id,dept,salary\n1,x,10\n5,x,10\n9,x,10\n10,x,10\n100,x,10\n"
    A, B = _side(tmp_path / "a.csv", "Left", text), _side(tmp_path / "b.csv", "Right", text)
    specs = [ColSpec(canon="id", a_src="id", b_src="id", kind="number"),
             ColSpec(canon="dept", a_src="dept", b_src="dept", kind="text"),
             ColSpec(canon="salary", a_src="salary", b_src="salary", kind="number")]
    both, _, _ = build_filters(_rows(("id", ">", "9", "Both", "auto")), "Left", "Right", specs)
    cfg = {"name": "Left_compare_Right", "mode": mode, "keys": ["id"] if mode == "key" else [],
           "specs": [s.__dict__ for s in specs], "compare_columns": ["dept", "salary"], "only_a": [], "only_b": [],
           "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0,
           "column_rules": {"dept": {"type": "string", "tolerance": 0.0}, "salary": {"type": "number"}},  # the app's rules
           "filters": both, "left_filters": {}, "right_filters": {}, "display_rows": 100,
           "null_tokens": ["NULL"], "table_formats": ["csv"], "matched_by": {}}
    res = run_comparison(A, B, cfg, ReadOptions(tokens=("NULL", ""), trim=True), "sig")["result"]
    assert not res.error
    assert (res.rows_left, res.rows_right, res.matched_rows) == (2, 2, 2)
    assert (res.rows_left_read, res.rows_right_read) == (5, 5)      # read before the filter, in both modes
    assert "try_cast(\"id\" AS DOUBLE) >" in res.filter_left


def test_two_sides_with_one_name_stay_apart():
    """Two database sides on one connection are both called SAMPLE: the labels a widget offers
    carry the tag, and a filter on B · SAMPLE lands on the right side, not silently on the left."""
    assert side_labels("HR", "Payroll") == ("HR", "Payroll")             # distinct names: as they are
    assert side_labels("SAMPLE", "SAMPLE") == ("A · SAMPLE", "B · SAMPLE")
    both, left, right = build_filters(_rows(("emp_id", "is not null", "", "B · SAMPLE", "auto"),
                                            ("salary", ">", "10", "A · SAMPLE", "auto"),
                                            ("active", "=", "y", "Both", "auto")), "SAMPLE", "SAMPLE", SPECS)
    assert right == {"emp_id": {"not_null": True}}
    assert left == {"salary": {"type": "number", "gt": "10"}}
    assert both == {"active": {"eq": "true"}}


def test_between_needs_two_values():
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("salary", "between", "3000", "Both", "number")), "Left", "Right", SPECS)
    assert "'between' on salary needs two values" in str(exc.value)
    both, _, _ = build_filters(_rows(("salary", "between", "3000..5000", "Both", "number"),
                                     ("emp_id", "is null", "", "Both", "auto")), "Left", "Right", SPECS)
    assert both == {"salary": {"type": "number", "between": ["3000", "5000"]}, "emp_id": {"is_null": True}}


def test_signature_ignores_display_only_settings():
    A, B = Side(label="a.csv"), Side(label="b.csv")
    cfg = {"name": "a_compare_b", "notes": ["key: id"], "table_formats": ["csv"], "display_rows": 1000,
           "matched_by": {"id": "name"}, "mode": "key", "keys": ["id"], "compare_columns": ["v"],
           "filters": {}, "left_filters": {}, "right_filters": {}}
    sig = signature(A, B, cfg)
    same = {**cfg, "name": "x_compare_y", "notes": [], "table_formats": ["csv", "parquet"],
            "display_rows": 100, "matched_by": {"id": "you"}}
    assert signature(A, B, same) == sig
    assert signature(A, B, {**cfg, "keys": []}) != sig
    assert signature(A, B, {**cfg, "filters": {"v": {"eq": "1"}}}) != sig
    assert signature(A, Side(label="b2.csv"), cfg) != sig
    assert ENGINE_HTML_ROWS == 2000
