from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

_STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _to_stockholm_date(dt_utc: datetime) -> date:
    """Convert a UTC datetime to the calendar date in Europe/Stockholm (CET/CEST)."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(_STOCKHOLM).date()

from app.db.database import get_db
from app.services.balancing_service import fetch_and_store_balancing, get_balancing_for_date
from app.services.esett_client import BalancingError
from app.services.price_service import (
    build_forecast,
    find_cheapest_window,
    get_or_fetch_prices,
    get_prices_for_date_range,
)

router = APIRouter(prefix="/prices", tags=["prices"])

DbDep = Annotated[Session, Depends(get_db)]

MAX_RANGE_DAYS = 30


VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}
AreaDep = Annotated[
    str,
    Query(description="Bidding area (SE1=Luleå, SE2=Sundsvall, SE3=Göteborg, SE4=Malmö)"),
]


def _build_response(
    target_date: date,
    prices: list[dict],
    is_estimate: bool,
    area: str = "SE3",
    month_avg_sek_kwh: float | None = None,
    **extra,
) -> dict:
    sek_values = [p["price_sek_kwh"] for p in prices]
    return {
        "area": area,
        "date": target_date.isoformat(),
        "currency": "SEK/kWh",
        "is_estimate": is_estimate,
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


def _get_month_avg(db: Session, ref_date: date, area: str = "SE3") -> float | None:
    """Current-month average spot price (SEK/kWh) up to ref_date, or None if no data."""
    month_start = ref_date.replace(day=1)
    rows = get_prices_for_date_range(db, month_start, ref_date, area=area)
    if not rows:
        return None
    return round(sum(float(r.price_sek_kwh) for r in rows) / len(rows), 4)


def _cet_hour_now() -> int:
    """Current hour (0-23) in Europe/Stockholm (CET in winter, CEST in summer)."""
    try:
        return datetime.now(_STOCKHOLM).hour
    except Exception:
        # Rough fallback: UTC+1 (off by 1h during CEST but acceptable for the published check)
        return (datetime.now(timezone.utc) + timedelta(hours=1)).hour


@router.get("/today")
def get_today_prices(db: DbDep, area: AreaDep = "SE3"):
    """
    Spot prices for today (Stockholm calendar day) for the given bidding area.
    Returns estimated (fallback) data during development if no API key or DB data is available.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    today = datetime.now(tz=timezone.utc).date()
    prices, is_estimate = get_or_fetch_prices(db, today, area=area)
    month_avg = _get_month_avg(db, today, area=area)
    return _build_response(today, prices, is_estimate, area=area, month_avg_sek_kwh=month_avg)


@router.get("/tomorrow")
def get_tomorrow_prices(db: DbDep, area: AreaDep = "SE3"):
    """
    Spot prices for tomorrow for the given bidding area.
    ENTSO-E publishes tomorrow's prices around 12:00-13:00 CET.
    Before that, `published` is False and estimated data is returned.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    tomorrow = datetime.now(tz=timezone.utc).date() + timedelta(days=1)
    prices, is_estimate = get_or_fetch_prices(db, tomorrow, area=area)
    today = datetime.now(tz=timezone.utc).date()
    month_avg = _get_month_avg(db, today, area=area)

    # If we got mock data and it's before 13:00 CET, prices aren't published yet
    published = not is_estimate or _cet_hour_now() >= 13
    return _build_response(tomorrow, prices, is_estimate, area=area, month_avg_sek_kwh=month_avg, published=published)


@router.get("/range")
def get_price_range(
    db: DbDep,
    start: date = Query(..., description="Start date (YYYY-MM-DD, inclusive)"),
    end: date = Query(..., description="End date (YYYY-MM-DD, inclusive)"),
    area: AreaDep = "SE3",
):
    """
    Spot prices for a date range. Max 30 days.
    Only returns data available in DB — no live ENTSO-E fetch per date.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    if end < start:
        raise HTTPException(status_code=422, detail="end must be >= start")

    delta_days = (end - start).days + 1
    if delta_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Range too large: {delta_days} days (max {MAX_RANGE_DAYS})",
        )

    rows = get_prices_for_date_range(db, start, end, area=area)

    # Group rows by Stockholm local date (CET in winter, CEST in summer)
    from collections import defaultdict
    by_date: dict[date, list[dict]] = defaultdict(list)
    for r in rows:
        cet_date = _to_stockholm_date(r.timestamp_utc)
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
        "area": area,
        "currency": "SEK/kWh",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dates": dates_out,
    }


