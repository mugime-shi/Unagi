"""
Open-Meteo Forecast API client.

Fetches wind speed, temperature, and solar radiation forecasts for Göteborg.
Used as ML features for electricity price prediction.

API: https://open-meteo.com/en/docs (free, no key, 10,000 req/day)

Design: stores forecast-as-issued (tagged with issued_date) so that
backtests use the forecast that was available at prediction time,
not hindsight actuals.
"""

import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.weather_forecast import WeatherForecast

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Göteborg coordinates
LAT = 57.7089
LON = 11.9746


class OpenMeteoError(Exception):
    pass


def fetch_forecast(forecast_days: int = 2) -> list[dict]:
    """
    Fetch hourly weather forecast from Open-Meteo.

    Returns list of dicts with:
    - target_utc: datetime
    - temperature_c: float
    - wind_speed_10m: float (km/h)
    - wind_speed_100m: float (km/h) — hub height for large turbines
    - global_radiation_wm2: float (W/m²)
    """
    params = {
        "latitude": LAT,
        "longitude": LON,
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

    log.info("Open-Meteo: fetched %d hourly forecast slots", len(slots))
    return slots


def store_forecast(
    db: Session,
    slots: list[dict],
    issued_date: date | None = None,
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
    log.info("Open-Meteo: stored %d forecast rows (issued %s)", len(rows), issued_date)
    return len(rows)


def fetch_and_store(db: Session, forecast_days: int = 2) -> int:
    """Fetch forecast from Open-Meteo and store to DB."""
    slots = fetch_forecast(forecast_days=forecast_days)
    return store_forecast(db, slots)
