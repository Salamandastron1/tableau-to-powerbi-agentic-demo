"""Reproduce the fictional sales fixture. No customer or patient data."""
import argparse
import calendar
import csv
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("order_date", "region", "territory", "product_line", "sku", "units", "revenue")
REGIONS = {
    "East": ("Atlantic", "Northeast"),
    "Central": ("Great Lakes", "Plains"),
    "South": ("Southeast", "Gulf"),
    "West": ("Pacific", "Mountain"),
}
PRODUCTS = {"Hips": 2400, "Knees": 3100, "Spine": 1900, "Trauma": 850, "Extremities": 650}


def generate(path: Path, rows: int = 2000, seed: int = 42) -> None:
    if rows < 480:
        raise ValueError("Use at least 480 rows to cover every month, product line and region.")
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for i in range(rows):
            year, month = 2024 + (i % 24) // 12, 1 + i % 12
            product = list(PRODUCTS)[(i // 24) % len(PRODUCTS)]
            region = list(REGIONS)[(i // 120) % len(REGIONS)]
            units = rng.randint(1, 16)
            price = Decimal(PRODUCTS[product]) * Decimal(rng.randint(85, 115)) / 100
            revenue = (price * units).quantize(Decimal("0.01"))
            writer.writerow({
                "order_date": date(year, month, rng.randint(1, calendar.monthrange(year, month)[1])).isoformat(),
                "region": region,
                "territory": rng.choice(REGIONS[region]),
                "product_line": product,
                "sku": f"{product[:3].upper()}-{rng.randint(1, 16):03d}",
                "units": units,
                "revenue": str(revenue),
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sample" / "data" / "ortho_sales.csv")
    parser.add_argument("--rows", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.output, args.rows, args.seed)
    print(f"Generated {args.rows} synthetic rows: {args.output}")


if __name__ == "__main__":
    main()
