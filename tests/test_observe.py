# tests/test_observe.py
"""What stands out in one table: a synthetic file plants every observation once and each
note, table row, the duplicate count and the headline are checked against it; a clean
table gives only the lines that genuinely hold; odd shapes never raise."""
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tablecmp.columns import single_specs
from tablecmp.keys import MAX_KEY_COLS
from tablecmp.observe import (CORR_COLS, DEP_COLS, OUTLIER_COLS, PATTERN_COLS, collapse,
                              observe)
from tablecmp.profile import freq_tables, stats_table
from tablecmp.sniff import looks_like
from tablecmp.sources import Side, file_stamp, source_schema
from tablecmp.sql import scratch
from tablecmp.values import ReadOptions, register

EX = Path(__file__).resolve().parent.parent / "examples"
OPTS = ReadOptions(tokens=("NULL", ""), trim=True)      # "" in tokens: empty cells read as null

DEPTS = ["Engineering", "Finance", "Sales", "Support", "Legal", "People", "Marketing", "Ops"]
WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 1]          # of 36 rows: the counts descend in DEPTS order
CCS = ["CC-100", "CC-200", "CC-300", "CC-400"]      # two departments each
CITIES = ["Paris", "London", "Berlin", "Madrid", "Rome", "Vienna", "Prague", "Lisbon", "Dublin",
          "Oslo", "Stockholm", "Helsinki", "Warsaw", "Athens", "Zurich", "Geneva", "Milan",
          "Munich", "Hamburg", "Lyon", "Porto", "Seville", "Naples", "Turin", "Ghent", "Bruges",
          "Leeds", "York", "Bath", "Cork"]
FIRST = ["Omar", "Ines", "Amara", "Jonas", "Elena", "Aarav", "Nadia", "Luca", "Mei", "Sofia",
         "Ivan", "Zara", "Hugo", "Lena", "Noah", "Aya", "Emil", "Sara", "Ravi", "Nora",
         "Theo", "Lina", "Kai"]                 # 23
LAST = ["Okafor", "Schmidt", "Costa", "Ibrahim", "Rossi", "Novak", "Tanaka", "Silva", "Meyer",
        "Dubois", "Nowak", "Larsen", "Kim", "Moreau", "Bauer", "Sato", "Fischer", "Weber",
        "Lopez"]                                # 19
SEEN_FROM = datetime(2023, 1, 1, 8, 30, 0)     # seen_at: 727 values a half-day and a second apart
SEEN_ODD = {300: datetime(2099, 5, 5, 10, 0, 0), 350: datetime(2098, 1, 1, 0, 0, 0),
            400: datetime(1850, 1, 1, 0, 0, 0)}  # two after today, one before 1900


def _side(path: Path, kind: str = "csv") -> Side:
    s = Side(name="t", label=path.name, csv_path=str(path), kind=kind)
    s.schema = source_schema(s.csv_path, kind, ",", True, file_stamp(s.csv_path))
    s.source_columns = list(s.schema)
    return s


def _measure(side: Side, keys=None, say=None, opts: ReadOptions = OPTS):
    """The Profiling page's read: looks taken into the specs, the table registered once,
    statistics and frequencies on it, then observe on the same connection."""
    looks = looks_like(side, side.columns, opts=opts)
    specs = single_specs(side, looks)
    con = scratch()
    register(con, side, "prof", specs, "A", opts, materialize=True)
    stats = stats_table(con, "prof", specs)
    freq = {s.canon: freq_tables(con, "prof", s.canon) for s in specs}
    out = observe(con, "prof", side, specs, stats, freq, opts, looks, keys, say)
    out["stats"] = stats
    return out


