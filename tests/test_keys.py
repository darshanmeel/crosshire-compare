# tests/test_keys.py
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tablecmp.keys import key_uniqueness, suggest_keys, suggest_keys_single
from tablecmp.profile import profile_singles, profile_tables, stats_table
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.sql import scratch
from tablecmp.values import ColSpec, ReadOptions, register

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


def _single():
    """hr_employees.csv on its own, every column a spec of its own name - the Profiling page."""
    P, = _read(Side(name="hr", label="hr_employees.csv", csv_path=str(EX / "hr_employees.csv")))
    kinds = {"salary": "number", "hire_date": "date", "active": "boolean"}
    return P, [ColSpec(canon=c, a_src=c, b_src=c, kind=kinds.get(c, "text")) for c in P.columns]


def _csv_single(tmp_path, header, rows):
    import csv
    with open(tmp_path / "t.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    P, = _read(Side(label="t.csv", csv_path=str(tmp_path / "t.csv")))
    return P


def test_reasons_and_overlap(tmp_path):
    A, B, specs = _sides()
    table, combos, note = suggest_keys(A, B, specs, "hr", "payroll", OPTS)
    assert combos[0] == ["emp_id"]
    top = table.iloc[0]
    assert top["Unique on both"] == "yes" and 95 < top["Overlap %"] < 100
    assert "identifier" in top["Why"] and "no nulls" in top["Why"]
    assert "hr" in top["Why"] and "payroll" in top["Why"]
    # a pair whose only unique combination holds a measure column: it is offered, and
    # the row says the measure is no key even so (the one-table search does the same)
    rows = [[i % 5, (i // 5) * 10.5] for i in range(25)]
    MA, MB = _csv_sides(tmp_path, ["dept", "amount"], rows, rows)
    mspecs = [ColSpec(canon="dept", a_src="dept", b_src="dept", kind="text"),
              ColSpec(canon="amount", a_src="amount", b_src="amount", kind="number")]
    mtable, mcombos, _ = suggest_keys(MA, MB, mspecs, "a", "b", OPTS)
    assert mcombos[0] == ["dept", "amount"]
    row = mtable.iloc[0]
    assert row["Unique on both"] == "yes" and row["Looks like a key"] == "measure columns"
    assert row["Why"].startswith("amount: a measure, decimal - never a key") and "measure" in row["Why"]


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
    assert "emp_id says identifier" in sup.iloc[0]["Why"]       # a hire date is not an identifier
    assert "say identifier" not in sup.iloc[0]["Why"]


def test_names_and_dates_are_not_called_identifiers():
    """name / date words rank a column like an identifier, but the Why must not call it one."""
    from tablecmp.keys import key_affinity, key_reasons
    d = {"probe_a": 10, "probe_b": 10}
    tot = {"probe_a": 10, "probe_b": 10}
    aff = {"emp_id": 3, "first_name": 3, "hire_date": 5, "surname": 0, "dept": 0}

    def why(cols): return key_reasons(cols, d, tot, aff, {}, 100.0, [], "how", "a", "b")
    assert why(["emp_id"]).startswith("name says identifier")
    assert why(["first_name", "emp_id"]).startswith("emp_id says identifier")
    assert why(["hire_date", "emp_id"]).startswith("emp_id says identifier")
    assert why(["first_name"]).startswith("a name, not an identifier")
    assert why(["surname"]).startswith("a name, not an identifier")
    assert why(["hire_date"]).startswith("a date, not an identifier")
    assert why(["hire_date", "first_name"]).startswith("a name, not an identifier")
    assert why(["dept"]).startswith("no identifier in the name")
    # the ranking is unchanged: a name or a date still scores like an identifier
    assert key_affinity("first_name", "VARCHAR", "VARCHAR") == 3
    assert key_affinity("hire_date", "DATE", "VARCHAR") == 5
    assert key_affinity("surname", "VARCHAR", "VARCHAR") == 0


def test_disjoint_ids_rank_below_shared(tmp_path):
    rows = {start: [[start + i, f"C{i}", i % 7] for i in range(200)] for start in (1, 5000)}
    A, B = _csv_sides(tmp_path, ["row_id", "code", "v"], rows[1], rows[5000])
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("row_id", "code", "v")]
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert combos[0] == ["code"]                          # unique on both AND shared
    row = table[table["Key columns"] == "row_id"].iloc[0]
    assert row["Overlap %"] == 0 and "no values in common" in row["Why"]
    assert row["Unique on both"] == "yes"
    assert "number their rows" not in row["Why"]           # a guess the figures cannot back


def test_zero_overlap_names_the_column_to_blame(tmp_path):
    """id is shared 100% and name is spelt differently on each side: the combination
    name + id shares nothing, and the Why says name is the reason - not the ids."""
    rows_a = [[i, f"N{i % 50}", i % 7] for i in range(200)]
    rows_b = [[i, f"M{i % 50}", i % 7] for i in range(200)]
    A, B = _csv_sides(tmp_path, ["id", "name", "v"], rows_a, rows_b)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "name", "v")]
    table, combos, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert combos[0] == ["id"] and table.iloc[0]["Overlap %"] == 100
    row = table[table["Key columns"] == "name + id"].iloc[0]
    assert row["Overlap %"] == 0
    assert "no values in common - none of a's name values found in b" in row["Why"]
    assert "number their rows" not in row["Why"]
    assert "adds nothing - id is already unique" in row["Why"]
    with_v = table[table["Key columns"] == "v + id"].iloc[0]
    assert with_v["Overlap %"] == 100 and "100.0% of a's values found in b" in with_v["Why"]


def test_zero_overlap_of_shared_columns_blames_the_combination(tmp_path):
    """Every column alone is shared, only the pairing differs - no column is named."""
    rows_a = [[i % 20, f"C{i}"] for i in range(200)]
    rows_b = [[(i + 1) % 20, f"C{i}"] for i in range(200)]
    A, B = _csv_sides(tmp_path, ["id", "code"], rows_a, rows_b)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "code")]
    table, _, _ = suggest_keys(A, B, specs, "a", "b", OPTS)
    row = table[table["Key columns"] == "id + code"].iloc[0]
    assert row["Overlap %"] == 0
    assert "no values in common, though every column alone shares some" in row["Why"]
    assert "none of" not in row["Why"] and "number their rows" not in row["Why"]


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


