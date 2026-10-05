# tests/test_web_values.py
"""Values and Rows over HTTP: How values are read, Transform and convert with its preview and
check, and the Rows filters."""
import os
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tablecmp import connections as cx
from tablecmp.values import NULL_TOKENS_DEFAULT
from tablecmp.web.app import create_app
from tablecmp.web.workspace import COOKIE

W = {"X-Compare": "1"}
EX = Path(__file__).resolve().parent.parent / "examples"
HR, PR = EX / "hr_employees.csv", EX / "payroll_employees.csv"
COMMA = {"op": "remove thousands separators", "params": {}}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("COMPARE_CONNECTIONS", str(tmp_path / "connections.json"))
    monkeypatch.delenv(cx.FILES_ENV, raising=False)
    monkeypatch.delenv("COMPARE_DATA_DIR", raising=False)
    for k in [k for k in os.environ if k.startswith(cx.ENV_PREFIX)]:
        monkeypatch.delenv(k)
    client = TestClient(create_app())
    client.get("/api/workspace")
    for tag, path, name in (("A", HR, "HR"), ("B", PR, "PR")):
        r = client.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), "name": name}, headers=W)
        assert r.status_code == 200, r.text
    return client


def ws_of(c):
    return c.app.state.workspaces.get(c.cookies.get(COOKIE))


def steps(c, canon, which, action, step=None):
    return c.post("/api/setup/steps", json={"canon": canon, "which": which, "action": action, "step": step},
                  headers=W)


def spec(view, canon):
    return next(s for s in view["specs"] if s["canon"] == canon)


def test_the_switches_start_at_their_defaults_and_change_one_at_a_time(c):
    assert c.get("/api/setup/settings").json() == {"trim": True, "empty_as_null": True, "ignore_case": False,
                                                    "tolerance": 0.0, "null_tokens": NULL_TOKENS_DEFAULT,
                                                    "nokey_mode": "hash"}
    s = c.put("/api/setup/settings", json={"ignore_case": True, "tolerance": 0.5}, headers=W).json()
    assert s["ignore_case"] is True and s["tolerance"] == 0.5 and s["trim"] is True
    assert c.put("/api/setup/settings", json={"tolerance": -1}, headers=W).status_code == 422
    assert c.put("/api/setup/settings", json={"nokey_mode": "guess"}, headers=W).status_code == 422
    ws_of(c).data["settings"]["display_rows"] = 500                 # a config's display setting is kept
    assert c.put("/api/setup/settings", json={"trim": False}, headers=W).json()["display_rows"] == 500


def test_what_a_step_can_be(c):
    meta = c.get("/api/setup/steps").json()
    assert meta["steps"]["left N characters"] == ["n"] and meta["steps"]["to date"] == ["fmt"]
    assert meta["presets"]["27/08/2026"] == "%d/%m/%Y" and meta["numeric"] == ["m", "n"]
    fns = c.get("/api/setup/functions").json()
    assert fns["columns"] == ["signature", "template", "description", "example"]
    assert any(r[0].startswith("regexp_replace(") for r in fns["rows"])


def test_steps_are_added_previewed_copied_and_cleared(c):
    v = steps(c, "salary", "B", "add", COMMA).json()
    assert spec(v, "salary")["b_steps"] == [COMMA] and spec(v, "salary")["a_steps"] == []
    assert spec(v, "salary")["b_said"] == ["remove thousands separators"]
    t = c.get("/api/setup/try", params={"canon": "salary", "which": "B"}).json()
    assert t["error"] == "" and t["columns"] == ["In the file", "After the steps", "Compared as", "Converts"]
    assert t["rows"][0] == ["12,686.95", "12686.95", "12686.95", "yes"]
    v = steps(c, "salary", "B", "copy").json()
    assert spec(v, "salary")["a_steps"] == [COMMA]
    v = steps(c, "salary", "A", "clear").json()
    assert spec(v, "salary")["a_steps"] == [] and spec(v, "salary")["b_steps"] == [COMMA]
    v = steps(c, "salary", "B", "add", {"op": "to date", "params": {"fmt": ""}}).json()
    assert spec(v, "salary")["kind"] == "date"                       # a conversion step sets the Type
    assert spec(steps(c, "salary", "B", "pop").json(), "salary")["b_steps"] == [COMMA]


