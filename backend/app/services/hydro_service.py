"""
Hydro reservoir service: ENTSO-E A72 fetch → DB UPSERT → read.

Weekly stored energy data for Swedish bidding zones (SE1–SE4).
Used as a feature in price forecasting — high reservoir levels
during spring snowmelt correlate with low electricity prices.
"""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.hydro_reservoir import HydroReservoir
from app.services.entsoe_client import (
    _AREA_TO_EIC,
    HydroReservoirPoint,
    fetch_hydro_reservoir,
)

# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_hydro(db: Session, points: list[HydroReservoirPoint], area: str = "SE3") -> int:
    """Persist HydroReservoirPoints using INSERT ON CONFLICT DO UPDATE. Idempotent."""
    if not points:
        return 0

    stmt = text("""
        INSERT INTO hydro_reservoir (area, week_start, stored_energy_mwh)
        VALUES (:area, :week_start, :mwh)
        ON CONFLICT (area, week_start)
        DO UPDATE SET stored_energy_mwh = EXCLUDED.stored_energy_mwh
    """)

    params = [{"area": area, "week_start": p.week_start, "mwh": p.stored_energy_mwh} for p in points]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_hydro_for_date(db: Session, target_date: date, area: str = "SE3") -> HydroReservoir | None:
    """Get the most recent hydro reservoir record on or before target_date."""
    return (
        db.query(HydroReservoir)
        .filter(
            HydroReservoir.area == area,
            HydroReservoir.week_start <= target_date,
        )
        .order_by(HydroReservoir.week_start.desc())
        .first()
    )


def get_hydro_range(db: Session, start_date: date, end_date: date, area: str = "SE3") -> list[HydroReservoir]:
    """Get all hydro reservoir records overlapping a date range."""
    # Include one extra week before start_date for forward-fill
    buffer_start = start_date - timedelta(weeks=2)
    return (
        db.query(HydroReservoir)
        .filter(
            HydroReservoir.area == area,
            HydroReservoir.week_start >= buffer_start,
            HydroReservoir.week_start <= end_date,
        )
        .order_by(HydroReservoir.week_start)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------


def fetch_and_store_hydro(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> int:
    """
    Pull A72 hydro reservoir data from ENTSO-E and persist.
    Fetches a 3-month window to ensure we get the latest weekly data.
    Returns the number of rows written.
    """
    eic_code = _AREA_TO_EIC.get(area, area)
    # A72 returns data in weekly chunks; fetch a wide window
    period_start = target_date - timedelta(days=90)
    period_end = target_date + timedelta(days=7)

    points = fetch_hydro_reservoir(
        period_start=period_start,
        period_end=period_end,
        area=eic_code,
        api_key=settings.entsoe_api_key,
    )
    return upsert_hydro(db, points, area=area)
