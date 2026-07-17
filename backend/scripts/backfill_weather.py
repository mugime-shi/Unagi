"""
Backfill per-area weather history from Open-Meteo.

Two sources, mirroring what the daily task stores going forward:
- archive API          → weather_data actuals (temperature, radiation)
- previous-runs API    → weather_forecast day-ahead forecasts as-issued
  (*_previous_day1 = the value yesterday's model run predicted for that hour,
  stored with issued_date = target_date - 1 — no hindsight leakage)

Validated against 90-day backtests in work/SE12_LOCAL_WEATHER_2026-07-16.md.

Usage:
    python -m scripts.backfill_weather --area SE1
    python -m scripts.backfill_weather --area SE2 --start 2025-03-16 --end 2026-07-14
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import httpx

from app.db.database import SessionLocal
from app.services.openmeteo_client import (
    AREA_COORDS,
    OpenMeteoError,
    store_forecast,
    store_weather_actuals,
)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _get(url: str, params: dict) -> dict:
    try:
        resp = httpx.get(url, params=params, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc
    return resp.json().get("hourly", {})


def backfill_actuals(db, area: str, start: date, end: date) -> int:
    lat, lon = AREA_COORDS[area]
    hourly = _get(
        ARCHIVE_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": "temperature_2m,shortwave_radiation",
            "timezone": "UTC",
        },
    )
    slots = []
    for i, ts_str in enumerate(hourly.get("time", [])):
        temp = hourly["temperature_2m"][i]
        rad = hourly["shortwave_radiation"][i]
        if temp is None and rad is None:
            continue  # archive not settled yet for the most recent days
        slots.append(
            {
                "timestamp_utc": datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc),
                "temperature_c": temp,
                "global_radiation_wm2": rad,
            }
        )
    return store_weather_actuals(db, slots, area)


def backfill_forecasts(db, area: str, start: date, end: date) -> int:
    lat, lon = AREA_COORDS[area]
    hourly = _get(
        PREVIOUS_RUNS_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": (
                "temperature_2m_previous_day1,wind_speed_10m_previous_day1,"
                "wind_speed_100m_previous_day1,shortwave_radiation_previous_day1"
            ),
            "timezone": "UTC",
        },
    )
    by_issued: dict[date, list[dict]] = defaultdict(list)
    for i, ts_str in enumerate(hourly.get("time", [])):
        target = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        slot = {
            "target_utc": target,
            "temperature_c": hourly["temperature_2m_previous_day1"][i],
            "wind_speed_10m": hourly["wind_speed_10m_previous_day1"][i],
            "wind_speed_100m": hourly["wind_speed_100m_previous_day1"][i],
            "global_radiation_wm2": hourly["shortwave_radiation_previous_day1"][i],
        }
        if all(slot[k] is None for k in ("temperature_c", "wind_speed_10m", "wind_speed_100m")):
            continue
        by_issued[target.date() - timedelta(days=1)].append(slot)

    count = 0
    for issued, slots in sorted(by_issued.items()):
        count += store_forecast(db, slots, issued_date=issued, area=area)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", required=True, choices=sorted(AREA_COORDS))
    parser.add_argument("--start", default="2025-03-16", help="first date (default 2025-03-16)")
    parser.add_argument("--end", default=None, help="last date (default: yesterday)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)

    db = SessionLocal()
    try:
        n_actual = backfill_actuals(db, args.area, start, end)
        n_forecast = backfill_forecasts(db, args.area, start, end)
        log.info(
            "Backfill %s %s→%s: %d actual rows, %d forecast rows",
            args.area,
            start,
            end,
            n_actual,
            n_forecast,
        )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
