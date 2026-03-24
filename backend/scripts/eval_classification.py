"""
Evaluate Cheap/Normal/Expensive classification accuracy per forecast horizon.

Reads from forecast_accuracy table (populated by run_backtest_horizon.py).
Classifies each day's average price relative to a 30-day rolling average:
  - Cheap:     daily_avg < rolling_avg * (1 - threshold)
  - Expensive: daily_avg > rolling_avg * (1 + threshold)
  - Normal:    in between

Usage:
    python -m scripts.eval_classification                    # default threshold 0.15
    python -m scripts.eval_classification --threshold 0.20   # stricter bands
"""

import argparse
import sys
from collections import defaultdict

from sqlalchemy import text

from app.db.database import SessionLocal

LABELS = ["Cheap", "Normal", "Expensive"]


def _classify(value: float, reference: float, threshold: float) -> str:
    if value < reference * (1 - threshold):
        return "Cheap"
    elif value > reference * (1 + threshold):
        return "Expensive"
    return "Normal"


def evaluate(area: str = "SE3", threshold: float = 0.15, days: int = 90):
    db = SessionLocal()
    try:
        # Fetch all horizon model predictions with actuals (daily averages)
        rows = db.execute(
            text("""
                SELECT
                    model_name,
                    target_date,
                    AVG(predicted_sek_kwh) AS predicted_avg,
                    AVG(actual_sek_kwh) AS actual_avg
                FROM forecast_accuracy
                WHERE area = :area
                  AND actual_sek_kwh IS NOT NULL
                  AND model_name LIKE 'lgbm_h%'
                  AND target_date >= CURRENT_DATE - :days
                GROUP BY model_name, target_date
                ORDER BY model_name, target_date
            """),
            {"area": area, "days": days},
        ).fetchall()

        if not rows:
            print("No data found. Run backtest-horizon first.")
            return 1

        # Also fetch actual daily averages for rolling reference (wider window)
        actuals = db.execute(
            text("""
                SELECT
                    target_date,
                    AVG(actual_sek_kwh) AS actual_avg
                FROM forecast_accuracy
                WHERE area = :area
                  AND actual_sek_kwh IS NOT NULL
                  AND model_name = 'lgbm_h1'
                  AND target_date >= CURRENT_DATE - :days - 30
                GROUP BY target_date
                ORDER BY target_date
            """),
            {"area": area, "days": days},
        ).fetchall()

        # Build actual daily averages for rolling reference
        daily_actuals = {r[0]: float(r[1]) for r in actuals}
        sorted_dates = sorted(daily_actuals.keys())

        # Compute 30-day rolling average for each date
        rolling_ref = {}
        for i, d in enumerate(sorted_dates):
            window = [
                daily_actuals[sorted_dates[j]]
                for j in range(max(0, i - 30), i)
                if sorted_dates[j] in daily_actuals
            ]
            if window:
                rolling_ref[d] = sum(window) / len(window)

        # Group predictions by model
        by_model = defaultdict(list)
        for r in rows:
            model_name, target_date, pred_avg, actual_avg = r
            by_model[model_name].append((target_date, float(pred_avg), float(actual_avg)))

        # Evaluate classification per model
        print()
        print("=" * 80)
        print(f"  CLASSIFICATION ACCURACY — area={area}, threshold=±{threshold:.0%}")
        print("  Reference: 30-day rolling average of actual daily prices")
        print("=" * 80)

        model_order = sorted(by_model.keys(), key=lambda m: int(m.split("_h")[1]))

        for model_name in model_order:
            entries = by_model[model_name]
            horizon = model_name.split("_h")[1]

            correct = 0
            total = 0
            # Confusion: (actual_class, predicted_class) -> count
            confusion = defaultdict(int)
            # Worst case: predicted Cheap but actual Expensive (or vice versa)
            worst_misclass = 0

            for target_date, pred_avg, actual_avg in entries:
                ref = rolling_ref.get(target_date)
                if ref is None:
                    continue

                pred_class = _classify(pred_avg, ref, threshold)
                actual_class = _classify(actual_avg, ref, threshold)
                confusion[(actual_class, pred_class)] += 1
                total += 1

                if pred_class == actual_class:
                    correct += 1

                # Worst misclassification: opposite direction
                if (pred_class == "Cheap" and actual_class == "Expensive") or (
                    pred_class == "Expensive" and actual_class == "Cheap"
                ):
                    worst_misclass += 1

            if total == 0:
                continue

            accuracy = correct / total * 100
            worst_pct = worst_misclass / total * 100

            print(f"\n  d+{horizon} — {total} days, accuracy: {accuracy:.1f}%, worst misclass: {worst_pct:.1f}%")
            print(f"  {'':>20} {'Pred Cheap':>12} {'Pred Normal':>12} {'Pred Exp':>12}")
            print(f"  {'':>20} {'-' * 12} {'-' * 12} {'-' * 12}")
            for actual_label in LABELS:
                row_vals = []
                for pred_label in LABELS:
                    count = confusion.get((actual_label, pred_label), 0)
                    row_vals.append(f"{count:>12}")
                print(f"  {'Actual ' + actual_label:>20} {''.join(row_vals)}")

        # Summary table
        print("\n" + "-" * 80)
        print(f"  {'Horizon':<10} {'Accuracy':>10} {'Worst Miss':>12} {'Days':>8}")
        print("-" * 80)

        for model_name in model_order:
            entries = by_model[model_name]
            horizon = model_name.split("_h")[1]

            correct = total = worst = 0
            for target_date, pred_avg, actual_avg in entries:
                ref = rolling_ref.get(target_date)
                if ref is None:
                    continue
                pred_class = _classify(pred_avg, ref, threshold)
                actual_class = _classify(actual_avg, ref, threshold)
                total += 1
                if pred_class == actual_class:
                    correct += 1
                if (pred_class == "Cheap" and actual_class == "Expensive") or (
                    pred_class == "Expensive" and actual_class == "Cheap"
                ):
                    worst += 1

            if total > 0:
                print(f"  d+{horizon:<9} {correct / total * 100:>9.1f}% {worst:>11} {total:>8}")

        print("=" * 80)
        return 0

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Evaluate classification accuracy")
    parser.add_argument("--area", default="SE3")
    parser.add_argument(
        "--threshold", type=float, default=0.15, help="Cheap/Expensive band width (default: 0.15 = +/-15%%)",
    )
    parser.add_argument("--days", type=int, default=90, help="Lookback period")
    args = parser.parse_args()
    return evaluate(args.area, args.threshold, args.days)


if __name__ == "__main__":
    sys.exit(main())