def test_key_uniqueness_counts_null_keys_apart_from_duplicates(tmp_path):
    """A row with no key identifies nothing: it is neither a distinct key nor a duplicate,
    and a key that is null on every row is not 'not unique, n-1 duplicate rows'."""
    rows_a = [["" if i % 10 == 0 else i, f"C{i}"] for i in range(100)]          # 10 empty ids
    rows_b = [[i // 2, f"C{i}"] for i in range(100)]                            # every id twice
    A, B = _csv_sides(tmp_path, ["id", "code"], rows_a, rows_b)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "code")]
    report = key_uniqueness(A, B, specs, ["id"], "a", "b", OPTS).set_index("Side")
    assert list(report.columns) == ["Rows", "Distinct keys", "Duplicate rows", "Null keys", "Unique"]
    assert report.loc["a"].to_dict() == {"Rows": 100, "Distinct keys": 90, "Duplicate rows": 0,
                                         "Null keys": 10, "Unique": "no"}
    assert report.loc["b"].to_dict() == {"Rows": 100, "Distinct keys": 50, "Duplicate rows": 50,
                                         "Null keys": 0, "Unique": "no"}
    # a two-column key is null when any of its columns is
    two = key_uniqueness(A, B, specs, ["id", "code"], "a", "b", OPTS).set_index("Side")
    assert two.loc["a"]["Null keys"] == 10 and two.loc["b"]["Unique"] == "yes"
    # null on every row: no duplicates to speak of
    (tmp_path / "all").mkdir()
    A2, B2 = _csv_sides(tmp_path / "all", ["id", "code"], [["", f"C{i}"] for i in range(20)], rows_b[:20])
    allnull = key_uniqueness(A2, B2, specs, ["id"], "a", "b", OPTS).set_index("Side")
    assert allnull.loc["a"].to_dict() == {"Rows": 20, "Distinct keys": 0, "Duplicate rows": 0,
                                          "Null keys": 20, "Unique": "no"}


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


