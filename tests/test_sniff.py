# tests/test_sniff.py
"""The looks-like cells: what a sample of a text column's values suggests - shown per side,
never applied. A column DuckDB already typed gets no suggestion."""
import csv
import json
from pathlib import Path

from tablecmp.columns import apply_mapping_json, build_table, fill_looks, mapping_json, normalise, untaken
from tablecmp.sniff import looks_like, text_like
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ReadOptions

EX = Path(__file__).resolve().parent.parent / "examples"


def _side(path: Path, kind: str = "csv") -> Side:
    s = Side(name=path.stem, label=path.name, csv_path=str(path), kind=kind)
    s.schema = source_schema(s.csv_path, kind, ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


def test_text_like_is_what_duckdb_did_not_type():
    assert text_like("VARCHAR") and text_like("JSON") and text_like("") and text_like("odd")
    assert not any(text_like(t) for t in ("DATE", "DOUBLE", "BOOLEAN", "BIGINT", "TIMESTAMP",
                                          "DECIMAL(10,2)", "BLOB"))


def test_directory_json():
    B = _side(EX / "directory_employees.json", "json")
    got = looks_like(B, B.columns)
    assert set(got) == set(B.columns)
    assert got["hire_date"].startswith("date · ") and got["hire_date"].endswith("%d-%b-%Y")
    assert B.schema["active"] == "BOOLEAN" and got["active"] == ""       # typed already
    assert B.schema["salary"] == "DOUBLE" and got["salary"] == ""
    assert got["name"] == "" and got["dept"] == "" and got["id"] == "" and got["manager_id"] == ""


def test_payroll_csv():
    B = _side(EX / "payroll_employees.csv")
    got = looks_like(B, B.columns)
    assert got["Salary"] == "number · 12,686.95 has thousands separators"   # the first value
    assert got["IsActive"] == "boolean · Y/N"
    # DuckDB's sniffer typed the d/m/Y column DATE, so the detected cell already says it
    assert B.schema["HireDate"] == "DATE" and got["HireDate"] == ""
    assert got["EmployeeId"] == "" and got["FullName"] == "" and got["CostCenter"] == ""


def test_hr_csv_is_all_typed_or_plain():
    A = _side(EX / "hr_employees.csv")
    assert set(looks_like(A, A.columns).values()) == {""}


def test_every_shape_on_a_text_file(tmp_path):
    """A null token DuckDB does not know keeps each column VARCHAR; the sniff skips the token
    and reads the rest: d/m/Y, a time of day, ISO with and without a preset, true/false,
    plain numbers, plain text, an empty column, and a column that is mostly numbers."""
    rows = [["dmy", "stamp", "iso", "isot", "flag", "num", "plain", "blank", "mixed"],
            ["04/03/2023", "27/08/2026 10:11", "2026-08-27", "2023-03-04T10:11:12Z", "true", "100", "abc", "", "1"],
            ["19/07/2026", "01/01/2020 23:59", "2020-01-01", "2020-01-01T00:00:00Z", "False", "2.5", "def", "", "x"],
            ["N/A", "NA", "NULL", "None", " ", "NA", "", "", "2"],
            ["05/01/2024", "05/01/2024 00:00", "2024-01-05", "2024-01-05T09:00:00Z", "TRUE", "-7", "ghi", "", "3"]]
    p = tmp_path / "shapes.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    S = _side(p)
    assert set(S.schema.values()) == {"VARCHAR"}
    got = looks_like(S, S.columns)
    assert got == {"dmy": "date · 04/03/2023 → %d/%m/%Y",
                   "stamp": "timestamp · 27/08/2026 10:11 → %d/%m/%Y %H:%M",
                   "iso": "date · 2026-08-27 → %Y-%m-%d",
                   "isot": "timestamp · 2023-03-04T10:11:12Z → ISO, no format needed",
                   "flag": "boolean · true/False",
                   "num": "number", "plain": "", "blank": "", "mixed": ""}
    # the null tokens come from the options: with none, N/A is a value and dmy is text
    assert looks_like(S, ["dmy"], opts=ReadOptions(tokens=("",)))["dmy"] == ""
    # a sample of one value still decides; asking for typed columns only gives blanks
    assert looks_like(S, ["num"], n=1)["num"] == "number"
    assert looks_like(S, []) == {}


def test_cells_ride_on_the_table_and_never_touch_the_type():
    A, B = _side(EX / "hr_employees.csv"), _side(EX / "payroll_employees.csv")
    looks = {"A": looks_like(A, A.columns), "B": looks_like(B, B.columns)}
    plain, cm = build_table(A, B), build_table(A, B, looks)
    assert list(cm["Type"]) == list(plain["Type"]) and set(plain["B looks like"]) == {""}
    by_b = cm.set_index("B column")
    assert by_b.at["Salary", "B looks like"].startswith("number · ")
    assert by_b.at["IsActive", "B looks like"] == "boolean · Y/N"
    assert by_b.at["IsActive", "Type"] == "text" and set(cm["A looks like"]) == {""}
    assert "looks like" not in mapping_json(cm)
    # the cells survive the editor round trip, a mapping file and a fill of Auto's table
    assert list(normalise(cm.copy(), cm, A, B, looks)["B looks like"]) == list(cm["B looks like"])
    again = apply_mapping_json(mapping_json(cm), A, B, looks)
    assert again.set_index("B column").at["Salary", "B looks like"] == by_b.at["Salary", "B looks like"]
    filled = fill_looks(plain, looks)
    assert list(filled["B looks like"]) == list(cm["B looks like"]) and list(filled["Type"]) == list(cm["Type"])


def test_untaken_lists_a_suggestion_the_type_does_not_follow():
    A, B = _side(EX / "hr_employees.csv"), _side(EX / "payroll_employees.csv")
    looks = {"A": looks_like(A, A.columns), "B": looks_like(B, B.columns)}
    cm = build_table(A, B, looks)
    # active/IsActive is read as text, Salary already as number: only the first is listed
    assert untaken(cm, "HR", "Payroll") == [("active", "Payroll looks like boolean (Y/N) - read as text")]
    taken = json.loads(mapping_json(cm))
    for c in taken["columns"]:
        if c["name"] == "active":
            c["b_steps"] = [{"op": "to boolean", "params": {}}]
    assert untaken(apply_mapping_json(json.dumps(taken), A, B, looks), "HR", "Payroll") == []
    for c in taken["columns"]:
        if c["name"] == "active":
            c["b_steps"], c["type"] = [], "boolean"
    assert untaken(apply_mapping_json(json.dumps(taken), A, B, looks), "HR", "Payroll") == []


def test_app_shows_the_cells_and_leaves_the_type_alone(monkeypatch, tmp_path):
    """Both files loaded: the table has the two columns filled from a sample, the Type is what
    the detected types give, the caption explains the cells and the setup card lists the one
    suggestion not taken."""
    from tests.test_apptest import _boot, _load_path, _ok
    at = _boot(monkeypatch, tmp_path)
    _load_path(at, "A", EX / "hr_employees.csv")
    at = _load_path(at, "B", EX / "payroll_employees.csv")
    A, B = at.session_state["A"], at.session_state["B"]
    looks = at.session_state["looks_like"]
    assert looks["B"]["IsActive"] == "boolean · Y/N" and looks["A"] == {c: "" for c in A.columns}
    cm = at.session_state["cmap"]
    by_b = cm.set_index("B column")
    assert by_b.at["Salary", "B looks like"] == "number · 12,686.95 has thousands separators"
    assert by_b.at["IsActive", "B looks like"] == "boolean · Y/N"
    assert list(cm["Type"]) == list(build_table(A, B)["Type"])
    assert by_b.at["IsActive", "Type"] == "text" and by_b.at["Salary", "Type"] == "number"
    assert any("looks like" in c.value and "the Type stays what you set" in c.value for c in at.caption)
    page = "\n".join(m.value for m in at.markdown)
    assert "Right looks like boolean (Y/N) - read as text" in page
    assert "looks like number" not in page                  # Salary is read as number already
    # the sample is taken once per pair of files: a rerun keeps the same dict
    at = _ok(at.run())
    assert at.session_state["looks_like"] is looks
    assert at.session_state["cmap"].set_index("B column").at["IsActive", "Type"] == "text"
