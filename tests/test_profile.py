# tests/test_profile.py
"""One table profiled on its own: a spec per column with the looks-like suggestion taken,
the statistics table and the ten most and least frequent values per column."""
from pathlib import Path

import pandas as pd

from tablecmp.columns import single_specs, suggested_steps
from tablecmp.keys import KEY_COLS
from tablecmp.observe import CORR_COLS, DEP_COLS, OUTLIER_COLS, PATTERN_COLS
from tablecmp.profile import STATS_COLS, measure, measure_on, profile_single, profile_tables, stats_table
from tablecmp.sniff import looks_like
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.sql import scratch
from tablecmp.values import ColSpec, ReadOptions, register

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL", ""), trim=True)


def _side(file: str, kind: str = "csv", base: Path = EX) -> Side:
    s = Side(name="t", label=file, csv_path=str(base / file), kind=kind)
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
    # narrated in the order it runs: the read, the statistics, the frequencies, the keys, the rest
    assert said[0] == "Reading t…" and said.index("t: statistics for 7 columns…") < said.index("t: value frequencies…")
    assert said.index("t: value frequencies…") < said.index("Looking for keys…") < said.index("What stands out…")


def test_profile_single_finds_the_key_and_what_stands_out():
    """The Profiling page's whole read on one registration of the table: the key
    candidates, the notes, the outlier, pattern and dependency tables and the headline
    come with the statistics - every one a DataFrame, list, string or int."""
    side = _side("hr_employees.csv")
    specs = single_specs(side, looks_like(side, side.columns, opts=OPTS))
    said = []
    prof = profile_single(side, specs, OPTS, said.append, name="hr")
    assert set(prof) == {"stats", "freq", "specs", "keys", "notes", "duplicates", "outliers",
                         "patterns", "deps", "corr", "headline"}
    table, combos, note = prof["keys"]
    assert list(table.columns) == KEY_COLS and combos[0] == ["emp_id"]
    assert table.iloc[0]["Key columns"] == "emp_id" and table.iloc[0]["Unique"] == "yes"
    assert note.endswith(" - single-column figures from the profile")      # not measured twice
    assert isinstance(prof["notes"], list) and all(isinstance(n, str) for n in prof["notes"])
    assert [n for n in prof["notes"] if n.startswith("key: ")] == ["key: emp_id - unique on every row"]
    assert prof["duplicates"] == 0
    out = prof["outliers"]
    assert list(out.columns) == OUTLIER_COLS and list(out["Column"]) == ["salary", "hire_date"]
    assert list(out["Type"]) == ["number", "date"]
    pats = prof["patterns"]
    assert list(pats.columns) == PATTERN_COLS and "emp_id" in set(pats["Column"])
    emp = pats[pats["Column"] == "emp_id"].iloc[0]
    assert emp["Pattern"] == "A99999" and emp["Collapsed"] == "A+9+" and emp["Count"] == 3000
    assert list(prof["deps"].columns) == DEP_COLS and list(prof["corr"].columns) == CORR_COLS
    assert prof["headline"].startswith("3,000 rows × 7 columns · key: emp_id · 0 duplicate rows")
    # the key search ran on the profile's own read, its figures from the statistics
    assert said.index("Looking for keys…") + 1 == said.index("Reading the profile…")
    assert said[-1] == "t: leading spaces, case variants, leading zeros…"


def test_profile_single_passes_the_key_depth_it_says(monkeypatch):
    """The page's warning, the notes and the headline all say keys.MAX_KEY_COLS, so the
    search is told that depth in so many words - not left to a default that could drift."""
    from tablecmp import keys
    seen = {}
    real = keys.suggest_keys_single

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(keys, "suggest_keys_single", spy)
    side = _side("hr_employees.csv")
    profile_single(side, single_specs(side), OPTS)
    assert seen["max_cols"] == keys.MAX_KEY_COLS == 4 and seen["view"] == "prof"


def test_stats_cols_order():
    assert STATS_COLS == ["Column", "Type", "Rows", "Nulls", "Null %", "Distinct", "Distinct % of filled",
                          "Distinct % of rows", "Top value", "Top %", "Min", "Max", "Mean", "Avg length",
                          "Min length", "Max length"]


def test_distinct_share_both_ways():
    """manager_id in the directory is null on about a tenth of the rows, so its distinct share
    of the filled rows is higher than its share of all rows - each straight from the definition."""
    side = _side("directory_employees.json", "json")
    by = profile_single(side, single_specs(side), OPTS)["stats"].set_index("Column")
    r = by.loc["manager_id"]
    assert r["Nulls"] > 0 and r["Null %"] > 5
    filled = r["Rows"] - r["Nulls"]
    assert r["Distinct % of filled"] == round(r["Distinct"] / filled * 100, 2)
    assert r["Distinct % of rows"] == round(r["Distinct"] / r["Rows"] * 100, 2)
    assert r["Distinct % of filled"] > r["Distinct % of rows"]
    assert by.at["id", "Distinct % of filled"] == by.at["id", "Distinct % of rows"] == 100.0    # no nulls: the same


def test_top_value_is_the_head_of_the_frequency_table():
    side = _side("hr_employees.csv")
    prof = profile_single(side, single_specs(side), OPTS)
    by = prof["stats"].set_index("Column")
    top, _ = prof["freq"]["department"]
    assert by.at["department", "Top value"] == top.iloc[0]["Value"] == "Support"
    assert by.at["department", "Top %"] == top.iloc[0]["%"] == round(412 / 3000 * 100, 2)
    assert by.at["emp_id", "Top %"] == round(1 / 3000 * 100, 2)             # unique: every value is a top value
    assert list(prof["stats"].columns) == STATS_COLS                          # the order holds after filling in


