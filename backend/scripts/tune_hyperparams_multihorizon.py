"""
Multi-horizon aware hyperparameter tuning.

Unlike the standard ``tune_hyperparams`` (single-step walk-forward CV), this
script evaluates each Optuna trial by running *recursive* predictions over
horizons d+1..d+7 and returning a weighted MAE. The goal is to find
hparams that stay robust when predictions become inputs to further
predictions — the weakness exposed by the 2026-04-22 retuning experiment.

Design:
  * 1 training per trial on [train_start, train_end]
  * For each perspective date P in (train_end, train_end + eval_days]:
    * Predict P+1 using real features (all data up to P is available)
    * For h in 2..max_horizon:
      * Rebuild features for P+h with price_overrides = accumulated
        predictions for P+1..P+h-1 (via build_feature_matrix)
      * Predict, accumulate into overrides
    * Compute MAE at each horizon vs actuals
  * Objective = weighted sum of per-horizon MAEs (weights front-loaded)

Usage:
    python -m scripts.tune_hyperparams_multihorizon --trials 30
    python -m scripts.tune_hyperparams_multihorizon \
        --trials 50 --perspectives 8 --horizon 7
"""

import argparse
import logging
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
optuna.logging.set_verbosity(optuna.logging.WARNING)

# Front-loaded weights: d+1 is most important but d+2..d+7 still matter.
# Must sum to 1.0 across the first max_horizon entries.
HORIZON_WEIGHTS_FULL = [0.28, 0.20, 0.15, 0.12, 0.10, 0.08, 0.07]


def _rows_to_xy(rows: list[dict]):
    X = np.array([[r.get(c) for c in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array([r.get(TARGET_COL) for r in rows], dtype=object)
    return X, y


def _train_point(X_train, y_train, X_val, y_val, hparams: dict):
    """Train a single Huber-loss LightGBM point model with early stopping."""
    train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
    valid_sets = []
    callbacks = [lgb.log_evaluation(period=0)]
    if len(X_val) > 0:
        val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)
        valid_sets.append(val_set)
        callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))

    params = {**hparams, "objective": "huber", "huber_delta": 1.0, "metric": "mae"}
    return lgb.train(
        params,
        train_set,
        num_boost_round=500,
        valid_sets=valid_sets if valid_sets else None,
        callbacks=callbacks,
    )


