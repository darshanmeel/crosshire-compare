"""GET /api/profiling/when - a date or timestamp column's page: range, span, precision,
repeats, calendar checks and rows per bin, for a typed column and for text read as one."""
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


def test_when_asks_for_a_profile_first(c):
    assert c.get("/api/profiling/when", params={"column": "hire_date"}).status_code == 409


def test_a_date_column(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    w = c.get("/api/profiling/when", params={"column": "hire_date"}).json()
    assert w["kind"] == "date" and w["form"] == "" and w["filled"] == 3000
    assert w["first"] <= w["last"] and len(w["first"]) == 10
    assert w["shared"] == w["filled"] - w["distinct"] and w["days"] == w["distinct"]
    assert w["date_only"] == 3000 and w["fraction_digits"] == 0 and w["whole_ms"] is None
    assert w["bin"] == "year" and sum(b["n"] for b in w["bins"]) == 3000
    assert [b["label"] for b in w["bins"]] == sorted(b["label"] for b in w["bins"])
    assert [d["label"] for d in w["weekday"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert sum(d["n"] for d in w["weekday"][5:]) == w["weekend"]
    assert sum(m["n"] for m in w["months"]) == 3000 and len(w["months"]) == 12
    assert [q["label"] for q in w["quarters"]] == ["Jan - Mar", "Apr - Jun", "Jul - Sep", "Oct - Dec"]
    assert sum(q["n"] for q in w["quarters"]) == 3000
    assert w["placeholders"] == [] and w["before_1900"] == 0
    assert all(r["n"] > 1 for r in w["repeated"]) and len(w["repeated"]) <= 5
    assert [r["n"] for r in w["repeated"]] == sorted((r["n"] for r in w["repeated"]), reverse=True)
    m = c.get("/api/profiling/when", params={"column": "hire_date", "bin": "month"}).json()
    assert m["bin"] == "month" and sum(b["n"] for b in m["bins"]) == 3000
    assert m["bins"][0]["label"] == w["first"][:7] and m["bins"][-1]["label"] == w["last"][:7]
    assert c.get("/api/profiling/when", params={"column": "hire_date", "bin": "weekday"}).json()["bins"] == w["weekday"]
    assert c.get("/api/profiling/when", params={"column": "hire_date", "bin": "hour"}).status_code == 400
    assert c.get("/api/profiling/when", params={"column": "hire_date", "bin": "nope"}).status_code == 400
    assert c.get("/api/profiling/when", params={"column": "first_name"}).status_code == 400   # text, not read as one
    assert c.get("/api/profiling/when", params={"column": "nope"}).status_code == 404


def test_text_stamps_read_as_a_timestamp(c, tmp_path):
    f = tmp_path / "z.csv"
    f.write_text("id,Stamp\n"
                 "1,20261001 05:30:00.128158Z\n"
                 "2,20261001 05:30:00.128158Z\n"
                 "3,20261001 07:17:59.375000Z\n"
                 "4,20261001 07:17:59.375000Z\n"
                 "5,20261001 07:17:59.375000Z\n"
                 "6,20261001 09:05:12.000001Z\n"
                 "7,20261001 17:30:41.059000Z\n"
                 "8,\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    w = c.get("/api/profiling/when", params={"column": "Stamp", "as": "timestamp"}).json()
    assert w["kind"] == "timestamp" and w["form"] == "%Y%m%d %H:%M:%S.%n"
    assert (w["filled"], w["distinct"], w["shared"]) == (7, 4, 3)
    assert w["first"] == "2026-10-01 05:30:00.128158" and w["last"] == "2026-10-01 17:30:41.059000"
    assert abs(w["span_seconds"] - 43240.930842) < 1e-6
    assert w["days"] == 1 and w["date_only"] == 0 and w["weekend"] == 0 and w["future"] == 0
    assert w["fraction_digits"] == 6 and w["whole_ms"] == 4          # .375000 three times and .059000
    assert w["repeated"] == [{"value": "2026-10-01 07:17:59.375000", "n": 3, "weekday": "Thu"},
                             {"value": "2026-10-01 05:30:00.128158", "n": 2, "weekday": "Thu"}]
    assert w["bin"] == "hour"                                         # one calendar day
    assert w["bins"][0] == {"label": "05:00", "n": 2} and w["bins"][-1] == {"label": "17:00", "n": 1}
    assert len(w["bins"]) == 13 and sum(b["n"] for b in w["bins"]) == 7     # empty hours kept
    m = c.get("/api/profiling/when", params={"column": "Stamp", "as": "timestamp", "bin": "minute"}).json()
    assert m["bins"][0] == {"label": "05:30", "n": 2} and len(m["bins"]) == 12 * 60 + 1
    assert c.get("/api/profiling/when", params={"column": "Stamp"}).status_code == 400   # text unless read as one


def test_calendar_checks_count_placeholders_the_future_and_a_long_span_by_month(c, tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("id,day\n1,1900-01-01\n2,1970-01-01\n3,2099-06-01\n4,2024-03-02\n5,2024-03-02\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    w = c.get("/api/profiling/when", params={"column": "day"}).json()
    assert w["placeholders"] == [{"value": "1900-01-01", "n": 1}, {"value": "1970-01-01", "n": 1}]
    assert w["future"] == 1 and w["first_of_month"] == 3 and w["before_1900"] == 0
    assert w["weekend"] == 2                                          # 2024-03-02 is a Saturday
    assert w["repeated"] == [{"value": "2024-03-02", "n": 2, "weekday": "Sat"}]
    assert w["bins"][0] == {"label": "1900", "n": 1} and len(w["bins"]) == 200
    assert c.get("/api/profiling/when", params={"column": "day", "bin": "day"}).status_code == 400   # too many bins
    m = c.get("/api/profiling/when", params={"column": "day", "bin": "month"}).json()   # 2,394 months: filled ones only
    assert m["bins"] == [{"label": "1900-01", "n": 1}, {"label": "1970-01", "n": 1},
                         {"label": "2024-03", "n": 2}, {"label": "2099-06", "n": 1}]
