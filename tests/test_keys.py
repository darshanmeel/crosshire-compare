# tests/test_keys.py
from pathlib import Path

from tablecmp.keys import suggest_keys
from tablecmp.profile import profile_singles, profile_tables
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ColSpec, ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL", ""), trim=True)      # "" in tokens: empty cells read as null


def _read(*sides):
    for s in sides:
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
        s.source_columns = list(s.schema)
    return sides


def _sides():
    A, B = _read(Side(name="hr", label="hr_employees.csv", csv_path=str(EX / "hr_employees.csv")),
                 Side(name="payroll", label="payroll_employees.csv", csv_path=str(EX / "payroll_employees.csv")))
    specs = [ColSpec(canon="emp_id", a_src="emp_id", b_src="EmployeeId", kind="text"),
             ColSpec(canon="department", a_src="department", b_src="Dept", kind="text"),
             ColSpec(canon="salary", a_src="salary", b_src="Salary", kind="number", b_steps=[{"op": "remove thousands separators"}]),
             ColSpec(canon="active", a_src="active", b_src="IsActive", kind="boolean")]
    return A, B, specs


def _csv_sides(tmp_path, header, rows_a, rows_b):
    import csv
    for name, rows in (("a.csv", rows_a), ("b.csv", rows_b)):
        with open(tmp_path / name, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
    return _read(Side(label="a.csv", csv_path=str(tmp_path / "a.csv")),
                 Side(label="b.csv", csv_path=str(tmp_path / "b.csv")))


def test_reasons_and_overlap():
    A, B, specs = _sides()
    table, combos, note = suggest_keys(A, B, specs, "hr", "payroll", OPTS)
    assert combos[0] == ["emp_id"]
    top = table.iloc[0]
    assert top["Unique on both"] == "yes" and 95 < top["Overlap %"] < 100
    assert "identifier" in top["Why"] and "no nulls" in top["Why"]
    assert "hr" in top["Why"] and "payroll" in top["Why"]
    sal = table[table["Key columns"].str.contains("salary")]
    if len(sal):
        assert "measure" in sal.iloc[0]["Why"]


def test_superset_of_a_unique_key_ranks_below_it():
    """emp_id + hire_date is unique too, but adds nothing - the minimal key wins whatever
    the affinity sum says, and the superset says so."""
    A, B, specs = _sides()
    specs.append(ColSpec(canon="hire_date", a_src="hire_date", b_src="HireDate", kind="date",
                         b_steps=[{"op": "to date", "params": {"fmt": "%d/%m/%Y"}}]))
    table, combos, _ = suggest_keys(A, B, specs, "hr", "payroll", OPTS)
    assert combos[0] == ["emp_id"]
    sup = table[table["Key columns"].str.contains("hire_date") & table["Key columns"].str.contains("emp_id")]
    assert len(sup) and "adds nothing - emp_id is already unique" in sup.iloc[0]["Why"]


def test_disjoint_ids_rank_below_shared(tmp_path):
    rows = {start: [[start + i, f"C{i}", i % 7] for i in range(200)] for start in (1, 5000)}
    A, B = _csv_sides(tmp_path, ["row_id", "code", "v"], rows[1], rows[5000])
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("row_id", "code", "v")]
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert combos[0] == ["code"]                          # unique on both AND shared
    row = table[table["Key columns"] == "row_id"].iloc[0]
    assert row["Overlap %"] == 0 and "no values in common" in row["Why"]
    assert row["Unique on both"] == "yes"


def test_non_unique_key_says_how_many_share_it(tmp_path):
    rows = [[i // 2, f"C{i // 2}"] for i in range(100)]     # every row twice - nothing is unique
    A, B = _csv_sides(tmp_path, ["id", "code"], rows, rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "code")]
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert combos and all(table["Unique on both"] == "no")
    row = table.iloc[0]
    assert "50 rows in a share it and 50 rows in b share it" in row["Why"]
    assert "50 distinct of 100 in a, 50 of 100 in b" in row["Why"]
    assert "adds nothing" not in row["Why"]


def test_nulls_are_counted(tmp_path):
    rows = [[i if i % 10 else "", f"C{i}"] for i in range(100)]   # 10 empty ids
    A, B = _csv_sides(tmp_path, ["id", "code"], rows, rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "code")]
    table, _, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    row = table[table["Key columns"].str.contains("id")].iloc[0]     # id alone is not unique: grown
    assert "20 nulls" in row["Why"]
    assert "no nulls" in table[table["Key columns"] == "code"].iloc[0]["Why"]


