# tests/test_compare.py
"""The Rows filters as the engine gets them, and what makes a run stale."""
import pandas as pd
import pytest

from tablecmp.compare import ENGINE_HTML_ROWS, build_filters, date_texts, signature
from tablecmp.sources import Side
from tablecmp.values import ColSpec

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
                                     ("seen", ">", "2024-01-05", "Both", "auto"),
                                     ("salary", ">", "10000", "Both", "auto")), "Left", "Right", SPECS)
    assert both["hire_date"] == {"ge": "2024-01-05", "type": "date", "between": ["2024-01-01", "2024-12-31"]}
    assert both["seen"] == {"gt": "2024-01-05 00:00:00"}          # a timestamp column keeps the time
    assert both["salary"] == {"gt": "10000"}
    # Type date on any column: a value with a time of day keeps it, the engine compares as timestamps
    both, _, _ = build_filters(_rows(("emp_id", "=", "2024-01-05T10:11:12", "Both", "date")), "Left", "Right", SPECS)
    assert both == {"emp_id": {"type": "date", "eq": "2024-01-05 10:11:12"}}
    assert date_texts("x", [], full=False) == []


@pytest.mark.parametrize("value,kind", [("not-a-date", "date"), ("2024-13-45", "date"), ("", "date"),
                                        ("not-a-date", "auto")])
def test_date_filter_refuses_what_is_not_a_date(value, kind):
    """A sentence from us, not DuckDB's ConversionException out of the engine."""
    with pytest.raises(ValueError) as exc:
        build_filters(_rows(("hire_date", ">=", value, "Both", kind)), "Left", "Right", SPECS)
    assert str(exc.value) == f"filter on 'hire_date': {value!r} is not a date"
    # a date value on a text column is only checked when the filter's Type says date
    assert build_filters(_rows(("emp_id", ">=", value, "Both", "auto")), "Left", "Right", SPECS)[0] == {"emp_id": {"ge": value}}


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
