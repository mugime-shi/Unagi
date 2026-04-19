from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.elhandlare import Elhandlare

router = APIRouter(prefix="/elhandlare", tags=["elhandlare"])

DbDep = Annotated[Session, Depends(get_db)]

VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}


@router.get("")
def list_elhandlare(
    db: DbDep,
    area: str = Query("SE3", description="Bidding area (SE1-SE4)"),
):
    """
    List electricity retailers (elhandlare) with currently valid tariffs for the given area.

    Note: påslag values are the *advertised* figures — definitions differ across companies
    (some include elcertifikat, some exclude inköpskostnader etc.). The frontend renders
    these alongside a transparency-gap explainer so consumers understand what each figure
    really covers. is_estimate=true marks values inferred from industry reports rather than
    official disclosure.
    """
    today = date.today()
    rows = (
        db.query(Elhandlare)
        .filter(
            Elhandlare.area == area,
            Elhandlare.valid_from <= today,
            Elhandlare.valid_to >= today,
        )
        .order_by(Elhandlare.paslag_ore_kwh, Elhandlare.monthly_fee_sek)
        .all()
    )

    return {
        "area": area,
        "count": len(rows),
        "retailers": [
            {
                "slug": r.slug,
                "name": r.name,
                "area": r.area,
                "contract_type": r.contract_type,
                "paslag_ore_kwh": float(r.paslag_ore_kwh),
                "monthly_fee_sek": float(r.monthly_fee_sek),
                "elcert_included": r.elcert_included,
                "binding_months": r.binding_months,
                "is_estimate": r.is_estimate,
                "notes": r.notes,
                "valid_from": r.valid_from.isoformat(),
                "valid_to": r.valid_to.isoformat(),
                "source_url": r.source_url,
            }
            for r in rows
        ],
    }
