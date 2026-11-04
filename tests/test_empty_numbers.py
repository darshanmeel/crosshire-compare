# tests/test_empty_numbers.py
"""A number column whose blanks are written as Excel's accounting dash, a dot, a space or a
non-breaking space on one side and left empty on the other: x in a custom expression is the
value as its Read as type, the 'if empty, use' step, a custom expression checked when it is set,
plain errors at Compare and preview, the Null = null switch and a name typed after Load."""
import json

import csvdiff
import duckdb
import pytest

from tablecmp.runconfig import read_config, run_pair
from tablecmp.values import compile_steps, expr_problem, step_sql, substitute_x
from tests.webkit import W, c, compare, seed_table, state, ws_of  # noqa: F401

NBSP = " "
LEFT = ["id,amount,note", '1,"  -     ",', '2,".",', '3," ",', f'4,"{NBSP}",', '5,"1,234.50",', "6,10,x"]
RIGHT = ["id,amount,note", "1,,", "2,,", "3,,", "4,,", "5,1234.5,", "6,10,x"]
COLS = [{"a": "id", "b": "id", "name": "id", "type": "text", "key": True, "compare": False},
        {"a": "amount", "b": "amount", "name": "amount", "type": "number", "key": False, "compare": True},
        {"a": "note", "b": "note", "name": "note", "type": "text", "key": False, "compare": True}]
COALESCE = {"op": "custom expression", "params": {"expr": "case when x is null then 0.0 else x end"}}
IF_EMPTY = {"op": "if empty, use", "params": {"v": "0"}}


def run_sql(expr, values):
    con = duckdb.connect()
    return [r[0] for r in con.execute(f"SELECT {substitute_x(expr, 'v')} FROM unnest(?) t(v)", [values]).fetchall()]


@pytest.fixture
def files(tmp_path):
    a, b = tmp_path / "left.csv", tmp_path / "right.csv"
    a.write_text("\n".join(LEFT) + "\n", encoding="utf-8")
    b.write_text("\n".join(RIGHT) + "\n", encoding="utf-8")
    return a, b


def load(c, files, names=("Left", "Right")):
    for tag, path, name in zip("AB", files, names):
        r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
        assert r.status_code == 200, r.text
    seed_table(c, COLS)


def add(c, which, step, canon="amount"):
    return c.post("/api/setup/steps", json={"canon": canon, "which": which, "action": "add", "step": step},
                  headers=W)


# ---- the engine ---------------------------------------------------------------------
def test_x_is_the_value_as_its_type_in_a_custom_expression():
    expr = compile_steps([COALESCE], "number")
    got = run_sql(expr, ["  -     ", ".", " ", NBSP, "1,234.50", "10", None])
    assert got == ["0.0", "0.0", "0.0", "0.0", "1234.5", "10.0", "0.0"]
    assert run_sql(compile_steps([{"op": "custom expression", "params": {"expr": "coalesce(x, 0)"}}], "number"),
                   [" - ", "7"]) == ["0.0", "7.0"]
    date = compile_steps([{"op": "custom expression", "params": {"expr": "x + 1"}}], "date")
    assert run_sql(date, ["2026-08-27", "not a date"]) == ["2026-08-28", None]
    # steps before it still run on text, and a text pair's x is the text as it always was
    assert run_sql(compile_steps([{"op": "replace text", "params": {"a": "k", "b": "000"}}, COALESCE], "number"),
                   ["5k"]) == ["5000.0"]
    assert step_sql({"op": "custom expression", "params": {"expr": "upper(x)"}}) == "upper(x)"


def test_if_empty_use_fills_null_and_blank_text():
    expr = step_sql(IF_EMPTY)
    assert run_sql(expr, [None, "", "   ", NBSP, "\t", " - ", "5"]) == ["0", "0", "0", "0", "0", " - ", "5"]


def test_a_custom_expression_is_checked_in_plain_words():
    assert expr_problem("case when x is null then 0.0 else x end", "number") == ""
    assert expr_problem("coalesce(x, 0)", "number") == ""
    assert expr_problem("upper(trim(x)", "text") == "The brackets don't match - 2 opened, 1 closed."
    assert expr_problem("coaelesce(try_cast(replace(trim(x)), ',', '') as double, 0.0)", "number") == \
        "Not a valid expression near ','."
    assert expr_problem("coaelesce(x, 0)", "number").startswith("There is no function called coaelesce - did you mean")
    assert expr_problem("case when x is null then 0.0 else x end", "text").startswith("x is text (VARCHAR) here - ")
    assert expr_problem("upper(x)", "number") == ""                 # written for text: read on text
    assert expr_problem("x; select 1") == "A custom expression is one expression - take out the ';'."
    assert expr_problem("x || ';'") == ""                          # a ';' in quotes is text


