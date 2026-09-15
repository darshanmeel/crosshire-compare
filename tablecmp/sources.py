"""One CSV file, and which of its rows to read. DuckDB streams it from disk."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .sql import ident, lit, scratch


@dataclass
class Side:
    name: str = ""          # what you call it - shown everywhere
    label: str = ""         # the file name
    csv_path: str = ""      # the file read: CSV / Parquet / JSON, or the Parquet a database fetch produced
    kind: str = "csv"       # csv | parquet | json
    origin: str = ""        # where a database fetch came from, for display ("Snowflake · HR.EMPLOYEES")
    cache_path: str = ""    # Parquet snapshot of the rows read, when one was taken
    delimiter: str = ","
    header: bool = True
    where: str = ""                                   # on the file's own columns
    order_by: list[str] = field(default_factory=list)
    desc: bool = False
    limit: int = 0                                    # 0 = every row
    schema: dict[str, str] = field(default_factory=dict)      # column -> detected type
    source_columns: list[str] = field(default_factory=list)  # names as the file has them
    rows: int | None = None

    @property
    def loaded(self) -> bool:
        return bool(self.schema)

    @property
    def columns(self) -> list[str]:
        return list(self.schema)

    @property
    def source_of(self) -> dict[str, str]:
        """column name as shown -> the name the file actually uses."""
        return dict(zip(self.columns, self.source_columns or self.columns))

    @property
    def read_key(self) -> list:
        """Everything that decides which rows come out of this file."""
        return [self.csv_path, self.kind, self.cache_path, self.delimiter, self.header, self.where,
                self.order_by, self.desc, self.limit]

    @property
    def cut(self) -> str:
        bits = []
        if self.where.strip():
            bits.append("WHERE " + " ".join(self.where.split()))
        if self.order_by:
            bits.append("ORDER BY " + ", ".join(self.order_by) + (" DESC" if self.desc else ""))
        if self.limit:
            bits.append(f"TOP {self.limit:,}")
        return " · ".join(bits)


FILE_KINDS = {".csv": "csv", ".txt": "csv", ".tsv": "csv", ".dat": "csv",
              ".parquet": "parquet", ".pq": "parquet",
              ".json": "json", ".jsonl": "json", ".ndjson": "json"}


def kind_of(path: str) -> str:
    return FILE_KINDS.get(Path(path).suffix.lower(), "csv")


def read_csv_expr(path: str, delimiter: str, header: bool, all_varchar: bool = True) -> str:
    return (f"read_csv({lit(path)}, delim={lit(delimiter)}, "
            f"header={'true' if header else 'false'}, null_padding=true"
            + (", all_varchar=true" if all_varchar else "") + ")")


def raw_expr(path: str, kind: str, delimiter: str = ",", header: bool = True,
             all_varchar: bool = True) -> str:
    """A DuckDB table expression for the file as it is, typed columns and all."""
    if kind == "parquet":
        return f"read_parquet({lit(path)})"
    if kind == "json":
        return f"read_json_auto({lit(path)}, maximum_object_size=67108864)"
    return read_csv_expr(path, delimiter, header, all_varchar)


def read_expr(path: str, kind: str, delimiter: str = ",", header: bool = True) -> str:
    """The same file with every column as text - the one form the rest of the app reads,
    so a Parquet DATE, a JSON number and a CSV field all go through the same typing."""
    if kind == "csv":
        return read_csv_expr(path, delimiter, header, all_varchar=True)
    cols = source_schema(path, kind, delimiter, header, file_stamp(path))
    sel = ", ".join(f"{ident(c)}::VARCHAR AS {ident(c)}" for c in cols) or "*"
    return f"(SELECT {sel} FROM {raw_expr(path, kind, delimiter, header)})"


def file_stamp(path: str) -> str:
    try:
        s = Path(path).stat()
        return f"{s.st_size}:{s.st_mtime_ns}"
    except OSError:
        return ""


@lru_cache(maxsize=64)
def source_schema(path: str, kind: str, delimiter: str, header: bool,
                  stamp: str = "") -> dict[str, str]:
    """Column names and the types the file itself carries (or DuckDB sniffs for a CSV) -
    cheap on a big file, DuckDB reads only what it needs to know the shape."""
    con = scratch()
    q = f"DESCRIBE SELECT * FROM {raw_expr(path, kind, delimiter, header, all_varchar=False)}"
    return {r[0]: r[1] for r in con.execute(q).fetchall()}


def csv_schema(path: str, delimiter: str, header: bool, stamp: str = "") -> dict[str, str]:
    return source_schema(path, "csv", delimiter, header, stamp)


def select_sql(side: Side) -> str:
    """The rows to read from the file, with the sidebar's filter, order and top-N."""
    sql = f"SELECT * FROM {read_expr(side.csv_path, side.kind, side.delimiter, side.header)}"
    if side.where.strip():
        sql += f" WHERE {side.where.strip()}"
    if side.order_by:
        sql += " ORDER BY " + ", ".join(
            f"{ident(c)} {'DESC' if side.desc else 'ASC'}" for c in side.order_by)
    if side.limit:
        sql += f" LIMIT {int(side.limit)}"
    return sql


