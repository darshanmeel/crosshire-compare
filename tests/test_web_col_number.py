"""GET /api/profiling/numform - a number column's form: log bins, digits before the point,
places after it, the DECIMAL it fits, round lots and values seen once."""
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


def test_numform_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/numform", params={"column": "x"}).status_code == 409


def test_hr_salary(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    assert c.get("/api/profiling/numform", params={"column": "nope"}).status_code == 404
    r = c.get("/api/profiling/numform", params={"column": "salary"}).json()
    assert r["column"] == "salary" and r["filled"] > 2900
    assert r["zeros"] == 0 and r["negatives"] == 0
    assert sum(b["n"] for b in r["log_bins"]) == r["filled"]
    assert sum(b["n"] for b in r["before"]) == r["filled"]
    assert r["log_bins"][-1]["hi"] >= r["log_bins"][-1]["lo"]
    assert r["fits"].startswith("DECIMAL(")
    assert len(r["top"]) == 10 and r["top"][0]["n"] >= r["top"][-1]["n"]
    assert len(r["once"]) <= 10
    # text answers an empty form
    t = c.get("/api/profiling/numform", params={"column": "department"}).json()
    assert t["filled"] == 0 and t["log_bins"] == []


def test_skewed_quantities(c, tmp_path):
    f = tmp_path / "q.csv"
    qty = [1] * 5 + [2] * 3 + [0] * 2 + [-4] + [50] * 4 + [500] * 3 + [5000] * 6 + [200000] * 7 + [37892500, 10007, 100093]
    f.write_text("id,qty,price\n" + "".join(f"{i},{q},{i}.25\n" for i, q in enumerate(qty)), encoding="utf-8")
    load_p(c, f)
    profile(c)
    r = c.get("/api/profiling/numform", params={"column": "qty"}).json()
    assert r["filled"] == len(qty) and r["zeros"] == 2 and r["negatives"] == 1
    assert [(b["label"], b["n"]) for b in r["log_bins"]] == [
        ("< 0", 1), ("0", 2), ("1 - 9", 8), ("10 - 99", 4), ("100 - 999", 3), ("1,000 - 9,999", 6),
        ("10,000 - 99,999", 1), ("100,000 - 999,999", 8), ("1,000,000 - 9,999,999", 0),
        ("10,000,000 - 37,892,500", 1)]
    assert r["log_bins"][-1]["hi"] == 37892500 and r["log_bins"][0] == {"label": "< 0", "lo": -4, "hi": 0, "n": 1}
    assert r["before"] == [{"label": "1-3", "n": 18}, {"label": "4-6", "n": 15}, {"label": "7-9", "n": 1}]
    assert r["places"] == {"min": 0, "max": 0} and r["fits"] == "DECIMAL(8, 0)"
    assert r["top"][0] == {"value": 200000, "n": 7} and r["top"][1] == {"value": 5000, "n": 6}
    assert r["round_lots"] == [200000, 5000] and r["lot_step"] == 1000
    assert r["once"] == [-4, 10007, 100093, 37892500]
    p = c.get("/api/profiling/numform", params={"column": "price"}).json()
    assert p["places"] == {"min": 2, "max": 2} and p["fits"] == "DECIMAL(4, 2)"
    assert p["log_bins"][0]["label"] == "0 - 1" and p["round_lots"] == [] and p["lot_step"] == 0


def test_number_form_reads_any_relation():
    """The analysis is a plain function on a connection and a relation - no profile, no route."""
    import duckdb

    from tablecmp.web.routes_col_number import number_form
    con = duckdb.connect()
    con.execute("CREATE TABLE orders AS SELECT * FROM (VALUES (1, 500), (2, 500), (3, 1200), (4, 7), (5, NULL)) v(order_id, OrderQty)")
    r = number_form(con, "orders", "OrderQty")
    assert r["column"] == "OrderQty" and r["filled"] == 4
    assert [(b["label"], b["n"]) for b in r["log_bins"]] == [("1 - 9", 1), ("10 - 99", 0), ("100 - 999", 2), ("1,000 - 1,200", 1)]
    assert r["round_lots"] == [500, 1200] and r["lot_step"] == 100 and r["fits"] == "DECIMAL(4, 0)"
    assert number_form(con, "orders", "OrderQty") == r        # a second call on the same connection
    con.close()


def test_number_form_counts_digits_of_doubles_written_with_an_exponent():
    """DuckDB writes 1e20 as 1e+20 and 0.000015 as 1.5e-05 - their digits are counted as the number has them."""
    import duckdb

    from tablecmp.web.routes_col_number import number_form
    con = duckdb.connect()
    con.execute("CREATE TABLE prices AS SELECT * FROM (VALUES (1e20::DOUBLE), (1.5e-5::DOUBLE)) v(Price)")
    r = number_form(con, "prices", "Price")
    assert r["places"] == {"min": 0, "max": 6} and r["fits"] == "DECIMAL(27, 6)"
    assert r["log_bins"][-1]["label"] == "100,000,000,000,000,000,000 - 100,000,000,000,000,000,000"
    con.close()