def test_profile_feeds_keys_and_notes():
    A, B, specs = _sides()
    prof = profile_tables(A, B, specs, OPTS)
    assert "both" in prof and set(prof["both"]["Column"]) == {s.canon for s in specs}
    assert prof["notes"] == []
    single = profile_singles(prof, "emp_id")
    assert single == {"probe_a": 3000, "probe_b": 2985, "nulls_a": 0, "nulls_b": 0, "constant": False}
    assert profile_singles(prof, "not_there") is None and profile_singles(None, "emp_id") is None
    table, combos, note = suggest_keys(A, B, specs, "hr", "payroll", OPTS, profile=prof)
    assert combos[0] == ["emp_id"] and "profile" in note.lower()
    plain, _, plain_note = suggest_keys(A, B, specs, "hr", "payroll", OPTS)
    assert "profile" not in plain_note.lower()
    assert list(plain["Key columns"]) == list(table["Key columns"])
    assert list(plain["Distinct in hr"]) == list(table["Distinct in hr"])


def test_constant_column_is_skipped(tmp_path):
    rows = [[i, "EMEA"] for i in range(50)]
    A, B = _csv_sides(tmp_path, ["id", "region"], rows, rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "region")]
    prof = profile_tables(A, B, specs, OPTS)
    assert any("region" in n and "constant" in n for n in prof["notes"])
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS, profile=prof)
    assert all("region" not in c for c in combos)


def test_profile_notes_empty_and_lopsided(tmp_path):
    rows_a = [[i, "", f"K{i}"] for i in range(50)]
    rows_b = [[i, "", f"K{i % 5}"] for i in range(50)]
    A, B = _csv_sides(tmp_path, ["id", "blank", "k"], rows_a, rows_b)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "blank", "k")]
    prof = profile_tables(A, B, specs, OPTS)
    assert any(n.startswith("blank: empty on both sides") for n in prof["notes"])
    assert any(n.startswith("k: 50 distinct values on A against 5 on B") for n in prof["notes"])
    assert profile_singles(prof, "blank")["constant"] is True


def test_auto_runner_up_is_a_real_alternative(tmp_path):
    rows = [[i, f"C{i}", i % 7] for i in range(200)]
    A, B = _csv_sides(tmp_path, ["row_id", "code", "v"], rows, rows)
    from tablecmp.auto import auto_configure
    _, notes, chosen, _ = auto_configure(A, B, "a", "b", OPTS, lambda _m: None)
    key_note = next(n for n in notes if n.startswith("key: "))
    other = "code" if chosen == ["row_id"] else "row_id"
    assert f". Runner-up: {other} - " in key_note and "adds nothing" not in key_note


def test_auto_configure_returns_profile_and_reasons():
    from tablecmp.auto import auto_configure
    A, B, _ = _sides()
    said: list[str] = []
    cmap, notes, chosen, prof = auto_configure(A, B, "hr", "payroll", OPTS, said.append, want_profile=True)
    assert chosen == ["emp_id"] and prof is not None and "both" in prof
    assert any(m.startswith("Profiling both sides") for m in said)
    key_note = next(n for n in notes if n.startswith("key: emp_id"))
    assert "identifier" in key_note and "no nulls" in key_note
    assert "Runner-up:" not in key_note                    # every other candidate only adds to emp_id
    assert any(n.startswith("key search:") for n in notes)
    assert any(n.startswith("last_name:") and "distinct values" in n for n in notes)   # a profile note
    cmap2, notes2, chosen2, prof2 = auto_configure(A, B, "hr", "payroll", OPTS, said.append, profile=prof)
    assert prof2 is prof and chosen2 == ["emp_id"]
    _, _, chosen3, prof3 = auto_configure(A, B, "hr", "payroll", OPTS, said.append)
    assert prof3 is None and chosen3 == ["emp_id"]
