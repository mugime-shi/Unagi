#!/usr/bin/env python3
"""
Build a feature matrix from historical data and print summary stats.

Usage:
    python -m scripts.build_feature_matrix --days 90 --area SE3

Outputs CSV to stdout (redirect with > features.csv).
"""

import argparse
import csv
import sys
from datetime import date, timedelta

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix


def main():
    parser = argparse.ArgumentParser(description="Build feature matrix for ML training")
    parser.add_argument("--days", type=int, default=90, help="Days of history (default: 90)")
    parser.add_argument("--area", type=str, default="SE3", help="Bidding area (default: SE3)")
    parser.add_argument("--csv", action="store_true", help="Output CSV to stdout")
    args = parser.parse_args()

    end_date = date.today() - timedelta(days=1)  # yesterday (fully settled)
    start_date = end_date - timedelta(days=args.days - 1)

    print(f"Building features: {start_date} → {end_date} ({args.days} days), area={args.area}",
          file=sys.stderr)

    db = SessionLocal()
    try:
        rows = build_feature_matrix(db, start_date, end_date, area=args.area)
    finally:
        db.close()

    if not rows:
        print("No data found. Run backfill first.", file=sys.stderr)
        sys.exit(1)

    # Summary stats
    n_rows = len(rows)
    n_nulls = {col: sum(1 for r in rows if r.get(col) is None) for col in FEATURE_COLS}
    non_null_cols = [c for c, n in n_nulls.items() if n == 0]
    partial_cols = {c: n for c, n in n_nulls.items() if 0 < n < n_rows}
    empty_cols = [c for c, n in n_nulls.items() if n == n_rows]

    print(f"\nRows: {n_rows} ({n_rows // 24} days × 24 hours)", file=sys.stderr)
    print(f"Features complete (0 nulls): {len(non_null_cols)}/{len(FEATURE_COLS)}", file=sys.stderr)
    if partial_cols:
        print(f"Features partial: {partial_cols}", file=sys.stderr)
    if empty_cols:
        print(f"Features empty (all null): {empty_cols}", file=sys.stderr)

    prices = [r[TARGET_COL] for r in rows]
    print(f"Price range: {min(prices):.4f} – {max(prices):.4f} SEK/kWh", file=sys.stderr)
    print(f"Price mean:  {sum(prices) / len(prices):.4f} SEK/kWh", file=sys.stderr)

    if args.csv:
        cols = ["date", "hour", TARGET_COL] + FEATURE_COLS
        writer = csv.DictWriter(sys.stdout, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
