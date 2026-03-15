"""
Daily price fetch task — runs as a CLI script or Lambda handler.

CLI usage:
    python -m app.tasks.fetch_prices                  # today + tomorrow
    python -m app.tasks.fetch_prices --date 2026-03-11
    python -m app.tasks.fetch_prices --backfill 30    # past 30 days

Lambda (EventBridge) usage:
    Handler: app.tasks.fetch_prices.lambda_handler
    Event:   {} (daily trigger) or {"backfill_days": 7}

Design:
- Retry up to MAX_RETRIES times with exponential back-off on ENTSO-E failures
- Logs each date result (rows saved / already cached / error)
- Exits with code 1 if ANY date permanently failed (useful for cron alerts)
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta

from app.config import settings
from app.db.database import SessionLocal
from app.services.entsoe_client import EntsoEError
from app.services.price_service import fetch_and_store, get_prices_for_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_SECONDS = 10  # doubles each attempt: 10 → 20 → 40


# ---------------------------------------------------------------------------
# Core fetch logic (single date, with retry)
# ---------------------------------------------------------------------------

def fetch_date(target_date: date, area: str = "SE3") -> dict:
    """
    Fetch and store prices for target_date. Returns a result dict.
    Retries up to MAX_RETRIES on ENTSO-E errors.
    """
    db = SessionLocal()
    try:
        # Skip if we already have data (idempotent guard)
        existing = get_prices_for_date(db, target_date, area)
        if existing:
            log.info("SKIP %s — %d rows already in DB", target_date, len(existing))
            return {"date": target_date.isoformat(), "status": "cached", "rows": len(existing)}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_and_store(db, target_date, area, api_key=settings.entsoe_api_key)
                log.info("OK   %s — %d rows saved (attempt %d)", target_date, len(rows), attempt)
                return {"date": target_date.isoformat(), "status": "ok", "rows": len(rows)}
            except EntsoEError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN %s — attempt %d/%d failed: %s. Retrying in %ds…",
                        target_date, attempt, MAX_RETRIES, e, wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL %s — all %d attempts failed: %s", target_date, MAX_RETRIES, e)

        return {"date": target_date.isoformat(), "status": "error", "error": str(last_error)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------

def fetch_dates(dates: list[date], area: str = "SE3") -> list[dict]:
    results = [fetch_date(d, area) for d in dates]
    ok = sum(1 for r in results if r["status"] in ("ok", "cached"))
    err = sum(1 for r in results if r["status"] == "error")
    log.info("Done — %d ok/cached, %d errors (total %d dates)", ok, err, len(dates))
    return results


def backfill(days: int, area: str = "SE3") -> list[dict]:
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    log.info("Backfill: fetching %d days (%s → %s)", days, dates[0], dates[-1])
    return fetch_dates(dates, area)


# ---------------------------------------------------------------------------
# Lambda handler (EventBridge trigger)
# ---------------------------------------------------------------------------

ALL_AREAS = ["SE1", "SE2", "SE3", "SE4"]


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda entry point.
    event = {}                              → today + tomorrow for ALL areas (SE1-SE4)
    event = {"area": "SE3"}                → today + tomorrow for a specific area
    event = {"backfill_days": N}           → past N days for ALL areas
    event = {"backfill_days": N, "area": "SE3"} → past N days for one area
    event = {"date": "YYYY-MM-DD"}         → single date for ALL areas
    """
    explicit_area = event.get("area")
    areas = [explicit_area] if explicit_area else ALL_AREAS

    all_results = []
    for area in areas:
        if "backfill_days" in event:
            results = backfill(int(event["backfill_days"]), area)
        elif "date" in event:
            results = [fetch_date(date.fromisoformat(event["date"]), area)]
        else:
            today = date.today()
            tomorrow = today + timedelta(days=1)
            results = fetch_dates([today, tomorrow], area)
        all_results.extend(results)

    failed = [r for r in all_results if r["status"] == "error"]
    return {
        "statusCode": 200 if not failed else 207,
        "results": all_results,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch SE3 day-ahead prices from ENTSO-E and save to DB.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--date", type=date.fromisoformat, metavar="YYYY-MM-DD",
        help="Fetch prices for a specific date (default: today + tomorrow)",
    )
    group.add_argument(
        "--backfill", type=int, metavar="N",
        help="Fetch prices for the past N days",
    )
    parser.add_argument(
        "--area", default=settings.default_area,
        help=f"Price area code (default: {settings.default_area})",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.backfill:
        results = backfill(args.backfill, args.area)
    elif args.date:
        results = [fetch_date(args.date, args.area)]
    else:
        today = date.today()
        tomorrow = today + timedelta(days=1)
        results = fetch_dates([today, tomorrow], args.area)

    failed = [r for r in results if r["status"] == "error"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
