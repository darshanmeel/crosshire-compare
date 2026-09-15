# tests/test_report.py
import re
from tablecmp.report import build_report
from tests.test_outputs import _run          # the sample run helper


def test_report_sections_and_no_secrets(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch)
    A.conn, A.database, A.query, A.fetched_at = "prod", "snowflake", "SELECT * FROM hr.employees", "10:12:01"
    A.origin = "Snowflake · hr.employees"
    html = build_report(run, A, B, "prod", "payroll", limit=50, notes=["key: emp_id - name says identifier"])
    for anchor in ("setup", "counts", "columns", "by-key", "rows", "only-a", "only-b"):
        assert f'id="{anchor}"' in html
    assert "Differences" in html and "small differences" in html.lower()
    assert "connection <code>prod</code>" in html and "SELECT * FROM hr.employees" in html
    assert "How this was worked out" in html and "name says identifier" in html
    assert "Values" in html and "trim" in html.lower()
    assert "@media print" in html and 'class="vp"' in html      # value pairs block
    assert "Settings as JSON" in html
    assert not re.search(r"password|secret", html, re.I)


def test_report_hash_mode_and_filters(tmp_path, monkeypatch):
    run, A, B = _run(tmp_path, monkeypatch, mode="hash")
    html = build_report(run, A, B, "hr", "payroll", limit=20)
    assert 'id="by-key"' not in html and 'id="rows"' not in html and 'class="vp"' not in html
    assert 'href="#only-a"' in html and 'id="only-a"' in html
    assert "Rows paired" in html and "by hashing the compared columns" in html
    run, A, B = _run(tmp_path, monkeypatch)
    run["cfg"]["filters"] = {"department": {"in": ["Sales", "Finance"]}}
    run["cfg"]["left_filters"] = {"active": {"eq": "true", "type": "text"}}
    run["cfg"]["right_filters"] = {"salary": {"not_null": True, "type": "number"}}
    run["cfg"]["ignore_case"], run["cfg"]["tolerance"] = True, 0.5
    html = build_report(run, A, B, "hr", "payroll", limit=20)
    assert "department in Sales, Finance · both sides" in html
    assert "active = true · hr" in html and "salary is not null · payroll" in html
    assert "<b>case ignored</b>" in html and "<b>tolerance 0.5</b>" in html
    assert "unique on both sides" in html and "How this was worked out" not in html
