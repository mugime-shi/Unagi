from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.services.price_service import (
    find_cheapest_window,
    get_or_fetch_prices,
    get_prices_for_date_range,
)

router = APIRouter(prefix="/prices", tags=["prices"])

DbDep = Annotated[Session, Depends(get_db)]

MAX_RANGE_DAYS = 30


def _build_response(
    target_date: date,
    prices: list[dict],
    is_mock: bool,
    month_avg_sek_kwh: float | None = None,
    **extra,
) -> dict:
    sek_values = [p["price_sek_kwh"] for p in prices]
    return {
        "area": settings.default_area,
        "date": target_date.isoformat(),
        "currency": "SEK/kWh",
        "is_mock": is_mock,
        "count": len(prices),
        "summary": {
            "min_sek_kwh": round(min(sek_values), 4) if sek_values else None,
            "max_sek_kwh": round(max(sek_values), 4) if sek_values else None,
            "avg_sek_kwh": round(sum(sek_values) / len(sek_values), 4) if sek_values else None,
            "month_avg_sek_kwh": month_avg_sek_kwh,
        },
        "prices": prices,
        **extra,
    }


def _get_month_avg(db: Session, ref_date: date) -> float | None:
    """Current-month average spot price (SEK/kWh) up to ref_date, or None if no data."""
    month_start = ref_date.replace(day=1)
    rows = get_prices_for_date_range(db, month_start, ref_date, area=settings.default_area)
    if not rows:
        return None
    return round(sum(float(r.price_sek_kwh) for r in rows) / len(rows), 4)


def _cet_hour_now() -> int:
    """Current hour (0-23) in CET/CEST (Europe/Stockholm)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Stockholm")).hour
    except Exception:
        # Rough fallback: UTC+1
        return (datetime.now(timezone.utc) + timedelta(hours=1)).hour


@router.get("/today")
def get_today_prices(db: DbDep):
    """
    SE3 spot prices for today (CET calendar day).
    Returns mock data during development if no API key or DB data is available.
    """
    today = datetime.now(tz=timezone.utc).date()
    prices, is_mock = get_or_fetch_prices(db, today)
    month_avg = _get_month_avg(db, today)
    return _build_response(today, prices, is_mock, month_avg_sek_kwh=month_avg)


@router.get("/tomorrow")
def get_tomorrow_prices(db: DbDep):
    """
    SE3 spot prices for tomorrow.
    ENTSO-E publishes tomorrow's prices around 12:00-13:00 CET.
    Before that, `published` is False and mock data is returned.
    """
    tomorrow = datetime.now(tz=timezone.utc).date() + timedelta(days=1)
    prices, is_mock = get_or_fetch_prices(db, tomorrow)
    today = datetime.now(tz=timezone.utc).date()
    month_avg = _get_month_avg(db, today)

    # If we got mock data and it's before 13:00 CET, prices aren't published yet
    published = not is_mock or _cet_hour_now() >= 13
    return _build_response(tomorrow, prices, is_mock, month_avg_sek_kwh=month_avg, published=published)


@router.get("/range")
def get_price_range(
    db: DbDep,
    start: date = Query(..., description="Start date (YYYY-MM-DD, inclusive)"),
    end: date = Query(..., description="End date (YYYY-MM-DD, inclusive)"),
):
    """
    SE3 spot prices for a date range. Max 30 days.
    Only returns data available in DB — no live ENTSO-E fetch per date.
    """
    if end < start:
        raise HTTPException(status_code=422, detail="end must be >= start")

    delta_days = (end - start).days + 1
    if delta_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Range too large: {delta_days} days (max {MAX_RANGE_DAYS})",
        )

    rows = get_prices_for_date_range(db, start, end)

    # Group rows by CET date
    from collections import defaultdict
    by_date: dict[date, list[dict]] = defaultdict(list)
    for r in rows:
        # CET date = UTC timestamp + 1h (rough; good enough for bucketing)
        cet_ts = r.timestamp_utc + timedelta(hours=1)
        cet_date = cet_ts.date()
        by_date[cet_date].append({
            "timestamp_utc": r.timestamp_utc.isoformat(),
            "price_eur_mwh": float(r.price_eur_mwh),
            "price_sek_kwh": float(r.price_sek_kwh),
            "resolution": r.resolution,
        })

    dates_out = []
    cur = start
    while cur <= end:
        day_prices = by_date.get(cur, [])
        sek_values = [p["price_sek_kwh"] for p in day_prices]
        dates_out.append({
            "date": cur.isoformat(),
            "count": len(day_prices),
            "summary": {
                "min_sek_kwh": round(min(sek_values), 4) if sek_values else None,
                "max_sek_kwh": round(max(sek_values), 4) if sek_values else None,
                "avg_sek_kwh": round(sum(sek_values) / len(sek_values), 4) if sek_values else None,
            },
            "prices": day_prices,
        })
        cur += timedelta(days=1)

    return {
        "area": settings.default_area,
        "currency": "SEK/kWh",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dates": dates_out,
    }


@router.get("/history")
def get_price_history(
    db: DbDep,
    days: int = Query(90, ge=7, le=365, description="Number of past days to include"),
):
    """
    Daily average SE3 spot prices for the past N days (default 90).
    Returns only daily summaries (no raw 15-min slots) — efficient for trend charts.
    """
    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days - 1)
    rows = get_prices_for_date_range(db, start, today, area=settings.default_area)

    from collections import defaultdict
    by_date: dict[date, list[float]] = defaultdict(list)
    for r in rows:
        cet_date = (r.timestamp_utc + timedelta(hours=1)).date()
        by_date[cet_date].append(float(r.price_sek_kwh))

    daily = []
    cur = start
    while cur <= today:
        vals = by_date.get(cur)
        daily.append({
            "date": cur.isoformat(),
            "avg_sek_kwh": round(sum(vals) / len(vals), 4) if vals else None,
            "min_sek_kwh": round(min(vals), 4) if vals else None,
            "max_sek_kwh": round(max(vals), 4) if vals else None,
        })
        cur += timedelta(days=1)

    return {
        "area": settings.default_area,
        "currency": "SEK/kWh",
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "daily": daily,
    }


@router.get("/cheapest-hours")
def get_cheapest_hours(
    db: DbDep,
    date: date = Query(..., description="Target date (YYYY-MM-DD)"),
    duration: int = Query(2, ge=1, le=12, description="Window size in hours (1-12)"),
):
    """
    Find the cheapest consecutive `duration`-hour block for the given date.
    Useful for scheduling appliances (washing machine, EV charging, etc.).
    """
    prices, is_mock = get_or_fetch_prices(db, date)
    if not prices:
        raise HTTPException(status_code=404, detail="No price data available for this date")

    window = find_cheapest_window(prices, duration)
    if window is None:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough data for a {duration}-hour window",
        )

    return {
        "area": settings.default_area,
        "date": date.isoformat(),
        "currency": "SEK/kWh",
        "is_mock": is_mock,
        "cheapest_window": window,
    }
