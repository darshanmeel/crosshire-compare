"""What a run leaves behind: one folder, a fixed set of files, one name.

<pair>__<run_id>/ with <pair>__summary.json (the whole run for a script), __summary.csv
(one row, fixed columns), __columns.csv, __profile.csv when a profile ran, the engine's
__cell_diffs / __left_only / __right_only / __diff.html, __paired.csv, __report.html, the same
tables as Parquet on a switch, and a zip of the lot. <pair> is <left>_compare_<right>, from the
side names - the Name box, else a database side's connection, else Left / Right.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from .sources import Side, out_dir, slug, work_dir
from .sql import lit

SCHEMA_VERSION = 1
SUMMARY_COLUMNS = ["schema_version", "run_id", "started_at", "pair", "left", "right", "mode", "keys",
                   "rows_left_read", "rows_right_read", "rows_left", "rows_right", "matched_rows",
                   "only_left", "only_right", "diff_rows", "cell_diffs", "duplicate_keys_left",
                   "duplicate_keys_right", "status", "tone", "seconds", "error"]
SETTINGS_KEYS = ["mode", "keys", "compare_columns", "only_a", "only_b", "trim", "empty_as_null",
                 "ignore_case", "tolerance", "column_rules", "filters", "left_filters", "right_filters",
                 "null_tokens", "specs", "table_formats"]
TABLES = ["cell_diffs", "left_only", "right_only", "paired", "columns", "profile"]
COLUMNS_HEADER = ["column", "name_a", "name_b", "role", "read_as", "matched_by", "matched", "mismatched",
                  "match_pct", "values_only_a", "values_only_b"]
PROFILE_HEADER = ["column", "side", "rows", "nulls", "null_pct", "distinct", "distinct_pct", "min", "max",
                  "mean", "avg_length"]
# what the sweep may remove from the work folder: run folders and zips (<pair>__<run_id>),
# uploads and snapshots (cmp_*), database fetches (fetch_*), key-search scratch files (ucc_*)
SWEEP_PREFIXES = ("cmp_", "fetch_", "ucc_")


@dataclass
class Verdict:
    status: str      # identical | differences | error
    tone: str        # ok | warn | bad
    word: str        # Identical | Small differences | Differences | Error
    rule: str = ("rows that differ under 5% of matched rows and one-sided rows no more than "
                 "matched rows count as small differences")


def verdict_of(res, mode: str = "key") -> Verdict:
    if getattr(res, "error", ""):
        return Verdict("error", "bad", "Error")
    orphans = res.only_left + res.only_right
    if not res.diff_rows and not orphans:
        return Verdict("identical", "ok", "Identical")
    pct = res.diff_rows / res.matched_rows * 100 if res.matched_rows else 100.0
    if pct < 5 and orphans <= res.matched_rows:
        return Verdict("differences", "warn", "Small differences")
    return Verdict("differences", "bad", "Differences")


def pair_name(name_a: str, name_b: str) -> str:
    """<left>_compare_<right> from the two side names, slugged; a blank side falls back to Left / Right."""
    return f"{slug(name_a) or 'Left'}_compare_{slug(name_b) or 'Right'}"


def run_id(started: datetime | None = None) -> str:
    return (started or datetime.now()).strftime("%Y%m%d-%H%M%S")


def table_formats(choice: str | None = None) -> set[str]:
    """csv always; parquet when asked for - by the Downloads radio or COMPARE_TABLE_FORMATS."""
    if choice:
        return {"csv", "parquet"} if choice == "both" else {choice}
    env = os.environ.get("COMPARE_TABLE_FORMATS", "csv")
    got = {p.strip().lower() for p in env.split(",") if p.strip()}
    return got or {"csv"}


def _under(path: str, root: Path) -> bool:
    try:
        p, r = Path(path).resolve(), root.resolve()
    except OSError:
        return False
    return p == r or r in p.parents


def _source_block(s: Side, rows_read: int) -> dict:
    """One side for summary.json - never a URI or a password, only the connection's name."""
    path = s.csv_path if s.csv_path and not s.is_database and not _under(s.csv_path, work_dir()) else ""
    return {"name": s.name, "kind": "database" if s.is_database else s.kind, "database": s.database,
            "connection": s.conn, "origin": s.origin, "label": s.label, "path": path, "sql": s.query,
            "fetched_at": s.fetched_at, "cap": s.cap, "capped": s.capped, "rows": rows_read,
            "cut": s.cut, "delimiter": s.delimiter, "header": s.header, "snapshot": bool(s.cache_path),
            "columns": list(s.schema)}