def _predict_day(db, model, target_date: date, area: str, overrides: dict) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Build features for target_date (using overrides), return (preds, actuals, hours)."""
    rows = build_feature_matrix(
        db,
        target_date,
        target_date,
        area=area,
        price_overrides=overrides if overrides else None,
    )
    if not rows:
        return np.array([]), np.array([]), []

    X, y = _rows_to_xy(rows)
    preds = model.predict(X)
    hours = [int(r["hour"]) for r in rows]
    return preds, y, hours


def _recursive_horizon_mae(
    db,
    model,
    perspective_date: date,
    area: str,
    max_horizon: int,
) -> dict[int, tuple[float, int]]:
    """Predict d+1..d+max_horizon recursively from perspective_date. Returns {h: (mae, n_samples)}."""
    overrides: dict[tuple[date, int], float] = {}
    out: dict[int, tuple[float, int]] = {}

    for h in range(1, max_horizon + 1):
        target = perspective_date + timedelta(days=h)
        preds, actuals, hours = _predict_day(db, model, target, area, overrides)
        if len(preds) == 0:
            continue

        # MAE against real actuals where available
        mask = np.array([a is not None for a in actuals])
        if mask.any():
            y_true = np.array([a for a in actuals[mask]], dtype=np.float64)
            abs_err = np.abs(preds[mask] - y_true)
            out[h] = (float(abs_err.mean()), int(mask.sum()))

        # Feed predictions forward as pseudo-actuals
        for pred, hr in zip(preds, hours):
            overrides[(target, hr)] = float(pred)

    return out


def _build_objective(db, train_start, train_end, perspective_dates, area, max_horizon):
    """Create Optuna objective closure with captured context."""

    # Load training data ONCE (shared across all trials)
    log.info("Loading training feature matrix %s..%s", train_start, train_end)
    train_rows = build_feature_matrix(db, train_start, train_end, area=area)
    log.info("Training rows: %d", len(train_rows))
    if len(train_rows) < 500:
        raise RuntimeError(f"Insufficient training data: {len(train_rows)} rows")

    X_full, y_full_obj = _rows_to_xy(train_rows)
    y_full = np.array([float(v) for v in y_full_obj], dtype=np.float64)

    # 90/10 train/val split for early stopping
    split = int(len(train_rows) * 0.9)
    X_train, y_train = X_full[:split], y_full[:split]
    X_val, y_val = X_full[split:], y_full[split:]

    weights = HORIZON_WEIGHTS_FULL[:max_horizon]
    weights_norm = [w / sum(weights) for w in weights]

    def objective(trial):
        hparams = {
            "verbose": -1,
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

        try:
            model = _train_point(X_train, y_train, X_val, y_val, hparams)
        except Exception as e:
            log.warning("trial %d: training failed: %s", trial.number, e)
            return float("inf")

        horizon_maes: dict[int, list[float]] = {h: [] for h in range(1, max_horizon + 1)}
        for p_date in perspective_dates:
            res = _recursive_horizon_mae(db, model, p_date, area, max_horizon)
            for h, (mae, _n) in res.items():
                horizon_maes[h].append(mae)

        total = 0.0
        total_w = 0.0
        for h in range(1, max_horizon + 1):
            if not horizon_maes[h]:
                continue
            avg = float(np.mean(horizon_maes[h]))
            w = weights_norm[h - 1]
            total += avg * w
            total_w += w

        if total_w <= 0:
            return float("inf")

        weighted = total / total_w
        # Attach horizon breakdown for reporting
        per_h = {
            h: float(np.mean(horizon_maes[h])) if horizon_maes[h] else None
            for h in range(1, max_horizon + 1)
        }
        trial.set_user_attr("per_horizon_mae", per_h)
        return weighted

    return objective


def _find_contiguous_eval_window(db, area: str, lookback_days: int, min_length: int):
    """Scan backward from today, find the most recent contiguous range of
    days that all have data. Returns (start, end) or (None, None) if no
    suitable range exists. The local dev DB often has gaps so we can't
    just pick `today - horizon` as the end of evaluation.
    """
    # Walk through lookback_days, collect ranges of contiguous days with data
    today = date.today()
    ranges: list[tuple[date, date]] = []
    run_start: date | None = None
    for i in range(lookback_days, 0, -1):
        d = today - timedelta(days=i)
        rows = build_feature_matrix(db, d, d, area=area)
        has = len(rows) > 0
        if has and run_start is None:
            run_start = d
        elif not has and run_start is not None:
            ranges.append((run_start, d - timedelta(days=1)))
            run_start = None
    if run_start is not None:
        ranges.append((run_start, today - timedelta(days=1)))

    # Prefer longest range (more perspectives + horizons possible)
    valid = [(s, e) for s, e in ranges if (e - s).days + 1 >= min_length]
    if not valid:
        return None, None
    valid.sort(key=lambda r: (r[1] - r[0]).days, reverse=True)
    return valid[0]


def main():
    parser = argparse.ArgumentParser(description="Multi-horizon recursive tune")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--train-days", type=int, default=300)
    parser.add_argument("--perspectives", type=int, default=5,
                        help="Number of perspective dates to sample from the eval window")
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--lookback-days", type=int, default=90,
                        help="How far back to scan for a contiguous eval window")
    args = parser.parse_args()

    if args.horizon > len(HORIZON_WEIGHTS_FULL):
        log.error("horizon %d exceeds HORIZON_WEIGHTS_FULL length %d",
                  args.horizon, len(HORIZON_WEIGHTS_FULL))
        return 1

    db = SessionLocal()
    try:
        # Need a contiguous window big enough for at least 1 perspective +
        # horizon + some slack (spread perspectives evenly).
        min_window = args.perspectives + args.horizon
        log.info("Scanning last %d days for a contiguous window >= %d days...",
                 args.lookback_days, min_window)
        eval_start, eval_end = _find_contiguous_eval_window(
            db, args.area, args.lookback_days, min_window
        )
        if eval_start is None:
            log.error("No contiguous range of %d+ days found in the last %d days. "
                      "The local DB may have gaps — check with `./unagi backfill`.",
                      min_window, args.lookback_days)
            return 1

        # Perspective dates live within the window. Each perspective P needs
        # P+1..P+horizon to stay within the contiguous range, so cap at
        # eval_end - horizon. Train cutoff is the day BEFORE the earliest
        # perspective (to prevent leakage).
        usable_end = eval_end - timedelta(days=args.horizon)
        usable_days = (usable_end - eval_start).days + 1
        if usable_days < 1:
            log.error("Contiguous window %s..%s is too short for horizon %d",
                      eval_start, eval_end, args.horizon)
            return 1

        step = max(1, usable_days // args.perspectives)
        p_dates = [
            eval_start + timedelta(days=i)
            for i in range(0, usable_days, step)
        ][: args.perspectives]

        train_end = p_dates[0] - timedelta(days=1)
        train_start = train_end - timedelta(days=args.train_days - 1)

        log.info("eval window:  %s .. %s", eval_start, eval_end)
        log.info("train:        %s .. %s (%d days)", train_start, train_end, args.train_days)
        log.info("perspectives: %s (n=%d)", [d.isoformat() for d in p_dates], len(p_dates))
        log.info("horizon:      1..%d", args.horizon)
        log.info("weights:      %s", HORIZON_WEIGHTS_FULL[: args.horizon])

        objective = _build_objective(db, train_start, train_end, p_dates, args.area, args.horizon)

        log.info("Starting Optuna study (%d trials)...", args.trials)
        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=args.trials)

        best = study.best_trial
        print("\n" + "=" * 72)
        print(f"  BEST WEIGHTED MULTI-HORIZON MAE: {best.value:.4f} (trial #{best.number})")
        print("=" * 72)

        per_h = best.user_attrs.get("per_horizon_mae", {})
        if per_h:
            print("\n  Per-horizon MAE of the best trial:")
            for h in range(1, args.horizon + 1):
                v = per_h.get(h) or per_h.get(str(h))
                if v is not None:
                    print(f"    d+{h}: {v:.4f}  (weight {HORIZON_WEIGHTS_FULL[h - 1]:.2f})")

        print("\n  Best hyperparameters (paste into ml_forecast_service.py default_base_params):\n")
        print("    default_base_params = {")
        print('        "verbose": -1,')
        for key, value in best.params.items():
            if isinstance(value, float):
                print(f'        "{key}": {value:.6f},')
            else:
                print(f'        "{key}": {value},')
        print("    }")
        print("=" * 72)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
