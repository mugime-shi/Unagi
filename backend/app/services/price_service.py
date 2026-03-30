"""
Price service: orchestrates ENTSO-E fetch → DB UPSERT → read for API endpoints.

Design decisions:
- UPSERT via INSERT ... ON CONFLICT DO UPDATE (idempotent; safe to call daily)
- Returns estimated (fallback) data when DB has no rows for today (allows development without API key)
- All timestamps stored as UTC; conversion to local time is a frontend concern
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.spot_price import SpotPrice
from app.services.entsoe_client import EntsoEError, PricePoint, fetch_day_ahead_prices
from app.services.riksbank_client import get_eur_sek_rate as _get_eur_sek
from app.utils.timezone import stockholm_day_range_utc, stockholm_midnight_utc

# Map friendly area names (used in DB/API) to ENTSO-E EIC codes
_AREA_TO_EIC = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
}


# ---------------------------------------------------------------------------
# UPSERT
# ---------------------------------------------------------------------------


def upsert_prices(db: Session, points: list[PricePoint], area: str = "SE3") -> int:
    """
    Persist a list of PricePoints to spot_prices using INSERT ON CONFLICT DO UPDATE.
    Returns the number of rows written.
    """
    if not points:
        return 0

    stmt = text("""
        INSERT INTO spot_prices (area, timestamp_utc, price_eur_mwh, price_sek_kwh, resolution)
        VALUES (:area, :ts, :eur, :sek, :res)
        ON CONFLICT (area, timestamp_utc, resolution)
        DO UPDATE SET
            price_eur_mwh = EXCLUDED.price_eur_mwh,
            price_sek_kwh = EXCLUDED.price_sek_kwh
    """)

    params = [
        {"area": area, "ts": p.timestamp_utc, "eur": p.price_eur_mwh, "sek": p.price_sek_kwh, "res": p.resolution}
        for p in points
    ]
    db.execute(stmt, params)
    db.commit()
    return len(points)


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------


def get_prices_for_date(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> list[SpotPrice]:
    """
    Fetch spot prices for target_date from DB.
    Window: Stockholm midnight → next Stockholm midnight (handles CET/CEST).
    """
    day_start, day_end = stockholm_day_range_utc(target_date)

    return (
        db.query(SpotPrice)
        .filter(
            SpotPrice.area == area,
            SpotPrice.timestamp_utc >= day_start,
            SpotPrice.timestamp_utc < day_end,
        )
        .order_by(SpotPrice.timestamp_utc)
        .all()
    )


# ---------------------------------------------------------------------------
# Fetch + store (used by the scheduler task and the router's cache-miss path)
# ---------------------------------------------------------------------------


def fetch_and_store(
    db: Session,
    target_date: date,
    area: str = "SE3",
    api_key: Optional[str] = None,
) -> list[SpotPrice]:
    """
    Pull prices from ENTSO-E and store them. Returns the stored rows.
    Raises EntsoEError if the API call fails.
    """
    eic_code = _AREA_TO_EIC.get(area, area)  # "SE3" → EIC code for ENTSO-E
    points = fetch_day_ahead_prices(
        target_date=target_date,
        area=eic_code,
        api_key=api_key,
    )
    upsert_prices(db, points, area=area)  # store with friendly name "SE3"
    return get_prices_for_date(db, target_date, area=area)


# ---------------------------------------------------------------------------
# READ: date range
# ---------------------------------------------------------------------------


def get_prices_for_date_range(
    db: Session,
    start_date: date,
    end_date: date,
    area: str = "SE3",
) -> list[SpotPrice]:
    """
    Fetch spot prices for a date range [start_date, end_date] inclusive.
    Window: start_date Stockholm midnight → end_date+1 Stockholm midnight (handles CET/CEST).
    """
    range_start = stockholm_midnight_utc(start_date)
    range_end = stockholm_midnight_utc(end_date + timedelta(days=1))

    return (
        db.query(SpotPrice)
        .filter(
            SpotPrice.area == area,
            SpotPrice.timestamp_utc >= range_start,
            SpotPrice.timestamp_utc < range_end,
        )
        .order_by(SpotPrice.timestamp_utc)
        .all()
    )


# ---------------------------------------------------------------------------
# Cheapest consecutive hours finder
# ---------------------------------------------------------------------------


def find_cheapest_window(prices_data: list[dict], duration_hours: int) -> dict | None:
    """
    Find the cheapest consecutive block of `duration_hours` hours.
    Handles both PT60M (hourly) and PT15M (15-min) data by grouping into hours first.
    Returns a dict with start_time, end_time, avg_sek_kwh, slots.
    """
    if not prices_data or duration_hours <= 0:
        return None

    # Group by hour: key = UTC hour truncated, value = list of sek prices
    from collections import defaultdict

    hourly: dict[datetime, list[float]] = defaultdict(list)
    for p in prices_data:
        ts = datetime.fromisoformat(p["timestamp_utc"])
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        hourly[hour_ts].append(float(p["price_sek_kwh"]))

    hours = sorted(hourly.keys())
    if len(hours) < duration_hours:
        return None

    # Average price per hour
    avg_per_hour = [(h, sum(hourly[h]) / len(hourly[h])) for h in hours]

    best_start_idx = 0
    best_avg = math.inf

    for i in range(len(avg_per_hour) - duration_hours + 1):
        window = avg_per_hour[i : i + duration_hours]
        window_avg = sum(p for _, p in window) / duration_hours
        if window_avg < best_avg:
            best_avg = window_avg
            best_start_idx = i

    best_window = avg_per_hour[best_start_idx : best_start_idx + duration_hours]
    start_ts = best_window[0][0]
    end_ts = best_window[-1][0] + timedelta(hours=1)

    return {
        "start_utc": start_ts.isoformat(),
        "end_utc": end_ts.isoformat(),
        "duration_hours": duration_hours,
        "avg_sek_kwh": round(best_avg, 4),
        "slots": [{"hour_utc": h.isoformat(), "avg_sek_kwh": round(p, 4)} for h, p in best_window],
    }


# ---------------------------------------------------------------------------
# Fallback data (development fallback when no API key or DB is empty)
# ---------------------------------------------------------------------------


def _generate_fallback_prices(target_date: date) -> list[dict]:
    """
    Produce a realistic 24-hour SE3 price curve with hourly slots.
    Pattern: cheap overnight, morning/evening peaks, mid-day moderate.
    Values are in SEK/kWh (typical 2025 SE3 range: 0.20–1.20).
    """
    # Typical hourly shape (index = CET hour 0-23), SEK/kWh
    shape = [
        0.28,
        0.25,
        0.22,
        0.21,
        0.22,
        0.35,  # 00-05 cheap overnight
        0.72,
        0.95,
        1.05,
        0.88,
        0.70,
        0.60,  # 06-11 morning peak
        0.55,
        0.52,
        0.50,
        0.53,
        0.65,
        0.95,  # 12-17 mid-day / afternoon
        1.10,
        1.05,
        0.85,
        0.65,
        0.48,
        0.32,  # 18-23 evening peak → night
    ]
    base_utc = stockholm_midnight_utc(target_date)
    result = []
    for hour, sek in enumerate(shape):
        ts = base_utc + timedelta(hours=hour)
        result.append(
            {
                "timestamp_utc": ts.isoformat(),
                "price_eur_mwh": round(sek / _get_eur_sek() * 1000, 2),
                "price_sek_kwh": sek,
                "resolution": "PT60M",
                "is_estimate": True,
            }
        )
    return result


# ---------------------------------------------------------------------------
# High-level: get today's prices (DB → ENTSO-E fallback → mock fallback)
# ---------------------------------------------------------------------------


def get_or_fetch_prices(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> tuple[list, bool]:
    """
    Returns (price_data, is_estimate).
    1. Try DB first (fastest, no external call)
    2. If empty, try ENTSO-E (requires API key)
    3. If that fails (no key, API down, future date), return fallback estimates
    """
    rows = get_prices_for_date(db, target_date, area)
    if rows:
        data = [
            {
                "timestamp_utc": r.timestamp_utc.isoformat(),
                "price_eur_mwh": float(r.price_eur_mwh),
                "price_sek_kwh": float(r.price_sek_kwh),
                "resolution": r.resolution,
                "is_estimate": False,
            }
            for r in rows
        ]
        return data, False

    # Try live fetch
    try:
        rows = fetch_and_store(db, target_date, area)
        data = [
            {
                "timestamp_utc": r.timestamp_utc.isoformat(),
                "price_eur_mwh": float(r.price_eur_mwh),
                "price_sek_kwh": float(r.price_sek_kwh),
                "resolution": r.resolution,
                "is_estimate": False,
            }
            for r in rows
        ]
        return data, False
    except EntsoEError:
        pass

    # Fallback: estimated data
    return _generate_fallback_prices(target_date), True


# ---------------------------------------------------------------------------
# Same-weekday price forecast
# ---------------------------------------------------------------------------


def build_forecast(rows: list, target_date: date) -> dict:
    """
    Build an hourly price forecast for target_date using same-weekday historical data.

    Algorithm:
    - Filters rows to those whose Stockholm date shares the same weekday as target_date
    - Groups into (date, hour) buckets and averages within each bucket
    - For each hour 0-23, collects one avg per historical date, then computes:
        low  = p10 of those averages
        avg  = mean
        high = p90 of those averages
    Returns a dict with 'slots' (list of 24 hourly dicts) and 'summary'.
    """
    target_weekday = target_date.weekday()

    # Collect prices per (stockholm_date, stockholm_hour) — same weekday only
    date_hour_prices: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        ts = r.timestamp_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        from zoneinfo import ZoneInfo

        local = ts.astimezone(ZoneInfo("Europe/Stockholm"))
        if local.date().weekday() != target_weekday:
            continue
        date_hour_prices[(local.date(), local.hour)].append(float(r.price_sek_kwh))

    # One avg per (date, hour), then group by hour across dates
    by_hour: dict[int, list[float]] = defaultdict(list)
    for (_, h), prices in date_hour_prices.items():
        by_hour[h].append(sum(prices) / len(prices))

    slots = []
    for hour in range(24):
        samples = sorted(by_hour.get(hour, []))
        if not samples:
            slots.append({"hour": hour, "avg_sek_kwh": None, "low_sek_kwh": None, "high_sek_kwh": None})
            continue
        n = len(samples)
        avg = sum(samples) / n
        low_idx = max(0, int(n * 0.10))
        high_idx = min(n - 1, int(n * 0.90))
        slots.append(
            {
                "hour": hour,
                "avg_sek_kwh": round(avg, 4),
                "low_sek_kwh": round(samples[low_idx], 4),
                "high_sek_kwh": round(samples[high_idx], 4),
            }
        )

    valid = [(s["low_sek_kwh"], s["avg_sek_kwh"], s["high_sek_kwh"]) for s in slots if s["avg_sek_kwh"] is not None]
    return {
        "slots": slots,
        "summary": {
            "predicted_avg_sek_kwh": round(sum(v[1] for v in valid) / len(valid), 4) if valid else None,
            "predicted_low_sek_kwh": round(min(v[0] for v in valid), 4) if valid else None,
            "predicted_high_sek_kwh": round(max(v[2] for v in valid), 4) if valid else None,
        },
    }
