"""
Backtest service: record forecast predictions, fill actuals, compute accuracy.

Workflow:
1. Forecast generated (Day N-1) → record_predictions() saves 24 hourly predictions
2. Actual prices published (Day N) → fill_actuals() fills actual_sek_kwh from spot_prices
3. score_forecast() / get_accuracy() → compute MAE/RMSE per model
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import sqrt
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.forecast_accuracy import ForecastAccuracy

_STOCKHOLM = ZoneInfo("Europe/Stockholm")


# ---------------------------------------------------------------------------
# Record predictions
# ---------------------------------------------------------------------------


def record_predictions(
    db: Session,
    target_date: date,
    area: str,
    model_name: str,
    slots: list[dict],
) -> int:
    """
    Upsert forecast predictions for 24 hours.

    slots: list of {"hour": 0-23, "avg_sek_kwh": float | None,
                     "low_sek_kwh": float | None, "high_sek_kwh": float | None}
    Returns the number of rows written.

    low/high are quantile prediction bounds (p10/p90) for coverage rate
    tracking. Only LGBM produces these; same_weekday_avg will pass None.
    """
    stmt = text("""
        INSERT INTO forecast_accuracy
            (target_date, area, model_name, hour, predicted_sek_kwh,
             predicted_low_sek_kwh, predicted_high_sek_kwh)
        VALUES (:date, :area, :model, :hour, :predicted, :low, :high)
        ON CONFLICT (target_date, area, model_name, hour)
        DO UPDATE SET
            predicted_sek_kwh      = EXCLUDED.predicted_sek_kwh,
            predicted_low_sek_kwh  = EXCLUDED.predicted_low_sek_kwh,
            predicted_high_sek_kwh = EXCLUDED.predicted_high_sek_kwh
    """)
    count = 0
    for s in slots:
        if s.get("avg_sek_kwh") is not None:
            low = s.get("low_sek_kwh")
            high = s.get("high_sek_kwh")
            db.execute(
                stmt,
                {
                    "date": target_date,
                    "area": area,
                    "model": model_name,
                    "hour": s["hour"],
                    "predicted": round(s["avg_sek_kwh"], 4),
                    "low": round(low, 4) if low is not None else None,
                    "high": round(high, 4) if high is not None else None,
                },
            )
            count += 1
    db.commit()
    return count


# ---------------------------------------------------------------------------
# Fill actuals from spot_prices
# ---------------------------------------------------------------------------


def fill_actuals(db: Session, target_date: date, area: str = "SE3") -> int:
    """
    Fill actual_sek_kwh in forecast_accuracy from spot_prices for the given date.

    Averages 15-min slots into hourly buckets (Stockholm time) to match
    the hourly granularity of forecasts.
    Returns the number of hours updated.
    """
    from app.services.price_service import get_prices_for_date

    rows = get_prices_for_date(db, target_date, area)
    if not rows:
        return 0

    # Average spot prices by Stockholm hour
    by_hour: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        if r.price_sek_kwh is None:
            continue
        local_dt = r.timestamp_utc.astimezone(_STOCKHOLM)
        by_hour[local_dt.hour].append(float(r.price_sek_kwh))

    count = 0
    for hour, prices in by_hour.items():
        avg_actual = round(sum(prices) / len(prices), 4)
        result = db.execute(
            text("""
            UPDATE forecast_accuracy
            SET actual_sek_kwh = :actual
            WHERE target_date = :date
              AND area = :area
              AND hour = :hour
              AND actual_sek_kwh IS NULL
        """),
            {
                "date": target_date,
                "area": area,
                "hour": hour,
                "actual": avg_actual,
            },
        )
        count += result.rowcount
    db.commit()
    return count


# ---------------------------------------------------------------------------
# Score a single date
# ---------------------------------------------------------------------------


def score_forecast(
    db: Session,
    target_date: date,
    area: str,
    model_name: str,
) -> dict | None:
    """
    Fill actuals (if missing) and compute MAE/RMSE for a specific date and model.
    Returns None if no scored rows exist.
    """
    fill_actuals(db, target_date, area)

    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.target_date == target_date,
            ForecastAccuracy.area == area,
            ForecastAccuracy.model_name == model_name,
            ForecastAccuracy.actual_sek_kwh.isnot(None),
        )
        .all()
    )
    if not rows:
        return None

    errors = [abs(float(r.predicted_sek_kwh) - float(r.actual_sek_kwh)) for r in rows]
    mae = sum(errors) / len(errors)
    rmse = sqrt(sum(e**2 for e in errors) / len(errors))

    return {
        "date": target_date.isoformat(),
        "model_name": model_name,
        "mae_sek_kwh": round(mae, 4),
        "rmse_sek_kwh": round(rmse, 4),
        "hours_scored": len(rows),
    }


# ---------------------------------------------------------------------------
# Aggregate accuracy over N days
# ---------------------------------------------------------------------------


def get_accuracy(
    db: Session,
    area: str = "SE3",
    model_name: str | None = None,
    days: int = 30,
) -> dict[str, dict]:
    """
    Compute MAE and RMSE per model over the last N days.

    Returns: {model_name: {mae_sek_kwh, rmse_sek_kwh, n_samples, n_days}}
    Only includes rows where actual_sek_kwh is not null.
    """
    cutoff = date.today() - timedelta(days=days)

    # Production model names: lgbm (d+1), lgbm_d2..d7, same_weekday_avg
    # Exclude backtest-only models (lgbm_h1..h7) from user-facing accuracy
    _PROD_MODELS = {"lgbm", "same_weekday_avg"} | {f"lgbm_d{h}" for h in range(2, 8)}

    query = db.query(ForecastAccuracy).filter(
        ForecastAccuracy.area == area,
        ForecastAccuracy.target_date >= cutoff,
        ForecastAccuracy.actual_sek_kwh.isnot(None),
    )
    if model_name:
        query = query.filter(ForecastAccuracy.model_name == model_name)
    else:
        query = query.filter(ForecastAccuracy.model_name.in_(_PROD_MODELS))

    rows = query.all()

    by_model: dict[str, list] = defaultdict(list)
    dates_by_model: dict[str, set] = defaultdict(set)
    for r in rows:
        error = abs(float(r.predicted_sek_kwh) - float(r.actual_sek_kwh))
        by_model[r.model_name].append(error)
        dates_by_model[r.model_name].add(r.target_date)

    results = {}
    for model, errors in by_model.items():
        n = len(errors)
        mae = sum(errors) / n
        rmse = sqrt(sum(e**2 for e in errors) / n)
        results[model] = {
            "mae_sek_kwh": round(mae, 4),
            "rmse_sek_kwh": round(rmse, 4),
            "n_samples": n,
            "n_days": len(dates_by_model[model]),
        }

    return results


# ---------------------------------------------------------------------------
# Accuracy breakdown by hour or weekday
# ---------------------------------------------------------------------------


def get_accuracy_breakdown(
    db: Session,
    area: str = "SE3",
    days: int = 30,
    by: str = "hour",
) -> dict[str, list[dict]]:
    """
    Compute MAE per model broken down by hour (0-23) or weekday (0=Mon..6=Sun).

    Returns: {model_name: [{"key": int, "mae_sek_kwh": float, "rmse_sek_kwh": float, "n": int}, ...]}
    """
    cutoff = date.today() - timedelta(days=days)

    _PROD_MODELS = {"lgbm", "same_weekday_avg"} | {f"lgbm_d{h}" for h in range(2, 8)}

    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.area == area,
            ForecastAccuracy.target_date >= cutoff,
            ForecastAccuracy.actual_sek_kwh.isnot(None),
            ForecastAccuracy.model_name.in_(_PROD_MODELS),
        )
        .all()
    )

    # Group errors by (model_name, bucket_key)
    buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        error = abs(float(r.predicted_sek_kwh) - float(r.actual_sek_kwh))
        if by == "weekday":
            key = r.target_date.weekday()
        else:
            key = r.hour
        buckets[r.model_name][key].append(error)

    results = {}
    for model, keys in buckets.items():
        breakdown = []
        for key in sorted(keys.keys()):
            errors = keys[key]
            n = len(errors)
            mae = sum(errors) / n
            rmse = sqrt(sum(e**2 for e in errors) / n)
            breakdown.append(
                {
                    "key": key,
                    "mae_sek_kwh": round(mae, 4),
                    "rmse_sek_kwh": round(rmse, 4),
                    "n": n,
                }
            )
        results[model] = breakdown

    return results


# ---------------------------------------------------------------------------
# Retrospective: retrieve past predictions for a given date
# ---------------------------------------------------------------------------


def get_retrospective(
    db: Session,
    target_date: date,
    area: str = "SE3",
) -> dict[str, list[dict]]:
    """
    Retrieve recorded predictions for a past date (both models).

    Returns: {model_name: [{"hour": 0-23, "predicted_sek_kwh": float, "actual_sek_kwh": float|None}, ...]}
    """
    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.target_date == target_date,
            ForecastAccuracy.area == area,
        )
        .order_by(ForecastAccuracy.hour)
        .all()
    )

    by_model: dict[str, list[dict]] = defaultdict(list)
    earliest_created: datetime | None = None
    for r in rows:
        by_model[r.model_name].append(
            {
                "hour": r.hour,
                "predicted_sek_kwh": round(float(r.predicted_sek_kwh), 4),
                "predicted_low_sek_kwh": round(float(r.predicted_low_sek_kwh), 4)
                if r.predicted_low_sek_kwh is not None
                else None,
                "predicted_high_sek_kwh": round(float(r.predicted_high_sek_kwh), 4)
                if r.predicted_high_sek_kwh is not None
                else None,
                "actual_sek_kwh": round(float(r.actual_sek_kwh), 4) if r.actual_sek_kwh is not None else None,
            }
        )
        if r.created_at is not None:
            if earliest_created is None or r.created_at < earliest_created:
                earliest_created = r.created_at

    return {
        "models": dict(by_model),
        "predicted_at": earliest_created.isoformat() if earliest_created else None,
    }


# ---------------------------------------------------------------------------
# Coverage rate: prediction interval calibration
# ---------------------------------------------------------------------------


def get_coverage_rate(
    db: Session,
    area: str = "SE3",
    days: int = 30,
) -> dict:
    """
    Compute prediction interval coverage rate for the LGBM model.

    Coverage = % of actual prices falling within [predicted_low, predicted_high].
    For a well-calibrated 80% prediction interval (p10-p90), coverage should be ~80%.

    Only includes rows where predicted_low, predicted_high, and actual are all non-NULL.
    The same_weekday_avg model has no quantile bounds so it is excluded.

    Returns: {coverage_pct, n_samples, expected_pct, calibration_error}
    """
    cutoff = date.today() - timedelta(days=days)

    rows = (
        db.query(ForecastAccuracy)
        .filter(
            ForecastAccuracy.area == area,
            ForecastAccuracy.model_name == "lgbm",
            ForecastAccuracy.target_date >= cutoff,
            ForecastAccuracy.actual_sek_kwh.isnot(None),
            ForecastAccuracy.predicted_low_sek_kwh.isnot(None),
            ForecastAccuracy.predicted_high_sek_kwh.isnot(None),
        )
        .all()
    )

    n = len(rows)
    if n == 0:
        return {
            "coverage_pct": None,
            "n_samples": 0,
            "expected_pct": 80.0,
            "calibration_error": None,
        }

    covered = sum(
        1 for r in rows if float(r.predicted_low_sek_kwh) <= float(r.actual_sek_kwh) <= float(r.predicted_high_sek_kwh)
    )
    coverage_pct = round(covered / n * 100, 1)

    return {
        "coverage_pct": coverage_pct,
        "n_samples": n,
        "expected_pct": 80.0,
        "calibration_error": round(coverage_pct - 80.0, 1),
    }


# ---------------------------------------------------------------------------
# Model degradation detection
# ---------------------------------------------------------------------------


def check_model_degradation(
    db: Session,
    area: str = "SE3",
    threshold: float = 1.5,
) -> dict | None:
    """
    Compare 7-day rolling MAE vs 30-day MAE for the LGBM model.

    Returns an alert dict if 7d MAE > threshold × 30d MAE,
    or None if insufficient data (< 48 samples in 7-day window = 2 full days).

    Used by the daily pipeline to trigger Telegram degradation alerts.
    """
    acc_30d = get_accuracy(db, area=area, model_name="lgbm", days=30)
    acc_7d = get_accuracy(db, area=area, model_name="lgbm", days=7)

    lgbm_30d = acc_30d.get("lgbm")
    lgbm_7d = acc_7d.get("lgbm")

    if not lgbm_30d or not lgbm_7d:
        return None

    # Require at least 2 days of data in 7-day window
    if lgbm_7d["n_samples"] < 48:
        return None

    mae_7d = lgbm_7d["mae_sek_kwh"]
    mae_30d = lgbm_30d["mae_sek_kwh"]

    if mae_30d == 0:
        return None

    ratio = round(mae_7d / mae_30d, 2)
    degraded = ratio > threshold

    return {
        "mae_7d": mae_7d,
        "mae_30d": mae_30d,
        "ratio": ratio,
        "threshold": threshold,
        "degraded": degraded,
    }
