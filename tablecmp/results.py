"""The results of a run with no page attached - what the React server calls: the verdict's words, the run's key and compared columns, the report kept in step with the
rows shown, the run's files as Downloads lists them, the paired rows a save adds, where a save
goes and the save itself, and which column cards and buckets a run opens with."""
from __future__ import annotations

import math
import os
import shutil
import tempfile
from pathlib import Path

from .compare import bucket_columns, have_paired, paired_path, side_labels
from .outputs import drop_zip, save_target, verdict_of
from .report import build_report
from .sources import Side, work_dir

COLUMN_CARDS = 12       # compared columns opened without being asked for - the worst first
# what each file in the run folder is called on the Downloads tab, in the order it is listed
DOWNLOAD_LABELS = [("cell_diffs.csv", "Cell differences"), ("left_only.csv", "Rows only in {NA}"),
                   ("right_only.csv", "Rows only in {NB}"), ("paired.csv", "Paired rows"),
                   ("columns.csv", "Columns"), ("profile.csv", "Profile"), ("summary.csv", "Summary"),
                   ("summary.json", "Settings and result"), ("report.html", "Report"),
                   ("diff.html", "Engine report")]
MIME = {".csv": "text/csv", ".json": "application/json", ".html": "text/html",
        ".parquet": "application/vnd.apache.parquet", ".zip": "application/zip"}
GONE = ("The files of this run are gone - the work folder is swept after `COMPARE_KEEP_HOURS` (24). "
        "Press **Compare** to run it again.")
SAVE_BLANK = "Type a folder to save into."


def run_keys(run: dict) -> list[str]:
    return list(run["result"].keys or run["cfg"]["keys"]) if run["mode"] == "key" else []


def run_columns(run: dict) -> list[str]:
    return list(run["result"].columns_compared or run["cfg"]["compare_columns"])


def pct_text(part: int, whole: int) -> str:
    """`part` of `whole` as a percentage, two decimals - but never 0 or 100 when it is neither:
    6 rows of 629,424 read 0.001 and 99.999, with as many decimals as that takes (up to 6)."""
    if not whole:
        return "0.00"
    pct = part / whole * 100
    if not 0 < part < whole or 0.005 <= pct <= 99.995:
        return f"{pct:.2f}"
    gap = min(pct, 100 - pct)
    d = min(6, -math.floor(math.log10(gap)))
    f = 10 ** d
    v = math.ceil(pct * f) / f if pct < 50 else math.floor(pct * f) / f
    return f"{v:.{d}f}".rstrip("0")


def verdict_parts(run: dict, NA: str, NB: str) -> dict:
    """The banner above the results in pieces: the tone, the word, the sentence as (text, bold)
    segments, and when the run took place - one page draws HTML from them, the other JSX."""
    res = run["result"]
    keys = run_keys(run)
    pct = pct_text(res.diff_rows, res.matched_rows)
    v = run.get("verdict") or verdict_of(res, run["mode"])
    n = len(res.columns_compared)
    if run["mode"] == "hash":
        seg = [(f"{res.matched_rows:,}", True), (f" identical rows found by hashing {n} columns", False)]
    elif keys:
        seg = [(f"{res.matched_rows:,}", True), (" rows matched on ", False), (" + ".join(keys), True)]
    else:
        seg = [(f"{res.matched_rows:,}", True), (" rows paired by position", False)]
    seg += [(" · ", False), (str(n), True), (" columns compared · ", False)]
    if res.diff_rows:
        seg += [(f"{res.diff_rows:,}", True), (f" rows ({pct}%) differ in ", False),
                (f"{res.cell_diffs:,}", True), (" cells", False)]
    elif run["mode"] != "hash":
        seg += [("no differences", True), (" on the matched rows", False)]
    else:
        seg += [("identical rows are identical by construction", False)]
    seg += [(" · ", False), (f"{res.only_left:,}", True), (f" only in {NA} · ", False),
            (f"{res.only_right:,}", True), (f" only in {NB}", False)]
    return {"tone": v.tone, "word": v.word, "segments": seg, "when": f"{run['seconds']:.1f}s at {run['at']}"}


