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
from tablecmp.sources import Side, file_stamp, preview_rows, set_aside_said, source_schema
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


# ---- the quote ---------------------------------------------------------------------------------
def test_a_correctly_quoted_file_reads_as_before(tmp_path):
    s = side_of(put(tmp_path, "good.csv", GOOD))
    assert s.columns == ["id", "name", "amt"] and s.rows == 4
    assert values(s) == [["1", "Smith, John", "10"], ["2", 'say "hi"', "20"], ["3", "two\nlines", "30"],
                         ["4", "short", None]]
    assert s.read_opts == {"skip_rows": 0, "quote": '"', "bad_rows": "keep"} and s.read_from == ""
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
        side_of(p, snapshot=False)
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
def test_keep_is_the_default_and_unchanged(tmp_path):
    s = side_of(put(tmp_path, "l.csv", LEFT))
    assert s.bad_rows == "keep" and s.rows == 6 and s.columns == ["id", "name", "amt", "column3"]
    assert s.set_aside_rows == 0 and set_aside_said(s) == ""


def test_set_aside_keeps_the_right_rows_and_counts_by_field_count(tmp_path):
    s = side_of(put(tmp_path, "l.csv", LEFT), bad_rows="set_aside")
    assert s.columns == ["id", "name", "amt"] and s.rows == 3
    assert [r[0] for r in values(s)] == ["1", "2", "5"] and values(s)[0][1] == "Smith, John"
    assert (s.set_aside_rows, s.set_aside_by, s.set_aside_fields) == (3, {2: 2, 4: 1}, 3)
    assert set_aside_said(s) == "3 rows set aside - 2 with 2 fields, 1 with 4 (the header has 3)"
    assert s.read_from == "wrong-width rows set aside"
    # captured once from the whole file: a WHERE and a top N do not change what was set aside
    cut = side_of(put(tmp_path, "l2.csv", LEFT), bad_rows="set_aside", where="id = '5'", limit=1)
    assert cut.rows == 1 and cut.set_aside_rows == 3


