# tests/test_web_flows.py
"""The page's flows over HTTP, in place of the Streamlit page's headless suites (phase 6).

Where each old test went (the old test files, test_apptest.py, test_ui_log.py, test_ui_results.py and the rest, were deleted with the Streamlit page; a "-> covered" line names the test that already asserts it; a name
without a file is in this one):
test_apptest.py::test_file_flow -> test_web_flows.py::test_file_flow_gives_the_counts_and_the_files (API); name hints and the Files line -> sources.test.tsx and the FilesSection test (Vitest); journey -> tests/e2e/test_e2e_page.py::test_the_sample_pair_compared_in_the_browser (Playwright)
test_apptest.py::test_side_names_name_the_files -> test_web_flows.py::test_named_sides_name_every_file (API)
test_apptest.py::test_database_flow -> test_web_flows.py::test_database_flow_keeps_the_two_samples_apart (API); "Both sides are called SAMPLE" -> sources.test.tsx; the tag radio and Copy-to button -> phase 3's Transform Vitest (columns.test.tsx / page.test.tsx)
test_apptest.py::test_empty_file_loads_with_no_rows_and_no_filter_blame -> test_web_flows.py::test_an_empty_file_loads_with_no_rows (API; all four files, test_web_sources.py::test_what_is_said_under_the_loaded_side has empty.csv only)
test_apptest.py::test_filter_leaving_no_rows_still_blames_the_filter -> test_web_flows.py::test_a_filter_leaving_no_rows_says_so (API)
test_apptest.py::test_profiling_page -> covered by test_web_profiling.py (the job, its lines and label, the notes entry, headline, keys, stats, the six files); the profile kept while the Compare side is used -> test_web_flows.py::test_the_profile_is_kept_while_the_compare_side_is_used (API); section order and folds -> profiling.test.tsx (Vitest); journey -> tests/e2e/test_e2e_page.py::test_one_table_profiled_in_the_browser (Playwright)
test_apptest.py::test_profiling_page_with_no_key_and_nothing_to_measure -> covered by test_web_profiling.py::test_no_key_and_an_empty_table_still_come_as_rows and ::test_a_failed_profile_says_why_and_keeps_the_last_one
test_apptest.py::test_compare_settings_survive_the_profiling_page -> tests/e2e/test_e2e_page.py::test_settings_survive_the_profiling_page (Playwright); the workspace side -> test_web_flows.py::test_settings_survive_the_profiling_routes (API); the data_editor stub -> dropped (Streamlit mechanics: AppTest cannot edit a data_editor)
test_apptest.py::test_load_with_nothing_picked_is_refused -> covered by test_web_sources.py::test_nothing_picked_and_a_bad_cut_are_sentences
test_apptest.py::test_profiling_page_from_a_database -> test_web_flows.py::test_profiling_a_database_table (API); no "Same SQL as A" on P -> database.test.tsx (Vitest)
test_apptest.py::test_key_written_differently_is_fixed_or_offered -> covered by test_web_keys.py::test_a_key_written_differently_is_fixed_or_offered (by Check key); Auto doing the same -> test_web_flows.py::test_auto_fixes_a_key_written_differently (API)
test_apptest.py::test_profile_checks_key_like_columns_first -> covered by test_web_keys.py::test_profile_both_files_checks_the_key_like_columns_first
test_apptest.py::test_a_saved_config_loads_both_sides_and_compares -> loading: covered by test_web_sources.py::test_a_config_by_path_loads_both_sides_and_the_column_table; comparing again to the same counts -> test_web_flows.py::test_a_saved_config_runs_again_to_the_same_counts (API)
test_apptest.py::test_a_folder_connection_picks_files_by_name_and_the_config_keeps_them -> listing and picking: covered by test_web_sources.py::test_a_folder_lists_its_files_and_a_file_is_picked_by_name; the config keeping folder and file -> test_web_flows.py::test_a_folder_pick_is_kept_in_the_config (API)
test_apptest.py::test_a_connections_file_is_imported_in_the_manager -> covered by test_web_connections.py::test_import_preview_import_and_export; the folder offered under Path on disk and not as a database -> test_web_flows.py::test_an_imported_folder_is_a_folder_not_a_database (API)
test_apptest.py::test_the_manager_makes_a_folder_connection -> covered by test_web_connections.py::test_test_a_folder_and_delete; no password box for a folder -> connections.test.tsx (Vitest)
test_apptest.py::test_editing_a_connection_keeps_its_env_reference -> covered by test_web_connections.py::test_an_env_reference_is_kept_and_shown_as_written and ::test_a_blank_password_on_save_keeps_the_saved_one
test_ui_log.py::test_auto_and_compare_land_in_the_log -> test_web_flows.py::test_auto_and_compare_land_in_the_log (API); the disc and the Log expander -> shell.test.tsx (Vitest)
test_ui_log.py::test_log_panel_is_there_before_anything_is_loaded -> covered by web/src/shell/shell.test.tsx
test_ui_log.py::test_running_draws_the_disc_and_writes_the_entry, ::test_a_run_started_far_down_the_page_draws_where_it_starts_too, ::test_a_slot_from_another_run_is_not_drawn_into -> dropped (the st.empty() slot); the disc is RunDisc (shell.test.tsx), the entry is test_web_jobs.py::test_a_job_says_its_lines_and_ends_done_with_its_time
test_ui_log.py::test_a_label_without_a_time_gets_one -> covered by test_web_jobs.py::test_a_job_says_its_lines_and_ends_done_with_its_time and ::test_a_label_with_a_time_is_left_as_it_is
test_ui_log.py::test_an_exception_marks_the_run_and_goes_on_up -> covered by test_web_jobs.py::test_a_job_that_raises_is_an_error_with_the_password_blanked
test_ui_log.py::test_note_and_clear, ::test_log_is_capped -> covered by test_web_jobs.py::test_the_log_is_capped_and_notes_go_in_it and ::test_the_log_routes_hide_results_and_clear
test_ui_results.py::test_verdict_reads_the_run, ::test_ensure_report_reuses_then_rebuilds -> not AppTests; they tested the ui_results module, whose logic now lives in tablecmp/results.py (both the module and the test file were deleted with the Streamlit page): the verdict is covered by test_web_compare.py::test_auto_works_it_out_and_compares and test_web_results.py, the report reuse by test_web_downloads.py::test_the_report_for_the_viewer_and_to_download (phase 4 moved both into tablecmp.results)
test_ui_results.py::test_summary_tab_opens_with_the_key -> covered by test_web_results.py::test_the_summary_opens_with_the_key (key row first); the one-sided row last -> test_web_flows.py::test_the_summary_ledger_starts_with_the_key (API); chips and tints -> results.test.tsx (Vitest); the table-styling CSS rules -> dropped (Streamlit mechanics: row_tint)
test_ui_results.py::test_one_view_is_drawn_and_what_it_counts_is_what_was_asked_for -> dropped (Streamlit built every tab); the bucket pick and folded cards -> covered by test_web_results.py::test_a_bucket_counts_its_rows_and_adds_what_is_asked_for and results.test.tsx
test_ui_results.py::test_downloads_tab_and_saves -> covered by test_web_downloads.py (files, report, paired rows, zip, Parquet, saves, refusals); what they leave out -> test_web_flows.py::test_downloads_and_saves (API)
test_ui_results.py::test_rows_filters_on_the_page -> test_web_flows.py::test_filters_refuse_in_a_sentence_and_filter_when_right (API)
test_columns.py::test_app_runs_with_a_column_paired_twice -> test_web_flows.py::test_app_runs_with_a_column_paired_twice_over_http (API)
test_columns.py::test_case_cell_beats_the_switch -> test_web_flows.py::test_case_cell_beats_the_switch_over_http (API)
test_columns.py::test_numeric_tolerance_leaves_text_pairs_alone -> test_web_flows.py::test_numeric_tolerance_leaves_text_pairs_alone_over_http (API)
test_columns.py::test_app_flow_with_every_item_together -> test_web_flows.py::test_app_flow_with_every_item_together_over_http (API)
test_columns.py::test_page_column_table_shows_roles_and_chips -> test_web_flows.py::test_page_column_table_shows_roles_and_chips_over_http (API); chips and tips -> columns.test.tsx (Vitest); the Role column not stored -> dropped (Streamlit's session_state)
test_sniff.py::test_app_shows_the_cells_and_leaves_the_type_alone -> test_web_flows.py::test_the_column_table_shows_the_cells_and_leaves_the_type_alone_over_http (API); "boolean · Y/N" itself is also in test_web_setup.py::test_the_table_is_built_for_the_pair; the sample taken once per pair -> same test
test_bootstrap.py (both tests) -> tests/test_start.py
"""
import json
import os
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from tests.webflow import (EX, FAKE_PW, OUTPUT_SUFFIXES, auto, boot, compare, expected_counts, fetch_and_load,
                           load_path, no_secret, profile, rows, run, settle, wait)

