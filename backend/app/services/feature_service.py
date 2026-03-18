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

from app.models.balancing_price import BalancingPrice
from app.models.generation_mix import GenerationMix
from app.models.spot_price import SpotPrice
from app.models.weather_data import WeatherData

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


def _load_hourly_weather(
    db: Session, start_date: date, end_date: date,
) -> dict[tuple[date, int], dict[str, float]]:
    """
    Load weather data and bucket into (stockholm_date, stockholm_hour).
    Returns {(date, hour): {"temperature_c": float, "radiation_wm2": float}}.
    """
    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(WeatherData)
        .filter(
            WeatherData.timestamp_utc >= range_start,
            WeatherData.timestamp_utc < range_end,
        )
        .order_by(WeatherData.timestamp_utc)
        .all()
    )

    result: dict[tuple[date, int], dict[str, float]] = {}
    for r in rows:
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        key = (local.date(), local.hour)
        if key not in result:
            result[key] = {}
        if r.temperature_c is not None:
            result[key]["temperature_c"] = float(r.temperature_c)
        if r.global_radiation_wm2 is not None:
            result[key]["radiation_wm2"] = float(r.global_radiation_wm2)

    return result


def _load_hourly_balancing(
    db: Session, start_date: date, end_date: date, area: str,
) -> dict[tuple[date, int], dict[str, float]]:
    """
    Load balancing prices and average into hourly buckets.
    Returns {(date, hour): {"up": avg_sek_kwh, "down": avg_sek_kwh}}.
    """
    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(BalancingPrice)
        .filter(
            BalancingPrice.area == area,
            BalancingPrice.timestamp_utc >= range_start,
            BalancingPrice.timestamp_utc < range_end,
        )
        .order_by(BalancingPrice.timestamp_utc)
        .all()
    )

    raw: dict[tuple[date, int, str], list[float]] = defaultdict(list)
    for r in rows:
        if r.price_sek_kwh is None:
            continue
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        cat = "up" if r.category == "A05" else "down"
        raw[(local.date(), local.hour, cat)].append(float(r.price_sek_kwh))

    result: dict[tuple[date, int], dict[str, float]] = defaultdict(dict)
    for (d, h, cat), vals in raw.items():
        result[(d, h)][cat] = sum(vals) / len(vals)

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
    # Load extra history for lag + rolling features (14 days before start_date)
    hist_start = start_date - timedelta(days=14)
    prices = _load_hourly_prices(db, hist_start, end_date, area)
    gen = _load_hourly_generation(db, hist_start, end_date, area)
    weather = _load_hourly_weather(db, hist_start, end_date)
    balancing = _load_hourly_balancing(db, hist_start, end_date, area)

    # Pre-compute daily aggregates
    daily_avg: dict[date, float] = {}
    daily_max: dict[date, float] = {}
    daily_min: dict[date, float] = {}
    daily_prices: dict[date, list[float]] = defaultdict(list)
    for (d, h), p in prices.items():
        daily_prices[d].append(p)
    for d, vals in daily_prices.items():
        daily_avg[d] = sum(vals) / len(vals)
        daily_max[d] = max(vals)
        daily_min[d] = min(vals)

    # Pre-compute daily average temperature
    daily_temps: dict[date, list[float]] = defaultdict(list)
    for (d, h), w in weather.items():
        if "temperature_c" in w:
            daily_temps[d].append(w["temperature_c"])
    daily_avg_temp: dict[date, float] = {
        d: sum(v) / len(v) for d, v in daily_temps.items()
    }

    # Pre-compute monthly average temperature (for deviation feature)
    monthly_temps: dict[int, list[float]] = defaultdict(list)
    for d, avg_t in daily_avg_temp.items():
        monthly_temps[d.month].append(avg_t)
    monthly_avg_temp: dict[int, float] = {
        m: sum(v) / len(v) for m, v in monthly_temps.items()
    }

    # Pre-compute daily average balancing (up/down)
    daily_bal_up: dict[date, list[float]] = defaultdict(list)
    daily_bal_down: dict[date, list[float]] = defaultdict(list)
    for (d, h), bal in balancing.items():
        if "up" in bal:
            daily_bal_up[d].append(bal["up"])
        if "down" in bal:
            daily_bal_down[d].append(bal["down"])

    # Build rows for [start_date, end_date]
    rows = []
    current = start_date
    while current <= end_date:
        for hour in range(24):
            target = prices.get((current, hour))
            if target is None:
                continue  # skip hours without actual price data

            prev_day = current - timedelta(days=1)
            prev_2day = current - timedelta(days=2)
            prev_3day = current - timedelta(days=3)
            prev_week = current - timedelta(days=7)

            # Generation from previous day same hour (available at prediction time)
            gen_prev = gen.get((prev_day, hour), {})
            gen_total = sum(gen_prev.values()) if gen_prev else 0.0

            # Weather from previous day same hour
            weather_prev = weather.get((prev_day, hour), {})

            # Rolling 7-day mean/std for this hour
            hour_prices_7d = [
                prices[(current - timedelta(days=d), hour)]
                for d in range(1, 8)
                if (current - timedelta(days=d), hour) in prices
            ]
            rolling_7d_mean = (
                sum(hour_prices_7d) / len(hour_prices_7d)
                if hour_prices_7d else None
            )
            rolling_7d_std = None
            if len(hour_prices_7d) >= 2:
                mean = rolling_7d_mean
                rolling_7d_std = (
                    sum((p - mean) ** 2 for p in hour_prices_7d)
                    / len(hour_prices_7d)
                ) ** 0.5

            # Price momentum
            p_d1 = prices.get((prev_day, hour))
            p_d2 = prices.get((prev_2day, hour))
            price_change_d1_d2 = (
                round(p_d1 - p_d2, 4) if p_d1 is not None and p_d2 is not None else None
            )

            # Previous day range
            prev_max = daily_max.get(prev_day)
            prev_min = daily_min.get(prev_day)
            daily_range = (
                round(prev_max - prev_min, 4)
                if prev_max is not None and prev_min is not None else None
            )

            # Temperature deviation from monthly average
            prev_day_temp = daily_avg_temp.get(prev_day)
            temp_dev = None
            if prev_day_temp is not None and current.month in monthly_avg_temp:
                temp_dev = round(prev_day_temp - monthly_avg_temp[current.month], 2)

            # Daily average balancing prices (previous day)
            bal_up_vals = daily_bal_up.get(prev_day, [])
            bal_up_avg = sum(bal_up_vals) / len(bal_up_vals) if bal_up_vals else None
            bal_down_vals = daily_bal_down.get(prev_day, [])
            bal_down_avg = sum(bal_down_vals) / len(bal_down_vals) if bal_down_vals else None
            bal_spread = (
                round(bal_up_avg - bal_down_avg, 4)
                if bal_up_avg is not None and bal_down_avg is not None else None
            )

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
                "is_weekend": 1 if current.weekday() >= 5 else 0,

                # Lag features
                "prev_day_same_hour": prices.get((prev_day, hour)),
                "prev_2day_same_hour": prices.get((prev_2day, hour)),
                "prev_3day_same_hour": prices.get((prev_3day, hour)),
                "prev_week_same_hour": prices.get((prev_week, hour)),
                "daily_avg_prev_day": daily_avg.get(prev_day),
                "daily_max_prev_day": prev_max,
                "daily_min_prev_day": prev_min,
                "daily_range_prev_day": daily_range,
                "price_change_d1_d2": price_change_d1_d2,

                # Rolling features
                "rolling_7d_mean": (
                    round(rolling_7d_mean, 4) if rolling_7d_mean is not None else None
                ),
                "rolling_7d_std": (
                    round(rolling_7d_std, 4) if rolling_7d_std is not None else None
                ),

                # Weather features (previous day as proxy)
                "temperature_c": weather_prev.get("temperature_c"),
                "radiation_wm2": weather_prev.get("radiation_wm2"),
                "daily_avg_temp_prev_day": (
                    round(prev_day_temp, 2) if prev_day_temp is not None else None
                ),
                "temp_deviation": temp_dev,

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

                # Balancing price features (previous day)
                "bal_up_avg_prev_day": (
                    round(bal_up_avg, 4) if bal_up_avg is not None else None
                ),
                "bal_down_avg_prev_day": (
                    round(bal_down_avg, 4) if bal_down_avg is not None else None
                ),
                "bal_spread_prev_day": bal_spread,
            }
            rows.append(row)

        current += timedelta(days=1)

    return rows


# Feature columns used by the ML model (excludes target and identifiers)
FEATURE_COLS = [
    # Calendar (10)
    "hour", "weekday", "month",
    "hour_sin", "hour_cos",
    "weekday_sin", "weekday_cos",
    "month_sin", "month_cos",
    "is_weekend",
    # Lag (8)
    "prev_day_same_hour",
    "prev_2day_same_hour",
    "prev_3day_same_hour",
    "prev_week_same_hour",
    "daily_avg_prev_day",
    "daily_max_prev_day",
    "daily_min_prev_day",
    "daily_range_prev_day",
    "price_change_d1_d2",
    # Rolling (2)
    "rolling_7d_mean",
    "rolling_7d_std",
    # Weather (4)
    "temperature_c",
    "radiation_wm2",
    "daily_avg_temp_prev_day",
    "temp_deviation",
    # Generation (7)
    "gen_hydro_mw", "gen_wind_mw", "gen_nuclear_mw",
    "gen_total_mw",
    "hydro_ratio", "wind_ratio", "nuclear_ratio",
    # Balancing (3)
    "bal_up_avg_prev_day",
    "bal_down_avg_prev_day",
    "bal_spread_prev_day",
]

TARGET_COL = "price_sek_kwh"
