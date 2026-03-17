"""
Backtest service: record forecast predictions, fill actuals, compute accuracy.

Workflow:
1. Forecast generated (Day N-1) → record_predictions() saves 24 hourly predictions
2. Actual prices published (Day N) → fill_actuals() fills actual_sek_kwh from spot_prices
3. score_forecast() / get_accuracy() → compute MAE/RMSE per model
"""

from collections import defaultdict
from datetime import date, timedelta, timezone
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

    slots: list of {"hour": 0-23, "avg_sek_kwh": float | None, ...}
    Returns the number of rows written.
    """
    stmt = text("""
        INSERT INTO forecast_accuracy
            (target_date, area, model_name, hour, predicted_sek_kwh)
        VALUES (:date, :area, :model, :hour, :predicted)
        ON CONFLICT (target_date, area, model_name, hour)
        DO UPDATE SET predicted_sek_kwh = EXCLUDED.predicted_sek_kwh
    """)
    count = 0
    for s in slots:
        if s.get("avg_sek_kwh") is not None:
            db.execute(stmt, {
                "date":      target_date,
                "area":      area,
                "model":     model_name,
                "hour":      s["hour"],
                "predicted": round(s["avg_sek_kwh"], 4),
            })
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
        result = db.execute(text("""
            UPDATE forecast_accuracy
            SET actual_sek_kwh = :actual
            WHERE target_date = :date
              AND area = :area
              AND hour = :hour
              AND actual_sek_kwh IS NULL
        """), {
            "date": target_date,
            "area": area,
            "hour": hour,
            "actual": avg_actual,
        })
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
    rmse = sqrt(sum(e ** 2 for e in errors) / len(errors))

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

    query = db.query(ForecastAccuracy).filter(
        ForecastAccuracy.area == area,
        ForecastAccuracy.target_date >= cutoff,
        ForecastAccuracy.actual_sek_kwh.isnot(None),
    )
    if model_name:
        query = query.filter(ForecastAccuracy.model_name == model_name)

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
        rmse = sqrt(sum(e ** 2 for e in errors) / n)
        results[model] = {
            "mae_sek_kwh": round(mae, 4),
            "rmse_sek_kwh": round(rmse, 4),
            "n_samples": n,
            "n_days": len(dates_by_model[model]),
        }

    return results
