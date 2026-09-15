"""Regenerates examples/left.csv and examples/right.csv: the same 3,000 orders exported by two
systems. Right renames every column, writes amounts with thousands separators, dates as
dd/mm/yyyy, booleans as Y/N, adds a column Left does not have (Region), drops the last 40
orders and adds 25 of its own, and changes a few values. Deterministic (seed 7).

    python examples/make_sample.py
"""
import csv
import random
from pathlib import Path

random.seed(7)
here = Path(__file__).resolve().parent
n = 3000
rows = []
for i in range(1, n + 1):
    rows.append({"order_id": f"O{i:05d}",
                 "customer": random.choice(["ACME", "Globex", "Initech", "Umbrella", "Hooli"]),
                 "amount": round(random.uniform(10, 5000), 2),
                 "ccy": random.choice(["EUR", "USD", "CHF"]),
                 "trade_date": f"2026-0{random.randint(1, 9)}-{random.randint(10, 28)}",
                 "active": random.choice([True, False])})
with open(here / "left.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

right = []
for r in rows[:-40]:
    amt = r["amount"] + (random.choice([0, 0, 0, 0, 0, 0, 0, 0, 1]) * round(random.uniform(-5, 5), 2))
    y, m, d = r["trade_date"].split("-")
    right.append({"OrderId": r["order_id"],
                  "Customer": r["customer"].upper() if random.random() < 0.3 else r["customer"],
                  "Amount": f"{amt:,.2f}",
                  "Currency": r["ccy"] if random.random() > 0.01 else "GBP",
                  "TradeDate": f"{d}/{m}/{y}",
                  "IsActive": "Y" if r["active"] else "N",
                  "Region": random.choice(["EU", "US"])})
for i in range(n + 1, n + 26):
    right.append({"OrderId": f"O{i:05d}", "Customer": "ACME", "Amount": "1,000.00", "Currency": "EUR",
                  "TradeDate": "01/02/2026", "IsActive": "Y", "Region": "EU"})
with open(here / "right.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(right[0]))
    w.writeheader()
    w.writerows(right)
print("left", n, "right", len(right))
