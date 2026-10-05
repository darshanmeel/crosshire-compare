"""GET /api/profiling/casts - text columns that could be read as a number, a date or a
timestamp, and how many of their values would, in the form most of them take."""
from tests.test_web_profiling import HR, c, load_p, profile  # noqa: F401 - c is the client fixture


def test_casts_ask_for_a_profile_first(c):
    r = c.get("/api/profiling/casts")
    assert r.status_code == 409


def test_text_that_reads_as_numbers_dates_and_timestamps(c, tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("id,amount,ordered,when,name\n"
                 "1,\"1,200.50\",04/05/2026,20260504004217,Ann\n"
                 "2,30,17/05/2026,20260505101500,Bob\n"
                 "3,x,,2026-05-06 08:00:00,Cy\n", encoding="utf-8")
    load_p(c, f)
    # read every column as text, as a file with stray values would be
    profile(c)
    got = {r["column"]: r for r in c.get("/api/profiling/casts").json()["columns"]}
    # amount is text for its "x": two of three read as numbers once the , goes
    assert got["amount"]["filled"] == 3 and got["amount"]["kind"] == "text"
    assert got["amount"]["number"] == {"any": 2, "form": "with , removed", "n": 2, "before": 4, "after": 2}
    assert "date" not in got["amount"] and "timestamp" not in got["amount"]
    # when mixes an ISO timestamp with compact ones: all three read, most as the compact form
    assert got["when"]["timestamp"] == {"any": 3, "form": "%Y%m%d%H%M%S", "n": 2}
    assert "date" not in got["when"]
    assert "ordered" not in got                          # read as a date already, not text
    assert "name" not in got                             # nothing reads as another type


def test_a_clean_sample_has_no_text_dates_or_numbers_left(c):
    load_p(c, HR, "HR")
    profile(c, "HR")
    cols = c.get("/api/profiling/casts").json()["columns"]
    assert all(r["filled"] > 0 for r in cols)
    assert c.get("/api/profiling/casts").json() == {"columns": cols}     # kept, the same answer


def test_parts_of_a_number_a_date_and_text(c, tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("id,amt,day,code\n"
                 "1,12.5,2026-05-04,SL1944\n"
                 "2,1234.25,2026-05-05,SL2001\n"
                 "3,7,2025-01-03,OM2001\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    g = {x["title"]: x["rows"] for x in c.get("/api/profiling/parts", params={"column": "amt"}).json()["groups"]}
    assert g["Digits before the point"] == [{"label": "1-3", "n": 2}, {"label": "4-6", "n": 1}]
    assert g["Places after the point"] == [{"label": "0", "n": 1}, {"label": "1-3", "n": 2}]
    assert sorted((r["label"], r["n"]) for r in g["Before · after"]) == [("1-3 · 0", 1), ("1-3 · 1-3", 1), ("4-6 · 1-3", 1)]
    d = {x["title"]: x["rows"] for x in c.get("/api/profiling/parts", params={"column": "day"}).json()["groups"]}
    assert d["Year"] == [{"label": "2025", "n": 1}, {"label": "2026", "n": 2}]
    assert d["Month"] == [{"label": "Jan", "n": 1}, {"label": "May", "n": 2}]
    assert d["Weekday"] == [{"label": "Mon", "n": 1}, {"label": "Tue", "n": 1}, {"label": "Fri", "n": 1}]
    assert "Hour" not in d
    t = {x["title"]: x["rows"] for x in c.get("/api/profiling/parts", params={"column": "code", "n": 2}).json()["groups"]}
    assert t["First 2 characters"] == [{"label": "SL", "n": 2}, {"label": "OM", "n": 1}]
    assert all(x["total"] == 3 for x in c.get("/api/profiling/parts", params={"column": "code"}).json()["groups"])
    assert t["Last 2 characters"][0] == {"label": "01", "n": 2}
    assert c.get("/api/profiling/parts", params={"column": "nope"}).status_code == 404


def test_a_number_column_of_compact_timestamps_could_be_a_timestamp(c, tmp_path):
    f = tmp_path / "o.csv"
    f.write_text("id,order_time,qty\n"
                 + "".join(f"{800012011026 + i},2026050{1 + i % 9}0042{10 + i},{i}\n" for i in range(20)), encoding="utf-8")
    load_p(c, f)
    profile(c)
    got = {r["column"]: r for r in c.get("/api/profiling/casts").json()["columns"]}
    assert got["order_time"]["kind"] == "number"
    assert got["order_time"]["timestamp"] == {"any": 20, "form": "%Y%m%d%H%M%S", "n": 20}
    assert "number" not in got["order_time"]
    assert "id" not in got and "qty" not in got       # a long id or a count is not a date


def test_text_timestamps_with_a_fraction_and_a_z_read_as_timestamps_and_are_taken_apart_as_one(c, tmp_path):
    f = tmp_path / "z.csv"
    f.write_text("id,OrderTime\n"
                 "1,20261001 05:30:00.128158Z\n"
                 "2,20261002 17:05:09.5Z\n"
                 "3,20261003 17:45:00Z\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    got = {r["column"]: r for r in c.get("/api/profiling/casts").json()["columns"]}
    assert got["OrderTime"]["kind"] == "text"
    assert got["OrderTime"]["timestamp"] == {"any": 3, "form": "%Y%m%d %H:%M:%S.%n", "n": 2}
    assert c.get("/api/profiling/parts", params={"column": "OrderTime"}).json()["reads_as"] == ""   # as text unless asked
    body = c.get("/api/profiling/parts", params={"column": "OrderTime", "as": "timestamp"}).json()
    assert body["reads_as"] == "timestamp"
    g = {x["title"]: x["rows"] for x in body["groups"]}
    assert g["Year"] == [{"label": "2026", "n": 3}]
    assert g["Weekday"] == [{"label": "Thu", "n": 1}, {"label": "Fri", "n": 1}, {"label": "Sat", "n": 1}]
    assert g["Hour"] == [{"label": "05", "n": 1}, {"label": "17", "n": 2}]


def test_parts_read_text_as_a_number_and_spelling_counts_case_and_space_variants(c, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("id,amount,kind\n1,\"1,200.50\",limit\n2,30,Limit\n3,x,\" limit\"\n4,7.5,stop\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    body = c.get("/api/profiling/parts", params={"column": "amount", "as": "number"}).json()
    assert body["reads_as"] == "number"
    g = {x["title"]: x["rows"] for x in body["groups"]}
    assert g["Digits before the point"] == [{"label": "1-3", "n": 2}, {"label": "4-6", "n": 1}]
    assert c.get("/api/profiling/parts", params={"column": "amount", "as": "nope"}).status_code == 400
    sp = c.get("/api/profiling/spelling", params={"column": "kind"}).json()
    assert sp == {"column": "kind", "distinct": 3, "folded": 2, "padded": 0}     # the read trims outer spaces
    assert c.get("/api/profiling/spelling", params={"column": "nope"}).status_code == 404


def test_parts_read_dates_in_the_form_the_casts_found_and_take_any_fraction(c, tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("id,shipped,stamp\n"
                 "1,05/04/2026,20261001 05:30:00.1234567Z\n"
                 "2,12/25/2026,20261002 17:05:09.123456789Z\n"
                 "3,01/02/2026,x\n"
                 "4,x,20261003 17:45:00Z\n", encoding="utf-8")
    load_p(c, f)
    profile(c)
    got = {r["column"]: r for r in c.get("/api/profiling/casts").json()["columns"]}
    assert got["shipped"]["date"]["form"] == "%m/%d/%Y"
    assert got["stamp"]["timestamp"]["any"] == 3                   # 7 and 9 digits after the point read too
    body = c.get("/api/profiling/parts", params={"column": "shipped", "as": "date"}).json()
    g = {x["title"]: x["rows"] for x in body["groups"]}
    # month first, as most values are written - not 05/04 read day-first as 5 April
    assert g["Month"] == [{"label": "Jan", "n": 1}, {"label": "May", "n": 1}, {"label": "Dec", "n": 1}]
