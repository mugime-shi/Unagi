"""
Run a multi-day backtest comparing LightGBM vs same_weekday_avg baseline.

Usage:
    python -m scripts.run_backtest              # last 30 days
    python -m scripts.run_backtest --days 60    # last 60 days
    python -m scripts.run_backtest --area SE3

For each past date that has actual spot prices:
1. Generate predictions from both models (as if forecasting that day)
2. Record predictions in forecast_accuracy table
3. Fill actuals from spot_prices
4. Print aggregate MAE/RMSE comparison
"""

import argparse
import logging
import sys
from datetime import date, timedelta

from app.db.database import SessionLocal
from app.services.backtest_service import fill_actuals, get_accuracy, record_predictions
from app.services.price_service import build_forecast, get_prices_for_date, get_prices_for_date_range

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def run_backtest(days: int = 30, area: str = "SE3") -> dict:
    db = SessionLocal()
    try:
        today = date.today()
        # Start from 2 days ago (yesterday's actuals may not be fully settled)
        end_date = today - timedelta(days=2)
        start_date = end_date - timedelta(days=days - 1)

        log.info("Backtest: %s → %s (%d days), area=%s", start_date, end_date, days, area)

        dates_processed = 0
        dates_skipped = 0

        for i in range(days):
            target = start_date + timedelta(days=i)

            # Check if actual data exists for this date
            actuals = get_prices_for_date(db, target, area)
            if not actuals:
                dates_skipped += 1
                continue

            # --- LightGBM ---
            try:
                from app.services.ml_forecast_service import build_lgbm_forecast
                lgbm_result = build_lgbm_forecast(db, target, area=area)
                if lgbm_result and lgbm_result.get("slots"):
                    has_predictions = any(
                        s.get("avg_sek_kwh") is not None for s in lgbm_result["slots"]
                    )
                    if has_predictions:
                        record_predictions(db, target, area, "lgbm", lgbm_result["slots"])
            except Exception as e:
                db.rollback()
                log.warning("LightGBM failed for %s: %s", target, e)

            # --- Baseline (same_weekday_avg) ---
            try:
                hist_start = target - timedelta(weeks=8)
                hist_end = target - timedelta(days=1)
                hist_rows = get_prices_for_date_range(db, hist_start, hist_end, area=area)
                baseline_result = build_forecast(hist_rows, target)
                if baseline_result and baseline_result.get("slots"):
                    has_predictions = any(
                        s.get("avg_sek_kwh") is not None for s in baseline_result["slots"]
                    )
                    if has_predictions:
                        record_predictions(
                            db, target, area, "same_weekday_avg", baseline_result["slots"]
                        )
            except Exception as e:
                db.rollback()
                log.warning("Baseline failed for %s: %s", target, e)

            # Fill actuals
            try:
                fill_actuals(db, target, area)
            except Exception as e:
                db.rollback()
                log.warning("fill_actuals failed for %s: %s", target, e)
            dates_processed += 1

            if dates_processed % 10 == 0:
                log.info("  ... processed %d/%d dates", dates_processed, days)

        log.info(
            "Backtest complete: %d dates processed, %d skipped (no data)",
            dates_processed, dates_skipped,
        )

        # Aggregate accuracy
        accuracy = get_accuracy(db, area, days=days + 10)  # wider window to catch all
        return accuracy

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Run backtest comparison")
    parser.add_argument("--days", type=int, default=30, help="Number of days to backtest")
    parser.add_argument("--area", default="SE3", help="Price area")
    args = parser.parse_args()

    results = run_backtest(args.days, args.area)

    if not results:
        print("\nNo scored results. Check that actual price data exists.")
        return 1

    # Pretty print comparison
    print("\n" + "=" * 65)
    print(f"  BACKTEST RESULTS — {args.days} days, area={args.area}")
    print("=" * 65)
    print(f"  {'Model':<20} {'MAE':>10} {'RMSE':>10} {'Samples':>10} {'Days':>8}")
    print("-" * 65)

    for model_name in sorted(results.keys()):
        m = results[model_name]
        print(
            f"  {model_name:<20} {m['mae_sek_kwh']:>10.4f} {m['rmse_sek_kwh']:>10.4f}"
            f" {m['n_samples']:>10} {m['n_days']:>8}"
        )

    print("-" * 65)

    # Highlight winner
    models = list(results.keys())
    if len(models) >= 2:
        best = min(models, key=lambda m: results[m]["mae_sek_kwh"])
        worst = max(models, key=lambda m: results[m]["mae_sek_kwh"])
        improvement = (
            (results[worst]["mae_sek_kwh"] - results[best]["mae_sek_kwh"])
            / results[worst]["mae_sek_kwh"]
            * 100
        )
        print(f"  Winner: {best} (MAE {improvement:.1f}% lower)")

    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
