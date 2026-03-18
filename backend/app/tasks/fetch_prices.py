"""
Daily price fetch task — runs as a CLI script or Lambda handler.

CLI usage:
    python -m app.tasks.fetch_prices                  # today + tomorrow (spot prices)
    python -m app.tasks.fetch_prices --date 2026-03-11
    python -m app.tasks.fetch_prices --backfill 30    # past 30 days (spot prices)
    python -m app.tasks.fetch_prices --backfill 365 --generation  # 1 year generation mix

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
from app.services.balancing_service import fetch_and_store_balancing, get_balancing_for_date
from app.services.entsoe_client import EntsoEError
from app.services.esett_client import BalancingError
from app.services.generation_service import fetch_and_store_generation, get_generation_for_date
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
# Balancing (imbalance) price fetch — ENTSO-E A85
# ---------------------------------------------------------------------------

def fetch_balancing_date(target_date: date, area: str = "SE3") -> dict:
    """
    Fetch and store imbalance prices for target_date. Returns a result dict.
    Imbalance prices are settled continuously; yesterday is always fully available.
    Today's data is available with a ~1-2 hour lag (partial day during the day).
    """
    db = SessionLocal()
    try:
        existing = get_balancing_for_date(db, target_date, area)
        if existing:
            log.info("SKIP balancing %s — %d rows already in DB", target_date, len(existing))
            return {"date": target_date.isoformat(), "market": "balancing", "status": "cached", "rows": len(existing)}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_and_store_balancing(db, target_date, area)
                log.info("OK   balancing %s — %d rows saved (attempt %d)", target_date, len(rows), attempt)
                return {"date": target_date.isoformat(), "market": "balancing", "status": "ok", "rows": len(rows)}
            except BalancingError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN balancing %s — attempt %d/%d: %s. Retry in %ds…",
                        target_date, attempt, MAX_RETRIES, e, wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL balancing %s — all %d attempts failed: %s", target_date, MAX_RETRIES, e)

        return {"date": target_date.isoformat(), "market": "balancing", "status": "error", "error": str(last_error)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Generation mix (ENTSO-E A75) fetch
# ---------------------------------------------------------------------------

def fetch_generation_date(target_date: date, area: str = "SE3") -> dict:
    """
    Fetch and store generation mix for target_date. Returns a result dict.
    """
    db = SessionLocal()
    try:
        existing = get_generation_for_date(db, target_date, area)
        if existing:
            log.info("SKIP generation %s %s — %d rows already in DB", target_date, area, len(existing))
            return {"date": target_date.isoformat(), "market": "generation", "status": "cached", "rows": len(existing)}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_and_store_generation(db, target_date, area)
                log.info("OK   generation %s %s — %d rows saved (attempt %d)", target_date, area, len(rows), attempt)
                return {"date": target_date.isoformat(), "market": "generation", "status": "ok", "rows": len(rows)}
            except EntsoEError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN generation %s %s — attempt %d/%d: %s. Retry in %ds…",
                        target_date, area, attempt, MAX_RETRIES, e, wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL generation %s %s — all %d attempts failed: %s", target_date, area, MAX_RETRIES, e)

        return {"date": target_date.isoformat(), "market": "generation", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def backfill_generation(days: int, area: str = "SE3") -> list[dict]:
    """Backfill generation mix data for the past N days."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    log.info("Backfill generation: fetching %d days (%s → %s) for %s", days, dates[0], dates[-1], area)
    return [fetch_generation_date(d, area) for d in dates]


# ---------------------------------------------------------------------------
# Lambda handler (EventBridge trigger)
# ---------------------------------------------------------------------------

