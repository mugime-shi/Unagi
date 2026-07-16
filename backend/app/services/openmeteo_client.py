"""
Open-Meteo Forecast API client.

Fetches wind speed, temperature, and solar radiation forecasts per bidding
area. Used as ML features for electricity price prediction. Local (per-area)
wind is the dominant driver of northern price shape — see
work/SE12_LOCAL_WEATHER_2026-07-16.md for the experiment behind the
coordinates below.

API: https://open-meteo.com/en/docs (free, no key, 10,000 req/day)

Design: stores forecast-as-issued (tagged with issued_date) so that
backtests use the forecast that was available at prediction time,
not hindsight actuals.
"""

import logging
import os
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.weather_data import WeatherData
from app.models.weather_forecast import WeatherForecast

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# One representative point per bidding area — every area gets its own local
# weather. SE3's point (Göteborg) doubles as the fallback for areas that have
# no backfilled local rows yet, because it was the single point all areas
# shared before per-area weather existed. Adoption evidence per area:
# work/SE12_LOCAL_WEATHER_2026-07-16.md.
AREA_COORDS: dict[str, tuple[float, float]] = {
    "SE1": (65.58, 22.15),  # Luleå
    "SE2": (62.39, 17.31),  # Sundsvall
    "SE3": (57.7089, 11.9746),  # Göteborg
    "SE4": (55.605, 13.0038),  # Malmö
}

# station_id for open-meteo rows in weather_data (SMHI station ids are 5-digit)
OPEN_METEO_STATION_ID = 0

# Areas beyond SE3 to fetch in the daily task, e.g. "SE1,SE2,SE4".
# SE3 is always fetched (it is also the fallback point), so listing it here
# is redundant and ignored. Scheduler-only env var; unset = single-point
# behaviour, unchanged.
LOCAL_WEATHER_ENV = "LOCAL_WEATHER_AREAS"


def local_weather_areas() -> list[str]:
    """Areas beyond the always-fetched SE3 to fetch weather for, from env."""
    raw = os.environ.get(LOCAL_WEATHER_ENV, "")
    return [a.strip() for a in raw.split(",") if a.strip() in AREA_COORDS and a.strip() != "SE3"]


class OpenMeteoError(Exception):
    pass


def fetch_forecast(forecast_days: int = 2, area: str = "SE3") -> list[dict]:
    """
    Fetch hourly weather forecast from Open-Meteo for one area's point.

    Returns list of dicts with:
    - target_utc: datetime
    - temperature_c: float
    - wind_speed_10m: float (km/h)
    - wind_speed_100m: float (km/h) — hub height for large turbines
    - global_radiation_wm2: float (W/m²)
    """
    lat, lon = AREA_COORDS[area]
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_speed_100m,global_tilted_irradiance",
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }

    try:
        resp = httpx.get(FORECAST_URL, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc

    data = resp.json()
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    wind10 = hourly.get("wind_speed_10m", [])
    wind100 = hourly.get("wind_speed_100m", [])
    rads = hourly.get("global_tilted_irradiance", [])

    slots = []
    for i, ts_str in enumerate(times):
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        slots.append({
            "target_utc": ts,
            "temperature_c": temps[i] if i < len(temps) else None,
            "wind_speed_10m": wind10[i] if i < len(wind10) else None,
            "wind_speed_100m": wind100[i] if i < len(wind100) else None,
            "global_radiation_wm2": rads[i] if i < len(rads) else None,
        })

    log.info("Open-Meteo: fetched %d hourly forecast slots (area %s)", len(slots), area)
    return slots


def store_forecast(
    db: Session,
    slots: list[dict],
    issued_date: date | None = None,
    area: str = "SE3",
) -> int:
    """
    UPSERT forecast slots into weather_forecast table.

    issued_date: the date the forecast was retrieved (default: today).
    Uses ON CONFLICT DO UPDATE so re-fetching on the same day is safe.
    """
    if not slots:
        return 0

    if issued_date is None:
        issued_date = date.today()

    rows = [
        {
            "issued_date": issued_date,
            "area": area,
            "target_utc": s["target_utc"],
            "temperature_c": s["temperature_c"],
            "wind_speed_10m": s["wind_speed_10m"],
            "wind_speed_100m": s["wind_speed_100m"],
            "global_radiation_wm2": s["global_radiation_wm2"],
            "source": "open-meteo",
        }
        for s in slots
    ]

    stmt = pg_insert(WeatherForecast).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_weather_forecast",
        set_={
            "temperature_c": stmt.excluded.temperature_c,
            "wind_speed_10m": stmt.excluded.wind_speed_10m,
            "wind_speed_100m": stmt.excluded.wind_speed_100m,
            "global_radiation_wm2": stmt.excluded.global_radiation_wm2,
        },
    )
    db.execute(stmt)
    db.commit()
    log.info("Open-Meteo: stored %d forecast rows (issued %s, area %s)", len(rows), issued_date, area)
    return len(rows)


def fetch_and_store(db: Session, forecast_days: int = 2, area: str = "SE3") -> int:
    """Fetch forecast from Open-Meteo and store to DB."""
    slots = fetch_forecast(forecast_days=forecast_days, area=area)
    return store_forecast(db, slots, area=area)


def fetch_recent_weather(area: str, past_days: int = 7) -> list[dict]:
    """
    Fetch recent hourly weather (temperature + radiation) from Open-Meteo.

    Used as weather_data actuals for areas whose observations don't come
    from SMHI. past_days uses Open-Meteo's assimilated recent data — the
    same series the archive settles to a few days later.
    """
    lat, lon = AREA_COORDS[area]
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,shortwave_radiation",
        "timezone": "UTC",
        "past_days": past_days,
        "forecast_days": 1,
    }

    try:
        resp = httpx.get(FORECAST_URL, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise OpenMeteoError(f"Open-Meteo request failed: {exc}") from exc

    hourly = resp.json().get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    rads = hourly.get("shortwave_radiation", [])

    now_utc = datetime.now(timezone.utc)
    slots = []
    for i, ts_str in enumerate(times):
        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        if ts >= now_utc:
            continue  # keep actuals only; forecasts go to weather_forecast
        slots.append({
            "timestamp_utc": ts,
            "temperature_c": temps[i] if i < len(temps) else None,
            "global_radiation_wm2": rads[i] if i < len(rads) else None,
        })

    log.info("Open-Meteo: fetched %d recent weather slots (area %s)", len(slots), area)
    return slots


def store_weather_actuals(db: Session, slots: list[dict], area: str) -> int:
    """UPSERT recent-weather slots into weather_data (source open-meteo)."""
    if not slots:
        return 0

    rows = [
        {
            "station_id": OPEN_METEO_STATION_ID,
            "area": area,
            "timestamp_utc": s["timestamp_utc"],
            "temperature_c": s["temperature_c"],
            "global_radiation_wm2": s["global_radiation_wm2"],
            "sunshine_hours": None,
            "source": "open-meteo",
        }
        for s in slots
    ]

    stmt = pg_insert(WeatherData).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_weather_data",
        set_={
            "temperature_c": stmt.excluded.temperature_c,
            "global_radiation_wm2": stmt.excluded.global_radiation_wm2,
        },
    )
    db.execute(stmt)
    db.commit()
    log.info("Open-Meteo: stored %d weather rows (area %s)", len(rows), area)
    return len(rows)