def _write(path: Path, header: list[str], rows: list[list]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


# ---- the planted table --------------------------------------------------------------
def _planted_row(i: int) -> list:
    """Row i of the synthetic table - every column a deterministic function of i, so each
    observation lands exactly where the test expects it."""
    cum, dept = 0, 0
    for j, w in enumerate(WEIGHTS):
        cum += w
        if i % 36 < cum:
            dept = j
            break
    emp_id = {993: "E12", 994: "E-0995", 995: "0996E"}.get(i, f"E{i + 1:04d}")   # 3 malformed
    full_name = f"{FIRST[i % 23]} {LAST[(i * 5) % 19]}"
    if i % 83 == 5:                                             # 12 rows with stray spaces
        full_name = f"  {full_name}" if i % 2 else f"{full_name} "
    manager = "" if i % 10 == 0 else f"M{i % 53 + 1:02d}"          # 10% null, 53 managers
    cust = i + 1 if i < 876 else i - 876 + 1                    # the last 120 rows reuse a cust_id
    cust_id = f"C{cust:04d}"
    status = "left" if i % 37 == 0 else "active"                # 27 of 1,000: active on 97.3%
    is_active = "N" if i % 11 == 0 else "Y"                    # 11: no other column's period
    salary = 3000 + (i * 7919) % 12001 + ((i * 31) % 100) / 100
    if i % 25 == 0:
        salary = 0.0                                            # 40 zeros
    salary = {7: -500.0, 17: -1250.75, 47: -80.25, 501: 1_000_000.0, 601: 900_000.0}.get(i, salary)
    r = (i * 13) % 200                                          # 200 zips, 24 of them 0xxxx
    zip_code = f"{9000 + r * 40:05d}" if r < 24 else f"{10000 + r * 40:05d}"
    city = CITIES[i % 30]
    if i % 90 == 30:
        city = "paris"
    elif i % 180 == 60:
        city = "PARIS"
    elif i % 60 == 31:
        city = "london"
    tenure = (i * 7) % 31 + 1
    leave = round(10 + tenure * 0.8 + ((i * 17) % 7 - 3), 1)         # tracks tenure: r ≈ 0.96
    hired = date(2000, 1, 1) + timedelta(days=((i * 973) % 887) * 10)
    hired = {700: date(2099, 1, 1), 800: date(1899, 6, 15)}.get(i, hired)
    seen = SEEN_ODD.get(i, SEEN_FROM + timedelta(seconds=43_201 * ((i * 37) % 727)))   # 727 values, a prime period
    return [emp_id, full_name, DEPTS[dept], CCS[dept // 2], "ACME", "", manager, cust_id,
            f"{cust_id.lower()}@example.com", status, is_active, f"{salary:,.2f}", zip_code,
            city, tenure, leave, hired.strftime("%d-%b-%Y"), seen.strftime("%Y-%m-%d %H:%M:%S")]


PLANTED_COLS = ["emp_id", "full_name", "department", "cost_center", "company", "notes",
                "manager", "cust_id", "cust_email", "status", "is_active", "salary", "zip",
                "city", "tenure_years", "leave_days", "hire_date", "seen_at"]


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    rows = [_planted_row(i) for i in range(996)]
    rows += [rows[11], rows[11], rows[21], rows[21]]            # 4 exact duplicate rows
    path = _write(tmp_path_factory.mktemp("planted") / "planted.csv", PLANTED_COLS, rows)
    said = []
    out = _measure(_side(path), keys=(pd.DataFrame(), [["emp_id"]], "by hand"), say=said.append)
    out["said"] = said
    out["rows"] = rows
    return out


def _lines(notes: list[str], prefix: str) -> list[str]:
    return [n for n in notes if n.startswith(prefix)]


def test_planted_table_level_notes(planted):
    notes = planted["notes"]
    assert planted["duplicates"] == 4
    assert notes[0] == "4 exact duplicate rows - the same values in every column"
    assert notes[1] == (f"no single column or combination up to {MAX_KEY_COLS} is unique - "
                        "closest: emp_id (996 distinct of 1,000)")
    assert notes[2] == "department → cost_center: every department has one cost_center"
    assert notes[3] == "cust_id ↔ cust_email: one-to-one"
    tenure, leave = (pd.Series([r[k] for r in planted["rows"]]) for k in (14, 15))
    r = tenure.corr(leave)                                      # pandas as the second opinion
    assert 0.9 < r < 1 and notes[4] == f"tenure_years ~ leave_days: correlated, r = {r:.2f}"
    cap = _lines(notes, "patterns:")
    assert len(cap) == 1 and "full_name" in cap[0] and "shapes" in cap[0]
    # every table-level line comes before the first per-column line
    assert notes.index(cap[0]) < notes.index("notes: empty - null on every row")


def test_planted_column_notes(planted):
    notes = planted["notes"]
    assert "notes: empty - null on every row" in notes
    assert "company: constant - one value on every row (ACME)" in notes
    assert "manager: null on 10.0% of rows" in notes
    assert "emp_id: nearly unique - 4 rows share a value with another" in notes
    assert "cust_id: says identifier but 124 rows share a value" in notes
    assert ("department: 8 values - Engineering, Finance, Sales, Support, Legal, People, "
            "Marketing, Ops") in notes
    assert "cost_center: 4 values - CC-100, CC-200, CC-300, CC-400" in notes
    assert "status: 2 values - active, left" in notes
    assert "status: active on 97.3% of rows" in notes
    # the 'read as' branch for a boolean, a number and a date - the suggestion's own words
    assert "is_active: read as a boolean - Y/N" in notes
    assert "salary: read as a number - 10,919.31 has thousands separators" in notes
    assert "hire_date: read as a date - 01-Jan-2000 → %d-%b-%Y" in notes
    assert "zip: read as a number" in notes
    assert "zip: reads as a number but 120 values have leading zeros - keep it as text" in notes
    assert "city: 5 values differ only in case - Paris / paris / PARIS" in notes
    assert "full_name: 12 values have leading or trailing spaces - trimmed before measuring" in notes
    out = _lines(notes, "salary: 2 outliers - above ")
    assert len(out) == 1 and out[0].endswith(" (1.5 × IQR) · highest 1,000,000") and "below" not in out[0]
    assert "salary: 3 negative values · 40 zeros" in notes
    out = _lines(notes, "hire_date: 2 outliers - below ")
    assert len(out) == 1 and " or above " in out[0]
    assert out[0].endswith(" (1.5 × IQR) · lowest 1899-06-15 · highest 2099-01-01")
    assert "hire_date: 1 date after today · 1 date before 1900" in notes
    # the timestamp column: fences to the second, the extremes with their time, plural dates
    out = _lines(notes, "seen_at: 3 outliers - below 2022-")
    assert len(out) == 1 and " or above 2024-" in out[0]
    lo, hi = out[0].split("below ")[1].split(" or above ")[0], out[0].split("above ")[1].split(" (")[0]
    assert len(lo) == len(hi) == 19 and "." not in lo + hi          # to the second, no microseconds
    assert out[0].endswith(" (1.5 × IQR) · lowest 1850-01-01 00:00:00 · highest 2099-05-05 10:00:00")
    assert "seen_at: 2 dates after today · 1 date before 1900" in notes
    pat = _lines(notes, "emp_id: 99.7% of values are A9999 - 3 are not (")
    assert len(pat) == 1 and pat[0].endswith(")") and "…" not in pat[0]
    assert all(v in pat[0] for v in ("E12", "E-0995", "0996E"))
    # nothing stands out about the columns that are plain
    assert not _lines(notes, "cust_email:") and not _lines(notes, "tenure_years:")
    assert not _lines(notes, "leave_days:")
    assert _lines(notes, "seen_at:") == [out[0], "seen_at: 2 dates after today · 1 date before 1900"]
    # per-column lines follow the table order
    first = {n.split(":")[0]: i for i, n in reversed(list(enumerate(notes))) if ":" in n
             and n.split(":")[0] in PLANTED_COLS}
    assert sorted(first, key=first.get) == [c for c in PLANTED_COLS if c in first]


def test_planted_tables(planted):
    out = planted["outliers"]
    assert list(out.columns) == OUTLIER_COLS
    assert list(out["Column"]) == ["salary", "zip", "tenure_years", "leave_days", "hire_date", "seen_at"]
    # whole numbers, blank on a date row, the way the stats table's lengths are - no object
    # column of ints and '' for Streamlit to fix on the way to Arrow
    assert str(out["Zeros"].dtype) == "Int64" and str(out["Negatives"].dtype) == "Int64"
    assert out["Outliers"].dtype.kind == "i" and out["Outlier %"].dtype.kind == "f"
    sal = out.set_index("Column").loc["salary"]
    assert sal["Outliers"] == 2 and sal["Zeros"] == 40 and sal["Negatives"] == 3
    assert sal["Highest"] == "1000000" and sal["Lowest"] == "-1250.75" and sal["Outlier %"] == 0.2
    assert sal["Std dev"] != "" and float(sal["High fence"]) < 900_000
    hd = out.set_index("Column").loc["hire_date"]
    assert hd["Type"] == "date" and hd["Outliers"] == 2
    assert hd["Lowest"] == "1899-06-15" and hd["Highest"] == "2099-01-01"
    assert hd["Std dev"] == "" and pd.isna(hd["Zeros"]) and pd.isna(hd["Negatives"])
    assert hd["Median"].startswith("20") and len(hd["Median"]) == 10       # a date, not a timestamp
    ts = out.set_index("Column").loc["seen_at"]
    assert ts["Type"] == "timestamp" and ts["Outliers"] == 3 and ts["Outlier %"] == 0.3
    assert ts["Median"].startswith("2023-") and len(ts["Median"]) == 19 and " " in ts["Median"]
    assert all(len(ts[q]) == 19 for q in ("P1", "P5", "P25", "P75", "P95", "P99"))   # interpolated: to the second
    assert ts["Lowest"] == "1850-01-01 00:00:00" and ts["Highest"] == "2099-05-05 10:00:00"
    assert ts["Low fence"].startswith("2022-") and ts["High fence"].startswith("2024-")
    assert len(ts["Low fence"]) == len(ts["High fence"]) == 19           # to the second
    assert ts["Std dev"] == "" and pd.isna(ts["Zeros"]) and pd.isna(ts["Negatives"])
    assert (out.set_index("Column")["Outliers"][["zip", "tenure_years", "leave_days"]] == 0).all()

    pat = planted["patterns"]
    assert list(pat.columns) == PATTERN_COLS
    emp = pat[pat["Column"] == "emp_id"]
    assert len(emp) == 3 and list(emp.iloc[0][["Pattern", "Collapsed", "Count", "%"]]) == ["A9999", "A+9+", 997, 99.7]
    assert emp.iloc[0]["Example"].startswith("E")
    mail = pat[pat["Column"] == "cust_email"]
    assert len(mail) == 1 and mail.iloc[0]["Pattern"] == "A9999@AAAAAAA.AAA"
    assert mail.iloc[0]["Collapsed"] == "A+9+@A+.A+" and mail.iloc[0]["Count"] == 1000
    assert not len(pat[pat["Column"] == "notes"]) and not len(pat[pat["Column"] == "salary"])
    assert not len(pat[pat["Column"] == "seen_at"])
    assert (pat.groupby("Column").size() <= 3).all()
    assert len(pat[pat["Column"] == "full_name"]) == 3

    deps = planted["deps"]
    assert list(deps.columns) == DEP_COLS
    assert deps.values.tolist() == [["department", "cost_center", "many-to-one", 8],
                                    ["cust_id", "cust_email", "one-to-one", 876]]
    corr = planted["corr"]
    assert list(corr.columns) == CORR_COLS
    assert len(corr) == 1 and list(corr.iloc[0][["Column A", "Column B"]]) == ["tenure_years", "leave_days"]
    tenure, leave = (pd.Series([r[k] for r in planted["rows"]]) for k in (14, 15))
    assert corr.iloc[0]["r"] == round(tenure.corr(leave), 3)


def test_planted_headline_and_progress(planted):
    assert planted["headline"] == (f"1,000 rows × 18 columns · no key up to {MAX_KEY_COLS} columns · "
                                   "4 duplicate rows · 1 empty column · 1 constant column · "
                                   "3 columns with outliers")
    assert planted["said"] and all(s.startswith("t: ") for s in planted["said"])
    assert any("outliers" in s for s in planted["said"])


# ---- the other forms of the lines -------------------------------------------------------
def _variant_row(i: int) -> list:
    """Row i of a 3,000-row table planting the forms the planted table does not: a category
    with 15 values (the line stops after 12), an identifier null on one row, a constant
    with nulls, a number whose only outlier is below, a shape with four odd values."""
    cum, kind = 0, 0
    for j in range(15):                          # 15 categories, counts 375 down to 25
        cum += 15 - j
        if i % 120 < cum:
            kind = j
            break
    return [f"E{i:04d}" if i != 7 else "",
            "CC-100" if i % 3 else "",
            f"cat{kind:02d}",
            -100_000 if i == 0 else i + 1,
            {10: "K12", 20: "K-0020", 30: "0030K", 40: "kk40"}.get(i, f"K{i:04d}")]


VARIANT_COLS = ["emp_id", "cc", "kind", "amount", "code"]


def test_the_other_forms_of_the_lines(tmp_path):
    out = _measure(_side(_write(tmp_path / "variants.csv", VARIANT_COLS,
                                [_variant_row(i) for i in range(3000)])))
    notes = out["notes"]
    assert _lines(notes, "emp_id:") == ["emp_id: null on 1 row of 3,000"]        # under 0.1%
    assert _lines(notes, "cc:") == ["cc: constant - one value on every filled row (CC-100)",
                                    "cc: null on 33.3% of rows"]
    assert _lines(notes, "kind:") == ["kind: 15 values - cat00, cat01, cat02, cat03, cat04, cat05, "
                                      "cat06, cat07, cat08, cat09, cat10, cat11, …"]
    # 1..3000 with one -100,000: P25 = 750.75, P75 = 2,250.25, the low fence -1,498.5
    assert _lines(notes, "amount:") == ["amount: 1 outlier - below -1,498.50 (1.5 × IQR) · lowest -100,000",
                                        "amount: 1 negative value"]
    assert _lines(notes, "code:") == ["code: 99.9% of values are A9999 - 4 are not (0030K, K-0020, K12, …)"]
    row = out["outliers"].set_index("Column").loc["amount"]
    assert row["Outliers"] == 1 and row["Low fence"] == "-1498.5" and row["High fence"] == "4499.5"
    assert "patterns: the 3 most common shapes per column are listed - more exist in code (5 shapes)" in notes


def test_correlation_pinned_on_a_known_list(tmp_path):
    xs, ys = list(range(1, 11)), [2, 4, 5, 4, 5, 7, 8, 9, 10, 12]
    out = _measure(_side(_write(tmp_path / "corr.csv", ["x", "y"], list(zip(xs, ys)))))
    r = pd.Series(xs).corr(pd.Series(ys))
    assert round(r, 2) == 0.97                     # 83 / sqrt(82.5 × 88.4) by hand
    assert out["corr"].values.tolist() == [["x", "y", round(r, 3)]]
    assert out["notes"] == [f"x ~ y: correlated, r = {r:.2f}"]


def test_spaces_line_without_trimming(tmp_path):
    rows = [["Paris"], [" London"], ["Berlin "], ["Rome"]] * 5
    path = _write(tmp_path / "pad.csv", ["city"], rows)
    trimmed = _measure(_side(path))["notes"]
    assert "city: 10 values have leading or trailing spaces - trimmed before measuring" in trimmed
    kept = _measure(_side(path), opts=ReadOptions(tokens=("NULL", ""), trim=False))["notes"]
    assert "city: 10 values have leading or trailing spaces" in kept
    assert not any("trimmed" in n for n in kept)


def test_looks_like_not_taken_says_read_as(tmp_path):
    """When the suggestion is not taken into the spec, the line says what it looks like
    and what it was read as."""
    path = _write(tmp_path / "flag.csv", ["flag", "n"], [["Y", "1,200.50"], ["N", "2,300.00"]] * 20)
    side = _side(path)
    looks = looks_like(side, side.columns, opts=OPTS)
    assert looks["flag"] == "boolean · Y/N" and looks["n"].startswith("number · ")
    specs = single_specs(side, {})                  # suggestions not taken: both stay text
    con = scratch()
    register(con, side, "prof", specs, "A", OPTS, materialize=True)
    stats = stats_table(con, "prof", specs)
    freq = {s.canon: freq_tables(con, "prof", s.canon) for s in specs}
    notes = observe(con, "prof", side, specs, stats, freq, OPTS, looks, None)["notes"]
    assert "flag: looks like a boolean - Y/N - read as text" in notes
    assert "n: looks like a number - 1,200.50 has thousands separators - read as text" in notes


# ---- null tokens in the raw checks --------------------------------------------------------
def test_raw_checks_fold_the_null_tokens(tmp_path):
    """Null tokens in another spelling, whitespace-only cells and a padded token are nulls to
    the reader, so they are not case variants or values with stray spaces."""
    rows = [["Paris"]] * 15 + [["London"]] * 12 + [["Berlin"]] * 8 \
        + [["NULL"], ["null"], ["Null"], ["   "], [" NULL "]]
    out = _measure(_side(_write(tmp_path / "tokens.csv", ["city"], rows)))
    st = out["stats"].iloc[0]
    assert st["Nulls"] == 5 and st["Distinct"] == 3
    assert _lines(out["notes"], "city:") == ["city: null on 12.5% of rows",
                                             "city: 3 values - Paris, London, Berlin"]


# ---- known numbers ------------------------------------------------------------------
def test_percentiles_and_fences_on_a_known_list(tmp_path):
    """1..100: quantile_cont interpolates, so P25 = 25.75; Tukey's fences on that."""
    path = _write(tmp_path / "hundred.csv", ["n"], [[i] for i in range(1, 101)])
    out = _measure(_side(path))
    row = out["outliers"].iloc[0]
    assert list(row[["P1", "P5", "P25", "Median", "P75", "P95", "P99"]]) == [
        "1.99", "5.95", "25.75", "50.5", "75.25", "95.05", "99.01"]
    assert row["Low fence"] == "-48.5" and row["High fence"] == "149.5"
    assert row["Std dev"] == "29.0115" and row["Outliers"] == 0 and row["Outlier %"] == 0.0
    assert row["Lowest"] == "1" and row["Highest"] == "100" and row["Zeros"] == 0
    assert out["notes"] == [] and out["headline"] == "100 rows × 1 column · 0 duplicate rows"


def test_non_finite_numbers_are_left_out_and_said(tmp_path):
    """inf, NaN and 1e400 (inf once cast) are not nulls to the reader but no quantile or
    std dev can hold them: they are left out of the outliers row and the note says so."""
    rows = [[i, i * 1.5] for i in range(97)] + [[97, "inf"], [98, "NaN"], [99, "1e400"]]
    out = _measure(_side(_write(tmp_path / "inf.csv", ["id", "ratio"], rows)))
    row = out["outliers"].set_index("Column").loc["ratio"]
    assert row["Outliers"] == 0 and row["Std dev"] != "" and row["Median"] == "72"
    assert row["Low fence"] != "" and row["High fence"] != ""
    assert "ratio: 3 values are NaN, infinite or beyond 1e150 - left out of the outliers" in out["notes"]
    one = _measure(_side(_write(tmp_path / "nan.csv", ["id", "amount"],
                                [[i, i * 1.5] for i in range(1, 50)] + [[50, "NaN"]])))
    assert "amount: 1 value is NaN, infinite or beyond 1e150 - left out of the outliers" in one["notes"]
    assert one["outliers"].set_index("Column").loc["amount"]["Outliers"] == 0
    # a NaN cell in one of two correlated columns does not stop corr()
    assert one["corr"].values.tolist() == [["id", "amount", 1.0]]
    assert "id ~ amount: correlated, r = 1.00" in one["notes"]
    # every value non-finite: no quantiles, no fences, nothing raised
    allbad = _measure(_side(_write(tmp_path / "allbad.csv", ["v"], [["inf"], ["NaN"], ["-inf"]])))
    row = allbad["outliers"].iloc[0]
    assert row["Outliers"] == 0 and row["Low fence"] == "" and row["Median"] == ""
    assert "v: 3 values are NaN, infinite or beyond 1e150 - left out of the outliers" in allbad["notes"]


def test_huge_numbers_and_infinite_dates_are_left_out(tmp_path):
    """A std dev squares its values, and one 1e200 among ordinary numbers overflows it -
    DuckDB raises rather than rounding. A number from 1e150 up is left out the way NaN is,
    and said. A date column can hold `infinity` (a Postgres export of an open-ended date):
    no quantile holds it either, so it is left out and said in its own words."""
    rows = [[i, (1e200 if i == 50 else i * 1.5)] for i in range(100)]
    out = _measure(_side(_write(tmp_path / "huge.csv", ["id", "v"], rows)))
    row = out["outliers"].set_index("Column").loc["v"]
    assert row["Outliers"] == 0 and row["Std dev"] == "43.7386" and row["Highest"] == "148.5"
    assert "v: 1 value is NaN, infinite or beyond 1e150 - left out of the outliers" in out["notes"]
    assert out["corr"].values.tolist() == [["id", "v", 1.0]]         # corr survives it too
    # 1e150 itself is out, 1e149 is in - and reads in prose as 1.00e+149, not 150 digits
    edge = _measure(_side(_write(tmp_path / "edge.csv", ["id", "v"],
                                 [[i, i] for i in range(99)] + [[99, "1e149"]])))
    assert "v: 1 outlier - above 148.50 (1.5 × IQR) · highest 1.00e+149" in edge["notes"]
    rows = [[i, ("infinity" if i % 3 == 0 else f"2024-01-{i % 28 + 1:02d}")] for i in range(100)]
    out = _measure(_side(_write(tmp_path / "infdate.csv", ["id", "valid_to"], rows)))
    row = out["outliers"].set_index("Column").loc["valid_to"]
    assert row["Type"] == "date" and row["Highest"] == "2024-01-28" and row["Outliers"] == 0
    assert "valid_to: 34 values are infinite - left out of the outliers" in out["notes"]
    assert not any("after today" in n for n in out["notes"])


def test_sentinel_dates_do_not_overflow(tmp_path):
    """A quartile on 9999-12-31 or 0001-01-01 puts a fence outside the calendar: that fence
    is blank, the counts still run, the extremes are shown and nothing raises."""
    normal = [date(2015, 1, 1) + timedelta(days=(i * 37) % 3650) for i in range(100)]

    def table(name, sentinel, k):
        rows = [[i, (sentinel if i % 10 < k else normal[i]).isoformat()] for i in range(100)]
        out = _measure(_side(_write(tmp_path / name, ["id", "valid_to"], rows)))
        return out, out["outliers"].set_index("Column").loc["valid_to"], out["notes"]

    # 30 of 100: the quartile itself is the sentinel, the fence on that side is off the calendar
    out, row, notes = table("open.csv", date(9999, 12, 31), 3)
    assert row["Type"] == "date" and row["Outliers"] == 0 and row["Highest"] == "9999-12-31"
    assert row["Low fence"] == "" and row["High fence"] == ""
    assert not any("outlier" in n for n in notes) and "valid_to: 30 dates after today" in notes
    out, row, notes = table("placeholder.csv", date(1, 1, 1), 3)
    assert row["Outliers"] == 0 and row["Lowest"] == "0001-01-01" and row["P25"] == "0001-01-01"
    assert row["Low fence"] == "" and len(row["High fence"]) == 10         # year 5,000-odd, still a date
    assert not any("outlier" in n for n in notes) and "valid_to: 30 dates before 1900" in notes
    # 20 of 100: the quartiles are ordinary dates, the sentinels lie beyond a fence
    out, row, notes = table("twenty.csv", date(9999, 12, 31), 2)
    assert row["Outliers"] == 20 and row["Highest"] == "9999-12-31"
    line = _lines(notes, "valid_to: 20 outliers - above ")
    assert len(line) == 1 and line[0].endswith(" (1.5 × IQR) · highest 9999-12-31")
    fence = line[0].split("above ")[1].split(" (")[0]
    assert len(fence) == 10 and fence.startswith("20") and "below" not in line[0]
    assert "valid_to: 20 dates after today" in notes
    out, row, notes = table("old.csv", date(1, 1, 1), 2)
    assert row["Outliers"] == 20 and "valid_to: 20 dates before 1900" in notes
    line = _lines(notes, "valid_to: 20 outliers - below ")
    assert len(line) == 1 and line[0].endswith(" (1.5 × IQR) · lowest 0001-01-01") and "above" not in line[0]
    # a crossed fence that is itself off the calendar (P25 in year 1, P75 in year 5000, ten
    # values beyond year 9999, which DuckDB hands over as text): the extreme is named instead
    mix = {0: "0001-01-01", 1: "0001-01-01", 2: "0001-01-01", 3: "5000-01-01", 4: "5000-01-01",
           5: "5000-01-01", 6: "99999-01-01"}
    rows = [[i, mix.get(i % 10, normal[i].isoformat())] for i in range(100)]
    out = _measure(_side(_write(tmp_path / "mix.csv", ["id", "valid_to"], rows)))
    row = out["outliers"].set_index("Column").loc["valid_to"]
    assert row["Outliers"] == 10 and row["Low fence"] == "" and row["High fence"] == ""
    assert row["P25"] == "0001-01-01" and row["P75"] == "5000-01-01" and row["P99"] == "99999-01-01"
    assert row["Highest"] == "99999-01-01" and row["Median"].startswith("20")
    assert _lines(out["notes"], "valid_to:") == ["valid_to: 10 outliers (1.5 × IQR) · highest 99999-01-01",
                                                 "valid_to: 40 dates after today · 30 dates before 1900"]


def test_shapes_take_any_script(tmp_path):
    """\\p{L} turns a letter of any script into A; the collapsed shape folds the runs."""
    path = _write(tmp_path / "names.csv", ["name"], [["Émile"], ["Zoë"], ["日本 12"], ["Finance & Control"]])
    pat = _measure(_side(path))["patterns"]
    assert set(pat["Pattern"]) <= {"AAAAA", "AAA", "AA 99", "AAAAAAA & AAAAAAA"}
    assert len(pat) == 3            # top 3 of 4 shapes
    assert collapse("AAAAAAA & AAAAAAA") == "A+ & A+" and collapse("9999-99-99") == "9+-9+-9+"
    assert collapse("A9999") == "A+9+"


# ---- a clean table --------------------------------------------------------------------
def test_clean_table_says_only_what_holds():
    side = _side(EX / "hr_employees.csv")
    out = _measure(side, keys=(pd.DataFrame(), [["emp_id"]], "by hand"))
    notes = out["notes"]
    assert notes[0] == "key: emp_id - unique on every row"
    assert "department: 8 values - " in " ".join(notes)
    for word in ("empty", "constant", "null on", "outlier", "spaces", "leading zeros", "case",
                 "duplicate", "says identifier", "negative", "before 1900", "infinite"):
        assert not any(word in n for n in notes), word
    assert "salary: nearly unique - 5 rows share a value with another" in notes    # it is: 2,995 distinct
    assert out["duplicates"] == 0
    assert out["headline"].startswith("3,000 rows × 7 columns · key: emp_id · 0 duplicate rows")
    assert len(out["outliers"]) == 2 and not len(out["deps"]) and not len(out["corr"])


# ---- caps -------------------------------------------------------------------------------
def test_caps_are_said(tmp_path):
    """45 low-cardinality columns: only 40 are tried as determinants; 32 number columns:
    only the first 30 are compared for correlation - and the notes say so."""
    header = [f"c{k:02d}" for k in range(45)] + [f"n{k:02d}" for k in range(32)]
    rows = [[f"v{(i * (k + 1)) % (k + 2)}" for k in range(45)]
            + [i * 3 + k for k in range(32)] for i in range(120)]     # unique: never determinants
    out = _measure(_side(_write(tmp_path / "wide.csv", header, rows)))
    notes = out["notes"]
    assert ("dependencies: only the 40 columns with the fewest values were tried as "
            "determinants - 5 more were not") in notes
    assert "correlations: only the first 30 number columns were compared - 2 more were not" in notes
    assert set(out["deps"]["Determines"]) <= set(header) and len(out["deps"])
    assert len(out["corr"]) == 435 and "… and 430 more" in notes


def test_ten_dependency_lines_then_the_rest(tmp_path):
    """A column that determines twelve others gives ten lines and '… and 2 more'."""
    header = ["k"] + [f"d{k}" for k in range(12)]
    rows = [[f"k{i % 5}"] + [f"{k}-{i % 5}" for k in range(12)] for i in range(50)]
    notes = _measure(_side(_write(tmp_path / "deps.csv", header, rows)))["notes"]
    lines = [n for n in notes if " ↔ " in n or " → " in n]
    assert len(lines) == 10 and "… and 68 more in Dependencies" in notes


# ---- nothing raises ---------------------------------------------------------------------
def test_never_raises_on_odd_tables(tmp_path):
    one = _measure(_side(_write(tmp_path / "one.csv", ["x"], [[1], [2], [2]])))
    assert one["headline"] == "3 rows × 1 column · 1 duplicate row" and not len(one["deps"])
    assert one["notes"] == ["1 exact duplicate row - the same values in every column"]
    nul = _measure(_side(_write(tmp_path / "nul.csv", ["a", "b"], [[1, ""], [2, ""]])))
    assert "b: empty - null on every row" in nul["notes"] and not len(nul["patterns"])
    assert nul["headline"].endswith("· 1 empty column")
    empty = _measure(_side(_write(tmp_path / "empty.csv", ["a", "b"], [])),
                     keys=(pd.DataFrame(), [["a"]], ""))
    assert empty["duplicates"] == 0 and empty["headline"].startswith("0 rows × 2 columns")
    assert not len(empty["outliers"]) and not len(empty["patterns"]) and not len(empty["deps"])
    assert not any("empty" in n or "outlier" in n for n in empty["notes"])
    nokeys = _measure(_side(EX / "hr_employees.csv"), keys=None)
    assert not any(n.startswith("key:") or n.startswith("no single") for n in nokeys["notes"])
    assert "key" not in nokeys["headline"]


def test_a_dependency_is_tried_on_a_sample_first_then_on_every_row(tmp_path, monkeypatch):
    """With the sample at a thousand rows: x determines y on the first thousand and not on
    the second, so it is not listed; x determines z on every row, both ways, so the pair
    is listed once as one-to-one. Every row is read for the ones that hold on the sample."""
    import tablecmp.observe as observe_mod
    monkeypatch.setattr(observe_mod, "SAMPLE_ROWS", 1000)
    rows = [[i, i // 10, (i // 10) if i < 1000 else -1 - (i % 3), i // 10] for i in range(2000)]
    out = _measure(_side(_write(tmp_path / "dep.csv", ["id", "x", "y", "z"], rows)))
    deps = out["deps"]
    pairs = {(r["Determines"], r["Determined"]): r["Kind"] for _, r in deps.iterrows()}
    assert ("x", "z") in pairs and pairs[("x", "z")] == "one-to-one"
    assert not any("y" in p for p in pairs), pairs
    assert any("x ↔ z: one-to-one" in n for n in out["notes"]), out["notes"]
    assert not any("x → y" in n for n in out["notes"])


def test_duplicate_rows_are_exact_and_nulls_equal(tmp_path):
    """Two rows alike in every column count once each as a duplicate; a null equals a null
    and differs from an empty-looking value; rows alike in all but one column do not."""
    rows = [["a", "1", ""], ["a", "1", ""], ["a", "1", "x"], ["b", "1", ""], ["b", "1", ""],
            ["b", "1", ""], ["c", "2", "0"]]
    out = _measure(_side(_write(tmp_path / "dup.csv", ["k", "n", "v"], rows)))
    assert out["duplicates"] == 3                       # one of the a's, two of the b's
    assert any(n.startswith("3 exact duplicate rows") for n in out["notes"]), out["notes"]


class _Counting:
    """A connection whose statements are kept, for what a measure ran and did not run."""
    def __init__(self, con):
        self.con, self.sent = con, []

    def execute(self, sql, *a, **k):
        self.sent.append(sql)
        return self.con.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self.con, name)


def _held(side: Side):
    looks = looks_like(side, side.columns, opts=OPTS)
    specs = single_specs(side, looks)
    con = scratch()
    register(con, side, "prof", specs, "A", OPTS, materialize=True)
    stats = stats_table(con, "prof", specs)
    freq = {s.canon: freq_tables(con, "prof", s.canon) for s in specs}
    return _Counting(con), specs, stats, freq, looks


def test_a_column_with_more_values_than_the_determinant_is_never_tried(tmp_path):
    """x has 5 values and y 10: every y belongs to a group of x, so x cannot determine y
    and no pass grouped by x reads y; y (10 values) → x (5) is tried and holds; z, with as
    many values as x, is tried both ways and is one-to-one with it."""
    from tablecmp.observe import dependencies, facts_of
    rows = [[i, i % 5, i % 10, (i % 5) * 7] for i in range(100)]
    con, specs, stats, freq, looks = _held(_side(_write(tmp_path / "card.csv", ["id", "x", "y", "z"], rows)))
    facts = facts_of(stats)
    deps, _ = dependencies(con, "prof", [s.canon for s in specs], facts, 100)
    pairs = {(r["Determines"], r["Determined"]): r["Kind"] for _, r in deps.iterrows()}
    assert pairs == {("x", "z"): "one-to-one", ("y", "x"): "many-to-one", ("y", "z"): "many-to-one"}, pairs
    by_x = [q for q in con.sent if 'GROUP BY 1' in q and 'SELECT "x", count(*)' in q]
    assert by_x and not any('"y"' in q for q in by_x), by_x       # y never read under x
    assert not any('"id"' in q for q in by_x)                     # nor the unique id


def test_the_key_and_the_duplicates_are_known_when_the_search_found_a_key(tmp_path):
    """The key search's own table says id is unique on every row: the key line takes its
    word - no count - and a unique key leaves no two rows alike, so the duplicates are
    0 without a count either. Without a key both are counted, as before."""
    from tablecmp.keys import suggest_keys_single
    rows = [[i, i % 3, "x"] for i in range(50)]
    side = _side(_write(tmp_path / "keyed.csv", ["id", "grp", "k"], rows))
    con, specs, stats, freq, looks = _held(side)
    keys = suggest_keys_single(side, specs, "t", OPTS, con=con, view="prof", stats=stats)
    assert keys[1][0] == ["id"] and keys[0].iloc[0]["Unique"] == "yes"
    con.sent.clear()
    out = observe(con, "prof", side, specs, stats, freq, OPTS, looks, keys)
    assert out["duplicates"] == 0 and any(n == "key: id - unique on every row" for n in out["notes"])
    assert not any("md5_number" in q for q in con.sent)
    assert not any('count(DISTINCT concat_ws' in q and 'FILTER' in q for q in con.sent)
    # every row twice: no key, and both are counted
    dup = [[i // 2, (i // 2) % 3, "x"] for i in range(50)]
    side2 = _side(_write(tmp_path / "dup.csv", ["id", "grp", "k"], dup))
    con2, specs2, stats2, freq2, looks2 = _held(side2)
    keys2 = suggest_keys_single(side2, specs2, "t", OPTS, con=con2, view="prof", stats=stats2)
    con2.sent.clear()
    out2 = observe(con2, "prof", side2, specs2, stats2, freq2, OPTS, looks2, keys2)
    assert out2["duplicates"] == 25 and any("closest" in n for n in out2["notes"])
    assert any("md5_number" in q for q in con2.sent)


def test_patterns_are_shaped_once_per_distinct_value(tmp_path):
    """The shapes, counts, example and odd values of a column read the same whether every
    row or every distinct value is shaped - and the statement groups the values first."""
    from tablecmp.observe import patterns
    rows = [[f"AB-{i % 7:03d}" if i % 50 else f"x{i}", f"{i % 4}"] for i in range(200)]
    con, specs, stats, freq, looks = _held(_side(_write(tmp_path / "shape.csv", ["code", "n"], rows)))
    pat, facts = patterns(con, "prof", specs)
    top = pat[pat["Column"] == "code"]
    assert list(top["Pattern"]) == ["AA-999", "A999", "A9"] and list(top["Count"]) == [196, 2, 1]
    assert top.iloc[0]["Example"] == "AB-000"
    assert facts["code"]["shapes"] == 4 and facts["code"]["others"] == 4
    assert facts["code"]["examples"] == ["x0", "x100", "x150"] and facts["code"]["more"] is True
    sent = [q for q in con.sent if "regexp_replace" in q and '"code"' in q]
    assert len(sent) == 1 and "GROUP BY 1" in sent[0] and "MATERIALIZED" in sent[0]
