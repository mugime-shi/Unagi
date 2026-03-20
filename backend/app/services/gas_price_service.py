"""
Gas price service: orchestrates Bundesnetzagentur/THE fetch → DB UPSERT → read.

Design mirrors load_forecast_service.py:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent)
- forward-fill for weekends/holidays (gas doesn't trade every day)
"""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.gas_price import GasPrice
from app.services.bundesnetzagentur_client import GasPricePoint, fetch_gas_prices

# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_gas_prices(db: Session, points: list[GasPricePoint]) -> int:
    """Persist GasPricePoints using INSERT ON CONFLICT DO UPDATE. Returns row count."""
    if not points:
        return 0

    stmt = text("""
        INSERT INTO gas_price
            (trade_date, price_eur_mwh, source)
        VALUES (:td, :price, :src)
        ON CONFLICT (trade_date, source)
        DO UPDATE SET
            price_eur_mwh = EXCLUDED.price_eur_mwh
    """)

    params = [{"td": p.trade_date, "price": p.price_eur_mwh, "src": p.source} for p in points]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_gas_price_for_date(
    db: Session,
    target_date: date,
) -> GasPrice | None:
    """
    Get gas price for target_date with forward-fill (up to 14 days lookback).

    Gas markets don't trade on weekends/holidays, so we return the most
    recent available price within a 14-day lookback window.
    """
    lookback_start = target_date - timedelta(days=14)

    row = (
        db.query(GasPrice)
        .filter(
            GasPrice.trade_date >= lookback_start,
            GasPrice.trade_date <= target_date,
        )
        .order_by(GasPrice.trade_date.desc())
        .first()
    )

    return row


def get_gas_prices_for_range(
    db: Session,
    start_date: date,
    end_date: date,
) -> list[GasPrice]:
    """Get all gas price rows in [start_date, end_date]."""
    return (
        db.query(GasPrice)
        .filter(
            GasPrice.trade_date >= start_date,
            GasPrice.trade_date <= end_date,
        )
        .order_by(GasPrice.trade_date)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store
# ---------------------------------------------------------------------------


def fetch_and_store_gas_prices(
    db: Session,
    start_date: date,
    end_date: date,
) -> int:
    """
    Pull THE gas prices for [start_date, end_date] and persist.
    Returns the number of rows written.
    """
    points = fetch_gas_prices(start_date, end_date)
    return upsert_gas_prices(db, points)
