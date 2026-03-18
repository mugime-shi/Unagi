"""
Hyperparameter tuning for LightGBM using Optuna + walk-forward CV.

Usage:
    python -m scripts.tune_hyperparams              # 100 trials
    python -m scripts.tune_hyperparams --trials 200  # more trials
    python -m scripts.tune_hyperparams --area SE3

Runs locally (not on Lambda). Prints the best parameters to paste into
ml_forecast_service.py.
"""

import argparse
import logging
import sys
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import optuna

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# Suppress Optuna INFO logs (too verbose)
optuna.logging.set_verbosity(optuna.logging.WARNING)


def _load_full_matrix(area: str, days: int = 365):
    """Load feature matrix for the training window."""
    db = SessionLocal()
    try:
        end_date = date.today() - timedelta(days=2)
        start_date = end_date - timedelta(days=days - 1)
        rows = build_feature_matrix(db, start_date, end_date, area=area)
        log.info("Loaded %d rows (%s to %s)", len(rows), start_date, end_date)
        return rows
    finally:
        db.close()


def _rows_to_arrays(rows):
    """Convert list of dicts to numpy arrays."""
    X = np.array([
        [r.get(col) for col in FEATURE_COLS]
        for r in rows
    ], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)
    return X, y


def _walk_forward_cv(rows, params, n_folds=4, val_days=30):
    """
    Walk-forward cross-validation.

    Splits data into n_folds expanding windows:
      Fold 1: train on first chunk, validate on next val_days
      Fold 2: train on first 2 chunks, validate on next val_days
      ...

    Returns average MAE across folds.
    """
    total_rows = len(rows)
    val_size = val_days * 24
    # Reserve space for n_folds validation windows at the end
    available = total_rows - val_size
    fold_step = available // n_folds

    if fold_step < 200:
        # Not enough data for proper walk-forward
        return float("inf")

    maes = []
    for fold in range(n_folds):
        train_end = fold_step * (fold + 1)
        val_start = train_end
        val_end = min(val_start + val_size, total_rows)

        if val_end <= val_start:
            continue

        train_rows = rows[:train_end]
        val_rows = rows[val_start:val_end]

        X_train, y_train = _rows_to_arrays(train_rows)
        X_val, y_val = _rows_to_arrays(val_rows)

        train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
        val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)

        model = lgb.train(
            params,
            train_set,
            num_boost_round=1000,
            valid_sets=[val_set],
            callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )

        preds = model.predict(X_val)
        mae = float(np.mean(np.abs(y_val - preds)))
        maes.append(mae)

    return sum(maes) / len(maes) if maes else float("inf")


def objective(trial, rows):
    """Optuna objective: minimize walk-forward CV MAE."""
    params = {
        "objective": "regression",
        "metric": "mae",
        "verbosity": -1,
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 12),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 5.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 5.0, log=True),
    }

    return _walk_forward_cv(rows, params, n_folds=4, val_days=30)


def main():
    parser = argparse.ArgumentParser(description="Tune LightGBM hyperparameters")
    parser.add_argument("--trials", type=int, default=100, help="Number of Optuna trials")
    parser.add_argument("--area", default="SE3", help="Price area")
    parser.add_argument("--days", type=int, default=365, help="Training window days")
    args = parser.parse_args()

    log.info("Loading feature matrix...")
    rows = _load_full_matrix(args.area, args.days)
    if len(rows) < 500:
        log.error("Insufficient data: %d rows", len(rows))
        return 1

    log.info("Starting Optuna study (%d trials, %d rows)...", args.trials, len(rows))
    study = optuna.create_study(direction="minimize")
    study.optimize(lambda trial: objective(trial, rows), n_trials=args.trials)

    best = study.best_trial
    print("\n" + "=" * 65)
    print(f"  BEST RESULT — MAE: {best.value:.4f} (trial #{best.number})")
    print("=" * 65)
    print("\n  Best hyperparameters (paste into ml_forecast_service.py):\n")
    print("    params = {")
    print('        "objective": "regression",')
    print('        "metric": "mae",')
    print('        "verbose": -1,')
    for key, value in best.params.items():
        if isinstance(value, float):
            print(f'        "{key}": {value:.6f},')
        else:
            print(f'        "{key}": {value},')
    print("    }")
    print("=" * 65)

    return 0


if __name__ == "__main__":
    sys.exit(main())
