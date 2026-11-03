"""An Excel sheet as a table: one sheet, the cells where the table sits, read once into a
Parquet file in the work folder that DuckDB then reads like any other.

openpyxl reads the sheet row by row (read-only, the values Excel last calculated), and the
rows go to Parquet in batches - a big sheet never sits in memory whole. Every cell becomes
text, as a CSV field would be: the app types the columns itself. The Parquet is named after
the file, its size and time, and the options, so the same read is made once and reused.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
import warnings
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

# workbooks written by other tools often lack a default style - openpyxl says so on every open
warnings.filterwarnings("ignore", message="Workbook contains no default style", module="openpyxl")

EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
BATCH = 5000                    # rows per Parquet batch
MAX_ROW, MAX_COL = 1_048_576, 16_384
XLS_NEEDS = "Save .xls files as .xlsx - the old format needs the xlrd package"
_RANGE = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d*))?$")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ---- the range box ------------------------------------------------------------------------
def col_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def parse_range(text: str) -> tuple[int, int, int | None, int | None]:
    """(first_row, first_col, last_row, last_col), 1-based, from "", "A1", "B4", "B4:H500" or
    "B4:H" (every row from 4 down). None = to the end. ValueError with a sentence otherwise."""
    t = (text or "").strip().upper().replace(" ", "")
    if not t:
        return 1, 1, None, None
    m = _RANGE.match(t)
    if not m:
        raise ValueError(f"\"{text.strip()}\" is not a cell or a range - write B4, or B4:H500, or B4:H "
                         "for every row from 4 down.")
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    first_col = col_number(c1)
    last_col = col_number(c2) if c2 else None
    last_row = int(r2) if r2 else None
    if r1 < 1 or (last_row is not None and last_row < 1):
        raise ValueError("Rows start at 1.")
    if first_col > MAX_COL or (last_col or 0) > MAX_COL or r1 > MAX_ROW or (last_row or 0) > MAX_ROW:
        raise ValueError(f"\"{text.strip()}\" lies past the last cell of a sheet (XFD1048576).")
    if last_col is not None and last_col < first_col:
        raise ValueError(f"The range ends in column {c2}, left of where it starts ({c1}).")
    if last_row is not None and last_row < r1:
        raise ValueError(f"The range ends on row {last_row}, above where it starts ({r1}).")
    return r1, first_col, last_row, last_col


# ---- a cell as text ------------------------------------------------------------------------
def _number_text(v: float) -> str:
    if v != v or v in (float("inf"), float("-inf")):
        return str(v)
    if v.is_integer() and abs(v) < 1e16:
        return str(int(v))
    s = format(v, ".15g")                         # 0.1 + 0.2 reads 0.3, as Excel shows it
    if "e" in s and 1e-10 <= abs(v) < 1e21:
        s = format(Decimal(s), "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
    return s


def _trim_ms(s: str) -> str:
    """"03:04:05.120" -> "03:04:05.12", "03:04:05.000" -> "03:04:05" - milliseconds, as Excel
    keeps them, without trailing zeros."""
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _duration_text(v: timedelta) -> str:
    """A duration as Excel's [h]:mm:ss shows it - 30:00:00, not "1 day, 6:00:00"."""
    total = round(v.total_seconds())
    sign = "-" if total < 0 else ""
    h, rest = divmod(abs(total), 3600)
    m, sec = divmod(rest, 60)
    return f"{sign}{h}:{m:02}:{sec:02}"


def cell_text(v) -> str | None:
    """One cell as the text the table holds: empty is NULL, 123.0 is 123, a date is ISO."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _number_text(v)
    if isinstance(v, datetime):
        if v.hour == v.minute == v.second == v.microsecond == 0:
            return v.date().isoformat()
        return _trim_ms(v.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds"))
    if isinstance(v, time):
        return _trim_ms(v.replace(tzinfo=None).isoformat(timespec="milliseconds"))
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, timedelta):
        return _duration_text(v)
    s = str(v)
    return s if s != "" else None


# ---- the workbook -------------------------------------------------------------------------
def _is_xls(path: str) -> bool:
    return Path(path).suffix.lower() == ".xls"


def _xlrd():
    try:
        import xlrd  # type: ignore[import-not-found]
    except ImportError:
        raise ValueError(XLS_NEEDS) from None
    return xlrd


def _open_xlsx(path: str):
    import openpyxl
    try:
        return openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:                      # a zip that is not a workbook, a locked file...
        raise ValueError(f"Could not open the Excel file: {exc}") from None


@lru_cache(maxsize=64)
def _sheet_info(path: str, stamp: str) -> tuple[tuple[str, bool], ...]:
    """(name, visible) for each sheet, in the workbook's order."""
    if _is_xls(path):
        xlrd = _xlrd()
        try:
            book = xlrd.open_workbook(path, on_demand=True)
        except Exception as exc:
            raise ValueError(f"Could not open the Excel file: {exc}") from None
        try:
            vis = list(getattr(book, "_sheet_visibility", []))
            return tuple((n, not (vis[i] if i < len(vis) else 0)) for i, n in enumerate(book.sheet_names()))
        finally:
            book.release_resources()
    wb = _open_xlsx(path)
    try:                                          # chart sheets hold no cells
        return tuple((ws.title, getattr(ws, "sheet_state", "visible") == "visible") for ws in wb.worksheets)
    finally:
        wb.close()


