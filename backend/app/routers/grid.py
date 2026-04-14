from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.grid_operator import GridOperator

router = APIRouter(prefix="/grid-operators", tags=["grid-operators"])

DbDep = Annotated[Session, Depends(get_db)]

VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}


@router.get("")
def list_grid_operators(
    db: DbDep,
    area: str = Query("SE3", description="Bidding area (SE1-SE4)"),
):
    """
    List grid operators with currently valid tariffs for the given area.
    Returns both apartment and house tariffs per operator.
    """
    today = date.today()
    rows = (
        db.query(GridOperator)
        .filter(
            GridOperator.area == area,
            GridOperator.valid_from <= today,
            GridOperator.valid_to >= today,
        )
        .order_by(GridOperator.slug, GridOperator.dwelling_type)
        .all()
    )

    return {
        "area": area,
        "count": len(rows),
        "operators": [
            {
                "slug": r.slug,
                "name": r.name,
                "city": r.city,
                "area": r.area,
                "dwelling_type": r.dwelling_type,
                "fast_fee_sek_year": float(r.fast_fee_sek_year),
                "transfer_fee_ore": float(r.transfer_fee_ore),
                "effect_fee_sek_kw": float(r.effect_fee_sek_kw) if r.effect_fee_sek_kw else None,
                "valid_from": r.valid_from.isoformat(),
                "valid_to": r.valid_to.isoformat(),
                "source_url": r.source_url,
            }
            for r in rows
        ],
    }
