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
                        target_date,
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
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
                        target_date,
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
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
                        target_date,
                        area,
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
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
# Load forecast (ENTSO-E A65) fetch
# ---------------------------------------------------------------------------


def fetch_load_forecast_date(target_date: date, area: str = "SE3") -> dict:
    """
    Fetch and store load forecast for target_date. Returns a result dict.
    """
    from app.services.load_forecast_service import fetch_and_store_load_forecast, get_load_forecast_for_date

    db = SessionLocal()
    try:
        existing = get_load_forecast_for_date(db, target_date, area)
        if existing:
            log.info("SKIP load_forecast %s %s — %d rows already in DB", target_date, area, len(existing))
            return {
                "date": target_date.isoformat(),
                "market": "load_forecast",
                "status": "cached",
                "rows": len(existing),
            }

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_and_store_load_forecast(db, target_date, area)
                log.info("OK   load_forecast %s %s — %d rows saved (attempt %d)", target_date, area, len(rows), attempt)
                return {"date": target_date.isoformat(), "market": "load_forecast", "status": "ok", "rows": len(rows)}
            except EntsoEError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN load_forecast %s %s — attempt %d/%d: %s. Retry in %ds…",
                        target_date,
                        area,
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    log.error(
                        "FAIL load_forecast %s %s — all %d attempts failed: %s", target_date, area, MAX_RETRIES, e
                    )

        return {"date": target_date.isoformat(), "market": "load_forecast", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def backfill_load_forecast(days: int, area: str = "SE3") -> list[dict]:
    """Backfill load forecast data for the past N days."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    log.info("Backfill load_forecast: fetching %d days (%s → %s) for %s", days, dates[0], dates[-1], area)
    return [fetch_load_forecast_date(d, area) for d in dates]


# ---------------------------------------------------------------------------
# DE-LU spot price (ENTSO-E A44) fetch
# ---------------------------------------------------------------------------


def fetch_de_price_date(target_date: date) -> dict:
    """Fetch and store DE-LU day-ahead spot prices for target_date."""
    from app.services.de_price_service import fetch_and_store_de_prices, get_de_prices_for_date

    db = SessionLocal()
    try:
        existing = get_de_prices_for_date(db, target_date)
        if existing:
            log.info("SKIP de_price %s — %d rows already in DB", target_date, len(existing))
            return {"date": target_date.isoformat(), "market": "de_price", "status": "cached", "rows": len(existing)}

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                rows = fetch_and_store_de_prices(db, target_date)
                log.info("OK   de_price %s — %d rows saved (attempt %d)", target_date, len(rows), attempt)
                return {"date": target_date.isoformat(), "market": "de_price", "status": "ok", "rows": len(rows)}
            except EntsoEError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN de_price %s — attempt %d/%d: %s. Retry in %ds…",
                        target_date,
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL de_price %s — all %d attempts failed: %s", target_date, MAX_RETRIES, e)

        return {"date": target_date.isoformat(), "market": "de_price", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def backfill_de_prices(days: int) -> list[dict]:
    """Backfill DE-LU spot prices for the past N days."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    log.info("Backfill de_price: fetching %d days (%s → %s)", days, dates[0], dates[-1])
    return [fetch_de_price_date(d) for d in dates]


# ---------------------------------------------------------------------------
# Gas price (Bundesnetzagentur/THE) fetch
# ---------------------------------------------------------------------------


def fetch_gas_prices_range(start_date: date, end_date: date) -> dict:
    """Fetch and store THE gas prices for [start_date, end_date]."""
    from app.services.bundesnetzagentur_client import GasPriceError
    from app.services.gas_price_service import fetch_and_store_gas_prices

    db = SessionLocal()
    try:
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                count = fetch_and_store_gas_prices(db, start_date, end_date)
                log.info("OK   gas_price %s → %s — %d rows saved (attempt %d)", start_date, end_date, count, attempt)
                return {"market": "gas_price", "status": "ok", "rows": count}
            except GasPriceError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning("WARN gas_price — attempt %d/%d: %s. Retry in %ds…", attempt, MAX_RETRIES, e, wait)
                    time.sleep(wait)
                else:
                    log.error("FAIL gas_price — all %d attempts failed: %s", MAX_RETRIES, e)

        return {"market": "gas_price", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def backfill_gas_prices(days: int) -> list[dict]:
    """Backfill gas prices for the past N days."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    log.info("Backfill gas_price: fetching %d days (%s → %s)", days, start, today)
    return [fetch_gas_prices_range(start, today)]


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
    event = {"predict_only": true}                  → record predictions only (manual)
    event = {"midnight_predict": true}              → nightly data completion + ML prediction
    """
    explicit_area = event.get("area")
    areas = [explicit_area] if explicit_area else ALL_AREAS

    # Nightly prediction run (00:05 UTC = 01:05 CET / 02:05 CEST).
    # By this time, yesterday's generation + balancing data is fully settled.
    # Re-fetch those, grab fresh weather forecast, then record ML predictions.
    if event.get("midnight_predict"):
        yesterday = date.today() - timedelta(days=1)
        tomorrow = date.today() + timedelta(days=1)
        log.info("midnight_predict — completing %s data, predicting %s, areas=%s", yesterday, tomorrow, areas)

        results = []
        # Re-fetch yesterday's generation + balancing (full 24h now available)
        # Fetch tomorrow's load forecast (A65, needed for ML features)
        for area in areas:
            results.append(fetch_generation_date(yesterday, area))
            results.append(fetch_balancing_date(yesterday, area))
            results.append(fetch_load_forecast_date(tomorrow, area))

        # Weather forecast (issued_date = today, used by LightGBM for tomorrow)
        results.append(_fetch_weather_forecast())

        # Gas prices (THE settlement) — needed for ML gas_price features
        results.append(_fetch_gas_prices())

        # Record ML predictions for tomorrow
        _record_predictions(areas)

        failed = [r for r in results if r["status"] == "error"]
        return {
            "statusCode": 200 if not failed else 207,
            "mode": "midnight_predict",
            "tomorrow": tomorrow.isoformat(),
            "areas": areas,
            "results": results,
        }

    # Prediction-only run (manual invocation, no scheduled cron)
    # Accepts optional "target_date" (YYYY-MM-DD) to predict a specific date instead of tomorrow.
    if event.get("predict_only"):
        target_date = date.fromisoformat(event["target_date"]) if event.get("target_date") else None
        label = target_date.isoformat() if target_date else "tomorrow"
        log.info("predict_only mode — recording %s predictions for %s", label, areas)
        _record_predictions(areas, target_date=target_date)
        return {"statusCode": 200, "mode": "predict_only", "target_date": label, "areas": areas}

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

    # Fetch balancing (imbalance) prices, generation mix, and weather for today/yesterday.
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
            # Load forecast (A65) — today + tomorrow for ML features
            for lf_date in [today, tomorrow]:
                lf_result = fetch_load_forecast_date(lf_date, area)
                all_results.append(lf_result)

        # Weather data (SMHI) — once per run (not per area, stations are fixed)
        weather_result = _fetch_weather()
        all_results.append(weather_result)

        # Weather forecast (Open-Meteo) — wind/temp/radiation for ML features
        forecast_result = _fetch_weather_forecast()
        all_results.append(forecast_result)

        # Gas prices (THE settlement) — once per run (not per area, EU-wide price)
        gas_result = _fetch_gas_prices()
        all_results.append(gas_result)

    # Generation backfill via Lambda event
    if event.get("backfill_generation"):
        gen_days = int(event["backfill_generation"])
        for area in areas:
            gen_results = backfill_generation(gen_days, area)
            all_results.extend(gen_results)

    # Load forecast backfill via Lambda event
    if event.get("backfill_load_forecast"):
        lf_days = int(event["backfill_load_forecast"])
        for area in areas:
            lf_results = backfill_load_forecast(lf_days, area)
            all_results.extend(lf_results)

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


def _fetch_weather() -> dict:
    """
    Fetch latest weather data from SMHI and store to DB.

    SMHI only offers 'latest-day' (~24h) or 'latest-months' (~4mo) periods.
    We fetch 'latest-months' but filter to the last 7 days before storing,
    so a week of missed runs can be recovered without writing ~3000 rows daily.
    """
    db = SessionLocal()
    try:
        from datetime import datetime, timezone

        from app.services.smhi_client import fetch_weather_slots, store_weather_slots

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                slots = fetch_weather_slots()  # fetches latest-months from SMHI
                recent = [s for s in slots if s.timestamp_utc >= cutoff]
                count = store_weather_slots(db, recent)
                log.info("OK   weather — %d rows stored/updated (attempt %d)", count, attempt)
                return {"market": "weather", "status": "ok", "rows": count}
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN weather — attempt %d/%d: %s. Retry in %ds…",
                        attempt,
                        MAX_RETRIES,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL weather — all %d attempts failed: %s", MAX_RETRIES, last_error)

        return {"market": "weather", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def _fetch_weather_forecast() -> dict:
    """Fetch weather forecast from Open-Meteo for ML features."""
    db = SessionLocal()
    try:
        from app.services.openmeteo_client import fetch_and_store as openmeteo_fetch_and_store

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                count = openmeteo_fetch_and_store(db, forecast_days=2)
                log.info("OK   weather forecast — %d rows stored (attempt %d)", count, attempt)
                return {"market": "weather_forecast", "status": "ok", "rows": count}
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning(
                        "WARN weather forecast — attempt %d/%d: %s. Retry in %ds…",
                        attempt,
                        MAX_RETRIES,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    log.error("FAIL weather forecast — all %d attempts failed: %s", MAX_RETRIES, last_error)

        return {"market": "weather_forecast", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def _fetch_gas_prices() -> dict:
    """
    Fetch THE gas settlement prices and store to DB.

    Uses the Preismonitor JSON API (returns current gas-day only).
    Accumulated daily to build up the gas price time series for ML features.
    Non-critical: pipeline continues even if this fails.
    """
    db = SessionLocal()
    try:
        from app.services.bundesnetzagentur_client import GasPriceError
        from app.services.gas_price_service import fetch_and_store_gas_prices

        today = date.today()
        start = today - timedelta(days=7)
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                count = fetch_and_store_gas_prices(db, start, today)
                log.info("OK   gas_price — %d rows stored (attempt %d)", count, attempt)
                return {"market": "gas_price", "status": "ok", "rows": count}
            except GasPriceError as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                    log.warning("WARN gas_price — attempt %d/%d: %s. Retry in %ds…", attempt, MAX_RETRIES, exc, wait)
                    time.sleep(wait)
                else:
                    log.error("FAIL gas_price — all %d attempts failed: %s", MAX_RETRIES, last_error)

        return {"market": "gas_price", "status": "error", "error": str(last_error)}
    finally:
        db.close()


def _record_predictions(areas: list[str], target_date: date | None = None) -> None:
    """
    Record predictions for both models (same_weekday_avg + lgbm).

    Called by the nightly cron (01:05 CET) with full previous-day data,
    and by the afternoon run as a fallback (idempotent upsert).
    If target_date is None, defaults to tomorrow.
    """
    db = SessionLocal()
    try:
        from app.services.backtest_service import record_predictions
        from app.services.ml_forecast_service import build_lgbm_forecast
        from app.services.price_service import build_forecast, get_prices_for_date_range

        target = target_date or (date.today() + timedelta(days=1))

        for area in areas:
            # same_weekday_avg
            try:
                hist_start = target - timedelta(weeks=8)
                hist_end = target - timedelta(days=1)
                rows = get_prices_for_date_range(db, hist_start, hist_end, area=area)
                result = build_forecast(rows, target)
                if result.get("slots"):
                    n = record_predictions(db, target, area, "same_weekday_avg", result["slots"])
                    log.info("Recorded %d same_weekday_avg predictions for %s %s", n, target, area)
            except Exception as exc:
                log.warning("same_weekday_avg record failed for %s %s: %s", target, area, exc)
                db.rollback()

            # lgbm
            try:
                result = build_lgbm_forecast(db, target, area=area)
                if result.get("slots") and result["slots"][0].get("avg_sek_kwh") is not None:
                    n = record_predictions(db, target, area, "lgbm", result["slots"])
                    log.info("Recorded %d lgbm predictions for %s %s", n, target, area)
            except Exception as exc:
                log.warning("lgbm record failed for %s %s: %s", target, area, exc)
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


def _check_model_degradation(areas: list[str]) -> None:
    """
    Check if the LGBM model has degraded (7d MAE > 1.5× 30d MAE).
    Sends a Telegram alert if degradation is detected.
    Called after fill_actuals so that the latest data is scored.
    """
    db = SessionLocal()
    try:
        from app.services.backtest_service import check_model_degradation
        from app.services.telegram_service import send_degradation_alert

        for area in areas:
            try:
                result = check_model_degradation(db, area=area)
                if result is None:
                    continue
                if result["degraded"]:
                    log.warning(
                        "Model degradation detected for %s: 7d MAE=%.4f, 30d MAE=%.4f, ratio=%.2f",
                        area,
                        result["mae_7d"],
                        result["mae_30d"],
                        result["ratio"],
                    )
                    send_degradation_alert(area, result)
                else:
                    log.info(
                        "Model health OK for %s: ratio=%.2f (threshold=%.1f)",
                        area,
                        result["ratio"],
                        result["threshold"],
                    )
            except Exception as exc:
                log.warning("Degradation check failed for %s: %s", area, exc)
    finally:
        db.close()


def _record_forecasts_and_actuals(areas: list[str]) -> None:
    """
    After the daily price fetch (13:30 CET):
    Fill yesterday's actuals (answer-check for MAE/RMSE scoring),
    then check for model degradation.
    Predictions are NOT re-recorded here — by 13:30 actual prices are
    already published, so post-hoc predictions would be meaningless.
    """
    _fill_actuals(areas)
    _check_model_degradation(areas)


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
        "--date",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="Fetch prices for a specific date (default: today + tomorrow)",
    )
    group.add_argument(
        "--backfill",
        type=int,
        metavar="N",
        help="Fetch prices for the past N days",
    )
    parser.add_argument(
        "--area",
        default=settings.default_area,
        help=f"Price area code (default: {settings.default_area})",
    )
    parser.add_argument(
        "--generation",
        action="store_true",
        help="Fetch generation mix (ENTSO-E A75) instead of spot prices",
    )
    parser.add_argument(
        "--load-forecast",
        action="store_true",
        help="Fetch load forecast (ENTSO-E A65) instead of spot prices",
    )
    parser.add_argument(
        "--de-price",
        action="store_true",
        help="Fetch DE-LU day-ahead prices (ENTSO-E A44) instead of SE spot prices",
    )
    parser.add_argument(
        "--gas-price",
        action="store_true",
        help="Fetch THE gas reference prices instead of spot prices",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not settings.is_local_db:
        log.warning("DATABASE_URL is not local: %s...", settings.database_url[:40])
        if input("Write to remote DB? [y/N] ").strip().lower() != "y":
            log.info("Aborted.")
            return 1

    if args.generation:
        # Generation mix mode
        if args.backfill:
            results = backfill_generation(args.backfill, args.area)
        elif args.date:
            results = [fetch_generation_date(args.date, args.area)]
        else:
            results = [fetch_generation_date(date.today(), args.area)]
    elif args.load_forecast:
        # Load forecast mode
        if args.backfill:
            results = backfill_load_forecast(args.backfill, args.area)
        elif args.date:
            results = [fetch_load_forecast_date(args.date, args.area)]
        else:
            results = [fetch_load_forecast_date(date.today(), args.area)]
    elif args.de_price:
        # DE-LU spot price mode
        if args.backfill:
            results = backfill_de_prices(args.backfill)
        elif args.date:
            results = [fetch_de_price_date(args.date)]
        else:
            results = [fetch_de_price_date(date.today())]
    elif args.gas_price:
        # Gas price mode
        if args.backfill:
            results = backfill_gas_prices(args.backfill)
        else:
            today = date.today()
            start = today - timedelta(days=7)
            results = [fetch_gas_prices_range(start, today)]
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
