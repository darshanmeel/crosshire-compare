# tests/test_profile.py
"""One table profiled on its own: a spec per column with the looks-like suggestion taken,
the statistics table and the ten most and least frequent values per column."""
from pathlib import Path

from tablecmp.columns import single_specs, suggested_steps
from tablecmp.profile import STATS_COLS, profile_single
from tablecmp.sniff import looks_like
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL", ""), trim=True)


def _side(file: str, kind: str = "csv") -> Side:
    s = Side(name="t", label=file, csv_path=str(EX / file), kind=kind)
    s.schema = source_schema(s.csv_path, kind, ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


def test_single_specs_name_every_column_as_itself():
    """No looks: one spec per column, the column on both sides, the detected type."""
    side = _side("hr_employees.csv")
    specs = single_specs(side)
    assert [(s.canon, s.a_src, s.b_src) for s in specs] == [(c, c, c) for c in side.columns]
    assert {s.canon: s.kind for s in specs} == {
        "emp_id": "text", "first_name": "text", "last_name": "text", "department": "text",
        "salary": "number", "hire_date": "date", "active": "boolean"}
    assert all(s.a_steps == [] and s.b_steps == [] for s in specs)


def test_single_specs_take_the_looks_like_suggestion():
    """A text column whose values look like a number with thousands separators, a date in
    its own spelling or a Y/N boolean is read as that - on the Profiling page there is no
    column table to take the suggestion in."""
    payroll = _side("payroll_employees.csv")
    by = {s.canon: s for s in single_specs(payroll, looks_like(payroll, payroll.columns, opts=OPTS))}
    assert by["Salary"].kind == "number"
    assert by["Salary"].a_steps == by["Salary"].b_steps == [{"op": "remove thousands separators", "params": {}}]
    assert by["IsActive"].kind == "boolean" and by["IsActive"].a_steps == []
    assert by["EmployeeId"].kind == "text" and by["HireDate"].kind == "date"     # HireDate: DuckDB typed it
    directory = _side("directory_employees.json", "json")
    by = {s.canon: s for s in single_specs(directory, looks_like(directory, directory.columns, opts=OPTS))}
    assert by["hire_date"].kind == "date"
    assert by["hire_date"].a_steps == [{"op": "to date", "params": {"fmt": "%d-%b-%Y"}}]
    # a suggestion that is not a type, or a column the looks do not mention, changes nothing
    assert single_specs(payroll, {"Dept": "something else"})[2].kind == "text"


def test_suggested_steps():
    assert suggested_steps("number", "12,686.95 has thousands separators") == [
        {"op": "remove thousands separators", "params": {}}]
    assert suggested_steps("number", "") == []
    assert suggested_steps("date", "06-Nov-2019 → %d-%b-%Y") == [{"op": "to date", "params": {"fmt": "%d-%b-%Y"}}]
    assert suggested_steps("timestamp", "2026-08-27 10:11:12 → %Y-%m-%d %H:%M:%S") == [
        {"op": "to timestamp", "params": {"fmt": "%Y-%m-%d %H:%M:%S"}}]
    assert suggested_steps("date", "2026-08-27 → ISO, no format needed") == []
    assert suggested_steps("boolean", "Y/N") == [] and suggested_steps("text", "") == []


def test_profile_single_measures_every_column():
    side = _side("hr_employees.csv")
    specs = single_specs(side)
    said = []
    prof = profile_single(side, specs, OPTS, said.append)
    stats = prof["stats"]
    assert list(stats.columns) == STATS_COLS
    assert len(stats) == 7 and list(stats["Column"]) == side.columns
    by = stats.set_index("Column")
    assert by.at["emp_id", "Distinct"] == 3000 and by.at["emp_id", "Null %"] == 0.0
    assert by.at["salary", "Type"] == "number" and by.at["salary", "Mean"] != ""
    assert set(prof["freq"]) == set(side.columns)
    for top, bottom in prof["freq"].values():
        assert 0 < len(top) <= 10 and 0 < len(bottom) <= 10
        assert list(top.columns) == list(bottom.columns) == ["Value", "Count", "%"]
    top, _ = prof["freq"]["department"]
    assert top["Count"].is_monotonic_decreasing and len(top) == 8       # 8 departments: all of them
    assert prof["specs"][0]["canon"] == "emp_id" and "both" not in prof      # one side: no pair sheet
    assert said[0] == "Reading t…" and said[-1] == "t: value frequencies…"