@router.get("/history")
def get_price_history(
    db: DbDep,
    days: int = Query(90, ge=7, le=365, description="Number of past days to include"),
    area: AreaDep = "SE3",
):
    """
    Daily average spot prices for the past N days (default 90).
    Returns only daily summaries (no raw 15-min slots) — efficient for trend charts.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days - 1)
    rows = get_prices_for_date_range(db, start, today, area=area)

    from collections import defaultdict
    by_date: dict[date, list[float]] = defaultdict(list)
    for r in rows:
        cet_date = _to_stockholm_date(r.timestamp_utc)
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
        "area": area,
        "currency": "SEK/kWh",
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "daily": daily,
    }


@router.get("/multi-zone")
def get_multi_zone_history(
    db: DbDep,
    days: int = Query(90, ge=7, le=365, description="Number of past days to include"),
):
    """
    Daily average spot prices for all four SE bidding zones (SE1-SE4) for the past N days.
    Useful for visualising the north-south price gradient and transmission bottlenecks.
    Zones with no DB data return null for each day (trigger a backfill first).
    """
    from collections import defaultdict

    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=days - 1)

    zones: dict[str, list[dict]] = {}
    for area in sorted(VALID_AREAS):
        rows = get_prices_for_date_range(db, start, today, area=area)

        by_date: dict[date, list[float]] = defaultdict(list)
        for r in rows:
            cet_date = _to_stockholm_date(r.timestamp_utc)
            by_date[cet_date].append(float(r.price_sek_kwh))

        daily = []
        cur = start
        while cur <= today:
            vals = by_date.get(cur)
            daily.append({
                "date": cur.isoformat(),
                "avg_sek_kwh": round(sum(vals) / len(vals), 4) if vals else None,
            })
            cur += timedelta(days=1)
        zones[area] = daily

    return {
        "currency": "SEK/kWh",
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "zones": zones,
    }


@router.get("/cheapest-hours")
def get_cheapest_hours(
    db: DbDep,
    date: date = Query(..., description="Target date (YYYY-MM-DD)"),
    duration: int = Query(2, ge=1, le=12, description="Window size in hours (1-12)"),
    area: AreaDep = "SE3",
):
    """
    Find the cheapest consecutive `duration`-hour block for the given date.
    Useful for scheduling appliances (washing machine, EV charging, etc.).
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    prices, is_estimate = get_or_fetch_prices(db, date, area=area)
    if not prices:
        raise HTTPException(status_code=404, detail="No price data available for this date")

    window = find_cheapest_window(prices, duration)
    if window is None:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough data for a {duration}-hour window",
        )

    return {
        "area": area,
        "date": date.isoformat(),
        "currency": "SEK/kWh",
        "is_estimate": is_estimate,
        "cheapest_window": window,
    }


@router.get("/forecast")
def get_price_forecast(
    db: DbDep,
    date: date = Query(..., description="Target date to forecast (YYYY-MM-DD)"),
    area: AreaDep = "SE3",
    weeks: int = Query(8, ge=2, le=16, description="Past same-weekday weeks to sample"),
    record: bool = Query(False, description="Record predictions for backtest scoring"),
    model: str = Query("same_weekday_avg", description="Forecast model: same_weekday_avg | lgbm"),
):
    """
    Hourly price forecast for date.

    Models:
    - same_weekday_avg (default): p10/p50/p90 from past N same-weekday historical prices
    - lgbm: LightGBM trained on 90 days of features (price lags, generation mix, calendar)

    Pass record=true to save predictions for later accuracy scoring.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    model_name = model  # rename to avoid shadowing date param

    if model_name == "lgbm":
        from app.services.ml_forecast_service import build_lgbm_forecast
        result = build_lgbm_forecast(db, date, area=area)
        extra = {}
    else:
        today = datetime.now(tz=timezone.utc).date()
        hist_start = date - timedelta(weeks=weeks)
        hist_end = min(date - timedelta(days=1), today)

        rows = get_prices_for_date_range(db, hist_start, hist_end, area=area)

        target_weekday = date.weekday()
        sample_dates = {
            r.timestamp_utc.astimezone(_STOCKHOLM).date()
            for r in rows
            if r.timestamp_utc.astimezone(_STOCKHOLM).date().weekday() == target_weekday
        }

        result = build_forecast(rows, date)
        extra = {"weeks_back": weeks, "dates_sampled": len(sample_dates)}

    # Optionally record predictions for backtest accuracy scoring
    if record and result.get("slots"):
        from app.services.backtest_service import record_predictions
        record_predictions(db, date, area, model_name, result["slots"])

    return {
        "area": area,
        "date": date.isoformat(),
        "weekday": date.strftime("%A"),
        "currency": "SEK/kWh",
        "model": model_name,
        **extra,
        **result,
    }


@router.get("/forecast/accuracy")
def get_forecast_accuracy(
    db: DbDep,
    area: AreaDep = "SE3",
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    model: str | None = Query(None, description="Filter by model name"),
):
    """
    Forecast accuracy metrics (MAE, RMSE) per model over the last N days.

    Only includes dates where both predictions and actuals are recorded.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    from app.services.backtest_service import get_accuracy
    results = get_accuracy(db, area, model_name=model, days=days)

    return {
        "area": area,
        "days": days,
        "models": results,
    }