# ---- the report ------------------------------------------------------------------------
def report_key(run: dict, limit: int) -> tuple:
    return ("report", run["at"], limit)


def report_current(run: dict, limit: int) -> bool:
    """Whether the report held was built for this many rows shown."""
    return bool(run.get("_report")) and run.get("_report_key") == report_key(run, limit)


def ensure_report(run: dict, A: Side, B: Side, NA: str, NB: str, limit: int, profile: dict | None = None) -> str:
    """The report HTML for this run - the one built as the run finished, unless the rows shown
    changed since. Whatever the route, <pair>__report.html sits in the run folder and is listed
    in run["files"]."""
    path = Path(run["folder"]) / f"{run['pair']}__report.html"
    if not report_current(run, limit):
        run["_report"] = build_report(run, A, B, NA, NB, limit=min(limit, 2000),
                                      notes=run["cfg"].get("notes") or [], profile=profile)
        run["_report_key"] = report_key(run, limit)
        path.write_text(run["_report"], encoding="utf-8", newline="\n")
        drop_zip(run)                    # a zip made before holds the old report
    elif not path.exists():
        path.write_text(run["_report"], encoding="utf-8", newline="\n")
    run["files"][path.name] = path
    return run["_report"]


# ---- the run's files -------------------------------------------------------------------
def download_rows(run: dict, NA: str, NB: str) -> list[dict]:
    """Every file of the run that is on disk, in the Downloads order, with its label and size.
    The config is not among them - it has a row of its own."""
    name = run["pair"]
    named = [(f"{name}__{suffix}", label.format(NA=NA, NB=NB)) for suffix, label in DOWNLOAD_LABELS]
    named += [(p.name, f"{p.name[len(name) + 2:-len('.parquet')]} (Parquet)")
              for p in sorted(run["files"].values()) if p.suffix == ".parquet"]
    out = []
    for fname, label in named:
        p = run["files"].get(fname)
        if p is not None and p.exists():
            out.append({"name": fname, "label": label, "bytes": p.stat().st_size})
    return out


def config_path(run: dict) -> Path | None:
    p = run["files"].get(f"{run['pair']}__config.json")
    return p if p is not None and p.exists() else None


def engine_path(run: dict) -> Path | None:
    p = run["files"].get(f"{run['pair']}__diff.html")
    return p if p is not None and p.exists() else None


def engine_gone(run: dict) -> bool:
    """The engine's report was written, and is no longer on disk."""
    p = run["files"].get(f"{run['pair']}__diff.html")
    return p is not None and not p.exists()


def paired_first(run: dict) -> dict[str, Path]:
    """The paired rows, written now if they are not on disk - what a save of everything adds.
    The whole file list is returned, not the one name: writing the paired rows can write their
    Parquet copy too, and a save that missed it would copy a summary.json that lists it."""
    if have_paired(run):
        return {}
    if not paired_path(run):
        return {}
    return {p.name: p for p in run["files"].values() if p.exists()}


# ---- saves -----------------------------------------------------------------------------
def default_save_base(side: Side | None) -> str:
    """Next to the side's file when it was given as a path; otherwise the user's Downloads folder
    (an upload or a fetch sits in the temp or work folder - no place to save next to, the
    start-up sweep clears what is saved there)."""
    if side is not None and side.csv_path:
        folder = Path(side.csv_path).resolve().parent
        for bare in (Path(tempfile.gettempdir()).resolve(), work_dir().resolve()):
            if folder == bare or bare in folder.parents:
                break
        else:
            return str(folder)
    downloads = Path.home() / "Downloads"
    return str(downloads if downloads.exists() else Path.home())


