"""Pick from values: a column's distinct values over the whole loaded side, and the quick clause
that takes picked values exactly as they are."""
import duckdb

from tablecmp.web.sides import panel
from tests.conftest import EX, W, ws_of

HR = EX / "hr_employees.csv"


def load(c, tag="A", path=HR, **kw):
    r = c.post(f"/api/sources/{tag}/load", json={"how": "path", "path": str(path), **kw}, headers=W)
    assert r.status_code == 200, r.text
    return r


def truth(sql, path=HR):
    return duckdb.sql(sql.replace("{f}", f"read_csv('{path.as_posix()}', all_varchar=true)")).fetchall()


def test_the_values_of_a_column_most_frequent_first_with_counts(c):
    load(c)
    r = c.get("/api/sources/A/values?column=department")
    assert r.status_code == 200
    b = r.json()
    want = truth("SELECT department, count(*) FROM {f} GROUP BY 1 ORDER BY 2 DESC, 1")
    assert b["column"] == "department" and b["rows"] == 3000 and b["distinct"] == 8 and not b["more"]
    assert [(v["value"], v["n"]) for v in b["values"]] == want and len(want) == 8


def test_a_where_on_the_side_does_not_change_the_list(c):
    load(c)
    before = c.get("/api/sources/A/values?column=department").json()
    load(c, where="department = 'Finance'", order_by=["salary"], limit=10)
    assert panel(ws_of(c), "A").side.rows == 10
    assert c.get("/api/sources/A/values?column=department").json() == before


def test_search_is_any_case_and_literal(c):
    load(c)
    b = c.get("/api/sources/A/values", params={"column": "department", "search": "ENG"}).json()
    assert [v["value"] for v in b["values"]] == ["Engineering"] and b["distinct"] == 1
    assert b["values"][0]["n"] == truth("SELECT count(*) FROM {f} WHERE department = 'Engineering'")[0][0]
    for odd in ("%", "_", "'"):                       # no wildcard, no quoting slip
        assert c.get("/api/sources/A/values", params={"column": "department", "search": odd}).json()["values"] == []


def test_null_is_a_value_and_limit_says_there_are_more(c, tmp_path):
    f = tmp_path / "odd.csv"
    f.write_text("id,tag\n1,a\n2,\n3,\n4,b\n5,\"x, 'y'\"\n6,a\n", encoding="utf-8")
    load(c, path=f)
    b = c.get("/api/sources/A/values?column=tag").json()
    assert b["values"] == [{"value": "a", "n": 2}, {"value": None, "n": 2}, {"value": "b", "n": 1},
                           {"value": "x, 'y'", "n": 1}]
    one = c.get("/api/sources/A/values?column=tag&limit=1").json()
    assert one["values"] == [{"value": "a", "n": 2}] and one["distinct"] == 4 and one["more"]
    ids = c.get("/api/sources/A/values?column=id&limit=1000").json()
    assert ids["distinct"] == 6 and len(ids["values"]) == 6 and not ids["more"]


def test_refusals(c):
    assert c.get("/api/sources/A/values?column=department").status_code == 409
    load(c, name="HR")
    r = c.get("/api/sources/A/values?column=nope")
    assert r.status_code == 400 and r.json()["detail"] == "HR has no column nope."
    assert c.get("/api/sources/A/values?column=department&limit=1001").status_code == 422
    assert c.get("/api/sources/X/values?column=department").status_code == 404


def test_a_renamed_column_reads_the_file_column_and_the_cache_goes_on_reload(c, tmp_path):
    load(c, column_names="id, first, last, dept")
    b = c.get("/api/sources/A/values?column=dept").json()
    assert b["column"] == "dept" and b["distinct"] == 8
    assert c.get("/api/sources/A/values?column=department").json()["values"] == b["values"]
    assert panel(ws_of(c), "A").values
    f = tmp_path / "one.csv"
    f.write_text("department\nX\n", encoding="utf-8")
    load(c, path=f)
    assert c.get("/api/sources/A/values?column=department").json()["values"] == [{"value": "X", "n": 1}]