def test_min_and_max_length():
    side = _side("hr_employees.csv")
    by = profile_single(side, single_specs(side), OPTS)["stats"].set_index("Column")
    assert by.at["emp_id", "Min length"] == by.at["emp_id", "Max length"] == 6           # E10001 … E13000
    assert by.at["emp_id", "Avg length"] == 6.0
    assert by.at["first_name", "Min length"] < by.at["first_name", "Max length"]
    assert str(by["Min length"].dtype) == str(by["Max length"].dtype) == "Int64"       # whole numbers, blank when null


def test_stats_on_an_all_null_column_and_an_empty_table(tmp_path):
    """Nothing filled: the shares are 0.0, the lengths blank, and the null is the top value.
    No rows at all: every count is 0 and the top value is blank."""
    (tmp_path / "t.csv").write_text("a,b\n1,NULL\n2,\n", encoding="utf-8")
    side = _side("t.csv", base=tmp_path)
    prof = profile_single(side, single_specs(side), OPTS)
    by = prof["stats"].set_index("Column")
    assert by.at["b", "Nulls"] == 2 and by.at["b", "Distinct"] == 0
    assert by.at["b", "Distinct % of filled"] == 0.0 and by.at["b", "Distinct % of rows"] == 0.0
    assert pd.isna(by.at["b", "Min length"]) and pd.isna(by.at["b", "Max length"])
    assert by.at["b", "Top value"] == "∅ null" and by.at["b", "Top %"] == 100.0
    assert by.at["a", "Min length"] == 1 and by.at["a", "Top %"] == 50.0
    (tmp_path / "e.csv").write_text("a,b\n", encoding="utf-8")
    side = _side("e.csv", base=tmp_path)
    by = profile_single(side, single_specs(side), OPTS)["stats"].set_index("Column")
    assert by.at["a", "Rows"] == 0 and by.at["a", "Distinct % of rows"] == 0.0
    assert by.at["a", "Top value"] == "" and by.at["a", "Top %"] == 0.0


def test_stats_table_alone_leaves_the_top_value_blank():
    """stats_table returns every STATS_COLS column; the top value is measure_on's to fill in
    from the frequency tables, so on its own it is blank and 0.0."""
    side = _side("hr_employees.csv")
    specs = single_specs(side)
    con = scratch()
    register(con, side, "prof", specs, "A", OPTS, materialize=True)
    stats = stats_table(con, "prof", specs)
    assert list(stats.columns) == STATS_COLS
    assert (stats["Top value"] == "").all() and (stats["Top %"] == 0.0).all()
    assert stats.set_index("Column").at["emp_id", "Distinct % of rows"] == 100.0


def test_measure_on_is_what_measure_and_profile_single_share():
    """measure opens its own scratch connection and hands it to measure_on; profile_single
    hands it the profile's - the same frames either way, Top value / Top % filled in one
    place, and the progress lines as they were."""
    side = _side("hr_employees.csv")
    specs = single_specs(side)
    said_a, said_b = [], []
    stats_a, freq_a = measure(side, "A", specs, OPTS, said_a.append)
    con = scratch()
    register(con, side, "prof", specs, "A", OPTS, materialize=True)
    stats_b, freq_b = measure_on(con, side, "A", specs, said_b.append)
    con.close()
    pd.testing.assert_frame_equal(stats_a, stats_b)
    assert set(freq_a) == set(freq_b) == set(side.columns)
    for c in freq_a:
        pd.testing.assert_frame_equal(freq_a[c][0], freq_b[c][0])
        pd.testing.assert_frame_equal(freq_a[c][1], freq_b[c][1])
    assert (stats_b["Top value"] != "").all() and (stats_b["Top %"] > 0).all()     # filled, not stats_table's blanks
    assert said_a == ["Reading t…", "t: statistics for 7 columns…", "t: value frequencies…"]
    assert said_b == said_a[1:]                     # measure_on reads nothing: the read is the caller's
    single = profile_single(side, specs, OPTS)["stats"]
    pd.testing.assert_frame_equal(single, stats_a)


def test_profile_tables_still_pairs():
    """The pair profile reads Distinct / Nulls / Rows / Min / Max by name, so the wider
    stats table changes nothing for it: the Both sides sheet and its notes as before."""
    A, B = _side("hr_employees.csv"), _side("payroll_employees.csv")
    specs = [ColSpec("emp_id", "emp_id", "EmployeeId", "text"),
             ColSpec("department", "department", "Dept", "text"),
             ColSpec("active", "active", "IsActive", "boolean")]
    prof = profile_tables(A, B, specs, OPTS)
    assert list(prof["stats"]["A"].columns) == list(prof["stats"]["B"].columns) == STATS_COLS
    both = prof["both"].set_index("Column")
    assert list(both.index) == ["emp_id", "department", "active"]
    assert both.at["emp_id", "Distinct A"] == 3000 and both.at["emp_id", "Rows B"] > 0
    assert set(both.columns) >= {"Nulls A", "Nulls B", "Min A", "Max B", "constant", "empty"}
    assert isinstance(prof["notes"], list)
    assert prof["freq"]["department"]["A"][0].iloc[0]["Value"] == "Support"
