#!/usr/bin/env python3
"""
Smoke test: fetch today's and tomorrow's SE3 spot prices and print to console.

Usage (from backend/ directory):
    python scripts/fetch_prices_smoke.py
    python scripts/fetch_prices_smoke.py --date 2026-03-09

Requires ENTSOE_API_KEY in backend/.env (or exported in shell).
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Add backend/ to sys.path so `app` package is importable without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from app.services.entsoe_client import EntsoEError, fetch_day_ahead_prices  # noqa: E402


def print_prices(target: date) -> None:
    print(f"\n=== SE3 day-ahead prices for {target} ===")
    try:
        prices = fetch_day_ahead_prices(target_date=target)
    except EntsoEError as e:
        print(f"ERROR: {e}")
        return

    print(f"{'Time (UTC)':<20} {'EUR/MWh':>10} {'SEK/kWh':>10} {'Res':>6}")
    print("-" * 52)
    for p in prices:
        time_str = p.timestamp_utc.strftime("%Y-%m-%d %H:%M")
        print(f"{time_str:<20} {p.price_eur_mwh:>10.2f} {p.price_sek_kwh:>10.4f} {p.resolution:>6}")

    sek_values = [p.price_sek_kwh for p in prices]
    print("-" * 52)
    print(f"{'Min':>30}: {min(sek_values):.4f} SEK/kWh")
    print(f"{'Max':>30}: {max(sek_values):.4f} SEK/kWh")
    print(f"{'Average':>30}: {sum(sek_values) / len(sek_values):.4f} SEK/kWh")
    print(f"{'Slots':>30}: {len(prices)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch SE3 spot prices from ENTSO-E")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="Target date in YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--tomorrow",
        action="store_true",
        help="Fetch tomorrow's prices (available after ~13:00 CET)",
    )
    args = parser.parse_args()

    target = args.date + timedelta(days=1) if args.tomorrow else args.date
    print_prices(target)


if __name__ == "__main__":
    main()
