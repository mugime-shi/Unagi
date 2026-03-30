"""
Generation mix router — ENTSO-E A75 actual generation per production type.

Endpoints:
  GET /api/v1/generation/today   — today's generation mix with renewable % badge
  GET /api/v1/generation/date    — generation mix for an arbitrary date (DB only)
"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.entsoe_client import EntsoEError
from app.services.generation_service import (
    build_generation_summary,
    fetch_and_store_generation,
    get_generation_for_date,
)

router = APIRouter(prefix="/generation", tags=["generation"])

DbDep = Annotated[Session, Depends(get_db)]

VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}
AreaDep = Annotated[
    str,
    Query(description="Bidding area (SE1–SE4)"),
]

# ---------------------------------------------------------------------------
# In-memory cache (survives between Lambda warm invocations)
# ---------------------------------------------------------------------------
_CACHE_TTL = 45 * 60  # seconds — matches the staleness threshold
_generation_cache: dict[tuple[str, str], tuple[dict, float]] = {}


def _get_cached(area: str, date_str: str) -> dict | None:
    key = (area, date_str)
    if key in _generation_cache:
        resp, cached_at = _generation_cache[key]
        if time.time() - cached_at <= _CACHE_TTL:
            return resp
        del _generation_cache[key]
    return None


@router.get("/today")
def get_today_generation(db: DbDep, area: AreaDep = "SE3"):
    """
    Actual generation mix for today (Stockholm calendar day).

    Returns the renewable energy percentage badge (hydro + wind + solar),
    carbon-free percentage (renewable + nuclear), a breakdown by group,
    and an hourly time series.

    Source: ENTSO-E A75 processType=A16 (Realised). Data lags ~15-30 min.
    If today's data is not yet in DB, attempts a live fetch.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    today = datetime.now(tz=timezone.utc).date()
    today_str = today.isoformat()

    # Fast path: return cached response if still fresh
    cached = _get_cached(area, today_str)
    if cached is not None:
        return cached

    rows = get_generation_for_date(db, today, area)

    # Re-fetch if no data or the latest slot is older than 45 min.
    # A75 data updates every 15 min with ~15-30 min ENTSO-E lag.
    # The scheduler Lambda pre-populates data at 12:30 UTC, so most
    # requests hit the DB cache.  45 min balances freshness vs latency.
    needs_fetch = not rows
    if rows:
        latest_ts = max(r.timestamp_utc for r in rows)
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        stale_seconds = (datetime.now(timezone.utc) - latest_ts).total_seconds()
        needs_fetch = stale_seconds > 45 * 60

    if needs_fetch:
        try:
            rows = fetch_and_store_generation(db, today, area)
        except EntsoEError as exc:
            if rows:
                pass  # stale data is better than nothing
            else:
                # Fallback: try yesterday (data may not be available yet for today)
                yesterday = today - timedelta(days=1)
                try:
                    rows = get_generation_for_date(db, yesterday, area)
                    if not rows:
                        rows = fetch_and_store_generation(db, yesterday, area)
                    today = yesterday  # report the date we actually got data for
                except EntsoEError:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No generation data available: {exc}",
                    )

    summary = build_generation_summary(rows)
    if not summary:
        raise HTTPException(status_code=404, detail="No generation data available")

    response = {
        "area": area,
        "date": today.isoformat(),
        "source": "ENTSO-E A75",
        "note": "renewable = hydro + wind + solar. carbon_free adds nuclear.",
        **summary,
    }

    # Cache the computed response for subsequent requests
    _generation_cache[(area, today.isoformat())] = (response, time.time())

    return response


@router.get("/date")
def get_generation_for_date_endpoint(
    db: DbDep,
    date: date = Query(..., description="Target date (YYYY-MM-DD)"),
    area: AreaDep = "SE3",
):
    """
    Generation mix for an arbitrary date (DB only — no live fetch).
    Use for historical charts.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    rows = get_generation_for_date(db, date, area)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No generation data in DB for {date}")

    summary = build_generation_summary(rows)
    return {
        "area": area,
        "date": date.isoformat(),
        "source": "ENTSO-E A75",
        **summary,
    }