def columns_frame(run: dict) -> pd.DataFrame:
    """The column sheet with machine headers - the report and the UI rename for display.
    matched_by is how each pair was made, from the column table (name, similar name, data,
    guess - check, you, file); blank on a one-sided column."""
    from .compare import column_ledger
    df = column_ledger(run, "A", "B").rename(columns={
        "Column": "column", "A": "name_a", "B": "name_b", "Role": "role", "Read as": "read_as",
        "Matched": "matched", "Mismatched": "mismatched", "Match %": "match_pct",
        "Values only in A": "values_only_a", "Values only in B": "values_only_b"})
    how = run["cfg"].get("matched_by") or {}
    paired = (df["name_a"] != "—") & (df["name_b"] != "—")
    df["matched_by"] = [how.get(c) if p else None for c, p in zip(df["column"], paired)]
    for c in COLUMNS_HEADER:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS_HEADER].copy()
    for c in ("name_a", "name_b"):                  # the ledger shows a dash for "no such column"
        df[c] = df[c].where(df[c] != "—", None)
    for c in ("matched", "mismatched", "values_only_a", "values_only_b"):   # counts stay whole, blanks blank
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def profile_frame(prof: dict, name_a: str, name_b: str) -> pd.DataFrame:
    rows = []
    for which, name in (("A", name_a), ("B", name_b)):
        stats = (prof.get("stats") or {}).get(which)
        if stats is None:
            continue
        for _, r in stats.iterrows():
            rows.append({"column": r["Column"], "side": name, "rows": r["Rows"], "nulls": r["Nulls"],
                         "null_pct": r["Null %"], "distinct": r["Distinct"], "distinct_pct": r["Distinct %"],
                         "min": r["Min"], "max": r["Max"], "mean": r["Mean"], "avg_length": r["Avg length"]})
    return pd.DataFrame(rows, columns=PROFILE_HEADER)


def _rows_in(p: Path) -> int | None:
    if p.suffix == ".csv":
        with open(p, "rb") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    if p.suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
            return int(pq.ParquetFile(p).metadata.num_rows)
        except Exception:                        # noqa: BLE001 - fall back to DuckDB
            return int(duckdb.connect().execute(
                f"SELECT count(*) FROM read_parquet({lit(str(p))})").fetchone()[0])
    return None


def files_listing(run: dict) -> list[dict]:
    """Every file in the run folder but summary.json itself: name, format, bytes, rows."""
    pair = run["pair"]
    return [{"name": p.name, "format": p.suffix.lstrip("."), "bytes": p.stat().st_size, "rows": _rows_in(p)}
            for p in sorted(Path(run["folder"]).iterdir())
            if p.is_file() and p.name != f"{pair}__summary.json"]


def summary_payload(run: dict, A: Side, B: Side, name_a: str, name_b: str,
                    notes: list[str] | None = None) -> dict:
    res, cfg = run["result"], run["cfg"]
    from .theme import APP_NAME
    verdict = run.get("verdict") or verdict_of(res, run.get("mode", cfg.get("mode", "key")))
    return {"schema_version": SCHEMA_VERSION, "app": APP_NAME, "engine": "csvdiff",
            "duckdb_version": duckdb.__version__, "run_id": run["run_id"], "started_at": run["started_at"],
            "seconds": round(run["seconds"], 3), "pair": run["pair"],
            "sources": {"A": {**_source_block(A, res.rows_left_read), "name": name_a},
                        "B": {**_source_block(B, res.rows_right_read), "name": name_b}},
            "settings": {k: cfg.get(k) for k in SETTINGS_KEYS if k in cfg},
            "result": asdict(res), "verdict": asdict(verdict), "notes": list(notes or []),
            "files": files_listing(run)}


