"""The results of a run with no page attached - what the React server calls."""
import tempfile
from pathlib import Path

import pytest

from tablecmp import results as rs
from tablecmp.outputs import write_parquet_copies, write_summary
from tablecmp.sources import Side
from tests.test_outputs import _run


def test_the_verdict_in_words(tmp_path, monkeypatch):
    run, _, _ = _run(tmp_path, monkeypatch)
    res = run["result"]
    v = rs.verdict_parts(run, "hr", "payroll")
    text = "".join(t for t, _ in v["segments"])
    assert v["tone"] == run["verdict"].tone and v["word"] == run["verdict"].word
    assert text.startswith(f"{res.matched_rows:,} rows matched on emp_id · 2 columns compared · ")
    assert text.endswith(f" · {res.only_left:,} only in hr · {res.only_right:,} only in payroll")
    assert ("emp_id", True) in v["segments"] and v["when"] == f"{run['seconds']:.1f}s at {run['at']}"


def test_the_verdict_without_a_key(tmp_path, monkeypatch):
    run, _, _ = _run(tmp_path, monkeypatch, mode="hash")
    text = "".join(t for t, _ in rs.verdict_parts(run, "hr", "payroll")["segments"])
    assert "identical rows found by hashing 2 columns" in text
    assert rs.run_keys(run) == [] and rs.run_columns(run) == ["department", "active"]