@router.get("/forecast/accuracy/breakdown")
def get_forecast_accuracy_breakdown(
    db: DbDep,
    area: AreaDep = "SE3",
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    by: str = Query("hour", description="Breakdown dimension: hour | weekday"),
):
    """
    Forecast accuracy broken down by hour (0-23) or weekday (0=Mon..6=Sun).

    Shows where models are accurate vs. struggling (e.g. morning peaks, weekends).
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")
    if by not in ("hour", "weekday"):
        raise HTTPException(status_code=422, detail="'by' must be 'hour' or 'weekday'")

    from app.services.backtest_service import get_accuracy_breakdown
    results = get_accuracy_breakdown(db, area, days=days, by=by)

    return {
        "area": area,
        "days": days,
        "by": by,
        "models": results,
    }


@router.get("/forecast/retrospective")
def get_forecast_retrospective(
    db: DbDep,
    date: date = Query(..., description="Target date to retrieve predictions for (YYYY-MM-DD)"),
    area: AreaDep = "SE3",
):
    """
    Retrieve recorded forecast predictions for a past date.

    Returns per-model hourly predictions alongside actuals (if available).
    Used to overlay "what we predicted" vs "what actually happened" on the Today chart.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    from app.services.backtest_service import get_retrospective
    models = get_retrospective(db, date, area)

    return {
        "area": area,
        "date": date.isoformat(),
        "models": models,
    }


@router.get("/balancing")
def get_balancing_prices(
    db: DbDep,
    date: date = Query(..., description="Target date (YYYY-MM-DD)"),
    area: AreaDep = "SE3",
):
    """
    Imbalance (balancing) prices for the given date from eSett EXP14.

    Returns two price series for each 15-min slot:
      - Long  (category A04): down-regulation price — typically at or below day-ahead
      - Short (category A05): up-regulation price — can spike 2–3× day-ahead

    Source: eSett Open Data API (Nordic imbalance settlement institution).
    Data lags ~5–6 hours behind real time. No API key required.

    These prices are set by Svenska kraftnät (SVK) and reflect the real cost
    of balancing the SE3 grid — a direct proxy for intraday grid stress.
    """
    if area not in VALID_AREAS:
        raise HTTPException(status_code=422, detail=f"Invalid area. Must be one of {sorted(VALID_AREAS)}")

    rows = get_balancing_for_date(db, date, area)

    # Re-fetch if no data, or if querying today and data is stale (>30 min).
    # eSett continuously publishes new 15-min slots with ~5-6h lag, so
    # cached DB rows for today will be missing the most recent hours.
    today_utc = datetime.now(tz=timezone.utc).date()
    needs_fetch = not rows
    if rows and date == today_utc:
        latest_ts = max(r.timestamp_utc for r in rows)
        stale_seconds = (datetime.now(timezone.utc) - latest_ts).total_seconds()
        needs_fetch = stale_seconds > 30 * 60

    if needs_fetch:
        try:
            rows = fetch_and_store_balancing(db, date, area)
        except BalancingError as exc:
            if not rows:
                raise HTTPException(
                    status_code=404,
                    detail=f"No balancing price data for {date}: {exc}",
                )

    long_prices  = []
    short_prices = []
    for r in rows:
        entry = {
            "timestamp_utc": r.timestamp_utc.isoformat(),
            "price_eur_mwh": float(r.price_eur_mwh),
            "price_sek_kwh": float(r.price_sek_kwh),
            "resolution":    r.resolution,
            "category":      r.category,
        }
        if r.category == "A04":
            long_prices.append(entry)
        else:
            short_prices.append(entry)

    all_prices = long_prices + short_prices
    sek_vals   = [p["price_sek_kwh"] for p in all_prices]

    return {
        "area":     area,
        "date":     date.isoformat(),
        "currency": "SEK/kWh",
        "source":   "eSett EXP14",
        "note": (
            "Long (A04) = down-regulation price, typically ≤ day-ahead. "
            "Short (A05) = up-regulation price, can spike far above day-ahead."
        ),
        "count": len(all_prices),
        "summary": {
            "min_sek_kwh": round(min(sek_vals), 4) if sek_vals else None,
            "max_sek_kwh": round(max(sek_vals), 4) if sek_vals else None,
            "avg_sek_kwh": round(sum(sek_vals) / len(sek_vals), 4) if sek_vals else None,
        },
        "long":  long_prices,
        "short": short_prices,
    }


@router.get("/exchange-rate")
def get_exchange_rate():
    """
    Current EUR/SEK exchange rate from Riksbank SWEA API.

    Published every Swedish business day at 16:15.
    Falls back to 11.0 on API failure.
    """
    from app.services.riksbank_client import fetch_eur_sek_rate
    rate, pub_date = fetch_eur_sek_rate()
    return {
        "pair": "EUR/SEK",
        "rate": rate,
        "published_date": pub_date.isoformat() if pub_date else None,
        "source": "Riksbank SWEA API",
        "is_fallback": pub_date is None,
    }