def sheet_info(path: str) -> list[tuple[str, bool]]:
    from .sources import file_stamp
    return list(_sheet_info(str(path), file_stamp(str(path))))


def sheet_names(path: str) -> list[str]:
    """The workbook's sheets in their order. ValueError when it cannot be opened."""
    return [n for n, _ in sheet_info(path)]


def hidden_sheets(path: str) -> list[str]:
    return [n for n, visible in sheet_info(path) if not visible]


def resolve_sheet(path: str, sheet: str = "") -> str:
    """The sheet a read takes: the one named, or the first one not hidden (a workbook often
    starts with a hidden lookup sheet). ValueError for a name it lacks."""
    info = sheet_info(path)
    names = [n for n, _ in info]
    if not names:
        raise ValueError("The workbook has no sheet with cells.")
    want = (sheet or "").strip()
    if not want:
        return next((n for n, visible in info if visible), names[0])
    if want in names:
        return want
    folded = [n for n in names if n.strip().lower() == want.lower()]
    if len(folded) == 1:
        return folded[0]
    raise ValueError(f"No sheet called {want} - the file has: {', '.join(names)}")


def _rows(path: str, sheet: str, first_row: int, first_col: int, last_row: int | None, last_col: int | None):
    """The sheet's rows from the range's corner, each a tuple of raw values (as long as the row
    is - empty rows may come as ())."""
    if _is_xls(path):
        yield from _xls_rows(path, sheet, first_row, first_col, last_row, last_col)
        return
    wb = _open_xlsx(path)
    try:
        ws = wb[sheet]
        ws.reset_dimensions()                     # the file's own size tag may be wrong; read every cell
        yield from ws.iter_rows(min_row=first_row, min_col=first_col, max_row=last_row,
                                max_col=last_col, values_only=True)
    finally:
        wb.close()


def _xls_rows(path, sheet, first_row, first_col, last_row, last_col):
    xlrd = _xlrd()
    book = xlrd.open_workbook(path, on_demand=True)
    try:
        sh = book.sheet_by_name(sheet)
        end_row = sh.nrows if last_row is None else min(last_row, sh.nrows)
        for r in range(first_row - 1, end_row):
            end_col = sh.row_len(r) if last_col is None else min(last_col, sh.row_len(r))
            out = []
            for c in range(first_col - 1, end_col):
                cell = sh.cell(r, c)
                t, v = cell.ctype, cell.value
                if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    v = None
                elif t == xlrd.XL_CELL_DATE:
                    v = xlrd.xldate.xldate_as_datetime(v, book.datemode)
                elif t == xlrd.XL_CELL_BOOLEAN:
                    v = bool(v)
                elif t == xlrd.XL_CELL_ERROR:
                    v = xlrd.error_text_from_code.get(v, "#ERR")
                out.append(v)
            yield tuple(out)
    finally:
        book.release_resources()


# ---- the table in the sheet -------------------------------------------------------------------
NO_RANGE = (1, 1, None, None)
PEEK_ROWS = 1000                # rows the column list and the formula check look at


def _table(path: str, sheet: str, rng: tuple, header: bool, stop_at_blank: bool):
    """The table's rows as text, each cut after its last value: the header row first (when
    `header`), then the data. Fully empty rows are skipped - before the header too, unless a
    range was given: then its first row is the header even when it is empty (its columns are
    named after their position, and the side says so) rather than a data row taking its
    place. `stop_at_blank` ends the table at the first empty row after it has started."""
    first_row, first_col, last_row, last_col = rng
    fixed = None if last_col is None else last_col - first_col + 1
    head_due = header and rng != NO_RANGE
    started = False
    for raw in _rows(path, sheet, first_row, first_col, last_row, last_col):
        row = [cell_text(v) for v in raw]
        if fixed is not None:
            row = row[:fixed]
        last = max((i for i, v in enumerate(row) if v is not None), default=-1)
        if head_due:                              # the range's first row, empty or not
            head_due, started = False, True
            yield row[:last + 1]
            continue
        if last < 0:                              # a fully empty row
            if stop_at_blank and started:
                return
            continue
        started = True
        yield row[:last + 1]


