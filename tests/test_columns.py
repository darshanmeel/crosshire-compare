# tests/test_columns.py
"""The column table: a source column may take part in more than one pair, and a text
pair has its own say on case."""
import json
from pathlib import Path

import pandas as pd

from tablecmp.columns import (MAP_COLS, SHOWN_COLS, apply_mapping_json, build_table, chips_html, key_chips_html,
                              mapping_json, norm_key, normalise, only_in, reused, role_tone, roles, specs_from)
from tablecmp.compare import run_comparison
from tablecmp.keys import key_uniqueness, suggest_keys
from tablecmp.outputs import columns_frame, write_summary
from tablecmp.profile import profile_tables
from tablecmp.report import build_report
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL", ""), trim=True)
# one JSON "name" column against HR's first_name and last_name, a split step on each pair
MAPPING = {"columns": [
    {"a": "emp_id", "b": "id", "name": "emp_id", "type": "text", "key": True, "compare": False,
     "b_steps": [{"op": "upper", "params": {}}]},
    {"a": "first_name", "b": "name", "name": "first_name", "type": "text", "compare": True,
     "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "1"}}]},
    {"a": "last_name", "b": "name", "name": "last_name", "type": "text", "compare": True,
     "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "2"}}]},
    {"a": "department", "b": "dept", "name": "department", "type": "text", "compare": True},
    {"a": "salary", "b": "salary", "name": "salary", "type": "number", "compare": True},
    {"a": "hire_date", "b": "hire_date", "name": "hire_date", "type": "date", "compare": True,
     "b_steps": [{"op": "to date", "params": {"fmt": "%d-%b-%Y"}}]},
    {"a": "active", "b": "active", "name": "active", "type": "boolean", "compare": True},
]}


def _side(name: str, file: str, kind: str = "csv") -> Side:
    s = Side(name=name, label=file, csv_path=str(EX / file), kind=kind)
    s.schema = source_schema(s.csv_path, kind, ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


def _sides() -> tuple[Side, Side]:
    return _side("hr", "hr_employees.csv"), _side("directory", "directory_employees.json", "json")


def _pairs(cmap: pd.DataFrame) -> list[tuple[str, str]]:
    return [(r["A column"], r["B column"]) for _, r in cmap.iterrows() if r["A column"] and r["B column"]]


def _set(cmap: pd.DataFrame, i: int, **cells) -> pd.DataFrame:
    """What the editor hands back after one row was changed."""
    e = cmap.copy()
    for c, v in cells.items():
        e.at[i, c] = v
    return e


def test_normalise_keeps_a_column_used_in_two_pairs():
    """Picking a B column that another row already uses keeps both pairs, the second marked
    "you", and adds no spare row for that column."""
    A, B = _sides()
    cm = build_table(A, B)
    assert ("first_name", "name") in _pairs(cm)                  # a similar-name guess
    assert "last_name" in only_in(cm, "A")
    j = cm.index[cm["A column"] == "last_name"][0]
    cm2 = normalise(_set(cm, j, **{"B column": "name"}), cm, A, B)
    assert _pairs(cm2).count(("first_name", "name")) == 1 and ("last_name", "name") in _pairs(cm2)
    assert cm2.loc[cm2["A column"] == "first_name", "Matched by"].iloc[0] != "you"
    assert cm2.loc[cm2["A column"] == "last_name", "Matched by"].iloc[0] == "you"
    assert (cm2["B column"] == "name").sum() == 2                # two pairs, no one-sided row
    assert "name" not in only_in(cm2, "B") and len(cm2) == len(cm)      # one row became a pair
    assert list(cm2.columns) == MAP_COLS and not cm2["Common name"].duplicated().any()
    # every column of either side is still on the sheet
    assert set(cm2["A column"]) - {""} == set(A.columns) and set(cm2["B column"]) - {""} == set(B.columns)
    # the same table back from the editor untouched: nothing moves
    cm3 = normalise(cm2.copy(), cm2, A, B)
    assert _pairs(cm3) == _pairs(cm2) and list(cm3["Matched by"]) == list(cm2["Matched by"])


def test_normalise_unpairing_gives_the_column_its_own_row_only_when_no_pair_is_left():
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    i = cm.index[cm["A column"] == "first_name"][0]
    cm2 = normalise(_set(cm, i, **{"B column": ""}), cm, A, B)   # last_name still uses name
    assert ("last_name", "name") in _pairs(cm2) and "name" not in only_in(cm2, "B")
    assert "first_name" in only_in(cm2, "A")
    j = cm2.index[cm2["A column"] == "last_name"][0]
    cm3 = normalise(_set(cm2, j, **{"B column": ""}), cm2, A, B)
    assert "name" in only_in(cm3, "B") and (cm3["B column"] == "name").sum() == 1


def test_normalise_empty_row_comes_back_and_a_second_pair_adds_no_spare_row():
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    n = len(cm)                                                  # 7 pairs and manager_id on its own
    i = cm.index[cm["B column"] == "manager_id"][0]
    cm2 = normalise(_set(cm, i, **{"B column": ""}), cm, A, B)   # nothing on either side: comes back
    assert len(cm2) == n and "manager_id" in only_in(cm2, "B")
    cm3 = normalise(_set(cm2, i, **{"A column": "emp_id"}), cm2, A, B)  # emp_id now in two pairs
    assert ("emp_id", "manager_id") in _pairs(cm3) and ("emp_id", "id") in _pairs(cm3)
    assert len(cm3) == n and not only_in(cm3, "A") and not only_in(cm3, "B")
    assert not cm3["Common name"].duplicated().any()             # the new pair keeps its own name


def test_apply_mapping_json_accepts_the_same_column_twice():
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    assert _pairs(cm) == [(c["a"], c["b"]) for c in MAPPING["columns"]]
    assert only_in(cm, "A") == [] and only_in(cm, "B") == ["manager_id"]
    assert (cm["B column"] == "name").sum() == 2
    specs = {s.canon: s for s in specs_from(cm)}
    assert specs["first_name"].b_src == specs["last_name"].b_src == "name"
    assert specs["first_name"].b_steps[0]["params"]["n"] == "1"
    assert specs["last_name"].b_steps[0]["params"]["n"] == "2"
    assert list(cm["Common name"]) == ["emp_id", "first_name", "last_name", "department", "salary",
                                       "hire_date", "active", "manager_id"]


def test_mapping_round_trip_keeps_both_pairs():
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    again = apply_mapping_json(mapping_json(cm), A, B)
    assert _pairs(again) == _pairs(cm)
    assert [s.__dict__ for s in specs_from(again)] == [s.__dict__ for s in specs_from(cm)]
    assert list(again["Key"]) == list(cm["Key"]) and list(again["Compare"]) == list(cm["Compare"])


def test_reused_names_the_column_and_the_side():
    A, B = _sides()
    specs = specs_from(apply_mapping_json(json.dumps(MAPPING), A, B))
    assert reused(specs, "HR", "Directory") == ["name used 2 times on the Directory"]
    assert reused(specs_from(build_table(A, B)), "HR", "Directory") == []


def test_run_with_a_column_paired_twice(tmp_path, monkeypatch):
    """The whole pipeline on the mapping: two specs read the JSON's name column with a
    different step each, and the key, profile, run, sheets and report all follow."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    specs = specs_from(cm)
    keys = ["emp_id"]
    compare = ["first_name", "last_name", "department", "salary", "hire_date", "active"]
    cfg = {"name": "hr_compare_directory", "mode": "key", "keys": keys, "specs": [s.__dict__ for s in specs],
           "compare_columns": compare, "only_a": only_in(cm, "A"), "only_b": only_in(cm, "B"),
           "trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0, "column_rules": {},
           "filters": {}, "left_filters": {}, "right_filters": {}, "display_rows": 100,
           "null_tokens": ["NULL"], "table_formats": ["csv"]}
    run = run_comparison(A, B, cfg, OPTS, "sig")
    res = run["result"]
    assert not res.error
    assert (res.matched_rows, res.only_left, res.only_right) == (2970, 30, 20)
    assert res.diffs_by_column.get("first_name", 0) == 0 and res.diffs_by_column.get("last_name", 0) == 0
    assert res.diffs_by_column.get("hire_date", 0) == 0

    uniq = key_uniqueness(A, B, specs, keys, "hr", "directory", OPTS)
    assert list(uniq["Unique"]) == ["yes", "yes"]
    table, combos, _ = suggest_keys(A, B, specs, "hr", "directory", OPTS)
    assert combos and combos[0] == ["emp_id"]
    prof = profile_tables(A, B, specs, OPTS)
    both = prof["both"].set_index("Column")
    # each pair profiles its own reading of name: a few dozen first or last names, not 2,990 full ones
    assert both.at["first_name", "Distinct B"] < 100 and both.at["last_name", "Distinct B"] < 100
    assert both.at["first_name", "Distinct B"] != both.at["last_name", "Distinct B"]
    assert set(prof["freq"]) == {s.canon for s in specs}

    write_summary(run, A, B, "hr", "directory", profile=prof)
    sheet = columns_frame(run).set_index("column")
    assert sheet.at["first_name", "name_b"] == sheet.at["last_name", "name_b"] == "name"
    assert sheet.at["first_name", "mismatched"] == 0 and sheet.at["last_name", "mismatched"] == 0
    assert sheet.at["manager_id", "role"] == "only in B"
    folder = Path(run["folder"])
    prof_csv = (folder / "hr_compare_directory__profile.csv").read_text(encoding="utf-8")
    assert prof_csv.count("first_name,") == 2 and prof_csv.count("last_name,") == 2   # one row per side
    html = build_report(run, A, B, "hr", "directory", limit=20)
    assert 'id="columns"' in html and "N=1" in html and "N=2" in html


def test_app_runs_with_a_column_paired_twice(monkeypatch, tmp_path):
    """The same mapping through the page: the table takes it, the setup card says name is used
    twice, Compare gives the counts, and Reset to name matches still undoes it."""
    from tests.test_apptest import _boot, _load_path, _ok
    at = _boot(monkeypatch, tmp_path)
    at.text_input(key="nick_A").input("HR").run()
    at.text_input(key="nick_B").input("Directory").run()
    _load_path(at, "A", EX / "hr_employees.csv")
    _load_path(at, "B", EX / "directory_employees.json")
    A, B = at.session_state["A"], at.session_state["B"]
    at.session_state["cmap"] = apply_mapping_json(json.dumps(MAPPING), A, B)
    at.session_state["map_rev"] += 1
    at = _ok(at.run())
    cm = at.session_state["cmap"]
    assert _pairs(cm) == [(c["a"], c["b"]) for c in MAPPING["columns"]]
    page = "\n".join(m.value for m in at.markdown)
    assert "name used 2 times on the Directory" in page
    assert any("more than one pair" in c.value for c in at.caption)
    at = _ok(at.button(key="go").click().run())
    res = at.session_state["result"]["result"]
    assert (res.matched_rows, res.only_left, res.only_right) == (2970, 30, 20)
    assert res.diffs_by_column.get("first_name", 0) == 0 and res.diffs_by_column.get("last_name", 0) == 0
    sheet = (Path(at.session_state["result"]["folder"]) / "HR_compare_Directory__columns.csv").read_text(encoding="utf-8")
    assert "first_name,first_name,name," in sheet and "last_name,last_name,name," in sheet
    reset = next(b for b in at.button if b.label == "Reset to name matches")
    at = _ok(reset.click().run())
    assert _pairs(at.session_state["cmap"]) == _pairs(build_table(A, B))


def test_mapping_round_trip_keeps_case():
    """The Case cell comes in from the mapping file, survives the editor and goes back out;
    only a text pair acts on it."""
    A, B = _sides()
    cols = json.loads(json.dumps(MAPPING))["columns"]
    cols[1]["case"] = "EXACT"           # first_name - spelt anyhow
    cols[2]["case"] = "loose"           # last_name - not a choice: blank
    cols[3]["case"] = "ignore"          # department
    cols[4]["case"] = "ignore"          # salary - a number pair keeps the cell but takes no notice
    cm = apply_mapping_json(json.dumps({"columns": cols}), A, B)
    by = cm.set_index("Common name")["Case"]
    assert (by["first_name"], by["last_name"], by["department"], by["salary"]) == ("exact", "", "ignore", "ignore")
    assert by["manager_id"] == "" and by["emp_id"] == ""       # one-sided or unset: blank
    out = {c["name"]: c["case"] for c in json.loads(mapping_json(cm))["columns"]}
    assert (out["first_name"], out["last_name"], out["department"]) == ("exact", "", "ignore")
    again = apply_mapping_json(mapping_json(cm), A, B)
    assert list(again["Case"]) == list(cm["Case"])
    assert [s.__dict__ for s in specs_from(again)] == [s.__dict__ for s in specs_from(cm)]
    specs = {s.canon: s for s in specs_from(cm)}
    assert specs["department"].case == "ignore" and specs["department"].case_rule() is True
    assert specs["first_name"].case_rule() is False and specs["last_name"].case_rule() is None
    assert specs["salary"].case == "ignore" and specs["salary"].case_rule() is None
    assert specs["department"].describe() == "text · ignore case"
    assert specs["first_name"].describe() == "text · exact case · B: part N split by S (separator=' ', N=1)"
    assert "case" not in specs["salary"].describe() and specs["emp_id"].describe() == "text · B: upper"
    # back from the editor: a cleared cell is blank, the others stay, and a bad value is blank
    i = cm.index[cm["Common name"] == "department"][0]
    j = cm.index[cm["Common name"] == "first_name"][0]
    cm2 = normalise(_set(_set(cm, i, Case=None), j, Case="Ignore "), cm, A, B)
    by2 = cm2.set_index("Common name")["Case"]
    assert by2["department"] == "" and by2["first_name"] == "ignore" and by2["salary"] == "ignore"
    assert list(cm2.columns) == MAP_COLS and "Case" in SHOWN_COLS


def test_case_cell_beats_the_switch(monkeypatch, tmp_path):
    """A small pair whose Right lower-cases every city and one code: the Case cell on city
    decides for city on its own, whatever the Ignore case in values switch says, and the
    run's rules, report and column sheet say so."""
    from tests.test_apptest import _boot, _load_path, _ok
    (tmp_path / "left.csv").write_text("id,city,code\n1,Paris,A1\n2,London,B2\n3,Rome,C3\n", encoding="utf-8")
    (tmp_path / "right.csv").write_text("id,city,code\n1,paris,A1\n2,london,b2\n3,rome,C3\n", encoding="utf-8")
    at = _boot(monkeypatch, tmp_path)
    _load_path(at, "A", tmp_path / "left.csv")
    _load_path(at, "B", tmp_path / "right.csv")
    A, B = at.session_state["A"], at.session_state["B"]

    def compare(case: str, switch: bool) -> dict:
        cols = [{"a": "id", "b": "id", "name": "id", "type": "text", "key": True, "compare": False},
                {"a": "city", "b": "city", "name": "city", "type": "text", "compare": True, "case": case},
                {"a": "code", "b": "code", "name": "code", "type": "text", "compare": True}]
        at.session_state["cmap"] = apply_mapping_json(json.dumps({"columns": cols}), A, B)
        at.session_state["map_rev"] += 1
        _ok(at.run())
        box = at.checkbox(key="opt_case")
        _ok((box.check() if switch else box.uncheck()).run())
        _ok(at.button(key="go").click().run())
        run = at.session_state["result"]
        assert not run["result"].error, run["result"].error
        return run

    def diffs(run) -> tuple[int, int]:
        d = run["result"].diffs_by_column
        return d.get("city", 0), d.get("code", 0)

    text = {"type": "string", "tolerance": 0.0}        # a text pair: never a number, no Case of its own
    run = compare("", False)                            # blank follows the switch: case matters
    assert diffs(run) == (3, 1) and run["cfg"]["column_rules"] == {"city": text, "code": text}
    assert "case matters · tolerance" in run["_report"]
    run = compare("ignore", False)                      # the cell alone ignores case on city
    assert diffs(run) == (0, 1)
    assert run["cfg"]["column_rules"] == {"city": {**text, "ignore_case": True}, "code": text}
    assert "case matters · <b>ignored on: city</b>" in run["_report"]
    assert "<code>city</code> text · ignore case" in run["_report"]
    sheet = (Path(run["folder"]) / f"{run['pair']}__columns.csv").read_text(encoding="utf-8")
    assert "city,city,city,compared,text · ignore case,file,3,0," in sheet    # matched_by: the mapping file
    assert "code,code,code,compared,text,file,2,1," in sheet
    page = "\n".join(m.value for m in at.markdown)
    assert "<code>city</code> text · ignore case" in page         # the setup card's Read as row
    run = compare("", True)                             # the switch alone: case ignored everywhere
    assert diffs(run) == (0, 0) and run["cfg"]["column_rules"] == {"city": text, "code": text}
    assert "<b>case ignored</b> · tolerance" in run["_report"]
    run = compare("exact", True)                        # the cell beats the switch on city
    assert diffs(run) == (3, 0)
    assert run["cfg"]["column_rules"] == {"city": {**text, "ignore_case": False}, "code": text}
    assert "<b>case ignored</b> · <b>exact on: city</b>" in run["_report"]
    run = compare("ignore", True)                       # the cell agrees with the switch: nothing to add
    assert diffs(run) == (0, 0) and "on: city" not in run["_report"]


def test_numeric_tolerance_leaves_text_pairs_alone(monkeypatch, tmp_path):
    """A text code 001 against 1 and a zip 02134 against 2134 stay different with a numeric
    tolerance above 0: the tolerance is for number pairs only, and every compared pair tells
    the engine so in its own rule."""
    from tests.test_apptest import _boot, _load_path, _ok
    (tmp_path / "left.csv").write_text("id,code,zip,amount\n1,001,02134,10.001\n2,B2,00501,20\n",
                                       encoding="utf-8")
    (tmp_path / "right.csv").write_text("id,code,zip,amount\n1,1,2134,10.002\n2,B2,501,20\n",
                                        encoding="utf-8")
    at = _boot(monkeypatch, tmp_path)
    _load_path(at, "A", tmp_path / "left.csv")
    _load_path(at, "B", tmp_path / "right.csv")
    A, B = at.session_state["A"], at.session_state["B"]
    cols = [{"a": "id", "b": "id", "name": "id", "type": "text", "key": True, "compare": False},
            {"a": "code", "b": "code", "name": "code", "type": "text", "compare": True},
            {"a": "zip", "b": "zip", "name": "zip", "type": "text", "compare": True, "case": "ignore"},
            {"a": "amount", "b": "amount", "name": "amount", "type": "number", "compare": True}]
    at.session_state["cmap"] = apply_mapping_json(json.dumps({"columns": cols}), A, B)
    at.session_state["map_rev"] += 1
    _ok(at.run())
    _ok(at.number_input(key="opt_tol").set_value(0.01).run())
    _ok(at.button(key="go").click().run())
    run = at.session_state["result"]
    res = run["result"]
    assert not res.error, res.error
    by = {c: res.diffs_by_column.get(c, 0) for c in ("code", "zip", "amount")}
    assert by == {"code": 1, "zip": 2, "amount": 0}          # amount's 0.001 gap is inside the tolerance
    assert run["cfg"]["column_rules"] == {"code": {"type": "string", "tolerance": 0.0},
                                          "zip": {"type": "string", "tolerance": 0.0, "ignore_case": True},
                                          "amount": {"type": "number"}}


def test_app_flow_with_every_item_together(monkeypatch, tmp_path):
    """One page flow across the sweep: named sides, Auto, the split mapping with Case ignore on
    department and a global tolerance, Compare, the looks-like cells, matched_by in columns.csv,
    the case choice in summary.json, and Save everything under the pair name."""
    from tests.test_apptest import _boot, _load_path, _ok
    at = _boot(monkeypatch, tmp_path)
    at.text_input(key="nick_A").input("HR").run()
    at.text_input(key="nick_B").input("Directory").run()
    _load_path(at, "A", EX / "hr_employees.csv")
    _load_path(at, "B", EX / "directory_employees.json")
    _ok(at.button(key="auto_btn").click().run())
    at = _ok(at.run())
    assert at.session_state["result"]["pair"] == "HR_compare_Directory"
    A, B = at.session_state["A"], at.session_state["B"]
    m = json.loads(json.dumps(MAPPING))
    next(c for c in m["columns"] if c["name"] == "department")["case"] = "ignore"
    at.session_state["cmap"] = apply_mapping_json(json.dumps(m), A, B)
    at.session_state["map_rev"] += 1
    at = _ok(at.run())
    _ok(at.number_input(key="opt_tol").set_value(0.01).run())
    at = _ok(at.button(key="go").click().run())
    run = at.session_state["result"]
    res = run["result"]
    assert not res.error and run["pair"] == "HR_compare_Directory"
    assert (res.matched_rows, res.only_left, res.only_right) == (2970, 30, 20)
    assert all(res.diffs_by_column.get(c, 0) == 0 for c in ("first_name", "last_name", "hire_date"))
    cm = at.session_state["cmap"].set_index("Common name")
    assert cm.at["hire_date", "B looks like"].endswith("%d-%b-%Y") and cm.at["hire_date", "A looks like"] == ""
    assert cm.at["department", "Case"] == "ignore" and cm.at["last_name", "B column"] == "name"
    folder, pair = Path(run["folder"]), run["pair"]
    sheet = (folder / f"{pair}__columns.csv").read_text(encoding="utf-8").splitlines()
    assert sheet[0].split(",")[:6] == ["column", "name_a", "name_b", "role", "read_as", "matched_by"]
    assert "department,department,dept,compared,text · ignore case,file," in "\n".join(sheet)
    settings = json.loads((folder / f"{pair}__summary.json").read_text(encoding="utf-8"))["settings"]
    assert settings["tolerance"] == 0.01
    assert settings["column_rules"]["department"] == {"type": "string", "tolerance": 0.0, "ignore_case": True}
    assert next(s for s in settings["specs"] if s["canon"] == "department")["case"] == "ignore"
    assert "ignored on: department" in run["_report"]
    _ok(at.button(key="save_all").click().run())
    saved = sorted(Path(tmp_path / "out").glob(f"{pair}__*"))
    assert len(saved) == 1 and (saved[0] / f"{pair}__summary.json").exists()


def test_roles_name_what_each_row_is():
    """A paired row is a key, compared or not compared; a one-sided row says which file has
    it - one role per row, on the table's own index."""
    A, B = _sides()
    cm = apply_mapping_json(json.dumps(MAPPING), A, B)
    cm.loc[cm["Common name"] == "department", "Compare"] = False
    got = roles(cm, "HR", "Directory")
    assert list(got.index) == list(cm.index)
    assert dict(zip(cm["Common name"], got)) == {
        "emp_id": "key", "first_name": "compared", "last_name": "compared", "department": "not compared",
        "salary": "compared", "hire_date": "compared", "active": "compared", "manager_id": "only in Directory"}
    cm2 = build_table(A, B)                                      # last_name has no counterpart here
    assert dict(zip(cm2["A column"], roles(cm2, "HR", "Directory")))["last_name"] == "only in HR"
    assert roles(cm.iloc[0:0], "HR", "Directory").empty
    assert [role_tone(r) for r in ("key", "compared", "not compared", "only in HR")] == ["pos", "", "neg", "neg"]


def test_chips_html_one_chip_per_row_in_its_colour():
    """Green for a key, plain for a compared column, red with the reason otherwise - the
    source name on a one-sided chip, the common name on a pair, everything escaped."""
    A = Side(name="a", label="a.csv", schema={"emp_id": "VARCHAR", "salary": "DOUBLE", "notes": "VARCHAR", "a<b": "VARCHAR"})
    B = Side(name="b", label="b.csv", schema={"emp_id": "VARCHAR", "salary": "DOUBLE", "notes": "VARCHAR", "CostCenter": "VARCHAR"})
    cm = build_table(A, B)
    cm.loc[cm["Common name"] == "emp_id", "Key"] = True
    cm.loc[cm["Common name"] == "notes", "Compare"] = False
    assert chips_html(cm, "HR", "Payroll") == (
        '<div class="chips"><span class="chip key">emp_id</span><span class="chip">salary</span>'
        '<span class="chip off">notes · not compared</span><span class="chip off">a&lt;b · only in HR</span>'
        '<span class="chip off">CostCenter · only in Payroll</span></div>')
    assert chips_html(cm.iloc[0:0], "HR", "Payroll") == '<div class="chips"></div>'


def test_key_chips_are_one_green_chip_per_key_column():
    """The Summary tab's Key block: every key column a green chip, escaped, in key order."""
    assert key_chips_html(["emp_id", "a<b"]) == ('<div class="chips"><span class="chip key">emp_id</span>'
                                                 '<span class="chip key">a&lt;b</span></div>')
    assert key_chips_html([]) == '<div class="chips"></div>'


def test_page_column_table_shows_roles_and_chips(monkeypatch, tmp_path):
    """After Auto on the sample pair the column table is open, with a green chip for the key
    and a red one for the column only Payroll has - and nothing to confirm or edit."""
    from tests.test_apptest import _boot, _load_path, _ok
    at = _boot(monkeypatch, tmp_path)
    at.text_input(key="nick_B").input("Payroll").run()
    _load_path(at, "A", EX / "hr_employees.csv")
    _load_path(at, "B", EX / "payroll_employees.csv")
    _ok(at.button(key="auto_btn").click().run())
    at = _ok(at.run())
    table = next(e for e in at.main.expander if e.label.startswith("Column table - "))
    assert table.label == "Column table - 6 pairs · every column from either file"
    page = "\n".join(m.value for m in at.markdown)
    assert 'class="chip key">emp_id<' in page and 'class="chip off">CostCenter · only in Payroll<' in page
    assert not [b for b in at.button if b.label in ("Confirm columns", "Edit columns")]
    assert "confirmed" not in at.session_state
    assert list(at.session_state["cmap"].columns) == MAP_COLS         # the Role column is not stored
    caption = next(c.value for c in at.caption if "One row per column" in c.value)
    assert "**Role**" in caption and "green for a key" in caption and "greyed" not in caption


def test_apply_mapping_json_skips_an_identical_pair_listed_twice():
    A, B = _sides()
    text = json.dumps({"columns": [
        {"a": "last_name", "b": "name", "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "2"}}]},
        {"a": "last_name", "b": "name", "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "2"}}]},
        {"a": "last_name", "b": "name", "b_steps": [{"op": "length", "params": {}}]},
    ]})
    cm = apply_mapping_json(text, A, B)
    pairs = cm[(cm["A column"] == "last_name") & (cm["B column"] == "name")]
    assert len(pairs) == 2 and list(pairs["Common name"]) == ["last_name", "last_name_2"]


def test_build_table_pairs_non_ascii_names_by_name_whatever_the_order():
    """Headers with no ASCII letters (CJK, Cyrillic, accented) pair with their namesake on
    the other side, not with whatever sits in the same position, and keep their own name."""
    A = Side(name="a", label="a.csv", schema={"社員番号": "BIGINT", "名前": "VARCHAR", "部署": "VARCHAR"})
    B = Side(name="b", label="b.csv", schema={"部署": "VARCHAR", "名前": "VARCHAR", "社員番号": "BIGINT"})
    cm = build_table(A, B)
    assert _pairs(cm) == [("社員番号", "社員番号"), ("名前", "名前"), ("部署", "部署")]
    assert list(cm["Matched by"]) == ["name"] * 3
    assert list(cm["Common name"]) == ["社員番号", "名前", "部署"]
    assert only_in(cm, "A") == [] and only_in(cm, "B") == []
    # Cyrillic and accented names likewise: matched case-blind, and a near miss is still
    # a similar-name guess rather than a "name" match
    A = Side(name="a", label="a.csv", schema={"Номер": "BIGINT", "Имя": "VARCHAR", "Prénom": "VARCHAR"})
    B = Side(name="b", label="b.csv", schema={"Prenom": "VARCHAR", "имя": "VARCHAR", "Номер сотр.": "BIGINT"})
    cm = build_table(A, B)
    assert _pairs(cm) == [("Номер", "Номер сотр."), ("Имя", "имя"), ("Prénom", "Prenom")]
    assert list(cm["Matched by"]) == ["guess - check", "name", "similar name"]
    assert list(cm["Common name"]) == ["номер", "имя", "prénom"]
    # ASCII names are normalised exactly as before
    assert norm_key("Emp_ Id") == "emp_id" and norm_key("salary_(usd)") == "salary_usd" and norm_key("  ") == "col"
