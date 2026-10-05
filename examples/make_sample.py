"""Regenerates the sample pair: the same 3,000 employees exported by two systems.

hr_employees.csv       the HR system: emp_id, first_name, last_name, department, salary,
                       hire_date (ISO), active (True/False)
payroll_employees.csv  payroll: renames every column, joins the two names, spells three
                       departments differently, writes salaries with thousands separators,
                       dates as dd/mm/yyyy, active as Y/N, adds a column HR does not have
                       (CostCenter), drops the last 40 employees and adds 25 of its own, and
                       changes a few salaries and a few active flags
directory_employees.json  the staff directory, written the way a JSON export comes out: an
                       array of objects with numbers and booleans as JSON types. id (3% typed in
                       lower case), name (first and last joined), dept (10% spelt the directory's
                       way, 5% with stray spaces), salary (8% changed, 5% with float noise inside
                       a 0.01 tolerance), hire_date as dd-Mon-yyyy, active as true/false,
                       manager_id (a column HR does not have, null for 10%); drops the first 30
                       HR employees, adds 20 of its own and flips 1% of the active flags
sample.duckdb          the same two tables as hr.employees and payroll.employees, so the
                       database path can be tried with no server

Deterministic (seed 7):    python examples/make_sample.py
"""
import csv
import json
import random
from pathlib import Path

import duckdb

random.seed(7)
here = Path(__file__).resolve().parent
FIRST = ["Aarav", "Amara", "Chen", "Elena", "Fatima", "Hugo", "Ines", "Jonas", "Kofi", "Lena",
         "Mateo", "Nadia", "Omar", "Priya", "Rafael", "Sara", "Tomasz", "Uma", "Viktor", "Zofia"]
LAST = ["Nair", "Okafor", "Kowalski", "Schmidt", "Rossi", "Haddad", "Novak", "Silva", "Tanaka",
        "Mensah", "Petrov", "Larsen", "Costa", "Nakamura", "Ibrahim", "Dubois", "Moreau", "Sato"]
DEPTS = ["Finance", "Engineering", "Sales", "Support", "Marketing", "Operations", "Legal", "People"]
RENAMED = {"Finance": "Finance & Control", "Engineering": "Eng", "Sales": "Sales EMEA"}
COST = {"Finance": "CC-110", "Engineering": "CC-220", "Sales": "CC-310", "Support": "CC-320",
        "Marketing": "CC-410", "Operations": "CC-510", "Legal": "CC-120", "People": "CC-130"}

n = 3000
rows = []
for i in range(1, n + 1):
    y = random.randint(2018, 2026)
    m = random.randint(1, 9 if y == 2026 else 12)
    rows.append({"emp_id": f"E{10000 + i}", "first_name": random.choice(FIRST),
                 "last_name": random.choice(LAST), "department": random.choice(DEPTS),
                 "salary": round(random.uniform(2150, 14980), 2),
                 "hire_date": f"{y}-{m:02d}-{random.randint(1, 28):02d}",
                 "active": random.random() < 0.85})
with open(here / "hr_employees.csv", "w", newline="\n", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)

payroll = []
for r in rows[:-40]:
    sal = r["salary"] + (random.choice([0] * 8 + [1]) * round(random.uniform(-150, 150), 2))
    dept = r["department"]
    if random.random() < 0.30:
        dept = RENAMED.get(dept, dept)
    active = r["active"] if random.random() > 0.01 else (not r["active"])
    y, m, d = r["hire_date"].split("-")
    payroll.append({"EmployeeId": r["emp_id"], "FullName": f"{r['first_name']} {r['last_name']}",
                    "Dept": dept, "Salary": f"{sal:,.2f}", "HireDate": f"{d}/{m}/{y}",
                    "IsActive": "Y" if active else "N", "CostCenter": COST[r["department"]]})
for i in range(n + 1, n + 26):
    payroll.append({"EmployeeId": f"E{10000 + i}", "FullName": "New Starter", "Dept": "People",
                    "Salary": "3,000.00", "HireDate": "01/09/2026", "IsActive": "Y", "CostCenter": "CC-130"})
with open(here / "payroll_employees.csv", "w", newline="\n", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(payroll[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(payroll)

# The directory export uses its own generator so the two CSVs above stay byte-identical.
rng = random.Random(11)
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DIR_NAMES = {"People": "People & Culture", "Support": "Customer Support", "Legal": "Legal Affairs"}
managers = [r["emp_id"] for r in rows[:60]]
directory = []
for r in rows[30:]:
    dept = r["department"]
    if rng.random() < 0.10:
        dept = DIR_NAMES.get(dept, dept)
    if rng.random() < 0.05:
        dept = f"  {dept} "
    sal = r["salary"]
    u = rng.random()
    if u < 0.08:
        sal = round(sal + rng.uniform(-200, 200), 2)
    elif u < 0.13:
        sal = sal + 0.000001 * rng.choice([1, -1])      # float noise: inside a 0.01 tolerance
    y, m, d = r["hire_date"].split("-")
    directory.append({"id": r["emp_id"].lower() if rng.random() < 0.03 else r["emp_id"],
                      "name": f"{r['first_name']} {r['last_name']}", "dept": dept, "salary": sal,
                      "hire_date": f"{int(d):02d}-{MON[int(m) - 1]}-{y}",
                      "active": r["active"] if rng.random() > 0.01 else (not r["active"]),
                      "manager_id": None if rng.random() < 0.10 else rng.choice(managers)})
for i in range(n + 1, n + 21):
    directory.append({"id": f"E{10000 + i}", "name": "Directory Only", "dept": "Operations",
                      "salary": 4100.0, "hire_date": "01-Sep-2026", "active": True,
                      "manager_id": managers[0]})
with open(here / "directory_employees.json", "w", newline="\n", encoding="utf-8") as f:
    json.dump(directory, f, indent=1)
    f.write("\n")

db = here / "sample.duckdb"
db.unlink(missing_ok=True)
con = duckdb.connect(str(db))
con.execute("CREATE SCHEMA hr; CREATE SCHEMA payroll")
con.execute(f"CREATE TABLE hr.employees AS SELECT * FROM read_csv('{(here / 'hr_employees.csv').as_posix()}', all_varchar=true)")
con.execute(f"CREATE TABLE payroll.employees AS SELECT * FROM read_csv('{(here / 'payroll_employees.csv').as_posix()}', all_varchar=true)")
con.close()
print("hr", n, "payroll", len(payroll), "directory", len(directory), "duckdb", db.name)