def header_names(cells: list[str | None], width: int) -> list[str]:
    """The header row's names for `width` columns: blank -> column{i}, repeats -> name_2."""
    out: list[str] = []
    seen: set[str] = set()
    for i in range(width):
        raw = cells[i] if i < len(cells) else None
        base = (raw or "").strip() or f"column{i}"
        name, n = base, 1
        while name.lower() in seen:
            n += 1
            name = f"{base}_{n}"
        seen.add(name.lower())
        out.append(name)
    return out


def _names(head: list | None, width: int, header: bool) -> list[str]:
    return header_names(head or [], width) if header else [f"column{i}" for i in range(width)]


def _no_cells(sheet: str, rng: tuple) -> ValueError:
    where = "" if rng == NO_RANGE else " in that range"
    return ValueError(f"The sheet {sheet} has no cells with values{where}.")


def peek_columns(path: str, sheet: str = "", cell_range: str = "", header: bool = True,
                 stop_at_blank: bool = False, n: int = PEEK_ROWS) -> list[str]:
    """The column names from the header and the first `n` rows, without writing anything -
    what the side's column list shows while the boxes are being filled. Load reads the whole
    sheet, so a wider row further down may still add a column there."""
    rng = parse_range(cell_range)
    real = resolve_sheet(path, sheet)
    fixed = None if rng[3] is None else rng[3] - rng[1] + 1
    head: list | None = None
    used = seen = 0
    for row in _table(path, real, rng, header, stop_at_blank):
        used = max(used, len(row))
        if header and head is None:
            head = row
            continue
        seen += 1
        if seen >= n:
            break
    width = fixed or used
    if width == 0:
        raise _no_cells(real, rng)
    return _names(head, width, header)


@lru_cache(maxsize=64)
def _unsaved(path: str, stamp: str, sheet: str, rng: tuple, n: int) -> tuple[int, bool]:
    import openpyxl
    first_row, first_col, last_row, last_col = rng
    end = first_row + n - 1 if last_row is None else min(last_row, first_row + n - 1)
    try:
        raw_wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    except Exception:                             # noqa: BLE001 - the read itself says what is wrong
        return 0, False
    count = rows = 0
    try:
        val_wb = _open_xlsx(path)
        try:
            raw_ws, val_ws = raw_wb[sheet], val_wb[sheet]
            raw_ws.reset_dimensions()
            val_ws.reset_dimensions()
            kw = dict(min_row=first_row, min_col=first_col, max_row=end, max_col=last_col, values_only=True)
            for f_row, v_row in zip(raw_ws.iter_rows(**kw), val_ws.iter_rows(**kw)):
                rows += 1
                v_row = tuple(v_row) + (None,) * max(0, len(f_row) - len(v_row))
                count += sum(1 for f, v in zip(f_row, v_row)
                             if v is None and isinstance(f, str) and f.startswith("="))
        finally:
            val_wb.close()
    finally:
        raw_wb.close()
    return count, rows >= n


def unsaved_formulas(path: str, sheet: str = "", cell_range: str = "", n: int = PEEK_ROWS) -> tuple[int, bool]:
    """(formula cells in the table's first `n` rows with no value saved, whether the sheet runs
    past those rows). A workbook a script wrote and Excel never saved has formulas but no
    results, and they would read as empty."""
    from .sources import file_stamp
    if _is_xls(path):                             # xlrd has the values only
        return 0, False
    try:
        rng = parse_range(cell_range)
        real = resolve_sheet(path, sheet)
        return _unsaved(str(path), file_stamp(str(path)), real, rng, n)
    except (ValueError, OSError, KeyError):
        return 0, False