def test_a_parquet_side_reads_its_values_as_text(c, tmp_path):
    pq = tmp_path / "hr.parquet"
    duckdb.sql(f"COPY (SELECT emp_id, salary::DOUBLE AS salary FROM read_csv('{HR.as_posix()}')) TO '{pq.as_posix()}'")
    load(c, path=pq, where="salary > '1'")
    b = c.get("/api/sources/A/values?column=salary&limit=1").json()
    assert b["rows"] == 3000 and isinstance(b["values"][0]["value"], str)


def clause(c, **kw):
    r = c.post("/api/sources/quick-clause", json={"column": "department", "where": "", **kw}, headers=W)
    assert r.status_code == 200, r.text
    return r.json()["where"]


def test_picked_values_go_in_exactly_as_they_are(c):
    op = "in (comma separated)"
    assert clause(c, op=op, values=["a, b", "O'Hara"]) == "\"department\" IN ('a, b', 'O''Hara')"
    assert clause(c, op=op, values=["Finance"], value="HR, Finance") == "\"department\" IN ('Finance', 'HR')"
    assert clause(c, op=op, value="HR, Finance") == "\"department\" IN ('HR', 'Finance')"      # as before
    assert clause(c, op="=", values=[" padded "], value=" padded ") == "\"department\" = ' padded '"
    assert clause(c, op="!=", value=" Finance ") == "\"department\" != 'Finance'"
    load(c)
    got = c.post("/api/sources/A/load", json={"how": "path", "path": str(HR),
                 "where": clause(c, op=op, values=["Finance", "Sales"])}, headers=W).json()["side"]
    assert got["rows"] == truth("SELECT count(*) FROM {f} WHERE department IN ('Finance', 'Sales')")[0][0]


def test_a_database_side_reads_the_fetched_file_not_the_database(c, monkeypatch):
    from tablecmp import databases
    from tests.test_web_sources import TABLE, wait
    monkeypatch.setenv("COMPARE_CONN_SAMPLE", "duckdb:///" + (EX / "sample.duckdb").as_posix())
    wait(c, c.post("/api/sources/A/fetch", json=TABLE, headers=W).json())
    c.post("/api/sources/A/load", json={"how": "database", "db": TABLE, "where": "department = 'Sales'"}, headers=W)

    def no(*a, **k):
        raise AssertionError("the database was asked again")
    monkeypatch.setattr(databases, "fetch_parquet", no)
    b = c.get("/api/sources/A/values?column=department").json()
    assert b["rows"] == 3000 and b["distinct"] == 8


def test_a_file_changed_or_gone_after_load_is_refused_not_read_again(c, tmp_path):
    import os
    f = tmp_path / "d.csv"
    f.write_text("dept\nA\nB\n", encoding="utf-8")
    load(c, path=f, where="dept = 'A'")
    assert c.get("/api/sources/A/values?column=dept").json()["rows"] == 2
    f.write_text("dept\nZZZ\nQQQ\nQQQ\n", encoding="utf-8")
    os.utime(f, ns=(1, 1))
    r = c.get("/api/sources/A/values?column=dept&limit=5")
    assert r.status_code == 409 and "changed since Load" in r.json()["detail"]
    f.unlink()
    assert c.get("/api/sources/A/values?column=dept&limit=6").status_code == 409


def test_the_cache_keys_the_search_as_duckdb_lowers_it(c, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("w\nstraße\nclass\nglass\n", encoding="utf-8")
    load(c, path=f)
    assert [v["value"] for v in c.get("/api/sources/A/values", params={"column": "w", "search": "ß"}).json()["values"]] == ["straße"]
    got = c.get("/api/sources/A/values", params={"column": "w", "search": "ss"}).json()["values"]
    assert sorted(v["value"] for v in got) == ["class", "glass"]


def test_a_list_read_while_the_side_was_loaded_again_is_not_kept(c, monkeypatch):
    from tablecmp.web import routes_sources
    load(c)
    p = panel(ws_of(c), "A")

    def swap(side, *a):
        p.side = type(side)(**{**side.__dict__})         # a Load landed mid-read
        return {"column": "department", "rows": 0, "distinct": 0, "values": [], "more": False}
    monkeypatch.setattr(routes_sources, "column_values", swap)
    c.get("/api/sources/A/values?column=department")
    assert not p.values
