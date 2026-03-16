"""
Balancing price service: orchestrates eSett EXP14 fetch → DB UPSERT → read.

Design mirrors price_service.py:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent, safe to rerun)
- Returns empty list (not an error) when DB has no rows for a date
- Caller decides whether to fall back to a live fetch or return nothing
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.balancing_price import BalancingPrice
from app.services.esett_client import (
    BalancingError,
    BalancingPoint,
    fetch_imbalance_prices,
    _AREA_TO_MBA as _AREA_TO_EIC,
)


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------

def upsert_balancing(db: Session, points: list[BalancingPoint], area: str = "SE3") -> int:
    """
    Persist a list of BalancingPoints using INSERT ON CONFLICT DO UPDATE.
    Returns the number of rows written.
    """
    if not points:
        return 0

    stmt = text("""
        INSERT INTO balancing_prices
            (area, timestamp_utc, price_eur_mwh, price_sek_kwh, category, resolution)
        VALUES (:area, :ts, :eur, :sek, :cat, :res)
        ON CONFLICT (area, timestamp_utc, category, resolution)
        DO UPDATE SET
            price_eur_mwh = EXCLUDED.price_eur_mwh,
            price_sek_kwh = EXCLUDED.price_sek_kwh
    """)

    for p in points:
        db.execute(stmt, {
            "area": area,
            "ts":   p.timestamp_utc,
            "eur":  p.price_eur_mwh,
            "sek":  p.price_sek_kwh,
            "cat":  p.category,
            "res":  p.resolution,
        })
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

def get_balancing_for_date(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[BalancingPrice]:
    """
    Fetch balancing prices for target_date from DB.
    Window: previous day 23:00 UTC → same day 23:00 UTC (= CET calendar day).
    Returns both categories (A04 Long + A05 Short), ordered by time then category.
    """
    day_start = (
        datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
        - timedelta(hours=1)
    )
    day_end = day_start + timedelta(hours=24)

    return (
        db.query(BalancingPrice)
        .filter(
            BalancingPrice.area == area,
            BalancingPrice.timestamp_utc >= day_start,
            BalancingPrice.timestamp_utc < day_end,
        )
        .order_by(BalancingPrice.timestamp_utc, BalancingPrice.category)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------

def fetch_and_store_balancing(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[BalancingPrice]:
    """
    Pull imbalance prices from ENTSO-E and persist them. Returns stored rows.
    Raises BalancingError if the API call or parse fails.
    """
    eic_code = _AREA_TO_EIC.get(area, area)
    points = fetch_imbalance_prices(
        target_date=target_date,
        area=eic_code,
    )
    upsert_balancing(db, points, area=area)
    return get_balancing_for_date(db, target_date, area=area)
