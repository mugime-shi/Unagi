"""
Load forecast service: orchestrates ENTSO-E A65 fetch → DB UPSERT → read.

Design mirrors generation_service.py:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent)
- Returns empty list when DB has no rows for a date
"""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.load_forecast import LoadForecast
from app.services.entsoe_client import (
    _AREA_TO_EIC,
    LoadForecastPoint,
    fetch_load_forecast,
)
from app.utils.timezone import stockholm_midnight_utc

# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_load_forecast(db: Session, points: list[LoadForecastPoint], area: str = "SE3") -> int:
    """
    Persist LoadForecastPoints using INSERT ON CONFLICT DO UPDATE.
    Returns the number of rows written.
    """
    if not points:
        return 0

    stmt = text("""
        INSERT INTO load_forecast
            (area, timestamp_utc, load_mw, resolution)
        VALUES (:area, :ts, :mw, :res)
        ON CONFLICT (area, timestamp_utc, resolution)
        DO UPDATE SET
            load_mw = EXCLUDED.load_mw
    """)

    params = [{"area": area, "ts": p.timestamp_utc, "mw": p.load_mw, "res": p.resolution} for p in points]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_load_forecast_for_date(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[LoadForecast]:
    """
    Fetch load forecast rows for target_date from DB.
    Window: Stockholm time (CET/CEST) calendar day.
    """
    day_start = stockholm_midnight_utc(target_date)
    day_end = day_start + timedelta(hours=24)

    return (
        db.query(LoadForecast)
        .filter(
            LoadForecast.area == area,
            LoadForecast.timestamp_utc >= day_start,
            LoadForecast.timestamp_utc < day_end,
        )
        .order_by(LoadForecast.timestamp_utc)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------


def fetch_and_store_load_forecast(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[LoadForecast]:
    """
    Pull A65 load forecast from ENTSO-E and persist. Returns stored rows.
    Raises EntsoEError if the API call or parse fails.
    """
    eic_code = _AREA_TO_EIC.get(area, area)
    points = fetch_load_forecast(
        target_date=target_date,
        area=eic_code,
        api_key=settings.entsoe_api_key,
    )
    upsert_load_forecast(db, points, area=area)
    return get_load_forecast_for_date(db, target_date, area=area)
