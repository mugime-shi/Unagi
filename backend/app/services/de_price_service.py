"""
DE-LU spot price service: orchestrates ENTSO-E A44 (DE-LU) fetch → DB UPSERT → read.

Design mirrors load_forecast_service.py:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent)
- Returns empty list when DB has no rows for a date
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.de_spot_price import DeSpotPrice
from app.services.entsoe_client import DePricePoint, fetch_de_day_ahead_prices

# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_de_prices(db: Session, points: list[DePricePoint]) -> int:
    """Persist DePricePoints using INSERT ON CONFLICT DO UPDATE. Returns row count."""
    if not points:
        return 0

    stmt = text("""
        INSERT INTO de_spot_price
            (timestamp_utc, price_eur_mwh, resolution)
        VALUES (:ts, :price, :res)
        ON CONFLICT (timestamp_utc, resolution)
        DO UPDATE SET
            price_eur_mwh = EXCLUDED.price_eur_mwh
    """)

    params = [{"ts": p.timestamp_utc, "price": p.price_eur_mwh, "res": p.resolution} for p in points]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_de_prices_for_date(
    db: Session,
    target_date: date,
) -> list[DeSpotPrice]:
    """Fetch DE-LU spot price rows for target_date from DB (CET calendar day)."""
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc) - timedelta(hours=1)
    day_end = day_start + timedelta(hours=24)

    return (
        db.query(DeSpotPrice)
        .filter(
            DeSpotPrice.timestamp_utc >= day_start,
            DeSpotPrice.timestamp_utc < day_end,
        )
        .order_by(DeSpotPrice.timestamp_utc)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------


def fetch_and_store_de_prices(
    db: Session,
    target_date: date,
) -> list[DeSpotPrice]:
    """Pull DE-LU A44 prices from ENTSO-E and persist. Returns stored rows."""
    points = fetch_de_day_ahead_prices(
        target_date=target_date,
        api_key=settings.entsoe_api_key,
    )
    upsert_de_prices(db, points)
    return get_de_prices_for_date(db, target_date)