def _refresh_files(run: dict) -> None:
    folder = Path(run["folder"])
    run["files"] = {p.name: p for p in folder.glob("*") if p.is_file()}


def write_summary(run: dict, A: Side, B: Side, name_a: str, name_b: str, notes=None, profile=None) -> None:
    """columns.csv, profile.csv when a profile ran, summary.csv, then summary.json listing them all."""
    folder, pair = Path(run["folder"]), run["pair"]
    res = run["result"]
    v = run.get("verdict") or verdict_of(res, run["mode"])
    columns_frame(run).to_csv(folder / f"{pair}__columns.csv", index=False, lineterminator="\n")
    if profile:
        profile_frame(profile, name_a, name_b).to_csv(folder / f"{pair}__profile.csv", index=False,
                                                       lineterminator="\n")
    row = {"schema_version": SCHEMA_VERSION, "run_id": run["run_id"], "started_at": run["started_at"],
           "pair": pair, "left": name_a, "right": name_b, "mode": run["mode"], "keys": "|".join(res.keys),
           **{k: getattr(res, k) for k in ("rows_left_read", "rows_right_read", "rows_left", "rows_right",
                                          "matched_rows", "only_left", "only_right", "diff_rows", "cell_diffs",
                                          "duplicate_keys_left", "duplicate_keys_right")},
           "status": v.status, "tone": v.tone, "seconds": round(run["seconds"], 3), "error": res.error}
    with open(folder / f"{pair}__summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerow(row)
    payload = summary_payload(run, A, B, name_a, name_b, notes)
    (folder / f"{pair}__summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n",
                                                   encoding="utf-8", newline="\n")
    _refresh_files(run)


def _relist_summary(run: dict) -> None:
    """After new files land in the folder, the file list inside summary.json follows."""
    path = Path(run["folder"]) / f"{run['pair']}__summary.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    payload["files"] = files_listing(run)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")


def write_parquet_copies(run: dict) -> list[Path]:
    """Every CSV table of the run as Parquet next to it, through DuckDB."""
    folder, pair = Path(run["folder"]), run["pair"]
    con = duckdb.connect()
    written = []
    for t in TABLES:
        src = folder / f"{pair}__{t}.csv"
        if not src.exists():
            continue
        dst = folder / f"{pair}__{t}.parquet"
        con.execute(f"COPY (SELECT * FROM read_csv({lit(str(src))}, all_varchar=true, header=true)) "
                    f"TO {lit(str(dst))} (FORMAT PARQUET)")
        written.append(dst)
    con.close()
    _refresh_files(run)
    _relist_summary(run)
    run.pop("zip", None)                         # the zip, if one was built, is stale now
    return written


def zip_run(run: dict) -> Path:
    """<pair>__<run_id>.zip beside the run folder, holding everything in it."""
    folder = Path(run["folder"])
    target = folder.parent / f"{run['pair']}__{run['run_id']}"
    z = Path(shutil.make_archive(str(target), "zip", root_dir=folder))
    run["zip"] = z
    return z


def default_save_folder(run: dict, base: Path) -> Path:
    root = out_dir() or base
    return root / f"{run['pair']}__{run['run_id']}"


def save_target(folder_text: str, run: dict) -> Path:
    """Where a save may go: anywhere, or only under COMPARE_OUT_DIR when it is set."""
    root = out_dir()
    if root is None:
        return Path(folder_text).expanduser().resolve()
    root = root.resolve()
    p = Path(folder_text).expanduser()
    p = (p if p.is_absolute() else root / p).resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"Saves must stay under {root}")
    return p


def sweep_work_dir(keep_hours: float | None = None) -> int:
    """Remove run folders, zips, uploads, snapshots and fetches older than COMPARE_KEEP_HOURS (24)."""
    hours = keep_hours if keep_hours is not None else float(os.environ.get("COMPARE_KEEP_HOURS", "24") or 24)
    cutoff = time.time() - hours * 3600
    n = 0
    for p in work_dir().iterdir():
        if "__" not in p.name and not p.name.startswith(SWEEP_PREFIXES):
            continue
        try:
            if p.stat().st_mtime < cutoff:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
                n += 1
        except OSError:
            pass
    return n
