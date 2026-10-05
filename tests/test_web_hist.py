"""GET /api/profiling/hist - one column's equal-width bins for the Profile page's column detail,
counted in DuckDB on the loaded table: numbers, dates and timestamps; no bins for other types."""
import pandas as pd
import pytest

from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


def test_hist_asks_for_a_profile_first(c):
    r = c.get("/api/profiling/hist", params={"column": "salary"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Profile the table first."


def test_salary_in_ten_bins_covers_every_row(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    h = c.get("/api/profiling/hist", params={"column": "salary"}).json()
    assert h["column"] == "salary" and h["kind"] == "number"
    bins = h["bins"]
    assert len(bins) == 10
    assert sum(b["n"] for b in bins) == 3000
    df = pd.read_csv(HR)
    assert bins[0]["lo"] == pytest.approx(df["salary"].min())
    assert bins[-1]["hi"] == pytest.approx(df["salary"].max())
    for a, b in zip(bins, bins[1:]):
        assert a["hi"] == pytest.approx(b["lo"])
    # every bin's count is what pandas finds between its edges (the last one closed at the top)
    for i, b in enumerate(bins):
        top = df["salary"] <= b["hi"] if i == len(bins) - 1 else df["salary"] < b["hi"]
        assert b["n"] == int(((df["salary"] >= b["lo"]) & top).sum())


def test_dates_come_back_as_iso_dates_and_bins_is_honoured(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    h = c.get("/api/profiling/hist", params={"column": "hire_date", "bins": 4}).json()
    assert h["kind"] == "date" and len(h["bins"]) == 4
    assert h["bins"][0]["lo"] == "2018-01-01"
    assert h["bins"][-1]["hi"] == "2026-09-28"
    assert sum(b["n"] for b in h["bins"]) == 3000


def test_text_has_no_bins_and_an_unknown_column_is_404(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    assert c.get("/api/profiling/hist", params={"column": "department"}).json() == {
        "column": "department", "kind": "text", "bins": []}
    r = c.get("/api/profiling/hist", params={"column": "nope"})
    assert r.status_code == 404
    assert c.get("/api/profiling/hist", params={"column": "salary", "bins": 0}).status_code == 422


def test_one_value_is_one_bin(c, tmp_path):
    f = tmp_path / "same.csv"
    f.write_text("id,v\n1,5\n2,5\n3,5\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    h = c.get("/api/profiling/hist", params={"column": "v"}).json()
    assert h["kind"] == "number"
    assert h["bins"] == [{"lo": 5.0, "hi": 5.0, "n": 3}]


def test_dates_before_1970_and_far_ahead_are_binned(c, tmp_path):
    f = tmp_path / "born.csv"
    f.write_text("id,born\n1,1965-04-02\n2,1990-01-01\n3,2000-05-05\n4,9999-12-31\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    h = c.get("/api/profiling/hist", params={"column": "born", "bins": 2}).json()
    assert h["kind"] == "date"
    assert (h["bins"][0]["lo"], h["bins"][-1]["hi"]) == ("1965-04-02", "9999-12-31")
    assert sum(b["n"] for b in h["bins"]) == 4


def test_nan_and_infinity_have_no_bin(c, tmp_path):
    f = tmp_path / "odd.csv"
    f.write_text("id,v\n1,1\n2,5\n3,NaN\n4,Infinity\n5,3\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    r = c.get("/api/profiling/hist", params={"column": "v", "bins": 2})
    assert r.status_code == 200
    h = r.json()
    assert h["kind"] == "number"
    assert (h["bins"][0]["lo"], h["bins"][-1]["hi"]) == (1, 5)
    assert sum(b["n"] for b in h["bins"]) == 3
