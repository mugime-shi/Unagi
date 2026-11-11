"""
Simulation endpoints (Layer 1: consumption optimization).
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.services.consumption_optimizer import PriceComponents, simulate
from app.services.price_service import get_prices_for_date_range
from app.utils.timezone import stockholm_today

router = APIRouter(prefix="/simulate", tags=["simulate"])

DbDep = Annotated[Session, Depends(get_db)]

LOOKBACK_DAYS = 30   # use last 30 days of real spot data for averages


class ConsumptionRequest(BaseModel):
    monthly_kwh: float = Field(..., gt=0, le=10_000, description="Monthly consumption (kWh)")
    fixed_price_sek_kwh: float = Field(
        ..., gt=0, le=10.0,
        description="All-in fixed contract price per kWh including VAT (SEK)",
    )
    shiftable_pct: float = Field(
        0.30, ge=0.0, le=1.0,
        description="Fraction of daily consumption that can be time-shifted (0–1)",
    )
    shift_hours: int = Field(
        8, ge=1, le=12,
        description="Number of cheapest hours per day to shift consumption into",
    )
    # Optional overrides for price components
    margin_sek_kwh: float | None = Field(None, description="Electricity company margin (SEK/kWh)")
    grid_fee_sek_kwh: float | None = Field(None, description="Grid / elnät fee (SEK/kWh)")
    energy_tax_sek_kwh: float | None = Field(None, description="Energy tax (SEK/kWh)")


@router.post("/consumption")
def simulate_consumption(body: ConsumptionRequest, db: DbDep):
    """
    Compare fixed-price contract vs dynamic (spot) contract for a given
    monthly consumption.

    Uses the last 30 days of real SE3 spot prices from DB.
    Also computes current-month average for Göteborg Energi monthly-avg contracts.
    """
    end_date = stockholm_today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS - 1)

    rows = get_prices_for_date_range(db, start_date, end_date, area=settings.default_area)

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                "No historical spot price data in DB. "
                f"Run `python -m app.tasks.fetch_prices --backfill {LOOKBACK_DAYS}` first."
            ),
        )

    # Build flat list + per-day groups
    from collections import defaultdict
    daily: dict[date, list[float]] = defaultdict(list)
    for r in rows:
        day_key = r.timestamp_utc.date()
        daily[day_key].append(float(r.price_sek_kwh))

    all_prices = [float(r.price_sek_kwh) for r in rows]
    daily_groups = list(daily.values())

    # Current-month average for Göteborg Energi monthly-avg contract
    month_start = end_date.replace(day=1)
    month_rows = get_prices_for_date_range(db, month_start, end_date, area=settings.default_area)
    monthly_avg_spot = (
        sum(float(r.price_sek_kwh) for r in month_rows) / len(month_rows)
        if month_rows else None
    )

    # Price component overrides
    from app.services.consumption_optimizer import MARGIN_SEK, GRID_FEE_SEK, ENERGY_TAX_SEK
    components = PriceComponents(
        margin_sek_kwh=body.margin_sek_kwh if body.margin_sek_kwh is not None else MARGIN_SEK,
        grid_fee_sek_kwh=body.grid_fee_sek_kwh if body.grid_fee_sek_kwh is not None else GRID_FEE_SEK,
        energy_tax_sek_kwh=body.energy_tax_sek_kwh if body.energy_tax_sek_kwh is not None else ENERGY_TAX_SEK,
    )

    result = simulate(
        monthly_kwh=body.monthly_kwh,
        fixed_price_sek_kwh=body.fixed_price_sek_kwh,
        spot_prices_sek=all_prices,
        daily_price_groups=daily_groups,
        components=components,
        shiftable_pct=body.shiftable_pct,
        shift_hours=body.shift_hours,
        monthly_avg_spot_sek=monthly_avg_spot,
    )

    result["period"] = {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days_with_data": len(daily_groups),
        "price_slots": len(all_prices),
        "month_start": month_start.isoformat(),
        "month_days_with_data": len({r.timestamp_utc.date() for r in month_rows}),
    }

    return result
