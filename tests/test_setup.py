# tests/test_setup.py
"""The column table, the setup card and the steps, with no page attached - what the Streamlit
page and the React server both call."""
from pathlib import Path

import pytest

from tablecmp import loading as ld
from tablecmp import setup as su
from tablecmp.columns import build_table
from tablecmp.sources import file_stamp, source_schema
from tablecmp.values import NULL_TOKENS_DEFAULT, steps_from_json

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """HR against payroll, loaded as the page loads them, and their fresh column table."""
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))

    def side(tag, name, path):
        schema = source_schema(str(path), "csv", ",", True, file_stamp(str(path)))
        return ld.build_side(tag, ld.ReadAsked(name=name, label=path.name, path=str(path), snapshot=False), schema)
    A, B = side("A", "HR", EX / "hr_employees.csv"), side("B", "PR", EX / "payroll_employees.csv")
    looks, said = su.sniff_sides(A, B, su.read_options({}))
    assert said == []
    return A, B, looks, build_table(A, B, looks)


def test_the_table_and_what_it_amounts_to(pair):
    A, B, looks, cmap = pair
    assert looks["B"]["IsActive"] == "boolean · Y/N"
    s = su.setup_of(cmap)
    assert s.canon == ["emp_id", "last_name", "salary", "hire_date", "active"]
    assert s.keys == [] and s.compare == s.canon
    assert (s.only_a, s.only_b) == (["first_name", "department"], ["Dept", "CostCenter"])
    assert su.seed_key(A, B) == ("hr_employees.csv", tuple(A.columns), "payroll_employees.csv", tuple(B.columns))


def test_one_cell_changed_and_the_table_made_whole(pair):
    A, B, looks, cmap = pair
    new, reshaped = su.edit_cell(cmap, looks, A, B, 1, "B column", "")       # last_name loses FullName
    assert reshaped and len(new) == len(cmap) + 1
    assert list(new["A column"]) == ["emp_id", "salary", "hire_date", "active", "first_name", "last_name",
                                     "department", "", "", ""]
    assert "FullName" in list(new["B column"]) and cmap.at[1, "B column"] == "FullName"   # the old one untouched
    ticked, reshaped = su.edit_cell(cmap, looks, A, B, 0, "Key", True)
    assert not reshaped and su.setup_of(ticked).keys == ["emp_id"] and not cmap.at[0, "Key"]
    paired, reshaped = su.edit_cell(cmap, looks, A, B, 5, "B column", "Dept")  # first_name takes Dept
    row = paired.set_index("Common name").loc["first_name"]
    assert reshaped and row["B column"] == "Dept" and row["Matched by"] == "you" and row["Compare"]
    renamed, _ = su.edit_cell(cmap, looks, A, B, 1, "Common name", "emp_id")
    assert list(renamed["Common name"][:2]) == ["emp_id", "emp_id_2"] and su.duplicate_names(renamed) == []


def test_a_cell_that_cannot_change_is_refused(pair):
    A, B, looks, cmap = pair
    with pytest.raises(ValueError, match="worked out"):
        su.edit_cell(cmap, looks, A, B, 0, "Matched by", "you")
    with pytest.raises(IndexError):
        su.edit_cell(cmap, looks, A, B, len(cmap), "Key", True)


def test_the_chips_and_the_card(pair):
    A, B, looks, cmap = pair
    chips = su.chip_items(cmap, "HR", "PR")
    assert chips[0] == ("emp_id", "") and ("Dept · only in PR", "off") in chips
    card = dict(su.card_rows(su.setup_of(cmap), "HR", "PR"))
    assert card["Paired"] == '5 columns · <span class="m">2 only in HR, 2 only in PR</span>'
    assert card["Key"].startswith('<span class="warn">none ticked')
    assert "PR looks like boolean (Y/N) - read as text" in card["Read as"]
    assert list(card) == ["Paired", "Key", "Compare", "Read as", "Only in HR", "Only in PR"]
    lt = su.edit_cell(cmap, looks, A, B, 1, "Common name", "<b>x</b>")[0]
    assert "&lt;b&gt;x&lt;/b&gt;" in dict(su.card_rows(su.setup_of(lt), "HR", "PR"))["Compare"]


def test_steps_and_types(pair):
    _, _, _, cmap = pair
    spec = su.spec_of(cmap, "salary")
    side, steps = su.steps_after(spec, "B", "add", {"op": "remove thousands separators", "params": {}})
    assert side == "B" and steps == [{"op": "remove thousands separators", "params": {}}]
    stepped = su.with_steps(cmap, "salary", "B", steps)
    assert steps_from_json(stepped.set_index("Common name").at["salary", "B steps"]) == steps
    assert cmap.set_index("Common name").at["salary", "B steps"] == "[]"            # the old one untouched
    side, steps = su.steps_after(su.spec_of(stepped, "salary"), "B", "add", {"op": "to date", "params": {"fmt": ""}})
    assert su.with_steps(stepped, "salary", "B", steps).set_index("Common name").at["salary", "Type"] == "date"
    assert su.steps_after(su.spec_of(stepped, "salary"), "B", "copy") == ("A", [{"op": "remove thousands separators", "params": {}}])
    assert su.steps_after(su.spec_of(stepped, "salary"), "B", "pop") == ("B", [])
    assert su.with_type(cmap, "active", "boolean").set_index("Common name").at["active", "Type"] == "boolean"
    with pytest.raises(ValueError, match="A Type is one of"):
        su.with_type(cmap, "active", "money")
    assert su.spec_of(cmap, "department") is None                                  # one-sided: no spec


def test_a_step_that_lacks_what_it_needs_is_said():
    assert su.step_problem({"op": "custom expression", "params": {"expr": "upper(y)"}}) == \
        "The expression must mention `x`, the value."
    assert su.step_problem({"op": "replace text", "params": {"a": "", "b": ""}}) == "Type the find first - one space counts."
    assert su.step_problem({"op": "replace text", "params": {"a": " ", "b": ""}}) == ""
    with pytest.raises(ValueError, match="An action is one of"):
        su.steps_after(su.ColSpec("x", "x", "x"), "A", "undo")


def test_the_switches_and_what_they_read():
    assert su.settings_of(None) == {"trim": True, "empty_as_null": True, "ignore_case": False, "tolerance": 0.0,
                                    "null_tokens": NULL_TOKENS_DEFAULT, "nokey_mode": "hash"}
    assert su.settings_of({"trim": False, "display_rows": 500})["display_rows"] == 500
    opts = su.read_options({"null_tokens": "-, n/a", "empty_as_null": False, "trim": False})
    assert opts.tokens == ("-", "n/a") and opts.trim is False
    assert "" in su.read_options({}).tokens


def test_a_filter_that_cannot_be_read_is_said(pair):
    _, _, _, cmap = pair
    import pandas as pd
    rows = pd.DataFrame([{"Apply to": "Both", "Column": "salary", "Operator": "between", "Value": "1", "Type": "number"}])
    assert su.filter_error(rows, "HR", "PR", su.setup_of(cmap).specs).startswith("'between' on salary needs two values")
    assert su.filter_error(pd.DataFrame([ld.BLANK_FILTER]), "HR", "PR", su.setup_of(cmap).specs) == ""
