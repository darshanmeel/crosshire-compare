"""DuckDB's memory and spill-to-disk limits: 2GB / 20GB by default, set from the page and kept
in the work folder, and fixed by COMPARE_DUCKDB_MEMORY / COMPARE_DUCKDB_DISK when those are set."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tablecmp.sql import memory_limit_bytes, scratch, size_bytes
from tablecmp.web.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPARE_WORK_DIR", str(tmp_path / "w"))
    monkeypatch.delenv("COMPARE_DUCKDB_MEMORY", raising=False)
    monkeypatch.delenv("COMPARE_DUCKDB_DISK", raising=False)
    return TestClient(create_app(), headers={"X-Compare": "1"})


def _disk(con) -> int:
    text = con.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]
    return size_bytes(text)


def test_defaults_are_two_gigabytes_of_memory_and_twenty_of_disk(client):
    got = client.get("/api/engine").json()
    assert (got["memory"], got["memory_from"], got["disk"], got["disk_from"]) == ("2GB", "default", "20GB", "default")
    assert got["machine_memory"] > 0
    con = scratch()
    assert 1_800_000_000 < memory_limit_bytes(con) <= 2_000_000_000
    assert 18 * 2 ** 30 <= _disk(con) <= 20_000_000_000


def test_the_page_sets_the_limits_for_the_next_connection(client):
    r = client.put("/api/engine", json={"memory": "1GB", "disk": "5GB"})
    assert r.status_code == 200 and r.json()["memory_from"] == "saved"
    con = scratch()
    assert 900_000_000 < memory_limit_bytes(con) <= 1_000_000_000
    assert 4 * 2 ** 30 <= _disk(con) <= 5_000_000_000
    assert client.get("/api/engine").json()["disk"] == "5GB"


@pytest.mark.parametrize("memory,disk,says", [("banana", "5GB", "not a size"), ("100MB", "5GB", "at least 256MB"),
                                              ("1GB", "100MB", "at least 1GB"), ("100000GB", "5GB", "at most")])
def test_a_bad_limit_is_refused_and_nothing_changes(client, memory, disk, says):
    r = client.put("/api/engine", json={"memory": memory, "disk": disk})
    assert r.status_code == 422 and says in r.text
    assert client.get("/api/engine").json()["memory_from"] == "default"


def test_the_environment_wins_over_the_page(client, monkeypatch):
    client.put("/api/engine", json={"memory": "1GB", "disk": "5GB"})
    monkeypatch.setenv("COMPARE_DUCKDB_MEMORY", "1.5GB")
    got = client.get("/api/engine").json()
    assert (got["memory"], got["memory_from"], got["disk_from"]) == ("1.5GB", "env", "saved")


def test_a_size_is_kept_as_duckdb_reads_it(client):
    assert client.put("/api/engine", json={"memory": "1 000MB", "disk": "5GB"}).status_code == 422
    r = client.put("/api/engine", json={"memory": "1.5 GiB", "disk": "5GB"})
    assert r.status_code == 200 and r.json()["memory"] == "1.5GiB"
    scratch().close()                   # DuckDB takes what was kept


def test_a_bad_value_in_the_file_falls_back_to_the_default(client, tmp_path):
    client.put("/api/engine", json={"memory": "1GB", "disk": "5GB"})
    f = tmp_path / "w" / "engine.json"
    f.write_text('{"memory": "1 000MB", "disk": "5GB"}', encoding="utf-8")
    got = client.get("/api/engine").json()
    assert (got["memory_from"], got["disk_from"]) == ("default", "saved")
    scratch().close()


def test_a_limit_fixed_by_the_environment_is_not_checked_or_kept(client, monkeypatch, tmp_path):
    monkeypatch.setenv("COMPARE_DUCKDB_MEMORY", "4G")
    r = client.put("/api/engine", json={"memory": "4G", "disk": "30GB"})
    assert r.status_code == 200 and r.json()["disk"] == "30GB"
    monkeypatch.delenv("COMPARE_DUCKDB_MEMORY")
    assert client.get("/api/engine").json()["memory_from"] == "default"