HR, PAY, DIR = EX / "hr_employees.csv", EX / "payroll_employees.csv", EX / "directory_employees.json"

# one JSON "name" column against HR's first_name and last_name, a split step on each pair
MAPPING = {"columns": [
    {"a": "emp_id", "b": "id", "name": "emp_id", "type": "text", "key": True, "compare": False,
     "b_steps": [{"op": "upper", "params": {}}]},
    {"a": "first_name", "b": "name", "name": "first_name", "type": "text", "compare": True,
     "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "1"}}]},
    {"a": "last_name", "b": "name", "name": "last_name", "type": "text", "compare": True,
     "b_steps": [{"op": "part N split by S", "params": {"s": " ", "n": "2"}}]},
    {"a": "department", "b": "dept", "name": "department", "type": "text", "compare": True},
    {"a": "salary", "b": "salary", "name": "salary", "type": "number", "compare": True},
    {"a": "hire_date", "b": "hire_date", "name": "hire_date", "type": "date", "compare": True,
     "b_steps": [{"op": "to date", "params": {"fmt": "%d-%b-%Y"}}]},
    {"a": "active", "b": "active", "name": "active", "type": "boolean", "compare": True},
]}


def _pair(f, a=HR, b=PAY, **names):
    """Both sides loaded; a name box left alone sends its default, as the page does."""
    load_path(f, "A", a, **({"name": names["A"]} if "A" in names else {}))
    load_path(f, "B", b, **({"name": names["B"]} if "B" in names else {}))


def _summary(res) -> dict:
    return json.loads((res["folder"] / f"{res['pair']}__summary.json").read_text(encoding="utf-8"))


def _specs(f) -> dict:
    return {s["canon"]: s for s in f.call("columns").json()["specs"]}


def _map(f, mapping, **case):
    """Load mapping with the Case of a column set - what the Case cell does on the page."""
    m = json.loads(json.dumps(mapping))
    for c in m["columns"]:
        if c["name"] in case:
            c["case"] = case[c["name"]]
    r = f.call("mapping", {"text": json.dumps(m)})
    assert r.status_code == 200, r.text
    return r.json()


def _pairs(view) -> list[tuple[str, str]]:
    return [(r["A column"], r["B column"]) for r in view["rows"] if r["A column"] and r["B column"]]


def _report(f) -> str:
    r = f.get(f"/api/results/{f.run_id()}/report")
    assert r.status_code == 200, r.text
    return r.text


# ---- files and databases ---------------------------------------------------------------------
def test_file_flow_gives_the_counts_and_the_files(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f)
    res = auto(f, profile=True)
    assert res["counts"] == expected_counts() and res["pair"] == "Left_compare_Right"   # the defaults, not the file stems
    assert res["keys"] == ["emp_id"]
    folder, pair = res["folder"], res["pair"]
    for suffix in OUTPUT_SUFFIXES:
        assert (folder / f"{pair}__{suffix}").exists(), suffix
    assert not (folder / f"{pair}__paired.csv").exists()      # written when asked for, not as the run goes
    # Auto's profile fills the Profile section with its button never pressed
    held = f.call("profile_both").json()
    assert held and held["stale"] is False and held["both"]["rows"]
    out = Path(os.environ["COMPARE_OUT_DIR"])
    target = out / f"{pair}__{res['body']['id']}"
    r = f.call("save", {"what": "all", "folder": str(target)})
    assert r.status_code == 200, r.text
    # everything means everything: the save writes the paired rows first, here and in the folder
    assert (target / f"{pair}__summary.json").exists()
    assert (folder / f"{pair}__paired.csv").exists() and (target / f"{pair}__paired.csv").exists()
    no_secret(f, folder, target)


def test_named_sides_name_every_file(monkeypatch, tmp_path):
    """The Name boxes decide the pair: HR and Directory give HR_compare_Directory, every file follows."""
    f = boot(monkeypatch, tmp_path)
    _pair(f, A="HR", B="Directory")
    res = auto(f)
    assert res["pair"] == "HR_compare_Directory"
    names = {p.name for p in res["folder"].iterdir()}
    assert names and all(n.startswith("HR_compare_Directory__") for n in names), names
    js = _summary(res)
    assert js["pair"] == "HR_compare_Directory"
    assert js["sources"]["A"]["name"] == "HR" and js["sources"]["B"]["name"] == "Directory"
    no_secret(f, res["folder"])


def test_database_flow_keeps_the_two_samples_apart(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    for tag, table in (("A", "hr.employees"), ("B", "payroll.employees")):
        side = fetch_and_load(f, tag, "SAMPLE", table)["side"]
        assert side["loaded"] and side["is_database"] and side["kind"] == "parquet", tag
        assert side["name"] == "SAMPLE" and side["conn"] == "SAMPLE", tag      # a database side is called after its connection
    assert f.call("state").json()["names"] == ["A · SAMPLE", "B · SAMPLE"]     # one name for both names neither
    res = auto(f, profile=True)
    assert res["counts"] == expected_counts() and res["pair"] == "A_SAMPLE_compare_B_SAMPLE"
    # the two sides are two columns in the tables the run writes, not one name twice
    sheet = (res["folder"] / f"{res['pair']}__columns.csv").read_text(encoding="utf-8")
    assert sheet.splitlines()[0].split(",")[:3] == ["column", "name_a", "name_b"]
    ledger = f.call("summary").json()["ledger"]
    assert [c for c in ledger["columns"] if "SAMPLE" in c] == ["A · SAMPLE", "B · SAMPLE"]
    js = _summary(res)
    assert js["sources"]["A"]["connection"] == "SAMPLE" and js["sources"]["A"]["sql"].startswith("SELECT")
    # where a side is picked the tag keeps the two SAMPLEs apart: a step added to B lands on B
    canon = f.call("columns").json()["specs"][0]["canon"]
    r = f.call("step", {"canon": canon, "which": "B", "action": "add", "step": {"op": "trim", "params": {}}})
    assert r.status_code == 200, r.text
    spec = _specs(f)[canon]
    assert spec["a_steps"] == [] and spec["b_steps"] == [{"op": "trim", "params": {}}]
    run_now = f.get("/api/compare").json()["run"]
    assert run_now["names"] == ["A · SAMPLE", "B · SAMPLE"]
    buckets = f.call("summary").json()["buckets"]
    assert [b["label"] for b in buckets[-2:]] == [f"Only in A · SAMPLE ({int(expected_counts()['only_left']):,})",
                                                   f"Only in B · SAMPLE ({int(expected_counts()['only_right']):,})"]
    no_secret(f, res["folder"], tmp_path / "work")


@pytest.mark.parametrize("name,text", [("empty.json", ""), ("empty_array.json", "[]"), ("empty.csv", ""),
                                       ("header_only.csv", "emp_id,first_name\n")])
def test_an_empty_file_loads_with_no_rows(monkeypatch, tmp_path, name, text):
    """An empty file loads with 0 rows: the side says the file has none, not that a filter cut them."""
    (tmp_path / name).write_text(text, encoding="utf-8")
    f = boot(monkeypatch, tmp_path)
    side = load_path(f, "A", tmp_path / name)["side"]
    assert side["loaded"] and side["rows"] == 0 and side["cut"] == "", name
    assert side["notes"] == [{"tone": "warning", "text": "The file has no rows."}], side["notes"]
    assert not [n for n in side["notes"] if n["tone"] == "error"]


def test_a_filter_leaving_no_rows_says_so(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    side = load_path(f, "A", HR, where="department = 'Nowhere'")["side"]
    assert side["rows"] == 0 and side["cut"] == "WHERE department = 'Nowhere'"
    assert side["notes"] == [{"tone": "warning", "text": "The filter left no rows."}]


# ---- the Profiling page ----------------------------------------------------------------------
def test_the_profile_is_kept_while_the_compare_side_is_used(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    assert load_path(f, "P", HR)["side"]["rows"] == 3000
    prof = profile(f)
    assert prof["headline"].startswith("3,000 rows × 7 columns · key: emp_id")
    load_path(f, "A", HR)                                        # the Compare page's side, not P
    assert f.call("profile_view").json()["profile"]["headline"] == prof["headline"]
    no_secret(f)


def test_settings_survive_the_profiling_routes(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f, A="HR")
    first = auto(f)
    f.call("settings", {"ignore_case": True, "null_tokens": "NULL, NA, -"})
    page = f.call("page_settings", {"display_rows": 500}).json()
    held = f.get("/api/setup/settings").json()
    assert held["ignore_case"] is True and held["null_tokens"] == "NULL, NA, -"
    typed = {"rows": [{"Apply to": "Both", "Column": "department", "Operator": "=", "Value": "Sales",
                       "Type": "auto"}]}
    assert f.call("filters", typed).json()["error"] == ""
    before = f.call("state").json()
    assert before["stale"] is True and before["run"]["id"] == first["body"]["id"]   # a change since the run
    load_path(f, "P", HR)
    profile(f)
    assert f.get("/api/setup/settings").json() == held
    assert f.get("/api/setup/filters").json()["rows"][0]["Column"] == "department"
    after = f.call("state").json()
    assert after["settings"] == before["settings"] and after["settings"]["display_rows"] == page["display_rows"] == 500
    assert after["stale"] is True                                # a stale result stays stale
    assert run(f)["body"]["id"] == first["body"]["id"]           # and it is the same run


def test_profiling_a_database_table(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    P = fetch_and_load(f, "P", "SAMPLE", "payroll.employees")["side"]
    assert P["loaded"] and P["is_database"] and P["rows"] == 2985
    assert P["name"] == "SAMPLE" and P["origin"].endswith("payroll.employees")
    by = {r["Column"]: r for r in rows(profile(f)["stats"])}
    # every column is VARCHAR in the database: the values decide - a number with thousands
    # separators, a date, Y/N - and the rest stays text
    assert {c: r["Type"] for c, r in by.items()} == {
        "EmployeeId": "text", "FullName": "text", "Dept": "text", "Salary": "number",
        "HireDate": "date", "IsActive": "boolean", "CostCenter": "text"}
    assert by["Salary"]["Mean"] not in ("", None) and by["IsActive"]["Distinct"] == 2
    view = f.call("profile_defaults").json()
    assert view["save_folder"].startswith(os.environ["COMPARE_OUT_DIR"])
    entries = f.get("/api/log").json()["entries"]
    assert [e["kind"] for e in entries[:3]] == ["Profile notes", "Profile", "Fetch"]      # newest first
    assert next(e for e in entries if e["kind"] == "Profile")["label"].startswith("Profile ready - key: EmployeeId in ")
    no_secret(f, tmp_path / "work")


# ---- keys, configs, connections --------------------------------------------------------------
def test_auto_fixes_a_key_written_differently(monkeypatch, tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("emp_code,ref,salary\n" + "".join(f"AB {i},R-{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    b.write_text("emp_code,ref,salary\n" + "".join(f"AB{i},{i:03d}x,{i * 10}\n" for i in range(1, 41)))
    f = boot(monkeypatch, tmp_path)
    _pair(f, a, b)
    auto(f)
    assert _specs(f)["emp_code"]["a_steps"] == [{"op": "remove spaces", "params": {}}]
    formats = f.call("keys").json()["formats"]
    assert any("emp_code: the two sides write the key differently" in x["text"] and "Applied" in x["text"]
               and x["tone"] == "success" for x in formats), formats
    assert any("ref: " in x["text"] and "Suggested" in x["text"] and x["apply"] is not None for x in formats), formats


def test_a_saved_config_runs_again_to_the_same_counts(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f, A="HR", B="Payroll")
    first = auto(f)
    conf_path = first["folder"] / "HR_compare_Payroll__config.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    assert conf["sides"]["A"]["name"] == "HR" and FAKE_PW not in conf_path.read_text(encoding="utf-8")
    fresh = boot(monkeypatch, tmp_path)                           # a new browser: a new workspace
    r = fresh.call("config", {"path": str(conf_path)})
    assert r.status_code == 200, r.text
    assert wait(fresh, r.json())["state"] == "done"
    settle(fresh)
    boxes = fresh.get("/api/sources").json()["config"]["boxes"]
    assert boxes["A"]["name"] == "HR" and boxes["B"]["path"] == str(PAY)
    again = run(fresh)
    assert again["pair"] == "HR_compare_Payroll" and again["counts"] == first["counts"]
    assert again["keys"] == first["keys"]
    no_secret(fresh, again["folder"])


def test_a_folder_pick_is_kept_in_the_config(monkeypatch, tmp_path):
    from tablecmp import connections as cx
    root = tmp_path / "exports"
    (root / "sub").mkdir(parents=True)
    shutil.copy(HR, root / "hr.csv")
    shutil.copy(PAY, root / "sub" / "payroll.csv")
    f = boot(monkeypatch, tmp_path)
    cx.save(cx.Connection(name="DATA", kind="folder", host=str(root)))
    assert [x["name"] for x in f.get("/api/sources/folders").json()] == ["DATA"]
    assert f.get("/api/sources/folders/DATA/files").json()["files"] == ["hr.csv", "sub/payroll.csv"]
    for tag, name, file in (("A", "HR", "hr.csv"), ("B", "Payroll", "sub/payroll.csv")):
        r = f.send("POST", f"/api/sources/{tag}/load", {"how": "path", "folder": "DATA", "file": file, "name": name})
        assert r.status_code == 200, r.text
    assert f.ws().data["panels"]["A"].side.folder == "DATA"
    assert f.ws().data["panels"]["B"].side.csv_path == str(root / "sub" / "payroll.csv")
    # the database list never offers a folder
    assert all(c["name"] != "DATA" for c in f.get("/api/connections").json() if not c["is_folder"])
    first = auto(f)
    conf_path = first["folder"] / "HR_compare_Payroll__config.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    assert (conf["sides"]["B"]["folder"], conf["sides"]["B"]["file"]) == ("DATA", "sub/payroll.csv")
    fresh = boot(monkeypatch, tmp_path)                           # same connections file: DATA is still saved
    assert wait(fresh, fresh.call("config", {"path": str(conf_path)}).json())["state"] == "done"
    settle(fresh)
    boxes = fresh.get("/api/sources").json()["config"]["boxes"]
    assert (boxes["B"]["folder"], boxes["B"]["file"]) == ("DATA", "sub/payroll.csv")
    assert run(fresh)["counts"] == first["counts"]


def test_an_imported_folder_is_a_folder_not_a_database(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    text = (f"connections:\n"
            f"  - {{name: PG, kind: postgresql, host: h, user: u, password: {FAKE_PW}}}\n"
            f"  - {{name: SNOW, kind: snowflake, account: acc, user: u, password: '${{SNOW_PW}}'}}\n"
            f"  - {{name: DATA, kind: folder, path: '{tmp_path.as_posix()}'}}\n")
    r = f.send("POST", "/api/connections/import", {"text": text, "filename": "team.yml", "keep_passwords": False})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in f.get("/api/sources/folders").json()] == ["DATA"]
    dbs = {c["name"] for c in f.get("/api/connections").json() if not c["is_folder"]}
    assert {"PG", "SNOW", "SAMPLE"} <= dbs and "DATA" not in dbs
    raw = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert FAKE_PW not in raw and "${SNOW_PW}" in raw
    no_secret(f)


# ---- the Log, the results, the downloads -----------------------------------------------------
def test_auto_and_compare_land_in_the_log(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f)
    auto(f)
    log = list(reversed(f.get("/api/log").json()["entries"]))     # oldest first, as the Streamlit log was
    kinds = [e["kind"] for e in log]
    assert kinds.index("Auto") < kinds.index("Auto decisions") < kinds.index("Compare") == len(log) - 1
    assert all(re.match(r"^\d\d:\d\d:\d\d$", e["at"]) for e in log), [e["at"] for e in log]
    a, decided, compared = (next(e for e in log if e["kind"] == k) for k in ("Auto", "Auto decisions", "Compare"))
    assert a["state"] == "done" and a["seconds"] > 0 and a["lines"]
    assert a["label"].startswith("Worked out in ") and "key: emp_id" in a["label"]
    assert decided["state"] == "done" and decided["seconds"] is None
    assert decided["lines"] == f.ws().data["auto_notes"] and len(decided["lines"]) > 0
    assert decided["label"] == f"{len(decided['lines'])} decisions - every one a cell in the column table"
    assert compared["state"] == "done" and compared["seconds"] > 0 and compared["lines"]
    assert compared["label"].startswith("Compared in ") and compared["label"].endswith("s")
    assert f.ws().last_run["Compare"]["id"] == compared["id"]       # the disc on the Compare page
    # Compare again, then Clear: the log is empty and the disc goes with it
    compare(f)
    assert [e["kind"] for e in f.get("/api/log").json()["entries"]].count("Compare") == 2
    assert f.send("DELETE", "/api/log").json()["entries"] == []
    assert not f.ws().last_run


def test_the_summary_ledger_starts_with_the_key(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f)
    auto(f)
    s = f.call("summary").json()
    roles = [r[s["ledger"]["columns"].index("Role")] for r in s["ledger"]["rows"]]
    assert roles[0] == "key" and roles[-1].startswith("only in ")
    assert s["tones"][0] == "pos" and s["tones"][-1] == "neg" and "compared" in roles


def test_downloads_and_saves(monkeypatch, tmp_path):
    """What test_web_downloads.py leaves out: the zip beside the run folder, a save that holds
    exactly the run's files, the default folder, and what a display-rows change does."""
    f = boot(monkeypatch, tmp_path)
    _pair(f)
    res = auto(f)
    folder, pair, rid = res["folder"], res["pair"], res["body"]["id"]
    out = tmp_path / "out"
    assert (folder / f"{pair}__report.html").exists() and not (folder / f"{pair}__paired.csv").exists()
    view = f.call("files").json()
    assert view["paired"] is False and view["zip"] is None and view["save_folder"] == str(out / f"{pair}__{rid}")
    assert "Paired rows" not in [x["label"] for x in view["files"]]
    z = f.call("zip").json()["zip"]
    assert z["name"] == f"{pair}__{rid}.zip" and (folder.parent / z["name"]).is_file()
    with zipfile.ZipFile(folder.parent / z["name"]) as zf:
        names = set(zf.namelist())
    for suffix in ("summary.json", "summary.csv", "columns.csv", "cell_diffs.csv", "left_only.csv",
                   "right_only.csv", "paired.csv", "report.html", "diff.html"):
        assert f"{pair}__{suffix}" in names, suffix
    r = f.call("save", {"what": "all", "folder": view["save_folder"]})
    assert r.status_code == 200, r.text
    saved = out / f"{pair}__{rid}"
    on_disk = {p.name for p in saved.iterdir()}
    expect = {p.name for p in f.ws().data["result"]["files"].values() if p.exists()}
    assert on_disk == expect and r.json()["text"].startswith(f"Saved {len(expect)} files to")
    # Rows to display is display-only: the report follows it, the run is not stale
    f.call("page_settings", {"display_rows": 500})
    assert f.call("state").json()["stale"] is False
    assert "first 500" in f.call("columns_view").json()["rows"]["title"]
    # a second run gets its own default folder
    second = compare(f)
    assert second["body"]["id"] != rid
    assert f.call("files").json()["save_folder"] == str(out / f"{pair}__{second['body']['id']}")
    assert not folder.exists() and not (folder.parent / z["name"]).exists()   # the old run and its zip are gone
    no_secret(f, saved)


def test_filters_refuse_in_a_sentence_and_filter_when_right(monkeypatch, tmp_path):
    f = boot(monkeypatch, tmp_path)
    _pair(f)
    first = auto(f)

    def row(col, op, val, where="Both", kind="auto"):
        return {"Apply to": where, "Column": col, "Operator": op, "Value": val, "Type": kind}
    bad = f.call("filters", {"rows": [row("salary", "between", "3000", kind="number")]})
    assert "between" in bad.json()["error"]
    assert "between" in f.call("state").json()["filter_error"]
    refused = f.call("compare")
    assert refused.status_code == 400 and "between" in refused.json()["detail"]
    assert run(f)["body"]["id"] == first["body"]["id"]                       # nothing ran
    f.call("filters", {"rows": [row("active", "=", "True", where="Left")]})
    new = compare(f)
    assert new["body"]["id"] != first["body"]["id"]
    js = _summary(new)
    assert js["settings"]["left_filters"] == {"active": {"eq": "true"}}
    assert js["result"]["rows_left"] == 2548 and js["result"]["rows_right"] == js["result"]["rows_right_read"] == 2985
    date = f.call("filters", {"rows": [row("hire_date", ">=", "not-a-date", kind="date")]}).json()
    assert date["error"] == "filter on 'hire_date': 'not-a-date' is not a date"
    refused = f.call("compare")
    assert refused.status_code == 400 and refused.json()["detail"] == date["error"]
    assert run(f)["body"]["id"] == new["body"]["id"]


# ---- the column table ------------------------------------------------------------------------
def test_app_runs_with_a_column_paired_twice_over_http(monkeypatch, tmp_path):
    """The same mapping through the page: the table takes it, the setup card says name is used
    twice, Compare gives the counts, and Reset to name matches still undoes it."""
    f = boot(monkeypatch, tmp_path)
    _pair(f, HR, DIR, A="HR", B="Directory")
    by_name = _pairs(f.call("columns").json())
    view = _map(f, MAPPING)
    assert _pairs(view) == [(c["a"], c["b"]) for c in MAPPING["columns"]]
    assert "name used 2 times on the Directory" in " ".join(x["html"] for x in view["card"])   # the setup card
    res = compare(f)
    r = _summary(res)["result"]
    assert (r["matched_rows"], r["only_left"], r["only_right"]) == (2970, 30, 20)
    assert r["diffs_by_column"].get("first_name", 0) == 0 and r["diffs_by_column"].get("last_name", 0) == 0
    sheet = (res["folder"] / "HR_compare_Directory__columns.csv").read_text(encoding="utf-8")
    assert "first_name,first_name,name," in sheet and "last_name,last_name,name," in sheet
    reset = f.send("POST", "/api/setup/reset").json()
    assert _pairs(reset) == by_name


def test_case_cell_beats_the_switch_over_http(monkeypatch, tmp_path):
    """A small pair whose Right lower-cases every city and one code: the Case cell on city
    decides for city on its own, whatever the Ignore case in values switch says, and the
    run's rules, report and column sheet say so."""
    (tmp_path / "left.csv").write_text("id,city,code\n1,Paris,A1\n2,London,B2\n3,Rome,C3\n", encoding="utf-8")
    (tmp_path / "right.csv").write_text("id,city,code\n1,paris,A1\n2,london,b2\n3,rome,C3\n", encoding="utf-8")
    f = boot(monkeypatch, tmp_path)
    _pair(f, tmp_path / "left.csv", tmp_path / "right.csv")

    def go(case: str, switch: bool) -> dict:
        cols = [{"a": "id", "b": "id", "name": "id", "type": "text", "key": True, "compare": False},
                {"a": "city", "b": "city", "name": "city", "type": "text", "compare": True, "case": case},
                {"a": "code", "b": "code", "name": "code", "type": "text", "compare": True}]
        assert f.call("mapping", {"text": json.dumps({"columns": cols})}).status_code == 200
        assert f.call("settings", {"ignore_case": switch}).status_code == 200
        res = compare(f)
        assert not _summary(res)["result"]["error"]
        return res

    def diffs(res) -> tuple[int, int]:
        d = _summary(res)["result"]["diffs_by_column"]
        return d.get("city", 0), d.get("code", 0)

    def rules(res) -> dict:
        return _summary(res)["settings"]["column_rules"]

    text = {"type": "string", "tolerance": 0.0}        # a text pair: never a number, no Case of its own
    res = go("", False)                                 # blank follows the switch: case matters
    assert diffs(res) == (3, 1) and rules(res) == {"city": text, "code": text}
    assert "case matters · tolerance" in _report(f)
    res = go("ignore", False)                           # the cell alone ignores case on city
    assert diffs(res) == (0, 1)
    assert rules(res) == {"city": {**text, "ignore_case": True}, "code": text}
    report = _report(f)
    assert "case matters · <b>ignored on: city</b>" in report
    assert "<code>city</code> text · ignore case" in report
    sheet = (res["folder"] / f"{res['pair']}__columns.csv").read_text(encoding="utf-8")
    assert "city,city,city,compared,text · ignore case,file,3,0," in sheet    # matched_by: the mapping file
    assert "code,code,code,compared,text,file,2,1," in sheet
    assert any("text · ignore case" in x["html"] for x in f.call("columns").json()["card"])   # the card's Read as row
    res = go("", True)                                  # the switch alone: case ignored everywhere
    assert diffs(res) == (0, 0) and rules(res) == {"city": text, "code": text}
    assert "<b>case ignored</b> · tolerance" in _report(f)
    res = go("exact", True)                             # the cell beats the switch on city
    assert diffs(res) == (3, 0)
    assert rules(res) == {"city": {**text, "ignore_case": False}, "code": text}
    assert "<b>case ignored</b> · <b>exact on: city</b>" in _report(f)
    res = go("ignore", True)                            # the cell agrees with the switch: nothing to add
    assert diffs(res) == (0, 0) and "on: city" not in _report(f)


def test_numeric_tolerance_leaves_text_pairs_alone_over_http(monkeypatch, tmp_path):
    """A text code 001 against 1 and a zip 02134 against 2134 stay different with a numeric
    tolerance above 0: the tolerance is for number pairs only, and every compared pair tells
    the engine so in its own rule."""
    (tmp_path / "left.csv").write_text("id,code,zip,amount\n1,001,02134,10.001\n2,B2,00501,20\n", encoding="utf-8")
    (tmp_path / "right.csv").write_text("id,code,zip,amount\n1,1,2134,10.002\n2,B2,501,20\n", encoding="utf-8")
    f = boot(monkeypatch, tmp_path)
    _pair(f, tmp_path / "left.csv", tmp_path / "right.csv")
    cols = [{"a": "id", "b": "id", "name": "id", "type": "text", "key": True, "compare": False},
            {"a": "code", "b": "code", "name": "code", "type": "text", "compare": True},
            {"a": "zip", "b": "zip", "name": "zip", "type": "text", "compare": True, "case": "ignore"},
            {"a": "amount", "b": "amount", "name": "amount", "type": "number", "compare": True}]
    assert f.call("mapping", {"text": json.dumps({"columns": cols})}).status_code == 200
    assert f.call("settings", {"tolerance": 0.01}).status_code == 200
    res = compare(f)
    r = _summary(res)["result"]
    assert not r["error"], r["error"]
    by = {c: r["diffs_by_column"].get(c, 0) for c in ("code", "zip", "amount")}
    assert by == {"code": 1, "zip": 2, "amount": 0}          # amount's 0.001 gap is inside the tolerance
    assert _summary(res)["settings"]["column_rules"] == {
        "code": {"type": "string", "tolerance": 0.0},
        "zip": {"type": "string", "tolerance": 0.0, "ignore_case": True},
        "amount": {"type": "number"}}


def test_app_flow_with_every_item_together_over_http(monkeypatch, tmp_path):
    """One flow across the sweep: named sides, Auto, the split mapping with Case ignore on
    department and a global tolerance, Compare, the looks-like cells, matched_by in columns.csv,
    the case choice in summary.json, and Save everything under the pair name."""
    f = boot(monkeypatch, tmp_path)
    _pair(f, HR, DIR, A="HR", B="Directory")
    assert auto(f)["pair"] == "HR_compare_Directory"
    _map(f, MAPPING, department="ignore")
    assert f.call("settings", {"tolerance": 0.01}).status_code == 200
    res = compare(f)
    r = _summary(res)["result"]
    assert not r["error"] and res["pair"] == "HR_compare_Directory"
    assert (r["matched_rows"], r["only_left"], r["only_right"]) == (2970, 30, 20)
    assert all(r["diffs_by_column"].get(c, 0) == 0 for c in ("first_name", "last_name", "hire_date"))
    by = {x["Common name"]: x for x in f.call("columns").json()["rows"]}
    assert by["hire_date"]["B looks like"].endswith("%d-%b-%Y") and by["hire_date"]["A looks like"] == ""
    assert by["department"]["Case"] == "ignore" and by["last_name"]["B column"] == "name"
    folder, pair = res["folder"], res["pair"]
    sheet = (folder / f"{pair}__columns.csv").read_text(encoding="utf-8").splitlines()
    assert sheet[0].split(",")[:6] == ["column", "name_a", "name_b", "role", "read_as", "matched_by"]
    assert "department,department,dept,compared,text · ignore case,file," in "\n".join(sheet)
    settings = _summary(res)["settings"]
    assert settings["tolerance"] == 0.01
    assert settings["column_rules"]["department"] == {"type": "string", "tolerance": 0.0, "ignore_case": True}
    assert next(s for s in settings["specs"] if s["canon"] == "department")["case"] == "ignore"
    assert "ignored on: department" in _report(f)
    target = tmp_path / "out" / f"{pair}__{res['body']['id']}"
    assert f.call("save", {"what": "all", "folder": str(target)}).status_code == 200
    saved = sorted((tmp_path / "out").glob(f"{pair}__*"))
    assert len(saved) == 1 and (saved[0] / f"{pair}__summary.json").exists()


def test_page_column_table_shows_roles_and_chips_over_http(monkeypatch, tmp_path):
    """After Auto on the sample pair the column table has a green chip for the key and a red
    one for the column only Payroll has - and nothing to confirm or edit."""
    f = boot(monkeypatch, tmp_path)
    _pair(f, B="Payroll")
    auto(f)
    v = f.call("columns").json()
    assert v["pairs"] == 6 and v["names"] == ["Left", "Payroll"]
    chips = {(c["text"], c["cls"]) for c in v["chips"]}
    assert ("emp_id", "key") in chips and ("CostCenter · only in Payroll", "off") in chips
    assert "confirmed" not in v and not [r for r in v["rows"] if r["Role"] == ""]
    assert v["rows"][0]["Role"] == "key" and v["rows"][0]["tone"] == "pos"


def test_the_column_table_shows_the_cells_and_leaves_the_type_alone_over_http(monkeypatch, tmp_path):
    """Both files loaded: the table has the two columns filled from a sample, the Type is what
    the detected types give, and the card lists the one suggestion not taken."""
    f = boot(monkeypatch, tmp_path)
    _pair(f, B="Right")
    v = f.call("columns").json()
    by_b = {r["B column"]: r for r in v["rows"] if r["B column"]}
    assert not any(r["A looks like"] for r in v["rows"])                     # HR is typed already
    assert by_b["Salary"]["B looks like"] == "number · 12,686.95 has thousands separators"
    assert by_b["IsActive"]["B looks like"] == "boolean · Y/N"
    assert by_b["IsActive"]["Type"] == "text" and by_b["Salary"]["Type"] == "number"   # a hint, not applied
    card = " ".join(x["html"] for x in v["card"])
    assert "Right looks like boolean (Y/N) - read as text" in card
    assert "looks like number" not in card                                   # Salary is read as number already
    again = f.call("columns").json()                                         # the sample is taken once per pair
    assert again["rev"] == v["rev"] and again["rows"] == v["rows"]
    assert {r["B column"]: r["Type"] for r in again["rows"] if r["B column"]}["IsActive"] == "text"
