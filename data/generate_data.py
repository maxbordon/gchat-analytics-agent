"""Generate a synthetic retail dataset (stores, products, inventory counts, P&L).

Everything here is invented. Distributions are tuned so the data tells a
story worth querying: a few stores have clearly abnormal shrinkage, and
margins differ by region and store format.

Usage:
    python data/generate_data.py                 # writes data/sample/*.csv
    python data/generate_data.py --stores 120 --months 24 --out data/full
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date
from pathlib import Path

REGIONS = ["North", "South", "East", "West", "Central"]
FORMATS = {"Express": 0.6, "Market": 1.0, "Hyper": 2.4}  # size multiplier
CITY_WORDS = ["Oak", "River", "Pine", "Lake", "Hill", "Stone", "Maple", "Bay", "Cedar", "Field",
              "Brook", "Park", "Spring", "Ridge", "Valley", "Harbor", "Mill", "Grove"]
DEPARTMENTS = {
    # department: (avg unit cost, markup, base shrink rate)
    "Dairy": (1.8, 0.30, 0.012),
    "Produce": (1.2, 0.45, 0.030),
    "Bakery": (1.5, 0.55, 0.025),
    "Meat": (6.5, 0.28, 0.018),
    "Beverages": (1.4, 0.35, 0.008),
    "Personal Care": (3.9, 0.50, 0.015),
    "Household": (4.2, 0.40, 0.009),
    "Snacks": (1.6, 0.42, 0.014),
}


def months_back(n: int, end: date) -> list[date]:
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate(n_stores: int, n_months: int, products_per_dept: int, seed: int, end: date):
    rng = random.Random(seed)

    # --- stores -----------------------------------------------------------
    stores = []
    used_names = set()
    for i in range(1, n_stores + 1):
        while True:
            name = f"{rng.choice(CITY_WORDS)} {rng.choice(CITY_WORDS)}"
            if name not in used_names and name.split()[0] != name.split()[1]:
                used_names.add(name)
                break
        fmt = rng.choices(list(FORMATS), weights=[5, 4, 1])[0]
        stores.append({
            "store_id": f"S{i:03d}",
            "store_name": name,
            "region": rng.choice(REGIONS),
            "format": fmt,
            "opened_year": rng.randint(1998, 2023),
        })
    # ~8% of stores have a shrinkage problem (theft, process, waste...)
    problem_stores = {s["store_id"] for s in rng.sample(stores, max(1, n_stores // 12))}

    # --- products ---------------------------------------------------------
    products = []
    for dept, (cost, markup, _) in DEPARTMENTS.items():
        for j in range(1, products_per_dept + 1):
            unit_cost = round(cost * rng.uniform(0.6, 1.6), 2)
            products.append({
                "sku": f"{dept[:3].upper()}-{j:03d}",
                "product_name": f"{dept} item {j}",
                "department": dept,
                "unit_cost": unit_cost,
                "unit_price": round(unit_cost * (1 + markup) * rng.uniform(0.95, 1.05), 2),
            })

    # --- monthly inventory counts (aggregated per store x department) ---------
    months = months_back(n_months, end)
    counts = []
    for store in stores:
        size = FORMATS[store["format"]]
        for month in months:
            for dept, (cost, _, base_rate) in DEPARTMENTS.items():
                expected_units = int(rng.gauss(4000, 600) * size)
                rate = base_rate * rng.uniform(0.7, 1.3)
                if store["store_id"] in problem_stores:
                    rate *= rng.uniform(2.0, 3.5)
                shrink_units = max(0, int(expected_units * rate))
                counts.append({
                    "store_id": store["store_id"],
                    "month": month.isoformat(),
                    "department": dept,
                    "expected_units": expected_units,
                    "counted_units": expected_units - shrink_units,
                    "shrink_units": shrink_units,
                    "expected_value": round(expected_units * cost, 2),
                    "shrink_value": round(shrink_units * cost, 2),
                })

    # --- monthly P&L --------------------------------------------------------
    region_cost_factor = {r: rng.uniform(0.95, 1.08) for r in REGIONS}
    shrink_by_store_month = {}
    for row in counts:
        key = (row["store_id"], row["month"])
        shrink_by_store_month[key] = shrink_by_store_month.get(key, 0) + row["shrink_value"]

    pnl = []
    for store in stores:
        size = FORMATS[store["format"]]
        for month in months:
            seasonality = 1.15 if month.month in (11, 12) else (0.92 if month.month in (1, 2) else 1.0)
            revenue = rng.gauss(420_000, 40_000) * size * seasonality
            cogs = revenue * rng.uniform(0.68, 0.73)
            shrink = shrink_by_store_month[(store["store_id"], month.isoformat())]
            staff = revenue * rng.uniform(0.09, 0.12) * region_cost_factor[store["region"]]
            rent = 18_000 * size * region_cost_factor[store["region"]]
            other = revenue * rng.uniform(0.03, 0.05)
            ebit = revenue - cogs - shrink - staff - rent - other
            pnl.append({
                "store_id": store["store_id"],
                "month": month.isoformat(),
                "revenue": round(revenue, 2),
                "cogs": round(cogs, 2),
                "shrink_cost": round(shrink, 2),
                "staff_cost": round(staff, 2),
                "rent": round(rent, 2),
                "other_opex": round(other, 2),
                "ebit": round(ebit, 2),
            })

    return stores, products, counts, pnl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stores", type=int, default=40)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--products-per-dept", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--end-month", default="2026-09", help="YYYY-MM of the last month")
    parser.add_argument("--out", default=str(Path(__file__).parent / "sample"))
    args = parser.parse_args()

    y, m = map(int, args.end_month.split("-"))
    stores, products, counts, pnl = generate(args.stores, args.months, args.products_per_dept, args.seed, date(y, m, 1))

    out = Path(args.out)
    for name, rows in [("stores", stores), ("products", products),
                       ("inventory_counts", counts), ("pnl_monthly", pnl)]:
        write_csv(out / f"{name}.csv", rows)
        print(f"{name:17s} {len(rows):>7,} rows -> {out / (name + '.csv')}")


if __name__ == "__main__":
    main()
