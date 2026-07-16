"""
SMHI Open Data API client.

Fetches global radiation (W/m²) and temperature data for Göteborg.
Stores results in the weather_data table.

API reference: https://opendata-download-metobs.smhi.se/api
Parameters used:
   11 — Global radiation (W/m²), hourly mean  [station 71415: Göteborg Sol]
    1 — Air temperature (°C), hourly mean      [station 71420: Göteborg A]

Available periods:
  latest-day    — last 24 hours
  latest-months — last ~4 months (default, covers solar simulation needs)
  corrected-archive — full historical archive (slow, use for backfill only)

Data format: JSON, `date` field is milliseconds since Unix epoch (UTC).
"""

import logging
from datetime import datetime, timezone
from typing import NamedTuple

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.weather_data import WeatherData

log = logging.getLogger(__name__)

SMHI_BASE = "https://opendata-download-metobs.smhi.se/api"
DEFAULT_STATION = 71415   # Göteborg Sol  (global radiation station)
TEMP_STATION = 71420      # Göteborg A    (temperature station)
PARAM_RADIATION = 11      # Global radiation W/m² (hourly mean, "Sol" stations only)
PARAM_TEMPERATURE = 1     # Air temperature °C (hourly mean)


class SMHIError(Exception):
    pass


class WeatherSlot(NamedTuple):
    timestamp_utc: datetime
    global_radiation_wm2: float | None
    temperature_c: float | None


# ---------------------------------------------------------------------------
# HTTP + parsing
# ---------------------------------------------------------------------------

def _fetch_parameter(
    station: int,
    parameter: int,
    period: str = "latest-months",
) -> list[dict]:
    """Return the raw `value` list from SMHI for one parameter."""
    url = (
        f"{SMHI_BASE}/version/1.0/parameter/{parameter}"
        f"/station/{station}/period/{period}/data.json"
    )
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SMHIError(f"SMHI request failed ({url}): {exc}") from exc

    return resp.json().get("value", [])


def _parse_values(raw: list[dict]) -> dict[datetime, float]:
    """Convert SMHI value list → {timestamp_utc: float}."""
    result: dict[datetime, float] = {}
    for item in raw:
        try:
            ts = datetime.fromtimestamp(item["date"] / 1000, tz=timezone.utc)
            val = float(item["value"])
            result[ts] = val
        except (KeyError, ValueError, TypeError):
            continue
    return result


def fetch_weather_slots(
    rad_station: int = DEFAULT_STATION,
    temp_station: int = TEMP_STATION,
    period: str = "latest-months",
) -> list[WeatherSlot]:
    """
    Fetch global radiation + temperature from SMHI and return merged hourly slots.

    Radiation (param 11) comes from station 71415 (Göteborg Sol).
    Temperature (param 1) comes from station 71420 (Göteborg A).
    Radiation is the primary series; temperature is joined by timestamp.
    If temperature fetch fails, temperature_c is None for all slots.
    """
    log.info("SMHI: fetching radiation (param %d, station %d, period=%s)",
             PARAM_RADIATION, rad_station, period)
    radiation = _parse_values(_fetch_parameter(rad_station, PARAM_RADIATION, period))

    try:
        log.info("SMHI: fetching temperature (param %d, station %d)",
                 PARAM_TEMPERATURE, temp_station)
        temperature = _parse_values(_fetch_parameter(temp_station, PARAM_TEMPERATURE, period))
    except SMHIError as exc:
        log.warning("SMHI temperature fetch failed, skipping: %s", exc)
        temperature = {}

    slots = [
        WeatherSlot(
            timestamp_utc=ts,
            global_radiation_wm2=radiation[ts],
            temperature_c=temperature.get(ts),
        )
        for ts in sorted(radiation.keys())
    ]
    log.info("SMHI: %d hourly slots fetched", len(slots))
    return slots


# ---------------------------------------------------------------------------
# DB storage
# ---------------------------------------------------------------------------

def store_weather_slots(
    db: Session,
    slots: list[WeatherSlot],
    station_id: int = DEFAULT_STATION,
) -> int:
    """
    UPSERT weather slots into weather_data table.

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE so re-fetching is safe.
    Returns the number of rows inserted or updated.
    """
    if not slots:
        return 0

    rows = [
        {
            "station_id": station_id,
            "area": "SE3",  # SMHI stations are Göteborg — the SE3 point
            "timestamp_utc": s.timestamp_utc,
            "global_radiation_wm2": s.global_radiation_wm2,
            "temperature_c": s.temperature_c,
            "sunshine_hours": None,
            "source": "smhi",
        }
        for s in slots
    ]

    stmt = pg_insert(WeatherData).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_weather_data",
        set_={
            "global_radiation_wm2": stmt.excluded.global_radiation_wm2,
            "temperature_c": stmt.excluded.temperature_c,
        },
    )
    db.execute(stmt)
    db.commit()
    log.info("SMHI: stored/updated %d weather rows for station %d", len(rows), station_id)
    return len(rows)


def fetch_and_store(
    db: Session,
    period: str = "latest-months",
) -> int:
    """Convenience: fetch from SMHI and store to DB in one call."""
    slots = fetch_weather_slots(period=period)
    return store_weather_slots(db, slots, station_id=DEFAULT_STATION)


# ---------------------------------------------------------------------------
# DB read helpers
# ---------------------------------------------------------------------------

def get_weather_for_date_range(
    db: Session,
    start: datetime,
    end: datetime,
    station_id: int = DEFAULT_STATION,
) -> list[WeatherData]:
    """Return weather rows between start (inclusive) and end (inclusive) UTC."""
    return (
        db.query(WeatherData)
        .filter(
            WeatherData.station_id == station_id,
            WeatherData.timestamp_utc >= start,
            WeatherData.timestamp_utc <= end,
        )
        .order_by(WeatherData.timestamp_utc)
        .all()
    )