def test_set_aside_over_http_and_in_the_compare(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    a, b = put(tmp_path, "left.csv", LEFT), put(tmp_path, "right.csv", RIGHT)
    va = load_path(f, "A", a, bad_rows="set_aside")["side"]
    vb = load_path(f, "B", b, bad_rows="set_aside")["side"]
    assert va["bad_rows"] == "set_aside" and va["quote"] == '"' and va["rows"] == 3
    assert va["set_aside"] == {"rows": 3, "kept": 3, "fields": 3,
                               "said": "3 rows set aside - 2 with 2 fields, 1 with 4 (the header has 3)",
                               "by": [{"fields": 2, "rows": 2}, {"fields": 4, "rows": 1}]}
    assert vb["rows"] == 4 and vb["set_aside"]["said"] == "2 rows set aside - 1 with 2 fields, 1 with 5 (the header has 3)"
    # the panel: a page at a time, in file order; the download holds them all
    page = f.get("/api/sources/A/set-aside", page=2, size=2).json()
    assert page["rows"] == 3 and page["page"] == 2 and page["lines"] == [{"line": 7, "fields": 2, "raw": "6,f"}]
    first = f.get("/api/sources/A/set-aside", page=1, size=2).json()["lines"]
    assert first == [{"line": 4, "fields": 2, "raw": "3,c"}, {"line": 5, "fields": 4, "raw": "4,d,40,x"}]
    r = f.c.get("/api/sources/A/set-aside.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert list(csv.reader(io.StringIO(r.text))) == [["line", "fields", "raw"], ["4", "2", "3,c"],
                                                     ["5", "4", "4,d,40,x"], ["7", "2", "6,f"]]
    assert f.get("/api/sources/P/set-aside").status_code == 409
    # the compare leaves them out
    got = auto(f)
    assert got["counts"]["matched"] == 3 and got["counts"]["only_left"] == 0
    assert got["counts"]["only_right"] == 1 and got["counts"]["diff_rows"] == 1
    assert got["body"]["set_aside"] == {"A": 3, "B": 2}
    said = "".join(s["text"] for s in got["body"]["verdict"]["segments"])
    assert said.endswith("3 rows set aside in Left · 2 rows set aside in Right")
    pair, folder = got["pair"], got["folder"]
    summary = json.loads((folder / f"{pair}__summary.json").read_text(encoding="utf-8"))
    assert (summary["result"]["set_aside_left"], summary["result"]["set_aside_right"]) == (3, 2)
    assert summary["sources"]["A"]["bad_rows"] == "set_aside" and summary["sources"]["A"]["set_aside"]["rows"] == 3
    assert (folder / f"{pair}__set_aside_right.csv").read_text(encoding="utf-8").splitlines()[1:] == [
        '5,5,"4,d,40,y,z"', "7,2,\"7,g\""]
    files = {x["name"]: x["label"] for x in f.call("files").json()["files"]}
    assert files[f"{pair}__set_aside_left.csv"] == "Rows set aside in Left"
    assert files[f"{pair}__set_aside_right.csv"] == "Rows set aside in Right"
    report = (folder / f"{pair}__report.html").read_text(encoding="utf-8")
    assert "<b>3</b> rows set aside in Left" in report and "2 rows set aside - 1 with 2 fields" in report
    # the run config carries the option; Run from config honours it
    conf = json.loads((folder / f"{pair}__config.json").read_text(encoding="utf-8"))
    assert conf["sides"]["A"]["bad_rows"] == "set_aside" and "quote" not in conf["sides"]["A"]
    fresh = boot(monkeypatch, tmp_path)
    r = fresh.call("config", {"path": str(folder / f"{pair}__config.json")})
    assert wait(fresh, r.json())["state"] == "done"
    settle(fresh)
    boxes = fresh.get("/api/sources").json()["config"]["boxes"]
    assert boxes["A"]["bad_rows"] == "set_aside" and boxes["A"]["quote"] == '"'
    again = fresh.call("state").json()["run"]
    assert again["set_aside"] == {"A": 3, "B": 2} and again["matched"] == 3


def test_a_new_load_drops_the_old_rows_set_aside(monkeypatch, tmp_path):
    from pathlib import Path

    from tablecmp.web.sides import panel
    f = boot(monkeypatch, tmp_path)
    a = put(tmp_path, "left.csv", LEFT)
    load_path(f, "A", a, bad_rows="set_aside")
    old = panel(f.ws(), "A").side.set_aside_path
    assert Path(old).exists()
    view = load_path(f, "A", a)["side"]
    assert view["set_aside"] is None and not Path(old).exists()
    assert f.get("/api/sources/A/set-aside").json()["rows"] == 0


def test_the_config_side_block_round_trip(tmp_path):
    p = put(tmp_path, "l.csv", LEFT)
    s = side_of(p, bad_rows="set_aside", quote="'")
    block = side_block(s, "L")
    assert block["bad_rows"] == "set_aside" and block["quote"] == "'"
    back = open_side(block, "A")
    assert (back.quote, back.bad_rows, back.set_aside_rows, back.rows) == ("'", "set_aside", 4, 2)   # "Smith, John" splits in two
    plain = side_block(side_of(p), "L")
    assert "quote" not in plain and "bad_rows" not in plain          # defaults stay out
    none = side_block(side_of(put(tmp_path, "n.csv", "a,b\n1,2\n"), quote=""), "N")
    assert none["quote"] == "" and open_side(none, "A").quote == ""
    with pytest.raises(ConfigError, match="quote character"):
        open_side({**block, "quote": "|"}, "A")
    with pytest.raises(ConfigError, match="a quote never closes"):
        open_side({**block, "quote": '"', "path": str(put(tmp_path, "b.csv", BROKEN))}, "A")
