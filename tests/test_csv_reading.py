"""How a CSV is read: the quote always given (a quote that never closes fails loudly instead of
reading the whole file wrong), the quote character picked (", ' or none), and rows with too few
or too many fields kept (padded, extra columns) or set aside and listed - on Load, over HTTP, in a
compare, its downloads, summary.json and report, and through a saved config."""
import csv
import io
import json

import pytest

from tablecmp.loading import ReadAsked, build_side
from tablecmp.runconfig import ConfigError, open_side, side_block
from tablecmp.sources import BadQuote, Side, file_stamp, filled_said, preview_rows, set_aside_said, source_schema
from tests.conftest import isolated_env
from tests.webflow import auto, boot, load_path, settle, wait

GOOD = 'id,name,amt\n1,"Smith, John",10\n2,"say ""hi""",20\n3,"two\nlines",30\n4,short\n'
BROKEN = 'id,name,amt\n1,"Smith, John",10\n5,"open quote,9\n6,f,60\n'
# 3 fields a row; 2-, 3- and 4-field rows on both sides
LEFT = 'id,name,amt\n1,"Smith, John",10\n2,b,20\n3,c\n4,d,40,x\n5,e,50\n6,f\n'
RIGHT = 'id,name,amt\n1,"Smith, John",10\n2,b,21\n3,c,30\n4,d,40,y,z\n5,e,50\n7,g\n'


@pytest.fixture(autouse=True)
def _work(monkeypatch, tmp_path):
    isolated_env(monkeypatch, tmp_path)


def put(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return p


def side_of(p, **kw) -> Side:
    schema = source_schema(str(p), "csv", ",", True, file_stamp(str(p)),
                           **{k: v for k, v in kw.items() if k in ("quote", "bad_rows", "skip_rows")})
    return build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="csv", **kw), schema)


def values(s: Side) -> list[list]:
    return preview_rows(s, 100).astype(object).where(lambda d: d.notna(), None).values.tolist()


def test_a_row_wider_than_the_sample_stops_the_load_with_a_plain_sentence(monkeypatch, tmp_path):
    rows = "".join(f"{i},a,1\n" for i in range(30_000))                # past DuckDB's sample of 20,480 lines
    f = boot(monkeypatch, tmp_path)
    p = put(tmp_path, "wide.csv", "id,name,amt\n" + rows + "9,b,12,33\n")
    r = f.c.post("/api/sources/A/load", json={"how": "path", "path": str(p), "name": "Left", "bad_rows": "keep"}, headers={"X-Compare": "1"})
    assert r.status_code == 400
    said = r.json()["detail"]
    assert said.startswith("wide.csv: line 30,002 has 4 fields where the rows before it have 3") and "decimal comma" in said
    assert "Possible fixes" not in said


# ---- the quote ---------------------------------------------------------------------------------
def test_a_correctly_quoted_file_reads_as_before(tmp_path):
    s = side_of(put(tmp_path, "good.csv", GOOD), bad_rows="keep")
    assert s.columns == ["id", "name", "amt"] and s.rows == 4
    assert values(s) == [["1", "Smith, John", "10"], ["2", 'say "hi"', "20"], ["3", "two\nlines", "30"],
                         ["4", "short", None]]
    assert s.read_opts == {"skip_rows": 0, "quote": '"', "bad_rows": "keep"} and s.read_from == "wrong-width rows kept"
    assert s.set_aside_rows == 0 and not s.set_aside_path


def test_a_quote_that_never_closes_fails_plainly_over_http(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    p = put(tmp_path, "broken.csv", BROKEN)
    got = f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(p)}).json()
    assert got["error"].startswith("broken.csv: a quote never closes, so the rows cannot be told apart - fix the "
                                   "file, or pick another quote character under Advanced.")
    assert "sniffing" in got["error"] and "SELECT" not in got["error"] and "Possible fixes" not in got["error"]
    for mode in ("keep", "set_aside"):
        r = f.send("POST", "/api/sources/A/load", {"how": "path", "path": str(p), "bad_rows": mode})
        assert r.status_code == 400 and r.json()["detail"].startswith("broken.csv: a quote never closes")
    # quote none reads it - the quotes are text then
    r = f.send("POST", "/api/sources/A/load", {"how": "path", "path": str(p), "quote": ""})
    assert r.status_code == 200, r.text
    assert r.json()["side"]["quote"] == "" and "no quoting" in r.json()["side"]["read_from"]