# ---- the Parquet -----------------------------------------------------------------------------
_CACHE_NAME = re.compile(r"^cmp_xl_([0-9a-f]{10})_([0-9a-f]{8})_([0-9a-f]{10})\.parquet$")


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _short(text: str, n: int) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def _where(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def cache_name(path: str, sheet: str, cell_range: str, header: bool, stop_at_blank: bool) -> str:
    """cmp_xl_<file>_<its stamp>_<the read>.parquet. The read holds the range as parsed, so "",
    "A1" and "$A$1" share one file; a newer stamp of the same file replaces the older ones."""
    from .sources import file_stamp
    opts = repr((sheet, parse_range(cell_range), bool(header), bool(stop_at_blank)))
    return f"cmp_xl_{_short(_where(path), 10)}_{_short(file_stamp(path), 8)}_{_short(opts, 10)}.parquet"


def _prune(dest: Path) -> None:
    """Remove the conversions of an older copy of the same workbook. Nothing reads them: a
    loaded side reads its own snapshot, or converts the file as it is now."""
    me = _CACHE_NAME.match(dest.name)
    if not me:
        return
    for other in dest.parent.glob(f"cmp_xl_{me.group(1)}_*.parquet"):
        m = _CACHE_NAME.match(other.name)
        if m and m.group(2) != me.group(2):
            try:
                other.unlink()
            except OSError:                       # being read right now: the sweep takes it later
                pass


def to_parquet(path: str, sheet: str = "", cell_range: str = "", header: bool = True,
               stop_at_blank: bool = False) -> str:
    """The sheet's table as a Parquet file in the work folder, every column text - made once for
    the file as it is now and these options, and reused. ValueError for a bad range or sheet."""
    from .sources import work_dir
    rng = parse_range(cell_range)
    real = resolve_sheet(path, sheet)
    dest = work_dir() / cache_name(path, real, cell_range, header, stop_at_blank)
    with _lock_for(str(dest)):
        if dest.is_file():
            try:
                os.utime(dest)                    # in use: the sweep leaves it
            except OSError:
                pass
            return str(dest)
        _write(path, real, rng, header, stop_at_blank, dest)
    _prune(dest)
    return str(dest)


def _write(path: str, sheet: str, rng: tuple, header: bool, stop_at_blank: bool, dest: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from .sql import ident, lit, scratch
    fixed = None if rng[3] is None else rng[3] - rng[1] + 1
    tag = uuid.uuid4().hex[:8]
    parts: list[Path] = []
    state = {"writer": None, "width": 0}
    head: list[str | None] | None = None
    used = 0                                      # columns up to the last one with a value
    batch: list[list[str | None]] = []

    def flush() -> None:
        if not batch:
            return
        need = max(len(r) for r in batch)
        if state["writer"] is None or need > state["width"]:
            if state["writer"] is not None:
                state["writer"].close()
            state["width"] = max(need, state["width"], 1)
            part = dest.with_name(f"{dest.stem}.{tag}.{len(parts)}.part.parquet")
            parts.append(part)
            schema = pa.schema([(f"c{i}", pa.string()) for i in range(state["width"])])
            state["writer"] = pq.ParquetWriter(str(part), schema)
        w = state["width"]
        cols = [pa.array([r[i] if i < len(r) else None for r in batch], type=pa.string()) for i in range(w)]
        state["writer"].write_batch(pa.RecordBatch.from_arrays(cols, names=[f"c{i}" for i in range(w)]))
        batch.clear()

    try:
        for row in _table(path, sheet, rng, header, stop_at_blank):
            used = max(used, len(row))
            if header and head is None:
                head = row
                continue
            batch.append(row)
            if len(batch) >= BATCH:
                flush()
        flush()
        if state["writer"] is not None:
            state["writer"].close()
            state["writer"] = None
        width = fixed or used
        if width == 0:
            raise _no_cells(sheet, rng)
        names = _names(head, width, header)
        tmp = dest.with_name(f"{dest.stem}.{tag}.tmp.parquet")
        con = scratch(ordered=True)
        try:
            if parts:
                have = state["width"]
                src = (f"read_parquet([{', '.join(lit(str(p)) for p in parts)}], union_by_name=true)"
                       if len(parts) > 1 else f"read_parquet({lit(str(parts[0]))})")
                sel = ", ".join((f"{ident(f'c{i}')}" if i < have else "NULL::VARCHAR") + f" AS {ident(n)}"
                                for i, n in enumerate(names))
                con.execute(f"COPY (SELECT {sel} FROM {src}) TO {lit(str(tmp))} (FORMAT PARQUET)")
            else:                                 # a header and no rows
                sel = ", ".join(f"NULL::VARCHAR AS {ident(n)}" for n in names)
                con.execute(f"COPY (SELECT {sel} WHERE false) TO {lit(str(tmp))} (FORMAT PARQUET)")
        finally:
            con.close()
        os.replace(tmp, dest)
    finally:
        if state["writer"] is not None:
            state["writer"].close()
        for p in parts:
            p.unlink(missing_ok=True)
        for p in dest.parent.glob(f"{dest.stem}.{tag}.tmp.parquet"):
            p.unlink(missing_ok=True)
