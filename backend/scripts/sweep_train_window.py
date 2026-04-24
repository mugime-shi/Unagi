"""
Sweep training window sizes to find the optimal LGBM_TRAIN_DAYS.

For each window size, runs a walk-forward backtest:
  - For each test date, train LGBM with that window and predict next day
  - Compare predictions against actuals
  - Report MAE per window size, per market regime (calm vs volatile)
  - Save hourly predictions to CSV (DB is never modified)

Usage:
    python -m scripts.sweep_train_window                     # 30 test days
    python -m scripts.sweep_train_window --test-days 60      # 60 test days
    python -m scripts.sweep_train_window --windows 60,90,180 # custom windows

Output:
    sweep_results_YYYYMMDD_HHMMSS.csv  — hourly predictions per window
"""

import argparse
import csv
import logging
import sys
from datetime import date, datetime, timedelta

import numpy as np

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix
from app.services.price_service import get_prices_for_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_WINDOWS = [30, 45, 60, 90, 120, 180, 270, 365]


def _train_and_predict(db, target_date, area, train_days):
    """Train LGBM with given window size and predict target_date. Returns 24 predictions or None."""
    import lightgbm as lgb

    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=train_days - 1)

    rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(rows) < 200:
        return None

    X = np.array([[r.get(col) for col in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X is None, np.nan, X).astype(np.float64)
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)

    # Use last 7 days as validation for early stopping
    split_idx = max(len(rows) - 7 * 24, len(rows) // 2)
    X_train, y_train = X[:split_idx], y[:split_idx]
    X_val, y_val = X[split_idx:], y[split_idx:]

    # Same Optuna-tuned params as production (100 trials, 2026-03-18)
    params = {
        "objective": "huber",
        "huber_delta": 1.0,  # Match production (tuned 2026-03-20, commit 4960ceb)
        "metric": "mae",
        "verbose": -1,
        "num_leaves": 117,
        "learning_rate": 0.015798,
        "max_depth": 11,
        "min_child_samples": 32,
        "feature_fraction": 0.541483,
        "bagging_fraction": 0.872229,
        "bagging_freq": 1,
        "lambda_l1": 4.663778,
        "lambda_l2": 0.000033,
    }

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
    val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)

    model = lgb.train(
        params,
        train_set,
        num_boost_round=500,
        valid_sets=[val_set],
        callbacks=[
            lgb.early_stopping(stopping_rounds=20, verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )

    # Predict target date
    pred_rows = build_feature_matrix(db, target_date, target_date, area=area, include_target=False)
    if not pred_rows:
        return None

    X_pred = np.array([[r.get(col) for col in FEATURE_COLS] for r in pred_rows], dtype=object)
    X_pred = np.where(X_pred is None, np.nan, X_pred).astype(np.float64)

    return model.predict(X_pred)


def _get_actuals(db, target_date, area):
    """Get actual hourly prices for target_date as numpy array."""
    prices = get_prices_for_date(db, target_date, area)
    if not prices or len(prices) < 24:
        return None
    sorted_prices = sorted(prices, key=lambda p: p.timestamp_utc)[:24]
    return np.array([p.price_sek_kwh for p in sorted_prices], dtype=np.float64)


def run_sweep(test_days, windows, area):
    """Run the sweep. Returns (summary_results, hourly_rows)."""
    db = SessionLocal()
    try:
        today = date.today()
        end_date = today - timedelta(days=2)
        start_date = end_date - timedelta(days=test_days - 1)

        log.info("Window sweep: %s → %s (%d test days), area=%s", start_date, end_date, test_days, area)
        log.info("Windows to test: %s", windows)

        # summary: {window: [(date, mae, daily_range), ...]}
        summary = {w: [] for w in windows}
        # hourly: list of dicts for CSV
        hourly_rows = []

        for i in range(test_days):
            target = start_date + timedelta(days=i)
            actuals = _get_actuals(db, target, area)
            if actuals is None:
                continue

            daily_range = float(np.max(actuals) - np.min(actuals))

            for w in windows:
                try:
                    preds = _train_and_predict(db, target, area, w)
                    if preds is not None and len(preds) >= 24:
                        hourly_errors = np.abs(actuals[:24] - preds[:24])
                        mae = float(np.mean(hourly_errors))
                        summary[w].append((target, mae, daily_range))

                        # Save hourly detail
                        for h in range(24):
                            hourly_rows.append(
                                {
                                    "date": target.isoformat(),
                                    "hour": h,
                                    "window_days": w,
                                    "actual": round(float(actuals[h]), 4),
                                    "predicted": round(float(preds[h]), 4),
                                    "error": round(float(preds[h] - actuals[h]), 4),
                                    "abs_error": round(float(hourly_errors[h]), 4),
                                    "daily_range": round(daily_range, 4),
                                }
                            )
                except Exception as e:
                    log.warning("Window %d, date %s failed: %s", w, target, e)

            completed = i + 1
            if completed % 5 == 0:
                log.info("  ... %d/%d dates processed", completed, test_days)

        return summary, hourly_rows
    finally:
        db.close()


def save_csv(hourly_rows, filepath):
    """Save hourly predictions to CSV."""
    if not hourly_rows:
        return
    fieldnames = ["date", "hour", "window_days", "actual", "predicted", "error", "abs_error", "daily_range"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(hourly_rows)
    log.info("Saved %d rows to %s", len(hourly_rows), filepath)


def print_results(summary, windows):
    # --- Overall MAE ---
    print("\n" + "=" * 90)
    print("  TRAINING WINDOW SWEEP RESULTS")
    print("=" * 90)
    print(f"\n  {'Window':>8} {'MAE':>10} {'RMSE':>10} {'Days':>6}  {'vs 365d':>10}  Best?")
    print("  " + "-" * 70)

    overall = {}
    for w in windows:
        entries = summary[w]
        if not entries:
            continue
        maes = [mae for _, mae, _ in entries]
        overall[w] = {
            "mae": np.mean(maes),
            "rmse": np.sqrt(np.mean(np.array(maes) ** 2)),
            "n": len(entries),
        }

    if not overall:
        print("  No results. Check that historical data exists.")
        return

    best_w = min(overall, key=lambda w: overall[w]["mae"])
    ref_mae = overall.get(365, {}).get("mae", overall[best_w]["mae"])

    for w in windows:
        if w not in overall:
            continue
        m = overall[w]
        delta = ((m["mae"] - ref_mae) / ref_mae * 100) if ref_mae > 0 else 0
        marker = "  ★" if w == best_w else ""
        print(f"  {w:>6}d {m['mae']:>10.4f} {m['rmse']:>10.4f} {m['n']:>6}  {delta:>+9.1f}%{marker}")

    print("  " + "-" * 70)
    print(f"  Winner: {best_w}d (MAE {overall[best_w]['mae']:.4f} SEK/kWh)")

    # --- Calm vs Volatile breakdown ---
    print(f"\n  {'':>8} {'— Calm days —':>25} {'— Volatile days —':>25}")
    print(f"  {'Window':>8} {'MAE':>10} {'n':>6}   {'MAE':>10} {'n':>6}   {'Vol/Calm':>10}")
    print("  " + "-" * 70)

    for w in windows:
        entries = summary[w]
        if not entries:
            continue
        ranges = [r for _, _, r in entries]
        median_range = np.median(ranges)

        calm = [mae for _, mae, r in entries if r <= median_range]
        volatile = [mae for _, mae, r in entries if r > median_range]

        calm_mae = np.mean(calm) if calm else 0
        vol_mae = np.mean(volatile) if volatile else 0
        ratio = vol_mae / calm_mae if calm_mae > 0 else 0

        best_calm = (
            " ★"
            if w
            == min(
                [ww for ww in windows if summary[ww]],
                key=lambda ww: (
                    np.mean([m for _, m, r in summary[ww] if r <= median_range])
                    if any(r <= median_range for _, _, r in summary[ww])
                    else float("inf")
                ),
            )
            else ""
        )
        best_vol = (
            " ★"
            if w
            == min(
                [ww for ww in windows if summary[ww]],
                key=lambda ww: (
                    np.mean([m for _, m, r in summary[ww] if r > median_range])
                    if any(r > median_range for _, _, r in summary[ww])
                    else float("inf")
                ),
            )
            else ""
        )

        print(
            f"  {w:>6}d {calm_mae:>10.4f} {len(calm):>6}{best_calm:2s} {vol_mae:>10.4f} {len(volatile):>6}{best_vol:2s} {ratio:>9.1f}x"
        )

    # --- Daily MAE time series (last 10 days) ---
    print("\n  Daily MAE (last 10 test days):")
    print(f"  {'Date':>12}", end="")
    for w in windows:
        if w in overall:
            print(f" {w:>6}d", end="")
    print("  Range   Winner")
    print("  " + "-" * (14 + 8 * len([w for w in windows if w in overall]) + 16))

    all_dates = set()
    for w in windows:
        for d, _, _ in summary[w]:
            all_dates.add(d)

    for d in sorted(all_dates)[-10:]:
        print(f"  {d.isoformat():>12}", end="")
        day_maes = {}
        day_range = 0
        for w in windows:
            if w not in overall:
                continue
            entry = next(((mae, r) for dd, mae, r in summary[w] if dd == d), None)
            if entry:
                day_maes[w] = entry[0]
                day_range = entry[1]
                print(f" {entry[0]:>6.3f}", end="")
            else:
                print(f" {'—':>6}", end="")
        if day_maes:
            best = min(day_maes, key=day_maes.get)
            print(f"  {day_range:.2f}  {best}d")
        else:
            print()

    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description="Sweep training window sizes")
    parser.add_argument("--test-days", type=int, default=30, help="Number of test days")
    parser.add_argument("--area", default="SE3", help="Price area")
    parser.add_argument(
        "--windows",
        default=",".join(str(w) for w in DEFAULT_WINDOWS),
        help="Comma-separated window sizes (default: 30,45,60,90,120,180,270,365)",
    )
    args = parser.parse_args()

    windows = sorted(int(w) for w in args.windows.split(","))

    summary, hourly_rows = run_sweep(args.test_days, windows, args.area)

    # Save to CSV (never touches DB)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"sweep_results_{timestamp}.csv"
    save_csv(hourly_rows, csv_path)

    print_results(summary, windows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