def source_expr(side: Side) -> str:
    """What every query reads from: the Parquet snapshot, or the CSV with the cut."""
    if side.cache_path:
        return f"read_parquet({lit(side.cache_path)})"
    return f"({select_sql(side)})"


def snapshot(side: Side, path: str) -> None:
    """Read the CSV once with its cut and keep the rows as Parquet."""
    con = scratch(ordered=True)
    con.execute(f"COPY ({select_sql(side)}) TO {lit(path)} (FORMAT PARQUET)")
    side.cache_path = path


def row_count(side: Side) -> int:
    return int(scratch().execute(f"SELECT count(*) FROM {source_expr(side)}").fetchone()[0])


def preview_rows(side: Side, n: int = 10) -> pd.DataFrame:
    """The first n rows as the file has them - cheap, DuckDB stops after n."""
    df = scratch(ordered=True).execute(f"SELECT * FROM {source_expr(side)} LIMIT {int(n)}").fetchdf()
    back = {raw: shown for shown, raw in side.source_of.items()}
    return df.rename(columns=back)


def quick_clause(col: str, op: str, value: str) -> str:
    """One condition from the sidebar's column / condition / value pickers."""
    c, v = ident(col), value.strip()
    if op == "is null":
        return f"{c} IS NULL"
    if op == "is not null":
        return f"{c} IS NOT NULL"
    if op.startswith("in"):
        items = [x.strip() for x in v.split(",") if x.strip()]
        return f"{c} IN ({', '.join(lit(x) for x in items) or lit('')})"
    if op == "contains":
        return f"{c} ILIKE {lit('%' + v + '%')}"
    if op == "starts with":
        return f"{c} ILIKE {lit(v + '%')}"
    if op in (">", ">=", "<", "<=") and re.fullmatch(r"[-+]?\d+(\.\d+)?", v):
        return f"try_cast({c} AS DOUBLE) {op} {v}"      # a number: compare as one
    return f"{c} {op} {lit(v)}"


AUTO_NAME = re.compile(r"^column\d+$", re.I)


def apply_names(schema: dict[str, str], names: list[str]) -> dict[str, str]:
    """Rename columns by position, for a file whose header is wrong or short."""
    types = list(schema.values())
    out, seen = {}, {}
    for i, t in enumerate(types):
        base = names[i].strip() if i < len(names) and names[i].strip() else list(schema)[i]
        n = seen.get(base, 0) + 1
        seen[base] = n
        out[base if n == 1 else f"{base}_{n}"] = t
    return out


def short_header(schema: dict[str, str]) -> int:
    """How many trailing columns the header row failed to name."""
    return sum(1 for c in schema if AUTO_NAME.match(str(c)))


def looks_headerless(schema: dict[str, str]) -> bool:
    """Header names that are really a data row: numbers, dates, duplicate stems."""
    names = list(schema)
    if not names:
        return False

    def datalike(n: str) -> bool:
        n = n.strip()
        if re.fullmatch(r"[-+]?\d[\d,.]*", n):
            return True
        if re.match(r"^\d{4}-\d{2}-\d{2}", n):
            return True
        return bool(re.fullmatch(r".*_\d+", n)) and n[0].isdigit()
    return sum(datalike(n) for n in names) >= max(2, len(names) // 4)
