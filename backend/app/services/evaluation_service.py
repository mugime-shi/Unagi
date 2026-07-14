"""
Evaluation service: regime-split MAE, cheapest-hours capture rate, interval coverage.

These are the three product-level metrics defined in work/PROMPT_ACCURACY_2026-07-14.md:

1. Regime-split MAE — "volatile" days are those where the baseline
   (same_weekday_avg) breaks down: baseline daily MAE >= threshold (0.35).
   The model's value is insurance: near coin-flip on calm days, but it should
   win 88-95% of volatile days. Any change that trades volatile-day wins for
   calm-day MAE is a regression, which headline MAE alone cannot see.

2. Capture rate — of the savings available on a day (running flexible load in
   the actually-cheapest N hours vs. at the daily average), what fraction is
   captured by following the model's predicted cheapest N hours. This is the
   product metric behind the cheapest-hours feature. Flat days (nothing to
   capture) are excluded and counted separately.

3. Coverage by regime — % of actuals inside [predicted_low, predicted_high],
   split by the same regime tags. A well-calibrated 80% interval should sit
   near 80% in both regimes, per area.

All metrics read forecast_accuracy only, so they work identically on synced
production history and on backtest-written rows.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.forecast_accuracy import ForecastAccuracy

DEFAULT_VOLATILE_THRESHOLD = 0.35  # baseline daily MAE (SEK/kWh) at which the baseline "breaks"
DEFAULT_MIN_HOURS = 20  # min scored hours for a day to count (DST days have 23/25)
DEFAULT_N_CHEAPEST = 3  # mirrors N_CHEAPEST_HOURS in forecast_export_service
FLAT_DAY_SPREAD_SEK = 0.005  # days with < 0.5 öre/kWh capturable spread are noise


def _rows_by_model_day(
    db: Session,
    area: str,
    days: int,
    models: list[str],
) -> dict[str, dict[date, list[ForecastAccuracy]]]:
    """Fetch scored rows for the given models, grouped by model then target_date."""
    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.area == area,
            ForecastAccuracy.target_date >= cutoff,
            ForecastAccuracy.model_name.in_(models),
            ForecastAccuracy.actual_sek_kwh.isnot(None),
        )
        .all()
    )
    out: dict[str, dict[date, list[ForecastAccuracy]]] = {m: defaultdict(list) for m in models}
    for r in rows:
        out[r.model_name][r.target_date].append(r)
    return out


def _daily_mae(rows: list[ForecastAccuracy]) -> float:
    errors = [abs(float(r.predicted_sek_kwh) - float(r.actual_sek_kwh)) for r in rows]
    return sum(errors) / len(errors)


# ---------------------------------------------------------------------------
# 1. Regime-split MAE
# ---------------------------------------------------------------------------


def get_regime_split(
    db: Session,
    area: str = "SE3",
    days: int = 90,
    model: str = "lgbm",
    baseline: str = "same_weekday_avg",
    threshold: float = DEFAULT_VOLATILE_THRESHOLD,
    min_hours: int = DEFAULT_MIN_HOURS,
) -> dict:
    """
    Split days into calm/volatile by the BASELINE's daily MAE and compare models.

    A day is volatile iff the baseline's daily MAE >= threshold (the baseline
    "broke" that day). Only days where both models have >= min_hours scored
    hours are compared. MAEs are means of daily MAEs (each day weighs equally,
    matching the daily win-rate framing).

    Returns:
        {area, model, baseline, threshold, n_days,
         calm: {n_days, model_mae, baseline_mae, win_rate},
         volatile: {...},
         regime_by_date: {date: "calm"|"volatile"}}
    """
    data = _rows_by_model_day(db, area, days, [model, baseline])
    model_daily = {d: _daily_mae(rows) for d, rows in data[model].items() if len(rows) >= min_hours}
    base_daily = {d: _daily_mae(rows) for d, rows in data[baseline].items() if len(rows) >= min_hours}
    common = sorted(set(model_daily) & set(base_daily))

    regime_by_date = {d: ("volatile" if base_daily[d] >= threshold else "calm") for d in common}

    def _aggregate(dates: list[date]) -> dict:
        if not dates:
            return {"n_days": 0, "model_mae": None, "baseline_mae": None, "win_rate": None}
        wins = sum(1 for d in dates if model_daily[d] < base_daily[d])
        return {
            "n_days": len(dates),
            "model_mae": round(sum(model_daily[d] for d in dates) / len(dates), 4),
            "baseline_mae": round(sum(base_daily[d] for d in dates) / len(dates), 4),
            "win_rate": round(wins / len(dates), 3),
        }

    return {
        "area": area,
        "model": model,
        "baseline": baseline,
        "threshold": threshold,
        "n_days": len(common),
        "calm": _aggregate([d for d in common if regime_by_date[d] == "calm"]),
        "volatile": _aggregate([d for d in common if regime_by_date[d] == "volatile"]),
        "regime_by_date": regime_by_date,
    }


# ---------------------------------------------------------------------------
# 2. Cheapest-hours capture rate
# ---------------------------------------------------------------------------


def get_capture_rate(
    db: Session,
    area: str = "SE3",
    days: int = 90,
    model: str = "lgbm",
    n_hours: int = DEFAULT_N_CHEAPEST,
    flat_spread: float = FLAT_DAY_SPREAD_SEK,
) -> dict:
    """
    Fraction of available daily savings captured by the model's cheapest-N picks.

    Per day with a full 24 scored hours:
        perfect  = cost of the N actually-cheapest hours
        nothing  = N * daily mean price (run whenever, no optimization)
        picked   = actual cost of the N hours the model predicted cheapest
        capture  = (nothing - picked) / (nothing - perfect)

    1.0 = picked the true cheapest hours; 0.0 = no better than not optimizing;
    < 0 = actively worse than not optimizing.

    Days where the capturable spread per kWh ((nothing - perfect) / n_hours)
    is below flat_spread are skipped (nothing to capture, ratio is noise) and
    reported as n_days_skipped_flat. mean_daily_spread_sek_kwh is reported over
    ALL full days — it measures how much this area offers to capture at all.
    """
    data = _rows_by_model_day(db, area, days, [model])
    captures: list[float] = []
    spreads: list[float] = []
    skipped_flat = 0

    for _d, rows in data[model].items():
        by_hour = {r.hour: (float(r.predicted_sek_kwh), float(r.actual_sek_kwh)) for r in rows}
        if len(by_hour) < 24:
            continue
        actuals = [by_hour[h][1] for h in range(24)]
        perfect = sum(sorted(actuals)[:n_hours])
        nothing = n_hours * sum(actuals) / 24
        spread = (nothing - perfect) / n_hours
        spreads.append(spread)
        if spread < flat_spread:
            skipped_flat += 1
            continue
        picked_hours = sorted(range(24), key=lambda h: by_hour[h][0])[:n_hours]
        picked = sum(by_hour[h][1] for h in picked_hours)
        captures.append((nothing - picked) / (nothing - perfect))

    if not captures:
        return {
            "area": area,
            "model": model,
            "n_hours": n_hours,
            "mean_capture": None,
            "median_capture": None,
            "n_days": 0,
            "n_days_skipped_flat": skipped_flat,
            "mean_daily_spread_sek_kwh": round(sum(spreads) / len(spreads), 4) if spreads else None,
        }

    ordered = sorted(captures)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2

    return {
        "area": area,
        "model": model,
        "n_hours": n_hours,
        "mean_capture": round(sum(captures) / len(captures), 3),
        "median_capture": round(median, 3),
        "n_days": len(captures),
        "n_days_skipped_flat": skipped_flat,
        "mean_daily_spread_sek_kwh": round(sum(spreads) / len(spreads), 4),
    }


# ---------------------------------------------------------------------------
# 3. Interval coverage by regime
# ---------------------------------------------------------------------------


def get_coverage_by_regime(
    db: Session,
    area: str = "SE3",
    days: int = 90,
    model: str = "lgbm",
    baseline: str = "same_weekday_avg",
    threshold: float = DEFAULT_VOLATILE_THRESHOLD,
) -> dict:
    """
    Prediction-interval coverage split by regime (calm/volatile, baseline-defined).

    overall includes every scored row with interval bounds; calm/volatile only
    cover days that could be regime-tagged (i.e. the baseline also scored them).

    Returns: {expected_pct, overall: {coverage_pct, n_samples},
              calm: {...}, volatile: {...}}
    """
    regime_by_date = get_regime_split(
        db, area=area, days=days, model=model, baseline=baseline, threshold=threshold
    )["regime_by_date"]

    cutoff = date.today() - timedelta(days=days)
    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.area == area,
            ForecastAccuracy.model_name == model,
            ForecastAccuracy.target_date >= cutoff,
            ForecastAccuracy.actual_sek_kwh.isnot(None),
            ForecastAccuracy.predicted_low_sek_kwh.isnot(None),
            ForecastAccuracy.predicted_high_sek_kwh.isnot(None),
        )
        .all()
    )

    buckets: dict[str, list[bool]] = {"overall": [], "calm": [], "volatile": []}
    for r in rows:
        covered = float(r.predicted_low_sek_kwh) <= float(r.actual_sek_kwh) <= float(r.predicted_high_sek_kwh)
        buckets["overall"].append(covered)
        regime = regime_by_date.get(r.target_date)
        if regime:
            buckets[regime].append(covered)

    def _rate(flags: list[bool]) -> dict:
        if not flags:
            return {"coverage_pct": None, "n_samples": 0}
        return {"coverage_pct": round(sum(flags) / len(flags) * 100, 1), "n_samples": len(flags)}

    return {
        "area": area,
        "model": model,
        "expected_pct": 80.0,
        "overall": _rate(buckets["overall"]),
        "calm": _rate(buckets["calm"]),
        "volatile": _rate(buckets["volatile"]),
    }