def test_a_quote_that_never_closes_far_down_the_file(tmp_path):
    """Past the sniffer's sample: Keep fails reading the rows, Set aside fails at Load - neither
    glues two rows into one quietly."""
    lines = ["id,name,amt"] + [f'{i},"n {i}",{i}' for i in range(30_000)]
    lines.insert(25_000, '99,"open quote,9')
    p = put(tmp_path, "deep.csv", "\n".join(lines) + "\n")
    with pytest.raises(Exception, match="unterminated quote"):
        side_of(p, snapshot=False, bad_rows="keep")
    with pytest.raises(ValueError, match="a quote never closes"):
        side_of(p, snapshot=False, bad_rows="set_aside")


def test_quote_single_and_none(tmp_path):
    p = put(tmp_path, "single.csv", "id,name\n1,'Smith, John'\n2,'it''s'\n")
    s = side_of(p, quote="'")
    assert values(s) == [["1", "Smith, John"], ["2", "it's"]] and s.read_from == "quote '"
    p = put(tmp_path, "none.csv", 'id,note\n1,5" pipe\n2,"x\n')
    s = side_of(p, quote="")
    assert values(s) == [["1", '5" pipe'], ["2", '"x']] and s.read_from == "no quoting"
    with pytest.raises(ValueError, match="quote character"):
        Side(kind="csv", quote="|").read_opts


# ---- rows with too few or too many fields ------------------------------------------------------
def test_every_row_of_the_wrong_width_goes_even_when_its_extra_fields_are_empty(tmp_path):
    """DuckDB's ignore_errors keeps a row whose extra fields are empty - shifted. None may stay."""
    text = "id,name,amt\n1,a,10\n2,b,20,,\n3,c,30,\n4,d,40\n"
    s = side_of(put(tmp_path, "e.csv", text))
    assert s.rows == 2 and values(s) == [["1", "a", "10"], ["4", "d", "40"]]
    assert s.set_aside_rows == 2 and s.set_aside_by == {4: 1, 5: 1} and s.set_aside_fields == 3


def test_a_file_where_no_row_fits_says_why(tmp_path):
    p = put(tmp_path, "c.csv", "id,price\n1,12,33\n2,45,10\n")
    schema = source_schema(str(p), "csv", ",", True, file_stamp(str(p)), bad_rows="set_aside")
    s = build_side("A", ReadAsked(name="X", label=p.name, path=str(p), kind="csv"), schema)
    assert s.rows == 0 and s.set_aside_rows == 2 and s.columns == ["id", "price"]
    said = set_aside_said(s)
    assert said.startswith("2 rows set aside - 2 rows have 3 fields (the header has 2). No row fits - ") and "decimal comma" in said


def test_set_aside_is_the_default_and_keep_still_pads(tmp_path):
    assert side_of(put(tmp_path, "d.csv", LEFT)).bad_rows == "set_aside"
    s = side_of(put(tmp_path, "l.csv", LEFT), bad_rows="keep")
    assert s.bad_rows == "keep" and s.rows == 6 and s.columns == ["id", "name", "amt", "column3"]
    assert s.set_aside_rows == 0 and set_aside_said(s) == ""


def test_set_aside_keeps_the_right_rows_and_counts_by_field_count(tmp_path):
    s = side_of(put(tmp_path, "l.csv", LEFT), bad_rows="set_aside")
    assert s.columns == ["id", "name", "amt"] and s.rows == 5
    assert [r[0] for r in values(s)] == ["1", "2", "3", "5", "6"] and values(s)[0][1] == "Smith, John"
    assert values(s)[2] == ["3", "c", None]                      # a short row reads, the field it lacks empty
    assert (s.set_aside_rows, s.set_aside_by, s.set_aside_fields) == (1, {4: 1}, 3)
    assert set_aside_said(s) == "1 row set aside - 2 rows have 2 fields, 3 have 3, 1 has 4 (the header has 3)"
    assert s.filled_rows == 2
    assert filled_said(s) == "2 rows have 2 fields, 3 have 3, 1 has 4 (the header has 3) - the missing fields read as empty."
    assert s.read_from == ""
    # captured once from the whole file: a WHERE and a top N do not change what was set aside
    cut = side_of(put(tmp_path, "l2.csv", LEFT), bad_rows="set_aside", where="id = '5'", limit=1)
    assert cut.rows == 1 and cut.set_aside_rows == 1


