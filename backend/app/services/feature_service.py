"""
Feature engineering for ML price prediction.

Builds a feature matrix from historical spot prices and generation mix data.
Each row represents one (date, hour) observation with features for LightGBM.
"""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import holidays
from astral import LocationInfo
from astral.sun import azimuth as _astral_azimuth
from astral.sun import elevation as _astral_elevation
from astral.sun import sun as _astral_sun
from sqlalchemy.orm import Session

from app.models.balancing_price import BalancingPrice
from app.models.generation_mix import GenerationMix
from app.models.spot_price import SpotPrice
from app.models.weather_data import WeatherData
from app.models.weather_forecast import WeatherForecast
from app.utils.timezone import stockholm_day_range_utc

_STOCKHOLM = ZoneInfo("Europe/Stockholm")
_STOCKHOLM_LOC = LocationInfo("Stockholm", "Sweden", "Europe/Stockholm", 59.3293, 18.0686)

# Holiday calendars for cross-border scoring (SE + NO + DE)
_HOLIDAYS_SE = holidays.Sweden()
_HOLIDAYS_NO = holidays.Norway()
_HOLIDAYS_DE = holidays.Germany()

# ENTSO-E PSR types that count as each group
_PSR_GROUP = {
    "B04": "gas",
    "B12": "hydro",
    "B14": "nuclear",
    "B16": "solar",
    "B19": "wind",
    "B20": "other",
}
_RENEWABLE = {"B12", "B16", "B19"}


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC (SQLite returns naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Internal: pure-computation feature helpers (no DB access)
# ---------------------------------------------------------------------------


def _holiday_features(d: date) -> dict[str, float]:
    """Compute holiday features for a date. Pure computation, no API."""
    is_se = 1 if d in _HOLIDAYS_SE else 0
    is_no = 1 if d in _HOLIDAYS_NO else 0
    is_de = 1 if d in _HOLIDAYS_DE else 0
    score = round((is_se + is_no + is_de) / 3.0, 4)

    # Bridge day: weekday between a holiday and a weekend (or vice versa)
    is_bridge = 0
    wd = d.weekday()
    if wd not in (5, 6) and not is_se:  # only non-holiday weekdays
        prev = d - timedelta(days=1)
        nxt = d + timedelta(days=1)
        prev_off = prev.weekday() >= 5 or prev in _HOLIDAYS_SE
        next_off = nxt.weekday() >= 5 or nxt in _HOLIDAYS_SE
        if prev_off and next_off:
            is_bridge = 1

    return {
        "is_holiday_se": is_se,
        "holiday_score": score,
        "is_bridge_day": is_bridge,
    }


def _solar_features(d: date, hour: int) -> dict[str, float]:
    """Compute solar position features for Stockholm. Pure computation, no API."""
    dt_local = datetime(d.year, d.month, d.day, hour, 30, tzinfo=_STOCKHOLM)

    elev = _astral_elevation(_STOCKHOLM_LOC.observer, dt_local)
    azim = _astral_azimuth(_STOCKHOLM_LOC.observer, dt_local)

    try:
        s = _astral_sun(_STOCKHOLM_LOC.observer, d, tzinfo=_STOCKHOLM)
        sunrise = s["sunrise"]
        sunset = s["sunset"]
        daylight = (sunset - sunrise).total_seconds() / 3600.0
    except ValueError:
        # Polar night or midnight sun — no sunrise/sunset
        daylight = 0.0 if d.month in (11, 12, 1) else 24.0

    return {
        "sun_elevation": round(elev, 2),
        "sun_azimuth": round(azim, 2),
        "daylight_hours": round(daylight, 2),
    }


# ---------------------------------------------------------------------------
# Internal: query helpers
# ---------------------------------------------------------------------------


def _cet_window(target_date: date) -> tuple[datetime, datetime]:
    """Return UTC range for one Stockholm time (CET/CEST) calendar day."""
    return stockholm_day_range_utc(target_date)


def _load_hourly_prices(
    db: Session,
    start_date: date,
    end_date: date,
    area: str,
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
    db: Session,
    start_date: date,
    end_date: date,
    area: str,
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
    db: Session,
    start_date: date,
    end_date: date,
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
    db: Session,
    start_date: date,
    end_date: date,
    area: str,
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


def _load_hourly_forecast(
    db: Session,
    target_date: date,
) -> dict[int, dict[str, float]]:
    """
    Load weather forecast for target_date, keyed by hour.
    Returns {hour: {"wind_speed_10m": float, "wind_speed_100m": float,
                     "temp_forecast": float, "radiation_forecast": float}}.

    Uses weather_forecast table (forecast-as-issued) when available.
    Falls back to weather_data actuals for historical dates where no
    forecast was stored (enables backtesting before forecast collection started).
    """
    range_start, _ = _cet_window(target_date)
    _, range_end = _cet_window(target_date)

    # Try forecast table first (issued on target_date - 1, which is when
    # the morning prediction would have fetched it)
    issued = target_date - timedelta(days=1)
    forecast_rows = (
        db.query(WeatherForecast)
        .filter(
            WeatherForecast.issued_date == issued,
            WeatherForecast.target_utc >= range_start,
            WeatherForecast.target_utc < range_end,
        )
        .all()
    )

    if forecast_rows:
        result: dict[int, dict[str, float]] = {}
        for r in forecast_rows:
            local = _ensure_utc(r.target_utc).astimezone(_STOCKHOLM)
            entry: dict[str, float] = {}
            if r.wind_speed_10m is not None:
                entry["wind_speed_10m"] = float(r.wind_speed_10m)
            if r.wind_speed_100m is not None:
                entry["wind_speed_100m"] = float(r.wind_speed_100m)
            if r.temperature_c is not None:
                entry["temp_forecast"] = float(r.temperature_c)
            if r.global_radiation_wm2 is not None:
                entry["radiation_forecast"] = float(r.global_radiation_wm2)
            result[local.hour] = entry
        return result

    # Fallback: use actual weather data as pseudo-forecast (for backtest)
    weather_rows = (
        db.query(WeatherData)
        .filter(
            WeatherData.timestamp_utc >= range_start,
            WeatherData.timestamp_utc < range_end,
        )
        .all()
    )
    result = {}
    for r in weather_rows:
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        entry = {}
        if r.temperature_c is not None:
            entry["temp_forecast"] = float(r.temperature_c)
        if r.global_radiation_wm2 is not None:
            entry["radiation_forecast"] = float(r.global_radiation_wm2)
        # No wind data in weather_data table — will be None
        result[local.hour] = entry
    return result


def _load_hourly_load_forecast(
    db: Session,
    start_date: date,
    end_date: date,
    area: str,
) -> dict[tuple[date, int], float]:
    """
    Load ENTSO-E A65 day-ahead load forecasts and bucket into (date, hour).
    Returns {(date, hour): load_mw}.
    """
    from app.models.load_forecast import LoadForecast

    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(LoadForecast)
        .filter(
            LoadForecast.area == area,
            LoadForecast.timestamp_utc >= range_start,
            LoadForecast.timestamp_utc < range_end,
        )
        .order_by(LoadForecast.timestamp_utc)
        .all()
    )

    buckets: dict[tuple[date, int], list[float]] = defaultdict(list)
    for r in rows:
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        buckets[(local.date(), local.hour)].append(float(r.load_mw))

    return {k: sum(v) / len(v) for k, v in buckets.items()}


def _load_gas_prices(
    db: Session,
    start_date: date,
    end_date: date,
) -> dict[date, float]:
    """
    Load gas prices and forward-fill for weekends/holidays.
    Returns {date: price_eur_mwh} for every date in range.
    """
    from app.models.gas_price import GasPrice

    # Fetch with extra lookback for forward-fill
    lookback_start = start_date - timedelta(days=14)
    rows = (
        db.query(GasPrice)
        .filter(
            GasPrice.trade_date >= lookback_start,
            GasPrice.trade_date <= end_date,
        )
        .order_by(GasPrice.trade_date)
        .all()
    )

    # Build raw map from trading days
    raw: dict[date, float] = {}
    for r in rows:
        raw[r.trade_date] = float(r.price_eur_mwh)

    # Forward-fill: for each date in range, use most recent available price
    result: dict[date, float] = {}
    current = start_date
    while current <= end_date:
        if current in raw:
            result[current] = raw[current]
        else:
            # Look back up to 14 days for most recent price
            for lookback in range(1, 15):
                prev = current - timedelta(days=lookback)
                if prev in raw:
                    result[current] = raw[prev]
                    break
        current += timedelta(days=1)

    return result


def _load_hourly_de_prices(
    db: Session,
    start_date: date,
    end_date: date,
) -> dict[tuple[date, int], float]:
    """
    Load DE-LU spot prices and average into (date, hour) buckets.
    Returns {(date, hour): price_eur_mwh}.
    """
    from app.models.de_spot_price import DeSpotPrice

    range_start, _ = _cet_window(start_date)
    _, range_end = _cet_window(end_date)

    rows = (
        db.query(DeSpotPrice)
        .filter(
            DeSpotPrice.timestamp_utc >= range_start,
            DeSpotPrice.timestamp_utc < range_end,
        )
        .order_by(DeSpotPrice.timestamp_utc)
        .all()
    )

    buckets: dict[tuple[date, int], list[float]] = defaultdict(list)
    for r in rows:
        local = _ensure_utc(r.timestamp_utc).astimezone(_STOCKHOLM)
        buckets[(local.date(), local.hour)].append(float(r.price_eur_mwh))

    return {k: sum(v) / len(v) for k, v in buckets.items()}


# ---------------------------------------------------------------------------
# Public: build feature matrix
# ---------------------------------------------------------------------------


def build_feature_matrix(
    db: Session,
    start_date: date,
    end_date: date,
    area: str = "SE3",
    include_target: bool = True,
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> list[dict]:
    """
    Build a feature matrix for [start_date, end_date] inclusive.

    Each row is one (date, hour) with:
    - Target: price_sek_kwh (only when include_target=True)
    - Calendar features: hour, weekday, month, sin/cos cyclical encodings
    - Lag features: prev_day_same_hour, prev_week_same_hour, daily_avg_prev_day
    - Generation features: hydro_ratio, wind_ratio, nuclear_ratio, total_mw
      (uses previous day's generation as proxy for next-day prediction)

    When include_target=False, rows are generated for all 24 hours even without
    actual prices for that date. This is used for prediction (future dates).

    price_overrides: optional dict of {(date, hour): price_sek_kwh} to inject
    predicted prices as pseudo-actuals for lag features (used in recursive
    multi-horizon forecasting, e.g. d+1 predictions used as lags for d+2).

    Returns a list of dicts (easily convertible to DataFrame).
    """
    # Load extra history for lag + rolling features (14 days before start_date)
    # When predicting (include_target=False), we only need prices up to end_date-1
    hist_start = start_date - timedelta(days=14)
    price_end = end_date if include_target else end_date - timedelta(days=1)
    prices = _load_hourly_prices(db, hist_start, price_end, area)

    # Merge predicted prices as pseudo-actuals for recursive forecasting
    if price_overrides:
        prices.update(price_overrides)
    gen = _load_hourly_generation(db, hist_start, end_date, area)
    weather = _load_hourly_weather(db, hist_start, end_date)
    balancing = _load_hourly_balancing(db, hist_start, end_date, area)
    load_fc = _load_hourly_load_forecast(db, hist_start, end_date, area)
    gas_prices = _load_gas_prices(db, hist_start, end_date)
    de_prices = _load_hourly_de_prices(db, hist_start, end_date)

    # Pre-compute daily aggregates
    daily_avg: dict[date, float] = {}
    daily_max: dict[date, float] = {}
    daily_min: dict[date, float] = {}
    daily_prices: dict[date, list[float]] = defaultdict(list)
    for (d, _h), p in prices.items():
        daily_prices[d].append(p)
    for d, vals in daily_prices.items():
        daily_avg[d] = sum(vals) / len(vals)
        daily_max[d] = max(vals)
        daily_min[d] = min(vals)

    # Pre-compute daily average temperature
    daily_temps: dict[date, list[float]] = defaultdict(list)
    for (d, _h), w in weather.items():
        if "temperature_c" in w:
            daily_temps[d].append(w["temperature_c"])
    daily_avg_temp: dict[date, float] = {d: sum(v) / len(v) for d, v in daily_temps.items()}

    # Pre-compute monthly average temperature (for deviation feature)
    monthly_temps: dict[int, list[float]] = defaultdict(list)
    for d, avg_t in daily_avg_temp.items():
        monthly_temps[d.month].append(avg_t)
    monthly_avg_temp: dict[int, float] = {m: sum(v) / len(v) for m, v in monthly_temps.items()}

    # Pre-compute daily average balancing (up/down)
    daily_bal_up: dict[date, list[float]] = defaultdict(list)
    daily_bal_down: dict[date, list[float]] = defaultdict(list)
    for (d, _h), bal in balancing.items():
        if "up" in bal:
            daily_bal_up[d].append(bal["up"])
        if "down" in bal:
            daily_bal_down[d].append(bal["down"])

    # Pre-compute daily load forecast aggregates (max, min per day)
    daily_load_max: dict[date, float] = {}
    daily_load_min: dict[date, float] = {}
    daily_load_vals: dict[date, list[float]] = defaultdict(list)
    for (d, _h), lf in load_fc.items():
        daily_load_vals[d].append(lf)
    for d, vals in daily_load_vals.items():
        daily_load_max[d] = max(vals)
        daily_load_min[d] = min(vals)

    # Pre-compute daily DE-LU price aggregates (previous day)
    daily_de_avg: dict[date, float] = {}
    daily_de_prices: dict[date, list[float]] = defaultdict(list)
    for (d, _h), dp in de_prices.items():
        daily_de_prices[d].append(dp)
    for d, vals in daily_de_prices.items():
        daily_de_avg[d] = sum(vals) / len(vals)

    # Pre-load weather forecasts for each date in the range
    forecast_cache: dict[date, dict[int, dict[str, float]]] = {}

    # Build rows for [start_date, end_date]
    rows = []
    current = start_date
    while current <= end_date:
        # Load forecast for this date (lazy, cached per date)
        if current not in forecast_cache:
            forecast_cache[current] = _load_hourly_forecast(db, current)
        forecast_day = forecast_cache[current]

        # Pre-compute per-day holiday + solar daylight features
        hol = _holiday_features(current)

        for hour in range(24):
            if include_target:
                target = prices.get((current, hour))
                if target is None:
                    continue  # skip hours without actual price data
            else:
                target = None  # prediction mode: no actual price needed

            prev_day = current - timedelta(days=1)
            prev_2day = current - timedelta(days=2)
            prev_3day = current - timedelta(days=3)
            prev_week = current - timedelta(days=7)

            # Generation from previous day same hour (available at prediction time)
            gen_prev = gen.get((prev_day, hour), {})
            gen_total = sum(gen_prev.values()) if gen_prev else 0.0

            # Weather from previous day same hour (actuals)
            weather_prev = weather.get((prev_day, hour), {})

            # Weather forecast for current date/hour (forward-looking)
            fc = forecast_day.get(hour, {})

            # Rolling 7-day mean/std for this hour
            hour_prices_7d = [
                prices[(current - timedelta(days=d), hour)]
                for d in range(1, 8)
                if (current - timedelta(days=d), hour) in prices
            ]
            rolling_7d_mean = sum(hour_prices_7d) / len(hour_prices_7d) if hour_prices_7d else None
            rolling_7d_std = None
            if len(hour_prices_7d) >= 2:
                mean = rolling_7d_mean
                rolling_7d_std = (sum((p - mean) ** 2 for p in hour_prices_7d) / len(hour_prices_7d)) ** 0.5

            # Price momentum
            p_d1 = prices.get((prev_day, hour))
            p_d2 = prices.get((prev_2day, hour))
            price_change_d1_d2 = round(p_d1 - p_d2, 4) if p_d1 is not None and p_d2 is not None else None

            # Previous day range
            prev_max = daily_max.get(prev_day)
            prev_min = daily_min.get(prev_day)
            daily_range = round(prev_max - prev_min, 4) if prev_max is not None and prev_min is not None else None

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
                round(bal_up_avg - bal_down_avg, 4) if bal_up_avg is not None and bal_down_avg is not None else None
            )

            # Solar position features (per hour)
            sol = _solar_features(current, hour)

            # Load forecast features (current day — forward-looking, available at prediction time)
            # Fallback to D-1 when current day not yet published
            # (ENTSO-E A65 published ~10:00 UTC, predictions run at 00:20 UTC)
            lf_hour = load_fc.get((current, hour)) or load_fc.get((prev_day, hour))
            lf_max = daily_load_max.get(current) or daily_load_max.get(prev_day)
            lf_min = daily_load_min.get(current) or daily_load_min.get(prev_day)
            lf_range = round(lf_max - lf_min, 1) if lf_max is not None and lf_min is not None else None
            # 7-day rolling average of daily max load (for anomaly detection)
            lf_max_7d = [
                daily_load_max[current - timedelta(days=d)]
                for d in range(1, 8)
                if (current - timedelta(days=d)) in daily_load_max
            ]
            lf_vs_avg = (
                round(lf_max / (sum(lf_max_7d) / len(lf_max_7d)), 4) if lf_max is not None and lf_max_7d else None
            )
            # Interaction: load × hour_sin (amplifies peak-hour load signal)
            lf_x_hour = round(lf_hour * math.sin(2 * math.pi * hour / 24), 4) if lf_hour is not None else None

            row = {
                # Target + identifiers
                "date": current.isoformat(),
                "hour": hour,
                **({"price_sek_kwh": round(target, 4)} if target is not None else {}),
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
                # Holiday features (pure computation)
                "is_holiday_se": hol["is_holiday_se"],
                "holiday_score": hol["holiday_score"],
                "is_bridge_day": hol["is_bridge_day"],
                # Solar position features (pure computation)
                "sun_elevation": sol["sun_elevation"],
                "sun_azimuth": sol["sun_azimuth"],
                "daylight_hours": sol["daylight_hours"],
                # Load forecast features (forward-looking: current day)
                "load_forecast_max": lf_max,
                "load_forecast_min": lf_min,
                "load_forecast_hour": lf_hour,
                "load_forecast_range": lf_range,
                "load_forecast_vs_avg": lf_vs_avg,
                "load_x_hour": lf_x_hour,
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
                "rolling_7d_mean": (round(rolling_7d_mean, 4) if rolling_7d_mean is not None else None),
                "rolling_7d_std": (round(rolling_7d_std, 4) if rolling_7d_std is not None else None),
                # Weather features (previous day as proxy)
                "temperature_c": weather_prev.get("temperature_c"),
                "radiation_wm2": weather_prev.get("radiation_wm2"),
                "daily_avg_temp_prev_day": (round(prev_day_temp, 2) if prev_day_temp is not None else None),
                "temp_deviation": temp_dev,
                # Generation features (previous day as proxy)
                "gen_hydro_mw": gen_prev.get("hydro"),
                "gen_wind_mw": gen_prev.get("wind"),
                "gen_nuclear_mw": gen_prev.get("nuclear"),
                "gen_total_mw": gen_total if gen_total > 0 else None,
                "hydro_ratio": (round(gen_prev.get("hydro", 0) / gen_total, 4) if gen_total > 0 else None),
                "wind_ratio": (round(gen_prev.get("wind", 0) / gen_total, 4) if gen_total > 0 else None),
                "nuclear_ratio": (round(gen_prev.get("nuclear", 0) / gen_total, 4) if gen_total > 0 else None),
                # Balancing price features (previous day)
                "bal_up_avg_prev_day": (round(bal_up_avg, 4) if bal_up_avg is not None else None),
                "bal_down_avg_prev_day": (round(bal_down_avg, 4) if bal_down_avg is not None else None),
                "bal_spread_prev_day": bal_spread,
                # Forecast features (forward-looking: target date)
                "wind_speed_10m_fc": fc.get("wind_speed_10m"),
                "wind_speed_100m_fc": fc.get("wind_speed_100m"),
                "temp_forecast": fc.get("temp_forecast"),
                "radiation_forecast": fc.get("radiation_forecast"),
                # Gas price features (forward-filled for weekends/holidays)
                "gas_price_eur_mwh": gas_prices.get(current),
                "gas_price_7d_avg": (
                    round(
                        sum(
                            gas_prices[current - timedelta(days=d)]
                            for d in range(7)
                            if (current - timedelta(days=d)) in gas_prices
                        )
                        / max(1, sum(1 for d in range(7) if (current - timedelta(days=d)) in gas_prices)),
                        2,
                    )
                    if any((current - timedelta(days=d)) in gas_prices for d in range(7))
                    else None
                ),
                "gas_price_change": (
                    round(gas_prices[current] - gas_prices[prev_day], 2)
                    if current in gas_prices and prev_day in gas_prices
                    else None
                ),
                # DE-LU price features (previous day — available at prediction time)
                "de_price_prev_day": (round(daily_de_avg[prev_day], 2) if prev_day in daily_de_avg else None),
                "de_se3_spread_prev_day": (
                    round(daily_de_avg[prev_day] - daily_avg[prev_day] * 1000 / 11.06, 2)
                    if prev_day in daily_de_avg and prev_day in daily_avg
                    else None
                ),
                "de_price_same_hour_prev_day": (
                    round(de_prices[(prev_day, hour)], 2) if (prev_day, hour) in de_prices else None
                ),
                # Interaction features
                "wind_x_hour": (
                    round(gen_prev.get("wind", 0) * math.sin(2 * math.pi * hour / 24), 4)
                    if gen_prev.get("wind") is not None
                    else None
                ),
                "temp_x_month": (
                    round(weather_prev.get("temperature_c", 0) * math.sin(2 * math.pi * (current.month - 1) / 12), 4)
                    if weather_prev.get("temperature_c") is not None
                    else None
                ),
            }
            rows.append(row)

        current += timedelta(days=1)

    return rows


# Feature columns used by the ML model (excludes target and identifiers)
FEATURE_COLS = [
    # Calendar (10)
    "hour",
    "weekday",
    "month",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "month_sin",
    "month_cos",
    "is_weekend",
    # Holiday (3)
    "is_holiday_se",
    "holiday_score",
    "is_bridge_day",
    # Solar position (3)
    "sun_elevation",
    "sun_azimuth",
    "daylight_hours",
    # Load forecast (6)
    "load_forecast_max",
    "load_forecast_min",
    "load_forecast_hour",
    "load_forecast_range",
    "load_forecast_vs_avg",
    "load_x_hour",
    # Lag (9)
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
    "gen_hydro_mw",
    "gen_wind_mw",
    "gen_nuclear_mw",
    "gen_total_mw",
    "hydro_ratio",
    "wind_ratio",
    "nuclear_ratio",
    # Balancing (3)
    "bal_up_avg_prev_day",
    "bal_down_avg_prev_day",
    "bal_spread_prev_day",
    # Forecast (4)
    "wind_speed_10m_fc",
    "wind_speed_100m_fc",
    "temp_forecast",
    "radiation_forecast",
    # Gas price (3)
    "gas_price_eur_mwh",
    "gas_price_7d_avg",
    "gas_price_change",
    # DE-LU price (3)
    "de_price_prev_day",
    "de_se3_spread_prev_day",
    "de_price_same_hour_prev_day",
    # Interactions (2)
    "wind_x_hour",
    "temp_x_month",
]

TARGET_COL = "price_sek_kwh"