ALL_AREAS = ["SE1", "SE2", "SE3", "SE4"]


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda entry point.
    event = {}                                      → today + tomorrow + balancing + generation for ALL areas
    event = {"area": "SE3"}                        → today + tomorrow for a specific area
    event = {"backfill_days": N}                   → past N days spot prices for ALL areas
    event = {"backfill_days": N, "area": "SE3"}   → past N days for one area
    event = {"backfill_generation": N}             → past N days generation mix (A75) for ALL areas
    event = {"backfill_generation": N, "area": "SE3"} → generation backfill for one area
    event = {"date": "YYYY-MM-DD"}                 → single date for ALL areas
    event = {"predict_only": true}                  → record predictions only (morning cron)
    """
    explicit_area = event.get("area")
    areas = [explicit_area] if explicit_area else ALL_AREAS

    # Morning prediction-only run (06:00 CET) — record forecasts before day-ahead publication
    if event.get("predict_only"):
        log.info("predict_only mode — recording tomorrow's predictions for %s", areas)
        _record_predictions(areas)
        return {"statusCode": 200, "mode": "predict_only", "areas": areas}

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

    # Fetch balancing (imbalance) prices and generation mix for today/yesterday.
    # Skip during backfill runs (use --generation flag for generation backfill).
    is_daily_run = "backfill_days" not in event and "date" not in event
    if is_daily_run:
        today = date.today()
        yesterday = today - timedelta(days=1)
        for area in areas:
            for bal_date in [yesterday, today]:
                bal_result = fetch_balancing_date(bal_date, area)
                all_results.append(bal_result)
            # Generation mix (A75) — accumulate daily for ML feature pipeline
            for gen_date in [yesterday, today]:
                gen_result = fetch_generation_date(gen_date, area)
                all_results.append(gen_result)

    # Generation backfill via Lambda event
    if event.get("backfill_generation"):
        gen_days = int(event["backfill_generation"])
        for area in areas:
            gen_results = backfill_generation(gen_days, area)
            all_results.extend(gen_results)

    failed = [r for r in all_results if r["status"] == "error"]

    # Record forecast predictions and fill yesterday's actuals for accuracy tracking.
    if is_daily_run:
        _record_forecasts_and_actuals(areas)

    # Send push notifications for tomorrow's prices after the daily scheduled run.
    if is_daily_run:
        _send_notifications(areas)

    return {
        "statusCode": 200 if not failed else 207,
        "results": all_results,
    }


def _record_predictions(areas: list[str]) -> None:
    """
    Record tomorrow's predictions for both models (same_weekday_avg + lgbm).

    Called by the morning cron (06:00 CET) BEFORE day-ahead prices are published (~13:00 CET),
    so predictions are genuine forecasts, not post-hoc reconstructions.
    Also called by the afternoon run as a fallback (idempotent upsert).
    """
    db = SessionLocal()
    try:
        from app.services.backtest_service import record_predictions
        from app.services.ml_forecast_service import build_lgbm_forecast
        from app.services.price_service import build_forecast, get_prices_for_date_range

        today = date.today()
        tomorrow = today + timedelta(days=1)

        for area in areas:
            # same_weekday_avg
            try:
                hist_start = tomorrow - timedelta(weeks=8)
                hist_end = today
                rows = get_prices_for_date_range(db, hist_start, hist_end, area=area)
                result = build_forecast(rows, tomorrow)
                if result.get("slots"):
                    n = record_predictions(db, tomorrow, area, "same_weekday_avg", result["slots"])
                    log.info("Recorded %d same_weekday_avg predictions for %s %s", n, tomorrow, area)
            except Exception as exc:
                log.warning("same_weekday_avg record failed for %s %s: %s", tomorrow, area, exc)
                db.rollback()

            # lgbm
            try:
                result = build_lgbm_forecast(db, tomorrow, area=area)
                if result.get("slots") and result["slots"][0].get("avg_sek_kwh") is not None:
                    n = record_predictions(db, tomorrow, area, "lgbm", result["slots"])
                    log.info("Recorded %d lgbm predictions for %s %s", n, tomorrow, area)
            except Exception as exc:
                log.warning("lgbm record failed for %s %s: %s", tomorrow, area, exc)
                db.rollback()
    finally:
        db.close()


def _fill_actuals(areas: list[str]) -> None:
    """Fill yesterday's actuals in forecast_accuracy (so MAE/RMSE can be scored)."""
    db = SessionLocal()
    try:
        from app.services.backtest_service import fill_actuals

        yesterday = date.today() - timedelta(days=1)
        for area in areas:
            try:
                n = fill_actuals(db, yesterday, area)
                if n:
                    log.info("Filled %d actuals for %s %s", n, yesterday, area)
            except Exception as exc:
                log.warning("fill_actuals failed for %s %s: %s", yesterday, area, exc)
                db.rollback()
    finally:
        db.close()


def _record_forecasts_and_actuals(areas: list[str]) -> None:
    """
    After the daily price fetch (13:30 CET):
    1. Fill yesterday's actuals (answer-check).
    2. Record predictions as fallback (morning cron should have already recorded them).
    """
    _fill_actuals(areas)
    _record_predictions(areas)


def _send_notifications(areas: list[str]) -> None:
    """Send Web Push + Telegram alerts for each area after a daily price fetch."""
    db = SessionLocal()
    try:
        from app.services.notify_service import notify_subscribers
        from app.services.telegram_service import send_telegram_alert
        for area in areas:
            try:
                notify_subscribers(db, area)
            except Exception as exc:
                log.warning("Web Push error for %s: %s", area, exc)
            try:
                # Telegram is single-user: only send once (SE3 or first area)
                if area == areas[0]:
                    send_telegram_alert(db, area)
            except Exception as exc:
                log.warning("Telegram error for %s: %s", area, exc)
    finally:
        db.close()


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
    parser.add_argument(
        "--generation", action="store_true",
        help="Fetch generation mix (ENTSO-E A75) instead of spot prices",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.generation:
        # Generation mix mode
        if args.backfill:
            results = backfill_generation(args.backfill, args.area)
        elif args.date:
            results = [fetch_generation_date(args.date, args.area)]
        else:
            results = [fetch_generation_date(date.today(), args.area)]
    else:
        # Spot prices mode (default)
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