def test_short_rows_alone_read_with_nothing_set_aside_and_the_last_line_need_not_end(tmp_path):
    s = side_of(put(tmp_path, "s.csv", 'id,name,amt\n"1","a, b",10\n"2"\n"3","c"'))
    assert values(s) == [["1", "a, b", "10"], ["2", None, None], ["3", "c", None]]
    assert s.set_aside_rows == 0 and s.filled_rows == 2 and s.read_from == ""


def test_the_message_suggests_which_field_uses_a_comma_and_the_app_changes_nothing(tmp_path):
    head = '"id","at","qty","price","name"\n'
    both = side_of(put(tmp_path, "b.csv", head + '"a",01/10/26 06:59:36,123,5,12,33,"x"\n"b",02/10/26 01:02:03,456,6,40,"y"\n'))
    assert both.rows == 0 and both.set_aside_rows == 2
    said = set_aside_said(both)
    assert "at seems to use a comma in the time, 12:11:35,284, and a number seems to use a decimal comma" in said
    time = side_of(put(tmp_path, "t.csv", head + '"b",02/10/26 01:02:03,456,6,40,"y"\n'))
    assert "at seems to use a comma in the time" in set_aside_said(time) and "decimal comma" not in set_aside_said(time)
    number = side_of(put(tmp_path, "n.csv", head + '"a",01/10/26,5,12,33,"x"\n'))
    assert "A number seems to use a decimal comma" in set_aside_said(number) and "in the time" not in set_aside_said(number)
    other = side_of(put(tmp_path, "o.csv", 'id,name\n1,a\n2,b,x\n'))
    assert set_aside_said(other) == "1 row set aside - 1 row has 2 fields, 1 has 3 (the header has 2)"      # nothing to suggest


