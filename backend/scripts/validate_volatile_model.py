"""
M step-1 minimal validation.

Question: does a LightGBM trained only on volatile training days predict
*volatile* target days more accurately than a LightGBM trained on all days?

Setup (per volatile target day d):
  - Training window: [d - 270, d - 1]
  - Per-day daily_std of hourly spot_prices → median-split into calm/volatile
    (proxy label, since only 123 days of production-MAE labels exist)
  - Model A: point Huber LightGBM trained on all training rows (baseline A = re-
    implementation of production; should land near production lgbm MAE)
  - Model B: same hyper-params, trained only on rows from volatile training days
  - Both predict target day d (24 hourly point forecasts)

Aggregation: across all volatile target days in the last `--days` window,
report mean MAE for Model A vs Model B.

Also reports A vs B on *calm* target days as a sanity check — Model B is
expected to underperform there (that's by design; the point is to see
whether the ensemble blend can improve the volatile tail).

Usage:
    python -m scripts.validate_volatile_model --days 90 --area SE3
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# Re-validation 2026-04-23: Training window extended to 500d after backfill.
# Expectation: volatile sample count doubles from ~1,080h to ~2,160h.
TRAIN_DAYS = 500
TEST_DAYS = 30
MIN_TRAIN_ROWS = 500

# Tuned via Optuna 2026-03-18 (unchanged in production)
LGBM_PARAMS = {
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
    "huber_delta": 1.0,
    "metric": "mae",
}


def get_production_mae_labels(db, days: int, area: str) -> dict[date, float]:
    end = date.today()
    start = end - timedelta(days=days)
    rows = db.execute(
        text(
            """
            SELECT target_date, hour, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"area": area, "start": start, "end": end},
    ).fetchall()
    by_day: dict[date, list[float]] = defaultdict(list)
    for d, _, pred, actual in rows:
        by_day[d].append(abs(float(pred) - float(actual)))
    return {d: float(np.mean(errs)) for d, errs in by_day.items()}


def get_actuals_for_day(db, target_date: date, area: str) -> dict[int, float]:
    rows = db.execute(
        text(
            """
            SELECT hour_local, AVG(price_sek_kwh) AS price
            FROM (
              SELECT
                date_part('hour', timestamp_utc AT TIME ZONE 'Europe/Stockholm')::int
                  AS hour_local,
                (timestamp_utc AT TIME ZONE 'Europe/Stockholm')::date AS day_local,
                price_sek_kwh
              FROM spot_prices
              WHERE area = :area
                AND price_sek_kwh IS NOT NULL
                AND timestamp_utc >= :start
                AND timestamp_utc < :end_excl
            ) t
            WHERE day_local = :d
            GROUP BY hour_local
            """
        ),
        {
            "area": area,
            "d": target_date,
            "start": target_date - timedelta(days=1),
            "end_excl": target_date + timedelta(days=2),
        },
    ).fetchall()
    return {int(h): float(p) for h, p in rows if p is not None}