def test_auto_drops_a_profile_measured_on_other_specs(tmp_path):
    """code is unique as text (001 and 1 differ) but not once Auto types it as a number: a
    profile taken on the text specs must not feed the key search or be handed back as current."""
    from tablecmp.auto import auto_configure
    from tablecmp.columns import build_table, specs_from
    rows = [["001", 10], ["1", 20], ["2", 30], ["3", 40], ["4", 50]]
    A, B = _csv_sides(tmp_path, ["code", "amount"], rows, rows)
    text_specs = specs_from(build_table(A, B))                 # the sniff keeps 001 as text
    assert {s.canon: s.kind for s in text_specs}["code"] == "text"
    stale = profile_tables(A, B, text_specs, OPTS)
    assert stale["specs"] == [asdict(s) for s in text_specs]
    assert profile_singles(stale, "code")["probe_a"] == 5
    said: list[str] = []
    cmap, notes, chosen, prof = auto_configure(A, B, "a", "b", OPTS, said.append,
                                               profile=stale, want_profile=True)
    assert {s.canon: s.kind for s in specs_from(cmap)}["code"] == "number"
    assert prof is not stale and prof["specs"] == [asdict(s) for s in specs_from(cmap)]
    assert any(m.startswith("Profiling both sides") for m in said)
    assert profile_singles(prof, "code")["probe_a"] == 4
    assert chosen != ["code"]                                  # 4 distinct of 5 - not a key on its own
    assert not any(n.startswith("key: code ") for n in notes)
    # without a fresh profile wanted, the stale one is dropped rather than passed on
    _, _, chosen2, prof2 = auto_configure(A, B, "a", "b", OPTS, said.append, profile=stale)
    assert prof2 is None and chosen2 == chosen


def test_single_table_key_and_reasons():
    P, specs = _single()
    table, combos, note = suggest_keys_single(P, specs, "hr", OPTS)
    assert list(table.columns) == ["Key columns", "Distinct", "Unique", "Duplicate rows", "Null keys",
                                   "Looks like a key", "Why"]
    assert combos[0] == ["emp_id"]
    top = table.iloc[0]
    assert top["Unique"] == "yes" and top["Distinct"] == 3000
    assert top["Duplicate rows"] == 0 and top["Null keys"] == 0 and top["Looks like a key"] == "yes"
    assert top["Why"].startswith("name says identifier") and "no nulls" in top["Why"]
    assert "3,000 distinct of 3,000" in top["Why"] and top["Why"].endswith("unique by itself")
    assert " in hr" not in top["Why"] and "found in" not in top["Why"]     # one table: no side names, no overlap
    assert "growing" in note and "profile" not in note.lower()
    sup = table[table["Key columns"] == "hire_date + emp_id"]
    assert len(sup) and sup.iloc[0]["Unique"] == "yes"
    assert "adds nothing - emp_id is already unique" in sup.iloc[0]["Why"] and "grown" in sup.iloc[0]["Why"]
    assert "emp_id says identifier" in sup.iloc[0]["Why"]