def test_the_read_offers_no_way_to_cut_a_row_to_fit(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    p = put(tmp_path, "c.csv", "id,price\n1,12,33\n")
    assert f.send("POST", "/api/sources/A/schema", {"how": "path", "path": str(p), "bad_rows": "first:2"}).status_code == 422


def test_a_file_where_every_row_is_too_wide_does_not_say_it_has_no_rows(tmp_path):
    from tablecmp.loading import loaded_notes
    notes = [t for _, t in loaded_notes(side_of(put(tmp_path, "c.csv", "id,price\n1,12,33\n2,45,10\n")))]
    assert not any("no rows" in t for t in notes)


def test_set_aside_over_http_and_in_the_compare(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    a, b = put(tmp_path, "left.csv", LEFT), put(tmp_path, "right.csv", RIGHT)
    va = load_path(f, "A", a, bad_rows="set_aside")["side"]
    vb = load_path(f, "B", b, bad_rows="set_aside")["side"]
    assert va["bad_rows"] == "set_aside" and va["quote"] == '"' and va["rows"] == 5
    assert va["set_aside"] == {"rows": 1, "kept": 1, "fields": 3,
                               "said": "1 row set aside - 2 rows have 2 fields, 3 have 3, 1 has 4 (the header has 3)",
                               "by": [{"fields": 4, "rows": 1}]}
    assert any("the missing fields read as empty" in n["text"] for n in va["notes"])
    assert vb["rows"] == 5 and vb["set_aside"]["said"] == "1 row set aside - 1 row has 2 fields, 4 have 3, 1 has 5 (the header has 3)"
    # the panel: a page at a time, in file order; the download holds them all
    page = f.get("/api/sources/A/set-aside", page=1, size=2).json()
    assert page["rows"] == 1 and page["page"] == 1 and page["lines"] == [{"line": 5, "fields": 4, "raw": "4,d,40,x"}]
    r = f.c.get("/api/sources/A/set-aside.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert list(csv.reader(io.StringIO(r.text))) == [["line", "fields", "raw"], ["5", "4", "4,d,40,x"]]
    assert f.get("/api/sources/P/set-aside").status_code == 409
    # the compare leaves them out
    got = auto(f)
    assert got["counts"]["matched"] == 4 and got["counts"]["only_left"] == 1
    assert got["counts"]["only_right"] == 1 and got["counts"]["diff_rows"] == 2
    assert got["body"]["set_aside"] == {"A": 1, "B": 1}
    said = "".join(s["text"] for s in got["body"]["verdict"]["segments"])
    assert said.endswith("1 row set aside in Left · 1 row set aside in Right")
    pair, folder = got["pair"], got["folder"]
    summary = json.loads((folder / f"{pair}__summary.json").read_text(encoding="utf-8"))
    assert (summary["result"]["set_aside_left"], summary["result"]["set_aside_right"]) == (1, 1)
    assert summary["sources"]["A"]["bad_rows"] == "set_aside" and summary["sources"]["A"]["set_aside"]["rows"] == 1
    assert (folder / f"{pair}__set_aside_right.csv").read_text(encoding="utf-8").splitlines()[1:] == [
        '5,5,"4,d,40,y,z"']
    files = {x["name"]: x["label"] for x in f.call("files").json()["files"]}
    assert files[f"{pair}__set_aside_left.csv"] == "Rows set aside in Left"
    assert files[f"{pair}__set_aside_right.csv"] == "Rows set aside in Right"
    report = (folder / f"{pair}__report.html").read_text(encoding="utf-8")
    assert "<b>1</b> row set aside in Left" in report and "1 row set aside - 1 row has 2 fields, 4 have 3, 1 has 5" in report
    assert "the missing fields read as empty" in report
    # the run config carries the option; Run from config honours it
    conf = json.loads((folder / f"{pair}__config.json").read_text(encoding="utf-8"))
    assert "bad_rows" not in conf["sides"]["A"] and "quote" not in conf["sides"]["A"]     # the defaults stay out
    fresh = boot(monkeypatch, tmp_path)
    r = fresh.call("config", {"path": str(folder / f"{pair}__config.json")})
    assert wait(fresh, r.json())["state"] == "done"
    settle(fresh)
    boxes = fresh.get("/api/sources").json()["config"]["boxes"]
    assert boxes["A"]["bad_rows"] == "set_aside" and boxes["A"]["quote"] == '"'
    again = fresh.call("state").json()["run"]
    assert again["set_aside"] == {"A": 1, "B": 1} and again["matched"] == 4


def test_a_new_load_drops_the_old_rows_set_aside(monkeypatch, tmp_path):
    from pathlib import Path

    from tablecmp.web.sides import panel
    f = boot(monkeypatch, tmp_path)
    a = put(tmp_path, "left.csv", LEFT)
    load_path(f, "A", a, bad_rows="set_aside")
    old = panel(f.ws(), "A").side.set_aside_path
    assert Path(old).exists()
    view = load_path(f, "A", a, bad_rows="keep")["side"]
    assert view["set_aside"] is None and not Path(old).exists()
    assert f.get("/api/sources/A/set-aside").json()["rows"] == 0


def test_the_config_side_block_round_trip(tmp_path):
    p = put(tmp_path, "l.csv", LEFT)
    s = side_of(p, bad_rows="set_aside", quote="'")
    block = side_block(s, "L")
    assert "bad_rows" not in block and block["quote"] == "'"
    back = open_side(block, "A")
    assert (back.quote, back.bad_rows, back.set_aside_rows, back.rows) == ("'", "set_aside", 2, 4)   # "Smith, John" splits in two
    plain = side_block(side_of(p), "L")
    assert "quote" not in plain and "bad_rows" not in plain          # defaults stay out
    none = side_block(side_of(put(tmp_path, "n.csv", "a,b\n1,2\n"), quote=""), "N")
    assert none["quote"] == "" and open_side(none, "A").quote == ""
    with pytest.raises(ConfigError, match="quote character"):
        open_side({**block, "quote": "|"}, "A")
    with pytest.raises(ConfigError, match="a quote never closes"):
        open_side({**block, "quote": '"', "path": str(put(tmp_path, "b.csv", BROKEN))}, "A")


def test_a_two_digit_year_reads_as_this_century_and_the_possible_types_name_it(tmp_path):
    import duckdb

    from tablecmp.sniff import possible_types
    from tablecmp.values import FALLBACK_FORMATS
    fl = "[" + ", ".join(repr(f) for f in FALLBACK_FORMATS) + "]"
    got = duckdb.sql(f"SELECT try_strptime('03/11/26', {fl})::DATE::VARCHAR, try_strptime('03/11/26 12:11:35', {fl})::VARCHAR, "
                     f"try_strptime('03/11/2026', {fl})::DATE::VARCHAR, try_strptime('2026/11/03', {fl})::DATE::VARCHAR").fetchone()
    assert got == ("2026-11-03", "2026-11-03 12:11:35", "2026-11-03", "2026-11-03")
    s = side_of(put(tmp_path, "t.csv", "d,n,w\n03/11/26,1,hi\n29/10/26,2,there\n"))
    ways = possible_types(s, ["d", "n", "w"])
    assert [w["label"] for w in ways["w"]] == ["text"]
    assert [w["label"] for w in ways["n"]][0] == "number" and ways["n"][-1]["label"] == "text"
    assert ways["d"][0] == {"type": "date", "format": "%d/%m/%y", "label": "date · 27/08/26"}
    assert not any(w.get("format") == "%d/%m/%Y" for w in ways["d"])


@pytest.mark.parametrize("text, kind, read", [
    ("01/10/26 06:59:36.884003000", "timestamp", "2026-10-01 06:59:36.884003"),
    ("31/08/26 08:09:29.893997", "timestamp", "2026-08-31 08:09:29.893997"),
    ("31/08/26 08:09:29", "timestamp", "2026-08-31 08:09:29"),
    ("01-10-26", "date", "2026-10-01"),
    ("2026/11/03", "date", "2026-11-03"),
    ("2026-11-03 01:02:03", "timestamp", "2026-11-03 01:02:03"),
])
def test_a_date_starting_with_a_day_is_never_read_as_the_year_it_looks_like(text, kind, read):
    """A cast reads 01/10/26 as the year 1; nine digits of a fraction used to fall through to it."""
    import duckdb

    from tablecmp.values import typed_exprs
    assert duckdb.sql(f"SELECT {typed_exprs(repr(text), kind)[1]}").fetchone()[0] == read


def test_nine_digits_of_a_fraction_read_alike_by_a_format_and_leave_far_dates_alone():
    import duckdb

    from tablecmp.values import typed_exprs
    read = lambda text, fmt="": duckdb.sql(f"SELECT {typed_exprs(repr(text), 'timestamp', fmt)[1]}").fetchone()[0]
    assert read("01/10/26 06:59:36.884003000", "%d/%m/%y %H:%M:%S.%n") == "2026-10-01 06:59:36.884003"
    assert read("9999-12-31 23:59:59") == "9999-12-31 23:59:59"
    assert read("31/12/9999") == "9999-12-31 00:00:00"


def test_an_unread_date_is_no_year_in_the_statistics():
    import duckdb

    from tablecmp.observe import measurable
    from tablecmp.values import ColSpec
    spec = ColSpec.__new__(ColSpec)
    spec.canon, spec.kind = "d", "timestamp"
    v = measurable(spec)[0]
    got = duckdb.sql(f"SELECT {v} FROM (SELECT '01/10/26 no' AS d UNION ALL SELECT '01/10/26')").fetchall()
    assert got == [(None,), (None,)]


def test_a_suggested_date_format_keeps_the_two_digit_year(tmp_path):
    from tablecmp.sniff import looks_like
    s = side_of(put(tmp_path, "t.csv", "d,w\n03/11/26 01:02:03.123456789,hi\n29/10/26 01:02:03.123456789,there\n"))
    s.schema["d"] = "VARCHAR"                     # DuckDB's own sniff calls it a timestamp of the year 3
    assert "%d/%m/%y %H:%M:%S.%n" in looks_like(s, ["d"])["d"]


def test_the_possible_types_are_served_a_side_each(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    load_path(f, "A", put(tmp_path, "a.csv", "d,n\n03/11/26,1\n29/10/26,2\n"))
    load_path(f, "B", put(tmp_path, "b.csv", "d,n\n2026-11-03,x\n2026-10-29,y\n"))
    got = f.c.get("/api/setup/possible-types").json()
    assert got["A"]["d"][0] == {"type": "date", "format": "%d/%m/%y", "label": "date · 27/08/26"}
    assert got["A"]["n"][0]["type"] == "number" and got["B"]["n"] == [{"type": "text", "label": "text"}]
    assert got["B"]["d"][0]["format"] == "%Y-%m-%d"

