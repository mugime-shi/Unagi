"""
Feature engineering for ML price prediction.

Builds a feature matrix from historical spot prices and generation mix data.
Each row represents one (date, hour) observation with features for LightGBM.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.generation_mix import GenerationMix
from app.models.spot_price import SpotPrice

_STOCKHOLM = ZoneInfo("Europe/Stockholm")

# ENTSO-E PSR types that count as each group
_PSR_GROUP = {
    "B04": "gas", "B12": "hydro", "B14": "nuclear",
    "B16": "solar", "B19": "wind", "B20": "other",
}
_RENEWABLE = {"B12", "B16", "B19"}


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC (SQLite returns naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Internal: query helpers
# ---------------------------------------------------------------------------

def _cet_window(target_date: date) -> tuple[datetime, datetime]:
    """Return UTC range for one CET calendar day."""
    start = datetime(target_date.year, target_date.month, target_date.day,
                     tzinfo=timezone.utc) - timedelta(hours=1)
    return start, start + timedelta(hours=24)


def _load_hourly_prices(
    db: Session, start_date: date, end_date: date, area: str,
) -> dict[tuple[date, int], float]:
    """
    Load spot prices and average into (stockholm_date, stockholm_hour) buckets.
    Returns {(date, hour): avg_sek_kwh}.
    """
    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(SpotPrice)
        .filter(
            SpotPrice.area == area,
            SpotPrice.timestamp_utc >= range_start,
            SpotPrice.timestamp_utc < range_end,
        )
        .order_by(SpotPrice.timestamp_utc)
        .all()
    )

    buckets: dict[tuple[date, int], list[float]] = defaultdict(list)
    for r in rows:
        if r.price_sek_kwh is None:
            continue
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        buckets[(local.date(), local.hour)].append(float(r.price_sek_kwh))

    return {k: sum(v) / len(v) for k, v in buckets.items()}


def _load_hourly_generation(
    db: Session, start_date: date, end_date: date, area: str,
) -> dict[tuple[date, int], dict[str, float]]:
    """
    Load generation mix and average into hourly buckets.
    Returns {(date, hour): {hydro: MW, wind: MW, nuclear: MW, ...}}.
    """
    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(GenerationMix)
        .filter(
            GenerationMix.area == area,
            GenerationMix.timestamp_utc >= range_start,
            GenerationMix.timestamp_utc < range_end,
        )
        .order_by(GenerationMix.timestamp_utc)
        .all()
    )

    # Collect: (date, hour, group) → [mw values]
    raw: dict[tuple[date, int, str], list[float]] = defaultdict(list)
    for r in rows:
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        group = _PSR_GROUP.get(r.psr_type, "other")
        raw[(local.date(), local.hour, group)].append(float(r.value_mw))

    # Average into (date, hour) → {group: avg_mw}
    result: dict[tuple[date, int], dict[str, float]] = defaultdict(dict)
    for (d, h, group), vals in raw.items():
        result[(d, h)][group] = sum(vals) / len(vals)

    return result


# ---------------------------------------------------------------------------
# Public: build feature matrix
# ---------------------------------------------------------------------------

def build_feature_matrix(
    db: Session,
    start_date: date,
    end_date: date,
    area: str = "SE3",
) -> list[dict]:
    """
    Build a feature matrix for [start_date, end_date] inclusive.

    Each row is one (date, hour) with:
    - Target: price_sek_kwh
    - Calendar features: hour, weekday, month, sin/cos cyclical encodings
    - Lag features: prev_day_same_hour, prev_week_same_hour, daily_avg_prev_day
    - Generation features: hydro_ratio, wind_ratio, nuclear_ratio, total_mw
      (uses previous day's generation as proxy for next-day prediction)

    Returns a list of dicts (easily convertible to DataFrame).
    """
    # Load extra history for lag features (7 days before start_date)
    hist_start = start_date - timedelta(days=8)
    prices = _load_hourly_prices(db, hist_start, end_date, area)
    gen = _load_hourly_generation(db, hist_start, end_date, area)

    # Pre-compute daily averages
    daily_avg: dict[date, float] = {}
    daily_prices: dict[date, list[float]] = defaultdict(list)
    for (d, h), p in prices.items():
        daily_prices[d].append(p)
    for d, vals in daily_prices.items():
        daily_avg[d] = sum(vals) / len(vals)

    # Build rows for [start_date, end_date]
    rows = []
    current = start_date
    while current <= end_date:
        for hour in range(24):
            target = prices.get((current, hour))
            if target is None:
                continue  # skip hours without actual price data

            prev_day = current - timedelta(days=1)
            prev_week = current - timedelta(days=7)

            # Generation from previous day same hour (available at prediction time)
            gen_prev = gen.get((prev_day, hour), {})
            gen_total = sum(gen_prev.values()) if gen_prev else 0.0

            row = {
                # Target
                "date": current.isoformat(),
                "hour": hour,
                "price_sek_kwh": round(target, 4),

                # Calendar features
                "weekday": current.weekday(),
                "month": current.month,
                "hour_sin": round(math.sin(2 * math.pi * hour / 24), 6),
                "hour_cos": round(math.cos(2 * math.pi * hour / 24), 6),
                "weekday_sin": round(math.sin(2 * math.pi * current.weekday() / 7), 6),
                "weekday_cos": round(math.cos(2 * math.pi * current.weekday() / 7), 6),
                "month_sin": round(math.sin(2 * math.pi * (current.month - 1) / 12), 6),
                "month_cos": round(math.cos(2 * math.pi * (current.month - 1) / 12), 6),

                # Lag features
                "prev_day_same_hour": prices.get((prev_day, hour)),
                "prev_week_same_hour": prices.get((prev_week, hour)),
                "daily_avg_prev_day": daily_avg.get(prev_day),

                # Generation features (previous day as proxy)
                "gen_hydro_mw": gen_prev.get("hydro"),
                "gen_wind_mw": gen_prev.get("wind"),
                "gen_nuclear_mw": gen_prev.get("nuclear"),
                "gen_total_mw": gen_total if gen_total > 0 else None,
                "hydro_ratio": (
                    round(gen_prev.get("hydro", 0) / gen_total, 4)
                    if gen_total > 0 else None
                ),
                "wind_ratio": (
                    round(gen_prev.get("wind", 0) / gen_total, 4)
                    if gen_total > 0 else None
                ),
                "nuclear_ratio": (
                    round(gen_prev.get("nuclear", 0) / gen_total, 4)
                    if gen_total > 0 else None
                ),
            }
            rows.append(row)

        current += timedelta(days=1)

    return rows


# Feature columns used by the ML model (excludes target and identifiers)
FEATURE_COLS = [
    "hour", "weekday", "month",
    "hour_sin", "hour_cos",
    "weekday_sin", "weekday_cos",
    "month_sin", "month_cos",
    "prev_day_same_hour",
    "prev_week_same_hour",
    "daily_avg_prev_day",
    "gen_hydro_mw", "gen_wind_mw", "gen_nuclear_mw",
    "gen_total_mw",
    "hydro_ratio", "wind_ratio", "nuclear_ratio",
]

TARGET_COL = "price_sek_kwh"