def test_the_report_follows_the_rows_shown(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    path = Path(run["folder"]) / f"{run['pair']}__report.html"
    assert not rs.report_current(run, 100)
    html = rs.ensure_report(run, A, B, "hr", "payroll", 100, profile=None)
    assert rs.report_current(run, 100) and not rs.report_current(run, 50)
    assert path.read_text(encoding="utf-8") == html and bytes([13, 10]) not in path.read_bytes()
    run["_report"] = "<html>kept</html>"
    path.unlink()
    assert rs.ensure_report(run, A, B, "hr", "payroll", 100) == "<html>kept</html>" and path.exists()
    assert rs.ensure_report(run, A, B, "hr", "payroll", 50) != "<html>kept</html>"
    assert run["files"][path.name] == path


def test_the_files_as_downloads_lists_them(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    write_summary(run, A, B, "hr", "payroll")
    rows = rs.download_rows(run, "hr", "payroll")
    labels = [r["label"] for r in rows]
    assert labels[:3] == ["Cell differences", "Rows only in hr", "Rows only in payroll"]
    assert "Paired rows" not in labels and "Summary" in labels and all(r["bytes"] > 0 for r in rows)
    assert rs.config_path(run) is None and rs.engine_path(run).name.endswith("__diff.html")
    assert not rs.engine_gone(run)
    write_parquet_copies(run)
    assert "cell_diffs (Parquet)" in [r["label"] for r in rs.download_rows(run, "hr", "payroll")]
    rs.engine_path(run).unlink()
    assert rs.engine_path(run) is None and rs.engine_gone(run)


def test_a_save_of_everything_writes_the_paired_rows_first(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    write_summary(run, A, B, "hr", "payroll")
    got = rs.paired_first(run)
    assert f"{run['pair']}__paired.csv" in got and all(p.exists() for p in got.values())
    assert rs.paired_first(run) == {}


def test_where_a_save_goes_by_default(tmp_path, monkeypatch):
    (tmp_path / "tmp").mkdir()
    here = tmp_path / "data"
    here.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    assert rs.default_save_base(Side(csv_path=str(here / "a.csv"))) == str(here.resolve())
    downloads = Path.home() / "Downloads"
    fallback = str(downloads if downloads.exists() else Path.home())
    assert rs.default_save_base(Side(csv_path=str(tmp_path / "tmp" / "up.csv"))) == fallback
    assert rs.default_save_base(None) == fallback and rs.default_save_base(Side()) == fallback


def test_a_save_lands_in_its_folder_and_stays_under_the_out_dir(tmp_path, monkeypatch):
    run, _, _ = _run(tmp_path, monkeypatch)
    monkeypatch.setenv("COMPARE_OUT_DIR", str(tmp_path / "out"))
    per_run = tmp_path / "out" / f"{run['pair']}__{run['run_id']}"
    left = run["files"][f"{run['pair']}__left_only.csv"]
    target, written = rs.save_files({"a.txt": b"x", "b.csv": left}, f'"{per_run}"', run)    # quotes from Copy as path
    assert target == per_run.resolve() and written == ["a.txt", "b.csv"]
    assert rs.save_base_after(target, run) == str(per_run.resolve().parent)
    assert rs.save_base_after(tmp_path / "out" / "mine", run) == str(tmp_path / "out" / "mine")
    assert (per_run / "a.txt").read_bytes() == b"x" and (per_run / "b.csv").read_bytes() == left.read_bytes()
    assert rs.saved_line(target, written) == f"Saved 2 files to `{target}`: a.txt, b.csv"
    assert rs.saved_line(target, ["a.txt"]).startswith("Saved 1 file to ")
    with pytest.raises(ValueError, match="Saves must stay under"):
        rs.save_files({"a.txt": b"x"}, str(tmp_path / "elsewhere"), run)
    with pytest.raises(ValueError, match="^Type a folder to save into.$"):
        rs.save_files({"a.txt": b"x"}, "  ", run)
    assert not (tmp_path / "elsewhere").exists()


def test_which_cards_and_buckets_a_run_opens_with(tmp_path, monkeypatch):
    run, _, _ = _run(tmp_path, monkeypatch)
    res = run["result"]
    differing, shown, rest = rs.card_order(res, ["department", "active"])
    assert differing == sorted(differing, key=lambda c: (-res.diffs_by_column[c], c))
    assert shown[:len(differing)] == differing and set(shown + rest) == {"department", "active"}
    buckets = dict(rs.bucket_list(res, ["emp_id"], "hr", "payroll"))
    assert buckets["matched"] == f"Keys matched ({res.matched_rows:,})"
    assert buckets["same"] == f"Matched and same ({res.matched_rows - res.diff_rows:,})"
    assert list(buckets) == ["matched", "same", "differ", "left", "right"]
    res.diff_rows, gone = 0, res.diff_rows                          # nothing differs: no second "Keys matched"
    assert "same" not in dict(rs.bucket_list(res, ["emp_id"], "hr", "payroll"))
    res.diff_rows = gone
    assert buckets["left"] == f"Only in hr ({res.only_left:,})"
    assert rs.first_bucket(buckets, "left") == "left"
    assert rs.first_bucket(buckets, "gone") == ("differ" if "differ" in buckets else "matched")
    assert dict(rs.bucket_list(res, ["emp_id"], "X", "X"))["left"].startswith("Only in A · X")
    own, shown_cols, others = rs.bucket_plan(run, "left", ["emp_id"], ["department", "active"])
    assert own == {"salary": "A"} and shown_cols == ["emp_id", "department", "active"]      # the side's own column waits until ticked
    _, shown_cols, others = rs.bucket_plan(run, "differ", ["emp_id"], ["department", "active"], keys_apart=True)
    assert "emp_id" not in shown_cols + others and set(shown_cols + others) >= {"department", "active"}
    assert shown_cols[0] == max(["department", "active"], key=lambda c: res.diffs_by_column.get(c, 0))


def test_the_default_save_base_is_never_in_the_work_folder(tmp_path, monkeypatch):
    work = tmp_path / "cmpwork"
    work.mkdir()
    monkeypatch.setenv("COMPARE_WORK_DIR", str(work))
    monkeypatch.setattr(rs.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    fallback = rs.default_save_base(None)
    for where in (work, work / "sub"):
        where.mkdir(exist_ok=True)
        assert rs.default_save_base(Side(csv_path=str(where / "up.csv"))) == fallback
    assert rs.default_save_base(Side(csv_path=str(tmp_path / "data.csv"))) == str(tmp_path.resolve())


def test_a_rebuilt_report_drops_the_stale_zip(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    rs.ensure_report(run, A, B, "hr", "payroll", 500)
    zp = Path(run["folder"]).parent / "old.zip"
    zp.write_bytes(b"zip")
    run["zip"] = zp
    rs.ensure_report(run, A, B, "hr", "payroll", 500)          # unchanged: the zip stays
    assert run.get("zip") == zp
    rs.ensure_report(run, A, B, "hr", "payroll", 300)          # rows shown changed: report rebuilt
    assert not run.get("zip") and not zp.exists()
