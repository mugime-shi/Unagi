"""
Ablation study: gas price features ON vs OFF.

Trains two LightGBM models on the same data — one with all 59 features,
one with the 3 gas features removed (56 features) — and compares MAE
on a shared test set.

Does NOT modify feature_service.py or ml_forecast_service.py.

Usage:
    python -m scripts.ablation_gas                # default 30 test days
    python -m scripts.ablation_gas --days 60      # 60 test days
    python -m scripts.ablation_gas --area SE3
"""

import argparse
import logging
import sys
from datetime import date, timedelta
from math import sqrt

import numpy as np

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# Gas features to ablate
GAS_FEATURES = ["gas_price_eur_mwh", "gas_price_7d_avg", "gas_price_change"]

# Optuna-tuned params (same as ml_forecast_service.py)
BASE_PARAMS = {
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
    "objective": "huber",
    "huber_delta": 0.5,
    "metric": "mae",
}

TRAIN_DAYS = 365
EARLY_STOP = 20


def _train_and_predict(X_train, y_train, X_val, y_val, X_test, feature_names):
    """Train a LightGBM model and return predictions on X_test."""
    import lightgbm as lgb

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
    callbacks = [lgb.log_evaluation(period=0)]

    if len(X_val) > 0:
        val_set = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=train_set)
        callbacks.append(lgb.early_stopping(stopping_rounds=EARLY_STOP, verbose=False))
        model = lgb.train(BASE_PARAMS, train_set, num_boost_round=500, valid_sets=[val_set], callbacks=callbacks)
    else:
        model = lgb.train(BASE_PARAMS, train_set, num_boost_round=200, callbacks=callbacks)

    return model.predict(X_test), model.best_iteration