def test_single_measure_column_in_the_only_key(tmp_path):
    """dept + amount is the only unique combination: it is offered, and the row says the
    measure column is no key even so."""
    P = _csv_single(tmp_path, ["dept", "amount"], [[i % 5, (i // 5) * 10.5] for i in range(25)])
    specs = [ColSpec(canon="dept", a_src="dept", b_src="dept", kind="text"),
             ColSpec(canon="amount", a_src="amount", b_src="amount", kind="number")]
    table, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos[0] == ["dept", "amount"]
    row = table.iloc[0]
    assert row["Unique"] == "yes" and row["Distinct"] == 25
    assert row["Looks like a key"] == "measure columns"
    assert row["Why"].startswith("amount: a measure, decimal - never a key") and "measure" in row["Why"]


def test_single_takes_the_profile_figures_and_connection():
    """The profile's connection and statistics table stand in for the read and the
    single-column measuring - the result is the same, and the note says where it came from."""
    P, specs = _single()
    plain, combos, note = suggest_keys_single(P, specs, "hr", OPTS)
    con = scratch()
    register(con, P, "prof", specs, "A", OPTS, materialize=True)
    shared, combos2, note2 = suggest_keys_single(P, specs, "hr", OPTS, con=con, view="prof")
    assert combos2 == combos and note2 == note
    assert shared.to_dict("records") == plain.to_dict("records")
    stats = stats_table(con, "prof", specs)
    said: list[str] = []
    fed, combos3, note3 = suggest_keys_single(P, specs, "hr", OPTS, said.append, con=con, view="prof", stats=stats)
    assert combos3 == combos and note3 == note + " - single-column figures from the profile"
    assert fed.to_dict("records") == plain.to_dict("records")
    assert any(m.startswith("Reading the profile") for m in said)
    assert int(fed.iloc[0]["Distinct"]) == int(stats.set_index("Column").at["emp_id", "Distinct"]) == 3000
    # a bare DataFrame of Column, Distinct, Nulls is enough
    bare = pd.DataFrame({"Column": stats["Column"], "Distinct": stats["Distinct"], "Nulls": stats["Nulls"]})
    bare_t, _, bare_note = suggest_keys_single(P, specs, "hr", OPTS, con=con, view="prof", stats=bare)
    assert bare_t.to_dict("records") == plain.to_dict("records") and bare_note == note3
    # the figures are taken from the profile, not measured: told emp_id has a null and 2,999
    # distinct, the search no longer offers it by itself and grows past it
    told = pd.DataFrame({"Column": ["emp_id"], "Distinct": [2999], "Nulls": [1]})
    grown, combos4, _ = suggest_keys_single(P, specs, "hr", OPTS, con=con, view="prof", stats=told)
    assert ["emp_id"] not in combos4 and all("emp_id" in c for c in combos4)
    assert "1 nulls" in grown.iloc[0]["Why"] and "grown" in grown.iloc[0]["Why"]


def test_single_grows_a_combination_when_no_column_is_unique(tmp_path):
    P = _csv_single(tmp_path, ["dept", "grade"], [[i % 5, i // 5] for i in range(25)])
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("dept", "grade")]
    table, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos[0] == ["dept", "grade"]
    row = table.iloc[0]
    assert row["Unique"] == "yes" and row["Distinct"] == 25
    assert row["Duplicate rows"] == 0 and row["Null keys"] == 0
    assert row["Why"] == ("no identifier in the name · no nulls · 25 distinct of 25 · "
                          "grown from the most selective column")


def test_single_counts_null_keys_apart_from_duplicates(tmp_path):
    rows = [[i if i % 10 else "", f"C{i}"] for i in range(100)]      # 10 empty ids
    P = _csv_single(tmp_path, ["id", "code"], rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "code")]
    table, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos[0] == ["code"]
    code = table.iloc[0]
    assert code["Unique"] == "yes" and code["Null keys"] == 0 and "no nulls" in code["Why"]
    row = table[table["Key columns"] == "id"].iloc[0]     # id is not unique, and code adds nothing to it
    assert row["Null keys"] == 10 and row["Duplicate rows"] == 0 and row["Unique"] == "no"
    # the 10 rows with no id share nothing - they have no key - so the Why does not say they do
    assert row["Why"] == ("name says identifier · 10 nulls · 90 distinct of 100 · "
                          "on its own - adding a column told no more rows apart")
    # every row twice: duplicates, no null keys
    (tmp_path / "dup").mkdir()
    D = _csv_single(tmp_path / "dup", ["id", "code"], [[i // 2, f"C{i // 2}"] for i in range(100)])
    dup_t, dup_c, _ = suggest_keys_single(D, specs, "t", OPTS)
    assert dup_c and all(dup_t["Unique"] == "no") and all(dup_t["Null keys"] == 0)
    assert dup_t.iloc[0]["Distinct"] == 50 and dup_t.iloc[0]["Duplicate rows"] == 50
    assert "50 distinct of 100 · 50 rows share it" in dup_t.iloc[0]["Why"]


def test_single_null_seed_stands_on_its_own(tmp_path):
    """With nulls apart a column that has a null can never be part of a unique key, so growing
    it only carries columns that tell no more rows apart: the seed is offered on its own, and
    the combination that is unique without it is found beside it."""
    rows = [[("" if i == 3 else f"E{i}"), f"a{i % 10}", f"b{i // 10}", f"d{i % 3}"] for i in range(100)]
    A, = _csv_sides(tmp_path, ["emp_id", "a", "b", "d"], rows, rows)[:1]
    table, combos, _ = suggest_keys_single(A, [ColSpec(c, c, c) for c in A.columns], "t", OPTS)
    by = table.set_index("Key columns")
    assert combos[0] == ["a", "b"] and by.at["a + b", "Unique"] == "yes"
    assert combos[1] == ["emp_id"]
    assert by.at["emp_id", "Distinct"] == 99 and by.at["emp_id", "Null keys"] == 1
    assert by.at["emp_id", "Why"].endswith("99 distinct of 100 · on its own - adding a column told no more rows apart")
    assert not any(len(c) > 2 for c in combos), combos        # nothing four columns wide


def test_single_null_keys_never_make_a_combination_unique(tmp_path):
    """name + id tells the 10 rows without an id apart only through the null - the table
    counts those rows apart, so the search must too: nothing is unique, no superset says a
    combination with null keys 'is already unique', and the null rows are not 'sharing'."""
    rows = [["" if i % 10 == 3 else i, f"n{i % 51}", f"x{i % 3}"] for i in range(100)]
    P = _csv_single(tmp_path, ["id", "name", "extra"], rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "name", "extra")]
    table, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos and all(table["Unique"] == "no")
    assert not any("already unique" in w for w in table["Why"])
    with_id = table[table["Key columns"].str.contains("id")]
    assert len(with_id) and all(with_id["Distinct"] == 90) and all(with_id["Null keys"] == 10)
    assert all(with_id["Duplicate rows"] == 0)
    assert not any("share it" in w for w in with_id["Why"])
    # an identifier with a few nulls, otherwise distinct: growing it separates only the null
    # rows (their names differ), so nothing claims to be unique
    (tmp_path / "emp").mkdir()
    rows = [["" if 0 < i < 6 else f"E{i}", i % 4, f"n{i % 20}"] for i in range(100)]
    E = _csv_single(tmp_path / "emp", ["emp_id", "grp", "name"], rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("emp_id", "grp", "name")]
    table, combos, _ = suggest_keys_single(E, specs, "t", OPTS)
    assert combos and all(table["Unique"] == "no")
    assert not any("already unique" in w for w in table["Why"])
    assert all(table[table["Key columns"].str.contains("emp_id")]["Distinct"] == 95)


def test_single_unique_column_outranks_a_combination_with_null_keys(tmp_path):
    """line_no + order_id is 100 distinct only when the row with no order_id counts as a
    value; hash is unique on every row, so hash is the key - first, and Unique = yes."""
    rows = [["" if i == 3 else f"O{i:03d}", i % 5 + 1, f"{i * 2654435761 % 2**32:08x}"] for i in range(100)]
    P = _csv_single(tmp_path, ["order_id", "line_no", "hash"], rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("order_id", "line_no", "hash")]
    table, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos[0] == ["hash"]
    top = table.iloc[0]
    assert top["Unique"] == "yes" and top["Distinct"] == 100 and top["Null keys"] == 0
    assert top["Why"].endswith("unique by itself")
    with_order = table[table["Key columns"].str.contains("order_id")]
    assert len(with_order) and all(with_order["Unique"] == "no")
    assert all(with_order["Distinct"] == 99) and all(with_order["Null keys"] == 1)
    # the only set anything is said to add nothing to is hash
    said_unique = [w.split("adds nothing - ")[1].split(" is already unique")[0]
                   for w in table["Why"] if "adds nothing - " in w]
    assert said_unique and all(s == "hash" for s in said_unique)


def test_the_cut_to_the_best_candidates_is_said(tmp_path):
    """Ten columns unique by themselves, eight rows shown: the note says so - on one table
    and on a pair alike."""
    header = [f"k{j}_id" for j in range(10)]
    rows = [[f"{j}-{i}" for j in range(10)] for i in range(30)]
    P = _csv_single(tmp_path, header, rows)
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in header]
    table, combos, note = suggest_keys_single(P, specs, "t", OPTS)
    assert len(table) == len(combos) == 8 and all(table["Unique"] == "yes")
    assert note.endswith(" - the best 8 of 10 candidates are listed")
    assert "the best" not in suggest_keys_single(P, specs[:8], "t", OPTS)[2]
    (tmp_path / "pair").mkdir()
    A, B = _csv_sides(tmp_path / "pair", header, rows, rows)
    two, combos2, note2 = suggest_keys(A, B, specs, "a", "b", OPTS)
    assert len(two) == len(combos2) == 8
    assert note2.endswith(" - the best 8 of 10 candidates are listed")
    assert "the best" not in suggest_keys(A, B, specs[:8], "a", "b", OPTS)[2]


def test_single_constant_column_is_never_a_candidate(tmp_path):
    P = _csv_single(tmp_path, ["id", "region", "blank"], [[i, "EMEA", ""] for i in range(50)])
    specs = [ColSpec(canon=c, a_src=c, b_src=c, kind="text") for c in ("id", "region", "blank")]
    _, combos, _ = suggest_keys_single(P, specs, "t", OPTS)
    assert combos == [["id"]]


def test_key_reasons_for_one_table():
    """The one-table wording: no side names, no overlap; the rest as on the Compare page."""
    from tablecmp.keys import key_reasons
    aff = {"emp_id": 3, "salary": -4, "dept": 0}
    d, tot = {"prof": 2998}, {"prof": 3000}
    how = "grown from the most selective column"
    # 2 nulls and 2,998 distinct: the 2 rows without a key share nothing, so nothing is said to
    assert key_reasons(["emp_id"], d, tot, aff, {"emp_id": 2}, None, [], how, "hr", null_keys=2) == \
        "name says identifier · 2 nulls · 2,998 distinct of 3,000 · grown from the most selective column"
    # 2 nulls and 2,996 distinct: 2 rows share a key
    assert key_reasons(["emp_id"], {"prof": 2996}, tot, aff, {"emp_id": 2}, None, [], how, "hr", null_keys=2) == \
        "name says identifier · 2 nulls · 2,996 distinct of 3,000 · 2 rows share it · grown from the most selective column"
    # nothing said about null keys: rows less distinct share, as on a pair
    assert key_reasons(["emp_id"], d, tot, aff, {"emp_id": 2}, None, [], how, "hr") == \
        "name says identifier · 2 nulls · 2,998 distinct of 3,000 · 2 rows share it · grown from the most selective column"
    assert key_reasons(["salary"], d, tot, aff, {}, None, [], "how", "hr").startswith(
        "salary: a measure, decimal - never a key")
    assert key_reasons(["dept", "emp_id"], tot, tot, aff, {}, None, [frozenset(["emp_id"])], "how", "hr") == \
        "emp_id says identifier · no nulls · 3,000 distinct of 3,000 · adds nothing - emp_id is already unique · how"