def test_nulls_differ_on_values_only_from_the_command_line(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("id,v,w\n1,,x\n,1,y\n", encoding="utf-8")
    b.write_text("id,v,w\n1,,x\n,1,y\n", encoding="utf-8")
    assert csvdiff.main(["file", str(a), str(b), "--keys", "id", "--out", str(tmp_path / "same"), "--no-html"]) == 0
    code = csvdiff.main(["file", str(a), str(b), "--keys", "id", "--out", str(tmp_path / "diff"), "--no-html",
                         "--nulls-differ"])
    assert code == 1
    got = json.loads(next((tmp_path / "diff").rglob("*summary.json")).read_text(encoding="utf-8"))[0]
    # v null on both sides now differs; the row with a null key still matched
    assert (got["matched_rows"], got["only_left"], got["only_right"]) == (2, 0, 0)
    assert got["diffs_by_column"] == {"v": 1}


# ---- over HTTP ----------------------------------------------------------------------
def test_dashes_and_blanks_compare_equal_once_read_as_number(c, files):
    load(c, files)
    r = add(c, "A", {"op": "custom expression", "params": {"expr": "case when x is null then 0.0 else x end"}})
    assert r.status_code == 200, r.text
    assert add(c, "B", IF_EMPTY).status_code == 200
    t = c.get("/api/setup/try", params={"canon": "amount", "which": "A"}).json()
    assert t["error"] == "" and [row[2] for row in t["rows"]] == ["0", "0", "0", "0", "1234.5"]
    rep = c.post("/api/setup/check", json={"canon": "amount"}, headers=W).json()
    failed = rep["columns"].index("Failed")
    assert {row[1] for row in rep["rows"]} == {"Left", "Right"} and [row[failed] for row in rep["rows"]] == [0, 0]
    done = compare(c)
    assert done["state"] == "done", done
    res = ws_of(c).data["result"]["result"]
    assert (res.matched_rows, res.diff_rows, res.only_left, res.only_right) == (6, 0, 0, 0)
    # Null = null off: the five notes null on both sides now differ, the key still matches
    s = c.put("/api/setup/settings", json={"nulls_equal": False}, headers=W).json()
    assert s["nulls_equal"] is False
    assert compare(c)["state"] == "done"
    run = ws_of(c).data["result"]
    assert (run["result"].matched_rows, run["result"].diff_rows) == (6, 5)
    summary = json.loads(next(p for n, p in run["files"].items() if n.endswith("summary.json")).read_text("utf-8"))
    assert summary["settings"]["nulls_equal"] is False
    report = next(p for n, p in run["files"].items() if n.endswith("__report.html")).read_text("utf-8")
    assert "null vs null differs" in report
    conf = json.loads(next(p for n, p in run["files"].items() if n.endswith("__config.json")).read_text("utf-8"))
    assert conf["settings"]["nulls_equal"] is False


def test_a_bad_expression_is_refused_when_it_is_set(c, files):
    load(c, files)
    r = add(c, "A", {"op": "custom expression", "params": {"expr": "coaelesce(try_cast(replace(trim(x)), ',', '') as double, 0.0)"}})
    assert r.status_code == 400 and r.json()["detail"] == "Not a valid expression near ','."
    r = add(c, "A", {"op": "custom expression", "params": {"expr": "replace(x, '-', '')"}})
    assert r.status_code == 200                                     # a text function: x stays text there
    r = add(c, "A", {"op": "custom expression", "params": {"expr": "x); select (1"}})
    assert r.json()["detail"] == "A custom expression is one expression - take out the ';'."
    r = add(c, "A", {"op": "custom expression", "params": {"expr": "x) FROM (SELECT 1 AS x) UNION SELECT (x"}})
    assert r.status_code == 400 and r.json()["detail"].startswith("Not a valid expression near")
    assert add(c, "A", {"op": "if empty, use", "params": {"v": ""}}).json()["detail"] == \
        "Type the value first - one space counts."


def test_a_cast_that_fails_is_said_in_plain_words(c, files):
    load(c, files)
    cast = {"op": "custom expression", "params": {"expr": "cast(x as decimal(18,3))"}}
    seed_table(c, [COLS[0], {**COLS[1], "type": "text", "a_steps": [cast], "b_steps": []}, COLS[2]])
    t = c.get("/api/setup/try", params={"canon": "amount", "which": "A"}).json()
    assert t["error"].startswith("amount on Left: 1 row holds '") and "which is not a number" in t["error"]
    assert "Use try_cast, or the 'if empty, use' step. (DuckDB says: Conversion Error" in t["error"]
    assert compare(c)["state"] == "error"
    said = ws_of(c).data["compare_said"][0][1]
    assert said.startswith("The comparison failed: amount on Left: 1 row holds '") and "LINE 1" not in said


def test_a_config_run_keeps_nulls_equal(c, files, tmp_path):
    load(c, files)
    add(c, "A", COALESCE)
    add(c, "B", IF_EMPTY)
    c.put("/api/setup/settings", json={"nulls_equal": False}, headers=W)
    assert compare(c)["state"] == "done"
    run = ws_of(c).data["result"]
    conf = read_config(next(p for n, p in run["files"].items() if n.endswith("__config.json")).read_text("utf-8"))
    out = run_pair(conf, out=str(tmp_path / "res"), say=lambda _m: None)
    assert out.error == "" and out.counts["differ"] == 5
    conf["settings"]["nulls_equal"] = True
    assert run_pair(conf, say=lambda _m: None).counts["differ"] == 0


# ---- the Name box after Load -------------------------------------------------------------
def test_a_name_typed_after_load_names_the_next_run(c, files):
    load(c, files)
    c.put("/api/setup/names", json={"A": "Ledger", "B": "Right"}, headers=W)    # the page sends the boxes as typed
    add(c, "A", COALESCE)
    add(c, "B", IF_EMPTY)
    assert compare(c)["state"] == "done"
    run = ws_of(c).data["result"]
    assert run["pair"] == "Ledger_compare_Right" and run["folder"].name.startswith("Ledger_compare_Right__")


def test_an_expression_written_for_text_x_still_reads_as_text():
    old = "coalesce(try_cast(replace(trim(x), ',', '') AS DOUBLE), 0.0)"     # set before x was typed
    assert expr_problem(old, "number") == ""
    assert compile_steps([{"op": "custom expression", "params": {"expr": old}}], "number") == old
    assert run_sql(old, [" -     ", "1,234.50"]) == [0.0, 1234.5]
    assert expr_problem("nosuch(x)", "number").startswith("There is no function called nosuch")


def test_an_expression_that_reads_on_text_keeps_text_x():
    for old in ("nullif(x, '-')", "coalesce(x, '0')", "x || 'a'", "strptime(x, '%d/%m/%Y')"):
        assert expr_problem(old, "number") == "" and compile_steps(
            [{"op": "custom expression", "params": {"expr": old}}], "number") == old, old
    assert run_sql("nullif(x, '-')", ["-", "12"]) == [None, "12"]
    assert expr_problem("case when x = '-' then 0.0 else x end", "number") == (
        "x is a number here, so '-' cannot be one - values that are not a number already read as null: "
        "test x is null instead.")
    assert expr_problem("coaelesce(x, 0)", "number") == "There is no function called coaelesce - did you mean coalesce?"


def test_null_differs_without_a_key_too(c, tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    for f in (a, b):
        f.write_text("k,v\n1,\n2,x\n", encoding="utf-8")
    load(c, (a, b))
    seed_table(c, [{"a": "k", "b": "k", "name": "k", "type": "text", "key": False, "compare": True},
                   {"a": "v", "b": "v", "name": "v", "type": "text", "key": False, "compare": True}])
    for nulls_equal, matched in ((True, 2), (False, 1)):
        c.put("/api/setup/settings", json={"nulls_equal": nulls_equal, "nokey_mode": "hash"}, headers=W)
        assert compare(c)["state"] == "done"
        res = ws_of(c).data["result"]["result"]
        assert (res.mode, res.matched_rows) == ("hash", matched), nulls_equal
