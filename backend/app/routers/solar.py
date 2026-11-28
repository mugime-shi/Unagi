"""
Solar simulation endpoints (Layer 2).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.solar_model import DEFAULT_PERFORMANCE_RATIO, optimize_solar_month

router = APIRouter(prefix="/simulate", tags=["solar"])

DbDep = Annotated[Session, Depends(get_db)]


class SolarRequest(BaseModel):
    panel_kwp: float = Field(..., gt=0, le=100, description="PV panel capacity (kWp)")
    battery_kwh: float = Field(0.0, ge=0, le=200, description="Battery capacity (kWh, 0 = none)")
    annual_consumption_kwh: float = Field(
        ..., gt=0, le=100_000, description="Annual household electricity consumption (kWh)"
    )
    month: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Simulation month (YYYY-MM)",
        examples=["2025-07"],
    )
    performance_ratio: float = Field(
        DEFAULT_PERFORMANCE_RATIO,
        ge=0.5,
        le=1.0,
        description="PV system efficiency (0.75–0.85 typical)",
    )


@router.post("/solar")
def simulate_solar(body: SolarRequest, db: DbDep):
    """
    Simulate monthly solar PV revenue and self-consumption savings.

    Compares:
      - Revenue from selling surplus to grid at spot price
      - Savings from self-consuming instead of buying at full retail price
      - Battery dispatch effect (if battery_kwh > 0)
      - Tax credit (skattereduktion) 2025 vs 2026

    Uses real SMHI hourly radiation data when available; falls back to
    Göteborg monthly reference table. Spot prices must exist in DB.
    """
    year, month = int(body.month[:4]), int(body.month[5:])

    try:
        result = optimize_solar_month(
            panel_kwp=body.panel_kwp,
            battery_kwh=body.battery_kwh,
            annual_consumption_kwh=body.annual_consumption_kwh,
            year=year,
            month=month,
            db=db,
            performance_ratio=body.performance_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return result