def run_ablation(test_days: int = 30, area: str = "SE3"):
    """
    Walk-forward ablation: for each test day, train with/without gas features
    on the preceding 365 days, predict 24 hours, measure MAE.
    """
    db = SessionLocal()
    try:
        today = date.today()
        test_end = today - timedelta(days=2)
        test_start = test_end - timedelta(days=test_days - 1)

        # Feature column indices for gas removal
        gas_indices = [FEATURE_COLS.index(f) for f in GAS_FEATURES]
        no_gas_cols = [c for c in FEATURE_COLS if c not in GAS_FEATURES]
        no_gas_indices = [i for i in range(len(FEATURE_COLS)) if i not in gas_indices]

        log.info("Ablation: %s → %s (%d test days), area=%s", test_start, test_end, test_days, area)
        log.info("All features: %d, Without gas: %d (removing %s)", len(FEATURE_COLS), len(no_gas_cols), GAS_FEATURES)

        # Collect errors per variant
        errors_all = []  # (date, hour, abs_error)
        errors_no_gas = []
        days_processed = 0

        for i in range(test_days):
            target = test_start + timedelta(days=i)

            # Build feature matrix: train window + target day
            train_start = target - timedelta(days=TRAIN_DAYS)
            train_end = target - timedelta(days=1)

            train_rows = build_feature_matrix(db, train_start, train_end, area=area)
            test_rows = build_feature_matrix(db, target, target, area=area)

            if len(train_rows) < 200 or not test_rows:
                log.debug("Skipping %s: train=%d, test=%d", target, len(train_rows), len(test_rows))
                continue

            # Build arrays
            X_all = np.array([[r.get(col) for col in FEATURE_COLS] for r in train_rows], dtype=object)
            X_all = np.where(X_all is None, np.nan, X_all).astype(np.float64)
            y_all = np.array([r[TARGET_COL] for r in train_rows], dtype=np.float64)

            X_test = np.array([[r.get(col) for col in FEATURE_COLS] for r in test_rows], dtype=object)
            X_test = np.where(X_test is None, np.nan, X_test).astype(np.float64)
            y_test = np.array([r[TARGET_COL] for r in test_rows], dtype=np.float64)

            # Train/val split (last 7 days for validation)
            split = max(len(train_rows) - 7 * 24, len(train_rows) // 2)
            X_tr, y_tr = X_all[:split], y_all[:split]
            X_va, y_va = X_all[split:], y_all[split:]

            # --- Variant A: ALL features (59) ---
            preds_a, rounds_a = _train_and_predict(X_tr, y_tr, X_va, y_va, X_test, FEATURE_COLS)

            for j, (pred, actual) in enumerate(zip(preds_a, y_test)):
                errors_all.append((target, j, abs(pred - actual)))

            # --- Variant B: WITHOUT gas features (56) ---
            X_tr_ng = X_tr[:, no_gas_indices]
            X_va_ng = X_va[:, no_gas_indices]
            X_test_ng = X_test[:, no_gas_indices]

            preds_b, rounds_b = _train_and_predict(X_tr_ng, y_tr, X_va_ng, y_va, X_test_ng, no_gas_cols)

            for j, (pred, actual) in enumerate(zip(preds_b, y_test)):
                errors_no_gas.append((target, j, abs(pred - actual)))

            days_processed += 1
            if days_processed % 5 == 0:
                log.info("  ... processed %d/%d test days", days_processed, test_days)

        if not errors_all:
            log.error("No test data available")
            return None

        # Compute results
        def _stats(errors):
            vals = [e[2] for e in errors]
            mae = sum(vals) / len(vals)
            rmse = sqrt(sum(v**2 for v in vals) / len(vals))
            return {"mae": round(mae, 4), "rmse": round(rmse, 4), "n": len(vals)}

        def _night_stats(errors):
            """Hours 0-6 only — gas-fired plants set marginal cost at night."""
            vals = [e[2] for e in errors if e[1] <= 6]
            if not vals:
                return None
            mae = sum(vals) / len(vals)
            return {"mae": round(mae, 4), "n": len(vals)}

        def _volatile_stats(errors):
            """Days where daily MAE > median daily MAE."""
            from collections import defaultdict

            by_day = defaultdict(list)
            for d, h, err in errors:
                by_day[d].append(err)
            daily_maes = {d: sum(errs) / len(errs) for d, errs in by_day.items()}
            median_mae = sorted(daily_maes.values())[len(daily_maes) // 2]
            volatile_errors = [e[2] for e in errors if daily_maes[e[0]] > median_mae]
            if not volatile_errors:
                return None
            mae = sum(volatile_errors) / len(volatile_errors)
            return {"mae": round(mae, 4), "n": len(volatile_errors), "threshold": round(median_mae, 4)}

        results = {
            "all_features": {
                "overall": _stats(errors_all),
                "night_h00_h06": _night_stats(errors_all),
                "volatile_days": _volatile_stats(errors_all),
            },
            "no_gas": {
                "overall": _stats(errors_no_gas),
                "night_h00_h06": _night_stats(errors_no_gas),
                "volatile_days": _volatile_stats(errors_no_gas),
            },
        }
        return results

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Ablation study: gas price features")
    parser.add_argument("--days", type=int, default=30, help="Number of test days")
    parser.add_argument("--area", default="SE3", help="Price area")
    args = parser.parse_args()

    results = run_ablation(args.days, args.area)
    if not results:
        print("\nNo results. Check that sufficient historical data exists.")
        return 1

    a = results["all_features"]
    b = results["no_gas"]

    print("\n" + "=" * 70)
    print(f"  ABLATION STUDY: GAS FEATURES — {args.days} test days, area={args.area}")
    print("=" * 70)

    print(f"\n  {'Metric':<25} {'All (59 feat)':>15} {'No gas (56)':>15} {'Δ MAE':>10}")
    print("  " + "-" * 65)

    # Overall
    delta = round(a["overall"]["mae"] - b["overall"]["mae"], 4)
    pct = round(delta / b["overall"]["mae"] * 100, 1) if b["overall"]["mae"] else 0
    sign = "+" if delta > 0 else ""
    print(
        f"  {'Overall MAE':<25} {a['overall']['mae']:>15.4f} {b['overall']['mae']:>15.4f} {sign}{delta:>9.4f} ({sign}{pct}%)"
    )

    # Night
    if a["night_h00_h06"] and b["night_h00_h06"]:
        delta_n = round(a["night_h00_h06"]["mae"] - b["night_h00_h06"]["mae"], 4)
        pct_n = round(delta_n / b["night_h00_h06"]["mae"] * 100, 1) if b["night_h00_h06"]["mae"] else 0
        sign_n = "+" if delta_n > 0 else ""
        print(
            f"  {'Night (H00-H06) MAE':<25} {a['night_h00_h06']['mae']:>15.4f} {b['night_h00_h06']['mae']:>15.4f} {sign_n}{delta_n:>9.4f} ({sign_n}{pct_n}%)"
        )

    # Volatile
    if a["volatile_days"] and b["volatile_days"]:
        delta_v = round(a["volatile_days"]["mae"] - b["volatile_days"]["mae"], 4)
        pct_v = round(delta_v / b["volatile_days"]["mae"] * 100, 1) if b["volatile_days"]["mae"] else 0
        sign_v = "+" if delta_v > 0 else ""
        print(
            f"  {'Volatile days MAE':<25} {a['volatile_days']['mae']:>15.4f} {b['volatile_days']['mae']:>15.4f} {sign_v}{delta_v:>9.4f} ({sign_v}{pct_v}%)"
        )

    print("  " + "-" * 65)
    print(f"  Samples: {a['overall']['n']}")

    # Verdict
    if a["overall"]["mae"] < b["overall"]["mae"]:
        imp = round((1 - a["overall"]["mae"] / b["overall"]["mae"]) * 100, 1)
        print(f"\n  ✅ Gas features IMPROVE accuracy by {imp}%")
    elif a["overall"]["mae"] > b["overall"]["mae"]:
        deg = round((a["overall"]["mae"] / b["overall"]["mae"] - 1) * 100, 1)
        print(f"\n  ⚠️  Gas features HURT accuracy by {deg}% — consider removing")
    else:
        print("\n  ➡️  No measurable difference")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