def build_training_arrays(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Convert feature rows → (X, y) numpy arrays matching production format."""
    X = np.array([[r.get(col) for col in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)
    return X, y


def label_training_days_by_std(rows: list[dict]) -> dict[date, bool]:
    """For each day in the training window, mark volatile=True if the day's
    actual-price std is above the window median.

    We use the proxy because we don't have production MAE labels for the full
    270-day training window.
    """
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        price = r.get(TARGET_COL)
        if price is None:
            continue
        by_day[r["date"]].append(float(price))
    stds: dict[str, float] = {}
    for d, prices in by_day.items():
        if len(prices) >= 20:
            stds[d] = float(np.std(prices))
    if not stds:
        return {}
    median_std = float(np.median(list(stds.values())))
    return {d: (s > median_std) for d, s in stds.items()}


def train_lightgbm(X_train, y_train, X_val, y_val, feature_names):
    import lightgbm as lgb

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
    callbacks = [lgb.log_evaluation(period=0)]
    if X_val is not None and len(X_val) > 0:
        val_set = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=train_set)
        callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))
        return lgb.train(LGBM_PARAMS, train_set, num_boost_round=500, valid_sets=[val_set], callbacks=callbacks)
    return lgb.train(LGBM_PARAMS, train_set, num_boost_round=200, callbacks=callbacks)


def predict_day(model, pred_rows: list[dict]) -> dict[int, float]:
    X_pred = np.array([[r.get(col) for col in FEATURE_COLS] for r in pred_rows], dtype=object)
    X_pred = np.where(X_pred == None, np.nan, X_pred).astype(np.float64)  # noqa: E711
    preds = model.predict(X_pred)
    return {int(pred_rows[i]["hour"]): float(preds[i]) for i in range(len(pred_rows))}


def run_one_day(db, target_date: date, area: str) -> dict | None:
    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=TRAIN_DAYS - 1)

    train_rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(train_rows) < MIN_TRAIN_ROWS:
        log.warning("insufficient train rows for %s: %d", target_date, len(train_rows))
        return None

    # Label each training day by actual-price std
    day_is_volatile = label_training_days_by_std(train_rows)
    if not day_is_volatile:
        log.warning("std labelling failed for %s", target_date)
        return None

    # Sort by date so the trailing slice can serve as val set
    train_rows.sort(key=lambda r: (r["date"], r["hour"]))

    # Build Model A training arrays (all days)
    X_all, y_all = build_training_arrays(train_rows)
    split_idx = len(train_rows) - TEST_DAYS * 24
    if split_idx < MIN_TRAIN_ROWS // 2:
        split_idx = len(train_rows)
    X_tr_a, y_tr_a = X_all[:split_idx], y_all[:split_idx]
    X_val_a, y_val_a = X_all[split_idx:], y_all[split_idx:]

    # Build Model B training arrays (volatile days only)
    vol_rows = [r for r in train_rows if day_is_volatile.get(r["date"], False)]
    if len(vol_rows) < MIN_TRAIN_ROWS // 2:
        log.warning("insufficient volatile rows for %s: %d", target_date, len(vol_rows))
        return None
    X_vol, y_vol = build_training_arrays(vol_rows)
    # Val set: last 30 distinct volatile training days
    vol_days_sorted = sorted({r["date"] for r in vol_rows})
    val_cutoff_day = vol_days_sorted[-30] if len(vol_days_sorted) >= 30 else vol_days_sorted[-1]
    val_mask = np.array([r["date"] >= val_cutoff_day for r in vol_rows])
    X_tr_b, y_tr_b = X_vol[~val_mask], y_vol[~val_mask]
    X_val_b, y_val_b = X_vol[val_mask], y_vol[val_mask]
    if len(X_tr_b) < MIN_TRAIN_ROWS // 2:
        log.warning("volatile train slice too small for %s: %d", target_date, len(X_tr_b))
        return None

    # Train both
    model_a = train_lightgbm(X_tr_a, y_tr_a, X_val_a, y_val_a, FEATURE_COLS)
    model_b = train_lightgbm(X_tr_b, y_tr_b, X_val_b, y_val_b, FEATURE_COLS)

    # Build prediction features for target_date
    pred_rows = build_feature_matrix(db, target_date, target_date, area=area, include_target=False)
    if not pred_rows:
        log.warning("no prediction features for %s", target_date)
        return None

    preds_a = predict_day(model_a, pred_rows)
    preds_b = predict_day(model_b, pred_rows)

    # Actuals
    actuals = get_actuals_for_day(db, target_date, area)
    if not actuals:
        log.warning("no actuals for %s", target_date)
        return None

    common_hours = sorted(set(preds_a) & set(preds_b) & set(actuals))
    if not common_hours:
        return None
    errs_a = [abs(preds_a[h] - actuals[h]) for h in common_hours]
    errs_b = [abs(preds_b[h] - actuals[h]) for h in common_hours]

    return {
        "date": target_date,
        "n_hours": len(common_hours),
        "mae_a": float(np.mean(errs_a)),
        "mae_b": float(np.mean(errs_b)),
        "n_train_all": len(train_rows),
        "n_train_vol": len(vol_rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Label window for calm/volatile split")
    parser.add_argument("--area", default="SE3")
    parser.add_argument(
        "--subset",
        default="volatile",
        choices=["volatile", "calm", "all"],
        help="Which target-day subset to evaluate",
    )
    parser.add_argument(
        "--max-days",
        type=int,
        default=None,
        help="Cap the number of target days processed (for quick smoke tests)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mae = get_production_mae_labels(db, args.days, args.area)
        if not mae:
            log.error("no MAE labels")
            return 1
        median_mae = float(np.median(list(mae.values())))
        log.info(
            "loaded %d days of production MAE, median=%.4f (split threshold)",
            len(mae),
            median_mae,
        )

        if args.subset == "volatile":
            target_days = sorted([d for d, m in mae.items() if m > median_mae])
        elif args.subset == "calm":
            target_days = sorted([d for d, m in mae.items() if m <= median_mae])
        else:
            target_days = sorted(mae.keys())

        if args.max_days:
            target_days = target_days[: args.max_days]
        log.info("running on %d %s target days", len(target_days), args.subset)

        results: list[dict] = []
        for i, d in enumerate(target_days, 1):
            log.info("[%d/%d] %s", i, len(target_days), d)
            res = run_one_day(db, d, args.area)
            if res is None:
                continue
            results.append(res)
            log.info(
                "    MAE A=%.4f  B=%.4f  Δ=%+.4f (%+.1f%%)",
                res["mae_a"],
                res["mae_b"],
                res["mae_b"] - res["mae_a"],
                (res["mae_b"] / res["mae_a"] - 1) * 100,
            )
    finally:
        db.close()

    if not results:
        log.error("no results")
        return 1

    total_hours = sum(r["n_hours"] for r in results)
    errs_a = []
    errs_b = []
    for r in results:
        errs_a.extend([r["mae_a"]] * r["n_hours"])
        errs_b.extend([r["mae_b"]] * r["n_hours"])
    agg_a = float(np.mean(errs_a))
    agg_b = float(np.mean(errs_b))

    wins_b = sum(1 for r in results if r["mae_b"] < r["mae_a"])
    print()
    print("=" * 72)
    print(f"  VALIDATE_VOLATILE_MODEL — subset={args.subset}, area={args.area}")
    print(f"  Days processed: {len(results)}  ({total_hours} hourly preds)")
    print("-" * 72)
    print(f"  Model A (all-days):      MAE = {agg_a:.4f}")
    print(f"  Model B (volatile-only): MAE = {agg_b:.4f}")
    delta = agg_b - agg_a
    pct = (agg_b / agg_a - 1) * 100
    print(f"  Δ = {delta:+.4f}  ({pct:+.1f}%)  |  B wins on {wins_b}/{len(results)} days")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
