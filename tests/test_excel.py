"""Excel files as a source: the range box, cells as text, the header, where the table ends, the
sheets - and over HTTP, an upload, the sheet list, a Load with a range, a compare against a
CSV and the run config run again. A CSV's lines above the header (skip_rows) too."""
import csv
import json
from datetime import date, datetime, time, timedelta

import pytest

from tablecmp import excel
from tablecmp.loading import ReadAsked, build_side, loaded_notes
from tablecmp.sources import Side, file_stamp, kind_of, preview_rows, row_count, select_sql, source_schema
from tests.conftest import EX, W, isolated_env
from tests.webflow import auto, boot, expected_counts, load_path, run, settle, wait

openpyxl = pytest.importorskip("openpyxl")
HR, PAY = EX / "hr_employees.csv", EX / "payroll_employees.csv"


@pytest.fixture(autouse=True)
def _work(monkeypatch, tmp_path):
    isolated_env(monkeypatch, tmp_path)


def book(path, sheets: dict[str, list[list]], cells: dict[str, dict[str, object]] | None = None):
    """An .xlsx with these rows on these sheets (rows from A1), and single cells set after."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        for ref, v in (cells or {}).get(name, {}).items():
            ws[ref] = v
    wb.save(path)
    return path


def read(path, **kw) -> tuple[dict, list[tuple]]:
    """(schema, rows) of a sheet as the app reads it."""
    opts = {"sheet": kw.pop("sheet", ""), "cell_range": kw.pop("cell_range", ""),
            "stop_at_blank": kw.pop("stop_at_blank", False)}
    header = kw.pop("header", True)
    schema = source_schema(str(path), "excel", ",", header, file_stamp(str(path)), **opts)
    s = Side(csv_path=str(path), kind="excel", header=header, schema=schema, **opts)
    from tablecmp.sql import scratch
    rows = scratch(ordered=True).execute(select_sql(s)).fetchall()
    return schema, rows


# ---- the range box ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, want", [
    ("", (1, 1, None, None)), ("A1", (1, 1, None, None)), ("b4", (4, 2, None, None)),
    ("B4:H500", (4, 2, 500, 8)), ("$B$4:$H$500", (4, 2, 500, 8)), ("B4:H", (4, 2, None, 8)),
    (" AA10 ", (10, 27, None, None)),
])
def test_parse_range(text, want):
    assert excel.parse_range(text) == want


@pytest.mark.parametrize("text", ["4B", "B0", "B4:A10", "B10:C4", "B4-H5", "Sheet1!B4", "XFE1", "A1:B2:C3"])
def test_parse_range_says_why_not(text):
    with pytest.raises(ValueError) as e:
        excel.parse_range(text)
    assert str(e.value).endswith(".")


# ---- cells as text ---------------------------------------------------------------------------
@pytest.mark.parametrize("v, want", [
    (None, None), ("", None), ("x", "x"), ("#N/A", "#N/A"), (True, "true"), (False, "false"),
    (123, "123"), (123.0, "123"), (12686.95, "12686.95"), (0.1 + 0.2, "0.3"), (-2.5, "-2.5"),
    (0.00001234, "0.00001234"), (1e22, "1e+22"),
    (datetime(2023, 3, 4), "2023-03-04"), (datetime(2023, 3, 4, 10, 5, 7), "2023-03-04 10:05:07"),
    (date(2020, 1, 2), "2020-01-02"), (time(9, 30), "09:30:00"),
    (datetime(2020, 1, 2, 3, 4, 5, 123000), "2020-01-02 03:04:05.123"),
    (datetime(2020, 1, 2, 3, 4, 5, 500000), "2020-01-02 03:04:05.5"), (time(9, 30, 0, 250000), "09:30:00.25"),
    (timedelta(hours=30), "30:00:00"), (timedelta(minutes=90, seconds=5), "1:30:05"),
    (timedelta(hours=-2), "-2:00:00"),
])
def test_cell_text(v, want):
    assert excel.cell_text(v) == want


def test_header_names():
    assert excel.header_names(["id", None, " name ", "id", "ID", ""], 7) == \
        ["id", "column1", "name", "id_2", "ID_3", "column5", "column6"]


# ---- a sheet read --------------------------------------------------------------------------
def test_kinds_of_cells_read_as_text(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [
        ["id", "amount", "flag", "when", "at"],
        [1, 10.5, True, datetime(2024, 1, 31), datetime(2024, 1, 31, 8, 0, 1)],
        [2, 3.0, False, datetime(2024, 2, 1), None],
    ]})
    assert kind_of(str(p)) == "excel"
    schema, rows = read(p)
    assert list(schema) == ["id", "amount", "flag", "when", "at"]
    assert set(schema.values()) == {"VARCHAR"}
    assert rows == [("1", "10.5", "true", "2024-01-31", "2024-01-31 08:00:01"),
                    ("2", "3", "false", "2024-02-01", None)]


def test_a_title_block_above_and_notes_below(tmp_path):
    rows = [["Quarterly sales"], ["made 2024-04-01"], [],
            [None, "region", "units", "price"],
            [None, "North", 10, 2.5],
            [None, "South", 7, 3],
            [],
            [None, "Total", 17, None],
            [None, "note: numbers are provisional"]]
    p = book(tmp_path / "t.xlsx", {"Sales": rows})
    schema, got = read(p, cell_range="B4", stop_at_blank=True)
    assert list(schema) == ["region", "units", "price"]
    assert got == [("North", "10", "2.5"), ("South", "7", "3")]
    # without the stop the empty row is skipped and the totals come along
    _, got = read(p, cell_range="B4")
    assert ("Total", "17", None) in got and len(got) == 4
    # a closed range: only those cells
    schema, got = read(p, cell_range="B4:C5")
    assert list(schema) == ["region", "units"] and got == [("North", "10")]
    # rows open-ended, columns fixed
    schema, got = read(p, cell_range="B4:C", stop_at_blank=True)
    assert list(schema) == ["region", "units"] and len(got) == 2


def test_blank_and_repeated_header_names(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [["id", None, "name", "name", None], [1, 2, "a", "b", None], [2, 3, "c", "d", "x"]]})
    schema, rows = read(p)
    assert list(schema) == ["id", "column1", "name", "name_2", "column4"]
    assert rows[1] == ("2", "3", "c", "d", "x")
    side = Side(name="t", kind="excel", header=True, schema=schema, rows=2)
    notes = loaded_notes(side)
    assert any("unnamed" in t for _, t in notes)          # the short header said, as for a CSV


def test_trailing_empty_columns_drop_and_wide_rows_widen(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [["a", "b"], [1, 2]]}, cells={"S": {"E1": None, "D3": "late"}})
    schema, rows = read(p)
    assert list(schema) == ["a", "b", "column2", "column3"]       # the widest row sets the width
    assert rows == [("1", "2", None, None), (None, None, None, "late")]


def test_no_header(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [[1, "x"], [2, "y"]]})
    schema, rows = read(p, header=False)
    assert list(schema) == ["column0", "column1"] and rows == [("1", "x"), ("2", "y")]


def test_sheets_first_named_unknown_and_empty(tmp_path):
    p = book(tmp_path / "t.xlsx", {"First": [["a"], [1]], "Second": [["b"], [2], [3]], "Empty": []})
    assert excel.sheet_names(str(p)) == ["First", "Second", "Empty"]
    assert excel.resolve_sheet(str(p), "") == "First"
    assert excel.resolve_sheet(str(p), "second") == "Second"     # case is forgiven
    assert read(p)[1] == [("1",)]
    assert read(p, sheet="Second")[1] == [("2",), ("3",)]
    with pytest.raises(ValueError, match="No sheet called Nope - the file has: First, Second, Empty"):
        read(p, sheet="Nope")
    with pytest.raises(ValueError, match="no cells with values"):
        read(p, sheet="Empty")
    with pytest.raises(ValueError, match="no cells with values in that range"):
        read(p, cell_range="D10")


def test_a_header_and_no_rows(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [["a", "b"]]})
    schema, rows = read(p)
    assert list(schema) == ["a", "b"] and rows == []


def test_the_parquet_is_made_once_and_remade_when_the_file_changes(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [["a"], [1]]})
    first = excel.to_parquet(str(p), "", "", True, False)
    assert excel.to_parquet(str(p), "", "", True, False) == first
    assert excel.to_parquet(str(p), "", "A1", False, False) != first      # other options, another file
    assert excel.to_parquet(str(p), "", "$A$1", True, False) == first      # the same read written otherwise
    book(p, {"S": [["a"], [1], [2]]})
    import os
    os.utime(p, ns=(os.stat(p).st_atime_ns, os.stat(p).st_mtime_ns + 10_000_000))
    again = excel.to_parquet(str(p), "", "", True, False)
    assert again != first and read(p)[1] == [("1",), ("2",)]
    from pathlib import Path
    assert not Path(first).exists() and Path(again).exists()             # the older copy's conversions go


def test_xls_without_xlrd_says_so(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_xlrd(name, *a, **k):
        if name == "xlrd":
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_xlrd)
    p = tmp_path / "old.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0 not really")
    assert kind_of(str(p)) == "excel"
    with pytest.raises(ValueError, match="Save .xls files as .xlsx"):
        excel.sheet_names(str(p))


def test_not_a_workbook(tmp_path):
    p = tmp_path / "bad.xlsx"
    p.write_text("not a zip", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not open the Excel file"):
        excel.sheet_names(str(p))


def test_build_side_snapshots_the_sheet_like_a_csv(tmp_path):
    p = book(tmp_path / "t.xlsx", {"Notes": [["x"]], "Data": [["id", "v"], [1, "a"], [2, "b"], [], ["total", None]]})
    schema = source_schema(str(p), "excel", ",", True, file_stamp(str(p)), sheet="Data", stop_at_blank=True)
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="excel", sheet="Data",
                                  stop_at_blank=True), schema)
    assert s.rows == 2 and s.cache_path                           # its own copy - the workbook may be saved again
    loose = build_side("B", ReadAsked(name="X", label=p.name, path=str(p), kind="excel", sheet="Data",
                                      stop_at_blank=True, snapshot=False), schema)
    assert loose.rows == 2 and loose.cache_path == ""
    assert s.read_from == "sheet Data · stops at the first blank row"
    assert list(preview_rows(s)["id"]) == ["1", "2"]
    cut = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="excel", sheet="Data",
                                    stop_at_blank=True, where="id = '2'"), schema)
    assert cut.rows == 1 and cut.cache_path
    assert row_count(cut) == 1


# ---- a CSV's lines above the header ------------------------------------------------------------
def test_csv_skip_rows(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Report of the day\nmade by: me\nid,v\n1,a\n2,b\n", encoding="utf-8")
    schema = source_schema(str(p), "csv", ",", True, file_stamp(str(p)), skip_rows=2)
    assert list(schema) == ["id", "v"]
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="csv", skip_rows=2, snapshot=False), schema)
    assert s.rows == 2 and s.read_from == "skips 2 lines"
    # the option means nothing to another kind - it never splits a cache or a key
    assert Side(kind="parquet", skip_rows=3).read_opts == {}
    assert Side(kind="csv", sheet="S").read_opts == {"skip_rows": 0, "quote": '"', "bad_rows": "keep"}


# ---- over HTTP ---------------------------------------------------------------------------------
def hr_book(path):
    """HR's rows as a workbook a person would keep: a title above the table at B4, a cover sheet
    first, numbers as numbers, dates as dates, and a total under a blank row."""
    with open(HR, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    head, body = rows[0], rows[1:]
    out = [["HR export"], ["as of 2024-06-30"], [], [None, *head]]
    for r in body:
        rec = dict(zip(head, r))
        rec["salary"] = float(rec["salary"]) if rec["salary"] else None
        rec["hire_date"] = datetime.strptime(rec["hire_date"], "%Y-%m-%d") if rec["hire_date"] else None
        out.append([None, *[rec[h] for h in head]])
    out += [[], [None, "Total", None, None, None, 1.0]]
    return book(path, {"Cover": [["read me"]], "Employees": out})


def test_upload_an_excel_file_and_compare_it_with_a_csv(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    xl = hr_book(tmp_path / "hr.xlsx")
    r = f.c.post("/api/sources/A/upload", params={"filename": "hr.xlsx"}, content=xl.read_bytes(), headers=W)
    assert r.status_code == 200, r.text
    assert r.json()["staged"] == "hr.xlsx"
    assert "xlsx" in f.get("/api/sources").json()["upload_types"]
    pick = {"how": "upload"}
    got = f.send("POST", "/api/sources/A/schema", pick).json()
    assert got["kind"] == "excel" and got["sheets"] == ["Cover", "Employees"] and got["sheet"] == "Cover"
    got = f.send("POST", "/api/sources/A/schema", {**pick, "sheet": "Nope"}).json()
    assert got["error"].startswith("No sheet called Nope") and got["columns"] == []
    got = f.send("POST", "/api/sources/A/schema", {**pick, "sheet": "Employees", "cell_range": "B4:Z"}).json()
    assert got["error"] == "" and got["sheet"] == "Employees"
    assert [c["name"] for c in got["columns"]][:2] == ["emp_id", "first_name"]
    bad = f.send("POST", "/api/sources/A/load", {**pick, "sheet": "Employees", "cell_range": "4B", "name": "Left"})
    assert bad.status_code == 400 and "not a cell or a range" in bad.json()["detail"]
    r = f.send("POST", "/api/sources/A/load", {**pick, "name": "Left", "sheet": "Employees",
                                                "cell_range": "B4", "stop_at_blank": True})
    assert r.status_code == 200, r.text
    view = r.json()["side"]
    assert view["kind"] == "excel" and view["rows"] == 3000 and view["sheet"] == "Employees"
    assert view["cell_range"] == "B4" and view["stop_at_blank"] is True
    assert view["read_from"] == "sheet Employees · B4 · stops at the first blank row"
    assert "sheet Employees" in view["caption"] and not view["notes"]
    load_path(f, "B", PAY)
    assert auto(f)["counts"] == expected_counts()


def test_two_excel_files_through_a_saved_config(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    xl = hr_book(tmp_path / "hr.xlsx")
    pay = tmp_path / "pay.xlsx"
    with open(PAY, newline="", encoding="utf-8") as fh:
        book(pay, {"Payroll": list(csv.reader(fh))})
    load_path(f, "A", xl, name="HR", sheet="Employees", cell_range="B4", stop_at_blank=True)
    load_path(f, "B", pay, name="Payroll")
    first = auto(f)
    assert first["counts"] == expected_counts()
    conf_path = first["folder"] / "HR_compare_Payroll__config.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    a, b = conf["sides"]["A"], conf["sides"]["B"]
    assert (a["kind"], a["sheet"], a["cell_range"], a["stop_at_blank"]) == ("excel", "Employees", "B4", True)
    assert b["kind"] == "excel" and "cell_range" not in b and "skip_rows" not in b      # defaults stay out
    assert b["sheet"] == "Payroll"                 # the sheet read, by name, though none was picked
    assert a["snapshot"] is True and b["snapshot"] is True
    fresh = boot(monkeypatch, tmp_path)
    r = fresh.call("config", {"path": str(conf_path)})
    assert r.status_code == 200, r.text
    assert wait(fresh, r.json())["state"] == "done"
    settle(fresh)
    boxes = fresh.get("/api/sources").json()["config"]["boxes"]
    assert (boxes["A"]["sheet"], boxes["A"]["cell_range"], boxes["A"]["stop_at_blank"]) == ("Employees", "B4", True)
    assert boxes["B"]["sheet"] == "Payroll" and boxes["B"]["skip_rows"] == 0
    assert run(fresh)["counts"] == first["counts"]


def test_csv_skip_rows_over_http_and_in_the_config(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    titled = tmp_path / "hr_titled.csv"
    titled.write_text("HR export\nas of 2024-06-30\n" + HR.read_text(encoding="utf-8"), encoding="utf-8")
    got = f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(titled), "skip_rows": 2}).json()
    assert got["columns"][0]["name"] == "emp_id" and got["sheets"] == []
    load_path(f, "A", titled, name="HR", skip_rows=2)
    load_path(f, "B", PAY, name="Payroll")
    first = auto(f)
    assert first["counts"] == expected_counts()
    conf = json.loads((first["folder"] / "HR_compare_Payroll__config.json").read_text(encoding="utf-8"))
    assert conf["sides"]["A"]["skip_rows"] == 2 and "sheet" not in conf["sides"]["A"]


def test_an_old_config_without_the_options_still_runs(tmp_path):
    from tablecmp.runconfig import open_side
    s = open_side({"name": "HR", "kind": "csv", "path": str(HR), "delimiter": ",", "header": True}, "A")
    assert s.rows == 3000 and s.read_opts == {"skip_rows": 0, "quote": '"', "bad_rows": "keep"}


def test_profiling_an_excel_table(monkeypatch, tmp_path):
    from tests.webflow import profile
    f = boot(monkeypatch, tmp_path)
    xl = hr_book(tmp_path / "hr.xlsx")
    load_path(f, "P", xl, sheet="Employees", cell_range="B4", stop_at_blank=True)
    prof = profile(f)
    assert prof is not None


# ---- review follow-ups -------------------------------------------------------------------------
def test_a_workbook_saved_again_after_load_does_not_change_the_side(monkeypatch, tmp_path):
    from tests.webflow import compare
    f = boot(monkeypatch, tmp_path)
    xl = tmp_path / "hr.xlsx"
    with open(HR, newline="", encoding="utf-8") as fh:
        hr = list(csv.reader(fh))
    book(xl, {"HR": hr})
    view = load_path(f, "A", xl, name="Left")["side"]
    assert view["snapshot"] is True and view["rows"] == 3000
    load_path(f, "B", PAY)
    first = auto(f)
    assert first["counts"] == expected_counts()
    book(xl, {"HR": hr[:-500]})                    # 500 rows fewer, saved over the file
    import os
    os.utime(xl, ns=(os.stat(xl).st_atime_ns, os.stat(xl).st_mtime_ns + 10_000_000))
    assert compare(f)["counts"] == first["counts"]                 # the side holds what Load read


def test_an_empty_header_row_in_a_range_stays_the_header(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [[None, None], ["Alice", "NY"], ["Bob", "LA"]]})
    schema, rows = read(p, cell_range="A1:B3")
    assert list(schema) == ["column0", "column1"] and rows == [("Alice", "NY"), ("Bob", "LA")]
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="excel", cell_range="A1:B3"), schema)
    assert s.rows == 2 and any("unnamed" in t for _, t in loaded_notes(s))
    # with no range the empty rows above the table are skipped, as before
    schema, rows = read(p)
    assert list(schema) == ["Alice", "NY"] and rows == [("Bob", "LA")]


def test_formulas_with_no_saved_value_are_said(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [["a", "b", "sum"], [1, 2, "=A2+B2"], [3, 4, "=A3+B3"]]})
    schema, rows = read(p)
    assert rows == [("1", "2", None), ("3", "4", None)]
    assert excel.unsaved_formulas(str(p)) == (2, False)
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="excel"), schema)
    said = [t for _, t in loaded_notes(s)]
    assert any("**2** formula cells have no saved value" in t for t in said), said
    plain = book(tmp_path / "plain.xlsx", {"S": [["a"], [1]]})
    assert excel.unsaved_formulas(str(plain)) == (0, False)


def test_the_first_visible_sheet_is_the_default(monkeypatch, tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Lookup"
    wb.active.append(["junk"])
    wb.active.sheet_state = "hidden"
    data = wb.create_sheet("Data")
    data.append(["id"])
    data.append([1])
    wb.active = 1
    p = tmp_path / "h.xlsx"
    wb.save(p)
    assert excel.resolve_sheet(str(p), "") == "Data" and excel.hidden_sheets(str(p)) == ["Lookup"]
    f = boot(monkeypatch, tmp_path)
    got = f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(p)}).json()
    assert got["sheets"] == ["Lookup", "Data"] and got["hidden"] == ["Lookup"] and got["sheet"] == "Data"
    assert [c["name"] for c in got["columns"]] == ["id"]


def test_schema_peeks_without_converting_the_sheet(monkeypatch, tmp_path):
    from tablecmp.sources import work_dir
    f = boot(monkeypatch, tmp_path)
    p = book(tmp_path / "t.xlsx", {"S": [["id", "v"], [1, "a"], [2, "b"]]})
    for rng in ("", "A1", "A1:B", "A1:B3"):
        got = f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(p), "cell_range": rng}).json()
        assert got["error"] == "" and [c["name"] for c in got["columns"]] == ["id", "v"]
    assert not list(work_dir().glob("cmp_xl_*"))
    assert excel.peek_columns(str(p), header=False) == ["column0", "column1"]


def test_excel_lock_files_are_not_offered(monkeypatch, tmp_path):
    from tablecmp.sources import folder_files
    d = tmp_path / "d"
    d.mkdir()
    book(d / "big.xlsx", {"S": [["a"], [1]]})
    (d / "~$big.xlsx").write_bytes(b"\x00" * 165)
    (d / ".hidden.csv").write_text("a\n1\n", encoding="utf-8")
    assert folder_files(str(d)) == ["big.xlsx"]
    f = boot(monkeypatch, tmp_path)
    got = f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(d / "~$big.xlsx")}).json()
    assert "lock file" in got["error"]


def test_the_headerless_note_names_the_box_on_the_page(tmp_path):
    p = book(tmp_path / "t.xlsx", {"S": [[1, 2], [3, 4], [5, 6]]})
    schema, _ = read(p)
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="excel"), schema)
    assert any("**Table starts at**" in t for _, t in loaded_notes(s))


def test_the_report_names_the_sheet(tmp_path):
    from tablecmp.report import _source_row
    s = Side(name="Feb", label="book.xlsx", csv_path="book.xlsx", kind="excel", sheet="Feb", cell_range="B4")
    assert "book.xlsx · sheet Feb · B4" in _source_row("Feb", s, 10, "book.xlsx")


def test_a_rerun_on_another_workbook_takes_its_sheet_and_range(tmp_path):
    from tablecmp.runconfig import with_file
    block = {"name": "HR", "kind": "excel", "path": "a.xlsx", "sheet": "Staff", "cell_range": "A4", "header": True}
    assert with_file(block, "b.xlsx")["sheet"] == "Staff"                    # monthly files keep their sheet
    got = with_file(block, "b.xlsx", read={"sheet": "Sheet1", "cell_range": "B2"})
    assert (got["sheet"], got["cell_range"]) == ("Sheet1", "B2")
    assert "sheet" not in with_file(block, "b.csv") and "cell_range" not in with_file(block, "b.csv")


def test_cli_sheet_and_range_options(monkeypatch, tmp_path):
    from tablecmp import run as cli
    seen = []
    monkeypatch.setattr(cli, "read_config", lambda _t: {"sides": {"A": {"path": "a.xlsx"}, "B": {"path": "b.csv"}}})
    monkeypatch.setattr(cli, "load_all", lambda: {})
    monkeypatch.setattr(cli, "passwords_for", lambda *_a: {})
    monkeypatch.setattr(cli, "run_pair", lambda *a, **k: seen.append(a) or __import__(
        "tablecmp.runconfig", fromlist=["PairOutcome"]).PairOutcome("x", "Identical", counts={
            "matched": 0, "differ": 0, "cells": 0, "only_left": 0, "only_right": 0}))
    conf = tmp_path / "c.json"
    conf.write_text("{}", encoding="utf-8")
    assert cli.main([str(conf), "--left", "o.xlsx", "--sheet-left", "Sheet1", "--range-left", "B4", "-q"]) == 0
    assert seen[0][-1] == ({"sheet": "Sheet1", "cell_range": "B4"}, {"sheet": None, "cell_range": None})
