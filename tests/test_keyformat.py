# tests/test_keyformat.py
"""Key columns written differently on the two sides: the fix found, simple or only suggested."""
import pytest

from tablecmp.keyformat import key_format_fixes
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.values import ColSpec, ReadOptions

OPTS = ReadOptions()
SPEC = [ColSpec(canon="emp_id", a_src="emp_id", b_src="emp_id", kind="text"),
        ColSpec(canon="name", a_src="name", b_src="name", kind="text")]


def _side(path, name, ids):
    path.write_text("emp_id,name\n" + "".join(f"{i},n{k}\n" for k, i in enumerate(ids)),
                    encoding="utf-8", newline="\n")
    s = Side(name=name, label=path.name, csv_path=str(path))
    s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


def _fixes(tmp_path, monkeypatch, a_ids, b_ids):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    A, B = _side(tmp_path / "a.csv", "Left", a_ids), _side(tmp_path / "b.csv", "Right", b_ids)
    return key_format_fixes(A, B, SPEC, ["emp_id"], OPTS)


N = range(1, 41)


@pytest.mark.parametrize("a_ids, b_ids, what, a_steps, b_steps", [
    ([f"{i:05d}" for i in N], [str(i) for i in N], "leading zeros",
     [{"op": "strip leading zeros", "params": {}}], [{"op": "strip leading zeros", "params": {}}]),
    ([f"e{i}x" for i in N], [f"E{i}X" for i in N], "case", [{"op": "upper", "params": {}}],
     [{"op": "upper", "params": {}}]),
    ([f"{i}.0" for i in N], [str(i) for i in N], "a trailing .0",
     [{"op": "regex replace", "params": {"a": r"\.0+$", "b": ""}}],
     [{"op": "regex replace", "params": {"a": r"\.0+$", "b": ""}}]),
])
def test_simple_fixes_are_found_and_marked_safe(tmp_path, monkeypatch, a_ids, b_ids, what, a_steps, b_steps):
    (fix,) = _fixes(tmp_path, monkeypatch, a_ids, b_ids)
    assert fix.canon == "emp_id" and fix.simple and fix.what == what
    assert fix.a_steps == a_steps and fix.b_steps == b_steps
    assert fix.before == 0 and fix.after == 1
    assert "applied" not in fix.said and fix.example[0] in a_ids and fix.example[1] in b_ids


def test_a_prefix_on_one_side_is_suggested_not_applied(tmp_path, monkeypatch):
    (fix,) = _fixes(tmp_path, monkeypatch, [f"EMP-{i:04d}" for i in N], [str(i) for i in N])
    assert not fix.simple and fix.what == "a prefix EMP- on A and leading zeros"
    assert fix.a_steps == [{"op": "regex replace", "params": {"a": r"^EMP\-", "b": ""}},
                           {"op": "strip leading zeros", "params": {}}]
    assert fix.b_steps == [{"op": "strip leading zeros", "params": {}}]
    assert fix.after == 1


def test_sides_that_already_meet_need_no_fix(tmp_path, monkeypatch):
    assert _fixes(tmp_path, monkeypatch, [str(i) for i in N], [str(i) for i in N]) == []


def test_a_fix_that_would_merge_two_keys_is_not_offered(tmp_path, monkeypatch):
    """'7' and '007' are two rows of A: stripping zeros would make the key a duplicate."""
    a = [str(i) for i in N] + [f"00{i}" for i in range(1, 6)]
    b = [f"{i:05d}" for i in N]
    assert all(f.what != "leading zeros" for f in _fixes(tmp_path, monkeypatch, a, b))


def test_unrelated_values_get_no_fix(tmp_path, monkeypatch):
    assert _fixes(tmp_path, monkeypatch, [f"A{i}" for i in N], [f"B{i + 100}" for i in N]) == []


def test_auto_applies_a_simple_fix_and_only_suggests_a_guess(tmp_path, monkeypatch):
    """emp_code is 'AB 7' on one side and 'AB7' on the other: Auto removes the spaces and says
    so; ref carries a prefix on one side only, so it is suggested and left alone."""
    from tablecmp.auto import auto_configure
    from tablecmp.values import steps_from_json
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "work"))
    (tmp_path / "a.csv").write_text("emp_code,ref,salary\n" + "".join(f"AB {i},R-{i:03d}x,{i * 10}\n" for i in N))
    (tmp_path / "b.csv").write_text("emp_code,ref,salary\n" + "".join(f"AB{i},{i:03d}x,{i * 10}\n" for i in N))
    A, B = (Side(name=n, label=f, csv_path=str(tmp_path / f)) for n, f in (("Left", "a.csv"), ("Right", "b.csv")))
    for s in (A, B):
        s.schema = source_schema(s.csv_path, "csv", ",", True, file_stamp(s.csv_path))
        s.source_columns = list(s.schema)
    fixes = []
    cmap, notes, chosen, _ = auto_configure(A, B, "a", "b", OPTS, lambda m: None, found_fixes=fixes)
    row = cmap.set_index("Common name")
    assert steps_from_json(row.at["emp_code", "A steps"]) == [{"op": "remove spaces", "params": {}}]
    assert steps_from_json(row.at["ref", "A steps"]) == []
    assert {f.canon: f.simple for f in fixes} == {"emp_code": True, "ref": False}
    assert any(n.startswith("emp_code: the two sides write the key differently") and n.endswith("- applied")
               for n in notes)
    assert any(n.startswith("ref:") and n.endswith("suggested, not applied") for n in notes)