def test_a_step_that_lacks_what_it_needs_is_refused_in_a_sentence(c):
    r = steps(c, "salary", "A", "add", {"op": "custom expression", "params": {"expr": "upper(y)"}})
    assert r.status_code == 400 and r.json()["detail"] == "The expression must mention `x`, the value."
    r = steps(c, "salary", "A", "add", {"op": "replace text", "params": {"a": "", "b": ""}})
    assert r.json()["detail"] == "Type the find first - one space counts."
    assert steps(c, "salary", "A", "add", {"op": "no such step"}).status_code == 400
    assert steps(c, "department", "A", "clear").status_code == 404   # one-sided: no pair to read
    bad = steps(c, "last_name", "A", "add", {"op": "custom expression", "params": {"expr": "x +* 1"}})
    assert bad.status_code == 200                                    # kept: the preview says what is wrong
    t = c.get("/api/setup/try", params={"canon": "last_name", "which": "A"}).json()
    assert t["error"].startswith("DuckDB says:") and t["rows"] == []


def test_the_type_and_the_check_on_all_rows(c):
    v = c.post("/api/setup/type", json={"canon": "active", "kind": "boolean"}, headers=W).json()
    assert spec(v, "active")["kind"] == "boolean"
    assert c.post("/api/setup/type", json={"canon": "active", "kind": "money"}, headers=W).status_code == 400
    rep = c.post("/api/setup/check", json={"canon": "active"}, headers=W).json()
    assert rep["columns"][:3] == ["Column", "Side", "Read as"] and {r[1] for r in rep["rows"]} == {"HR", "PR"}
    assert rep["said"] == ""
    text = c.post("/api/setup/check", json={"canon": "emp_id"}, headers=W).json()
    assert text["rows"] == [] and text["said"] == "Text with no steps - nothing to convert."


def test_a_step_drops_what_was_worked_out_from_the_table(c):
    ws = ws_of(c)
    c.get("/api/setup")
    ws.data.update(profile=("k", {}), key_report=((), None))
    steps(c, "salary", "B", "add", COMMA)
    assert "profile" not in ws.data and "key_report" not in ws.data


def test_the_filters_are_kept_with_the_columns_they_were_typed_for(c):
    f = c.get("/api/setup/filters").json()
    assert f["rows"] == [{"Apply to": "Both", "Column": "", "Operator": "=", "Value": "", "Type": "auto"}]
    assert f["apply_to"] == ["Both", "HR", "PR"] and "between" in f["ops"] and f["error"] == ""
    assert f["columns"] == ["emp_id", "last_name", "salary", "hire_date", "active"]
    row = {"Apply to": "HR", "Column": "salary", "Operator": "between", "Value": "1", "Type": "number"}
    f = c.put("/api/setup/filters", json={"rows": [row]}, headers=W).json()
    assert f["rows"] == [row] and f["error"].startswith("'between' on salary needs two values")
    f = c.put("/api/setup/filters", json={"rows": [{**row, "Value": "1, 9000"}]}, headers=W).json()
    assert f["error"] == ""
    assert c.put("/api/setup/filters", json={"rows": [{**row, "Operator": "drop"}]}, headers=W).status_code == 400
    v = c.get("/api/setup").json()
    c.post("/api/setup/cell", json={"rev": v["rev"], "row": 1, "column": "B column", "value": ""}, headers=W)
    assert c.get("/api/setup/filters").json()["rows"][0]["Column"] == ""     # other columns now: a blank row


def test_rows_a_config_put_in_are_taken_for_the_table(c):
    ws = ws_of(c)
    c.get("/api/setup")
    ws.data["filter_rows"] = pd.DataFrame([{"Apply to": "Both", "Column": "emp_id", "Operator": "=",
                                            "Value": "E10001", "Type": "auto"}])
    assert c.get("/api/setup/filters").json()["rows"][0]["Value"] == "E10001"