def save_files(files: dict[str, bytes | Path], folder_text: str, run: dict) -> tuple[Path, list[str]]:
    """The files written - or copied, for a Path - into the folder typed, under COMPARE_OUT_DIR
    when it is set. Returns where they went and their names."""
    if not (folder_text or "").strip():
        raise ValueError(SAVE_BLANK)
    target = save_target(folder_text.strip().strip('"'), run)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not use the folder `{target}` - check the path and that you may write there.") from exc
    staged: list[tuple[str, Path]] = []        # every file written beside its place first, then moved in
    try:
        for fname, data in files.items():
            part = target / (fname + ".part")
            if isinstance(data, Path):
                shutil.copyfile(data, part)
            else:
                part.write_bytes(data)
            staged.append((fname, part))
    except OSError as exc:
        for _, part in staged:
            part.unlink(missing_ok=True)
        raise ValueError(f"Could not write {fname} - the folder may be full or read-only. Nothing was saved.") from exc
    written: list[str] = []
    for fname, part in staged:
        try:
            os.replace(part, target / fname)
        except OSError as exc:
            for _, rest in staged:
                rest.unlink(missing_ok=True)
            done = f" Saved before that: {', '.join(written)}." if written else " Nothing was saved."
            raise ValueError(f"Could not write {fname} - it may be open in another program.{done}") from exc
        written.append(fname)
    return target, written


def save_base_after(target: Path, run: dict) -> str:
    """The base the next default folder is built from: the parent of a per-run folder, else the folder."""
    return str(target.parent if target.name == f"{run['pair']}__{run['run_id']}" else target)


def saved_line(target: Path, written: list[str]) -> str:
    return (f"Saved {len(written)} file{'s' if len(written) != 1 else ''} to `{target}`: "
            + ", ".join(written))


# ---- what a run opens with -------------------------------------------------------------
def card_order(res, cols: list[str]) -> tuple[list[str], list[str], list[str]]:
    """The compared columns that differ (worst first), the cards opened without asking, and the rest."""
    differing = sorted([c for c in cols if res.diffs_by_column.get(c, 0)],
                       key=lambda c: (-res.diffs_by_column.get(c, 0), c))
    agreeing = sorted(c for c in cols if not res.diffs_by_column.get(c, 0))
    order = differing + agreeing
    shown = (differing or order)[:COLUMN_CARDS]
    return differing, shown, [c for c in order if c not in shown]


def bucket_list(res, keys: list[str], NA: str, NB: str) -> list[tuple[str, str]]:
    """The buckets of rows this run has, each with its label and count - two SAMPLEs told apart."""
    label_a, label_b = side_labels(NA, NB)
    out = []
    if res.matched_rows and keys:
        out.append(("matched", f"Keys matched ({res.matched_rows:,})"))
    if res.matched_rows > res.diff_rows and res.diff_rows and keys:     # with no differences it is "Keys matched" again
        out.append(("same", f"Matched and same ({res.matched_rows - res.diff_rows:,})"))
    if res.diff_rows and keys:
        out.append(("differ", f"Matched but different ({res.diff_rows:,})"))
    if res.only_left:
        out.append(("left", f"Only in {label_a} ({res.only_left:,})"))
    if res.only_right:
        out.append(("right", f"Only in {label_b} ({res.only_right:,})"))
    return out


def first_bucket(names: dict, want: str | None) -> str:
    """The bucket held when this run has it, else the differing rows, else the first."""
    if want in names:
        return want
    return "differ" if "differ" in names else next(iter(names))


BUCKET_SHOWN = 3                        # columns counted for a bucket besides the key, before any is asked for


def mismatched(run: dict, cols: list[str]) -> list[str]:
    """The columns of `cols` that differ on some paired row, the most differences first."""
    by = getattr(run["result"], "diffs_by_column", None) or {}
    return sorted((c for c in cols if by.get(c)), key=lambda c: -by[c])


def bucket_plan(run: dict, bucket: str, keys: list[str], cols: list[str],
                keys_apart: bool = False) -> tuple[dict, list[str], list[str]]:
    """For a bucket: the one-sided columns its rows carry (with their side), the columns counted
    without asking, and the others. Counted without asking: the key, then every column that differs
    (worst first) for paired rows, else the first BUCKET_SHOWN compared columns. A column only one
    side has is never counted without asking - it is offered apart, to tick.
    With `keys_apart` (the differing rows, whose key values have tables of their own) the key is
    left out."""
    own = bucket_columns(run, bucket)
    mine = [c for c in own if c not in keys and c not in cols]
    rest = [c for c in cols if c not in keys]
    first = (bucket not in ("left", "right") and mismatched(run, rest)) or rest[:BUCKET_SHOWN]
    shown = ([] if keys_apart else list(keys)) + first
    return own, shown, [c for c in rest + mine if c not in first]
