"""Deterministic generator for the synthetic investment portfolio (data/portfolio.csv).

ILLUSTRATIVE DATA. The portfolio is designed, not observed: a barbell of
2020-21 low coupons bought at a premium (held to maturity) and 2023-25
production coupons (available for sale), plus Treasuries. It does not
represent the holdings of any institution.

The random seed is fixed, so the file is reproducible:  python scripts/generate_portfolio.py
"""

import csv
import random
from pathlib import Path

SEED = 20261110
AS_OF = (2026, 11)
OUT = Path(__file__).resolve().parents[1] / "data" / "portfolio.csv"
rng = random.Random(SEED)

# (asset_type, term_years, coupons, origination years, pools, current face $mm, designation)
BUCKETS = [
    ("MBS_30Y", 30, [2.0, 2.5, 3.0], [2020, 2021], 32, 3775, "HTM"),
    ("MBS_30Y", 30, [3.5, 4.0, 4.5], [2019, 2022], 12, 1275, "HTM"),
    ("MBS_30Y", 30, [5.5, 6.0, 6.5], [2023, 2024, 2025], 22, 1950, "AFS"),
    ("MBS_15Y", 15, [1.5, 2.0, 2.5], [2020, 2021], 8, 900, "HTM"),
    ("MBS_15Y", 15, [4.5, 5.0, 5.5], [2023, 2024, 2025], 6, 600, "AFS"),
]
# (term, origination year) -> range of the pool factor today
FACTOR = {
    (30, 2019): (0.35, 0.55), (30, 2020): (0.68, 0.78), (30, 2021): (0.74, 0.84),
    (30, 2022): (0.80, 0.88), (30, 2023): (0.74, 0.86), (30, 2024): (0.82, 0.93),
    (30, 2025): (0.92, 0.98), (15, 2020): (0.52, 0.62), (15, 2021): (0.58, 0.68),
    (15, 2023): (0.76, 0.84), (15, 2024): (0.84, 0.91), (15, 2025): (0.92, 0.97),
}  # fmt: skip
# origination year -> range of the book price (amortised cost per 100 face)
BOOK_PRICE = {
    2019: (102.0, 104.0), 2020: (102.0, 104.5), 2021: (101.0, 103.5), 2022: (95.5, 99.5),
    2023: (99.0, 101.5), 2024: (99.5, 102.0), 2025: (100.0, 102.5),
}  # fmt: skip
# Treasuries: (original tenor, coupon, purchase year, face $mm, book price)
TREASURIES = [
    (2, 3.875, 2025, 150, 99.80), (3, 4.000, 2025, 200, 100.15), (5, 4.125, 2024, 250, 99.40),
    (5, 3.750, 2025, 200, 99.10), (7, 4.250, 2024, 200, 100.60), (7, 4.000, 2025, 150, 99.55),
    (10, 4.375, 2024, 200, 100.90), (10, 4.250, 2025, 150, 99.70),
]  # fmt: skip


def split(total: float, n: int) -> list[float]:
    """Split ``total`` into n random pool sizes that add back to the total."""
    weights = [rng.uniform(0.5, 1.8) for _ in range(n)]
    sizes = [round(total * w / sum(weights), 1) for w in weights]
    sizes[-1] = round(total - sum(sizes[:-1]), 1)
    return sizes


def main() -> None:
    rows, counter = [], {}
    for asset_type, term, coupons, years, n_pools, total, designation in BUCKETS:
        for face in split(total, n_pools):
            coupon, year = rng.choice(coupons), rng.choice(years)
            agency = rng.choices(["FNMA", "FHLMC", "GNMA"], [45, 35, 20] if term == 30 else [55, 45, 0])[0]
            wala = (AS_OF[0] - year) * 12 + AS_OF[1] - rng.randint(1, 12)
            wac = coupon + (rng.uniform(0.45, 0.60) if agency == "GNMA" else rng.uniform(0.55, 0.95))
            factor = rng.uniform(*FACTOR[(term, year)])
            book_price = rng.uniform(*BOOK_PRICE[year])
            prefix = {"FNMA": "FN", "FHLMC": "FR", "GNMA": "G2"}[agency]
            counter[prefix] = counter.get(prefix, 0) + 1
            rows.append(
                {
                    "position_id": f"{prefix}{term}-{coupon:.1f}-{counter[prefix]:03d}",
                    "asset_type": asset_type,
                    "agency": agency,
                    "term_years": term,
                    "coupon": coupon,
                    "wac": round(wac, 3),
                    "orig_year": year,
                    "wala_months": wala,
                    "wam_months": term * 12 - wala - rng.randint(0, 3),
                    "original_face_mm": round(face / factor, 1),
                    "factor": round(factor, 4),
                    "current_face_mm": face,
                    "book_price": round(book_price, 3),
                    "designation": designation,
                    "avg_loan_size_k": rng.randrange(210, 430, 5),
                }
            )

    for i, (tenor, coupon, year, face, book_price) in enumerate(TREASURIES, 1):
        held = (AS_OF[0] - year) * 12 + AS_OF[1] - rng.randint(2, 11)
        rows.append(
            {
                "position_id": f"UST{tenor}-{coupon:.3f}-{i:03d}",
                "asset_type": "UST",
                "agency": "UST",
                "term_years": tenor,
                "coupon": coupon,
                "wac": "",
                "orig_year": year,
                "wala_months": held,  # months since issue
                "wam_months": tenor * 12 - held,  # months to maturity
                "original_face_mm": face,
                "factor": 1.0,
                "current_face_mm": face,
                "book_price": book_price,
                "designation": "AFS",
                "avg_loan_size_k": "",
            }
        )

    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    total = sum(r["current_face_mm"] for r in rows)
    print(f"wrote {OUT} ({len(rows)} positions, ${total:,.1f}mm current face)")


if __name__ == "__main__":
    main()
