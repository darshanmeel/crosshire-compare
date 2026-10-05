"""
compare_app.py - compare two tables (a CSV or JSON file, or a database table, on each side),
row by row, on a key you choose - or, on the Profiling page, profile one table on its own.

    pip install -r requirements.txt
    python compare_app.py                    # the page at http://127.0.0.1:8501
    python compare_app.py --port 8600 --no-browser

Files: compare_app.py, csvdiff.py (the engine) and the tablecmp/ folder, together.
Everything else - colours, fonts, limits - is in tablecmp/theme.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUCKDB_FLOOR = "1.2"


def layout_problem() -> str:
    """'' when compare_app.py, csvdiff.py and tablecmp/ sit together; else what to do."""
    if not (HERE / "tablecmp" / "__init__.py").exists():
        loose = sorted(p.name for p in HERE.glob("*.py") if p.name not in ("compare_app.py", "csvdiff.py"))
        hint = (f"\nThese look like its modules, loose in the same folder: {', '.join(loose)}\n"
                f"Make a folder called  tablecmp  next to compare_app.py and move them into it." if loose else "")
        return (f"compare_app.py needs the folder  {HERE / 'tablecmp'}  (with __init__.py, theme.py, "
                f"compare.py, ... inside) next to it, and it is not there.{hint}\n"
                f"Expected layout:\n  {HERE.name}\\\n    compare_app.py\n    csvdiff.py\n"
                f"    tablecmp\\\n      __init__.py  theme.py  sql.py  sources.py  values.py  columns.py\n"
                f"      keys.py  profile.py  compare.py  report.py  auto.py  web\\  web_dist\\")
    if not (HERE / "csvdiff.py").exists():
        return "csvdiff.py must sit in the same folder as compare_app.py."
    return ""


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


if __name__ == "__main__":
    if "streamlit" in sys.modules:               # `streamlit run compare_app.py`, from habit
        print("This page is no longer a Streamlit app - start it with: python compare_app.py", file=sys.stderr)
        raise SystemExit(1)
    problem = layout_problem()
    if problem:
        print(problem, file=sys.stderr)
        raise SystemExit(1)
    sys.path.insert(0, str(HERE))
    import duckdb
    if _version(duckdb.__version__) < _version(DUCKDB_FLOOR):
        print(f"duckdb {DUCKDB_FLOOR} or newer is needed (found {duckdb.__version__}). "
              f"Run `pip install -U duckdb`.", file=sys.stderr)
        raise SystemExit(1)
    try:
        import fastapi  # noqa: F401  - the app itself loads inside uvicorn, so look for it here
        import uvicorn  # noqa: F401
        from tablecmp.web.__main__ import main
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] not in ("fastapi", "uvicorn", "starlette", "pydantic"):
            raise
        print("The page needs FastAPI and uvicorn, which are not installed here - "
              "run: pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1:], prog="python compare_app.py"))
