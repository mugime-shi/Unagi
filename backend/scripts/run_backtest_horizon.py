"""
Run a multi-horizon backtest comparing d+1, d+2, d+3 forecast accuracy.

Usage:
    python -m scripts.run_backtest_horizon                      # last 80 days, d+1..d+3
    python -m scripts.run_backtest_horizon --days 10 --horizon 2  # quick check
    python -m scripts.run_backtest_horizon --area SE3 --train-days 270

For each past date D that has actual spot prices:
1. Train LightGBM model on data through D (reused across horizons)
2. Predict D+1 (standard d+1 forecast)
3. Inject D+1 predictions as pseudo-actuals, predict D+2 (recursive)
4. Inject D+1+D+2 predictions, predict D+3 (recursive)
5. Fill actuals and compute MAE/RMSE per horizon

Uses recursive forecasting: each horizon's predictions become lag
features for the next horizon. Same model, different feature inputs.
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.services.backtest_service import fill_actuals, record_predictions
from app.services.feature_service import FEATURE_COLS, build_feature_matrix
from app.services.ml_forecast_service import _train_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def _predict_with_model(models, db, target_date, area, price_overrides=None):
    """Generate 24-hour predictions using a pre-trained model dict.

    Returns list of {"hour": int, "avg_sek_kwh": float} or None on failure.
    """
    rows = build_feature_matrix(
        db,
        target_date,
        target_date,
        area=area,
        include_target=False,
        price_overrides=price_overrides,
    )
    if not rows:
        return None

    X = np.array([[r.get(col) for col in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711

    point_model = models["point"]
    low_model = models.get("low")
    high_model = models.get("high")
    q_hat = models.get("q_hat", 0.0)

    preds = point_model.predict(X)

    if low_model is not None and high_model is not None:
        low_preds = low_model.predict(X) - q_hat
        high_preds = high_model.predict(X) + q_hat
    else:
        low_preds = preds - 0.10
        high_preds = preds + 0.10

    return [
        {
            "hour": i,
            "avg_sek_kwh": round(float(preds[i]), 4),
            "low_sek_kwh": round(max(0.0, float(low_preds[i])), 4),
            "high_sek_kwh": round(float(high_preds[i]), 4),
        }
        for i in range(len(preds))
    ]


def _slots_to_overrides(slots, target_date):
    """Convert prediction slots to price_overrides dict for the next horizon."""
    overrides = {}
    for s in slots:
        if s.get("avg_sek_kwh") is not None:
            overrides[(target_date, s["hour"])] = s["avg_sek_kwh"]
    return overrides


def _compute_accuracy(db: Session, area: str, model_name: str, days: int):
    """Compute MAE/RMSE for a model over the given period."""
    from sqlalchemy import text

    result = db.execute(
        text("""
            SELECT
                COUNT(*) AS n,
                COUNT(DISTINCT target_date) AS n_days,
                AVG(ABS(predicted_sek_kwh - actual_sek_kwh)) AS mae,
                SQRT(AVG(POWER(predicted_sek_kwh - actual_sek_kwh, 2))) AS rmse
            FROM forecast_accuracy
            WHERE area = :area
              AND model_name = :model
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= CURRENT_DATE - :days
        """),
        {"area": area, "model": model_name, "days": days + 10},
    ).fetchone()

    if result and result[0] > 0:
        return {
            "n_samples": result[0],
            "n_days": result[1],
            "mae_sek_kwh": float(result[2]),
            "rmse_sek_kwh": float(result[3]),
        }
    return None


def run_backtest_horizon(
    days: int = 80,
    max_horizon: int = 3,
    area: str = "SE3",
    train_days: int = 270,
) -> dict:
    """Run walk-forward backtest for d+1 through d+max_horizon.

    Returns dict of {horizon_label: {mae, rmse, n_samples, n_days}}.
    """
    original_train_days = os.environ.get("LGBM_TRAIN_DAYS")
    os.environ["LGBM_TRAIN_DAYS"] = str(train_days)

    # Reload the module-level constant
    import app.services.ml_forecast_service as ml_svc
    ml_svc._TRAIN_DAYS = train_days

    db = SessionLocal()
    try:
        today = date.today()
        end_date = today - timedelta(days=2)
        start_date = end_date - timedelta(days=days - 1)

        log.info(
            "Horizon backtest: %s -> %s (%d days), area=%s, max_horizon=d+%d, train_days=%d",
            start_date, end_date, days, area, max_horizon, train_days,
        )

        # Model names for each horizon
        model_names = {h: f"lgbm_h{h}" for h in range(1, max_horizon + 1)}

        dates_processed = 0
        dates_skipped = 0

        for i in range(days):
            # D = the "perspective day" — we have actuals through D
            perspective_day = start_date + timedelta(days=i)

            # Check that ALL target dates (D+1 .. D+max_horizon) have actuals
            target_dates = [perspective_day + timedelta(days=h) for h in range(1, max_horizon + 1)]
            all_have_actuals = True
            for td in target_dates:
                if td > end_date:
                    all_have_actuals = False
                    break

            if not all_have_actuals:
                dates_skipped += 1
                continue

            # Train model once for this perspective day
            # Model is trained on data through perspective_day (target = perspective_day + 1)
            train_target = perspective_day + timedelta(days=1)
            models = _train_model(db, train_target, area)
            if models is None:
                log.warning("Training failed for perspective %s, skipping", perspective_day)
                dates_skipped += 1
                continue

            # Recursive prediction: d+1, d+2, ..., d+max_horizon
            cumulative_overrides = {}

            for horizon in range(1, max_horizon + 1):
                target = perspective_day + timedelta(days=horizon)
                model_name = model_names[horizon]

                slots = _predict_with_model(
                    models, db, target, area,
                    price_overrides=cumulative_overrides if horizon > 1 else None,
                )

                if slots and any(s.get("avg_sek_kwh") is not None for s in slots):
                    record_predictions(db, target, area, model_name, slots)
                    # Accumulate predictions for next horizon's lag features
                    cumulative_overrides.update(_slots_to_overrides(slots, target))
                else:
                    log.warning("Prediction failed: perspective=%s horizon=d+%d", perspective_day, horizon)

                # Fill actuals for this target date
                try:
                    fill_actuals(db, target, area)
                except Exception as e:
                    db.rollback()
                    log.warning("fill_actuals failed for %s: %s", target, e)

            dates_processed += 1
            if dates_processed % 10 == 0:
                log.info("  ... processed %d/%d perspective days", dates_processed, days)

        log.info(
            "Horizon backtest complete: %d perspective days processed, %d skipped",
            dates_processed, dates_skipped,
        )

        # Compute accuracy for each horizon
        results = {}
        for horizon in range(1, max_horizon + 1):
            model_name = model_names[horizon]
            acc = _compute_accuracy(db, area, model_name, days + 10)
            if acc:
                results[f"d+{horizon}"] = acc

        return results

    finally:
        # Restore original TRAIN_DAYS
        if original_train_days is not None:
            os.environ["LGBM_TRAIN_DAYS"] = original_train_days
        elif "LGBM_TRAIN_DAYS" in os.environ:
            del os.environ["LGBM_TRAIN_DAYS"]
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Run multi-horizon backtest")
    parser.add_argument("--days", type=int, default=80, help="Number of perspective days")
    parser.add_argument("--horizon", type=int, default=3, help="Max forecast horizon (1-7)")
    parser.add_argument("--area", default="SE3", help="Price area")
    parser.add_argument("--train-days", type=int, default=270, help="Training window (days)")
    args = parser.parse_args()

    results = run_backtest_horizon(args.days, args.horizon, args.area, args.train_days)

    if not results:
        print("\nNo scored results. Check that actual price data exists.")
        return 1

    # Pretty print
    print()
    print("=" * 72)
    print(f"  HORIZON BACKTEST — {args.days} days, area={args.area}, TRAIN_DAYS={args.train_days}")
    print("=" * 72)
    print(f"  {'Horizon':<10} {'MAE':>10} {'RMSE':>10} {'Samples':>10} {'Days':>8} {'vs d+1':>10}")
    print("-" * 72)

    baseline_mae = results.get("d+1", {}).get("mae_sek_kwh")

    for label in sorted(results.keys()):
        m = results[label]
        mae = m["mae_sek_kwh"]
        vs_d1 = ""
        if baseline_mae and label != "d+1":
            pct = ((mae - baseline_mae) / baseline_mae) * 100
            vs_d1 = f"+{pct:.1f}%"

        print(
            f"  {label:<10} {mae:>10.4f} {m['rmse_sek_kwh']:>10.4f}"
            f" {m['n_samples']:>10} {m['n_days']:>8} {vs_d1:>10}"
        )

    print("-" * 72)

    # Go/No-Go verdict
    go_threshold = 0.36
    if "d+2" in results:
        d2_mae = results["d+2"]["mae_sek_kwh"]
        if d2_mae <= go_threshold:
            verdict = f"GO (MAE {d2_mae:.4f} <= {go_threshold})"
        elif d2_mae <= 0.50:
            verdict = f"REVIEW (MAE {d2_mae:.4f} — check classification accuracy)"
        else:
            verdict = f"NO-GO (MAE {d2_mae:.4f} > 0.50)"
        print(f"  d+2 verdict: {verdict}")

    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
