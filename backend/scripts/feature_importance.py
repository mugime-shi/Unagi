"""
Feature importance analysis for the current LightGBM model.

Trains with production hparams on the last N days of SE3 data and
prints per-feature importance (gain + split) and group-level aggregation.

Usage:
    python -m scripts.feature_importance
    python -m scripts.feature_importance --days 365 --area SE3
"""

import argparse
import logging
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix
from app.services.ml_forecast_service import SHAP_GROUPS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

# Mirror the production base_params in ml_forecast_service.py
BASE_PARAMS = {
    "verbose": -1,
    "objective": "regression",
    "metric": "mae",
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

FEAT_TO_GROUP: dict[str, str] = {}
for _grp, _feats in SHAP_GROUPS.items():
    for _f in _feats:
        FEAT_TO_GROUP[_f] = _grp


def _load_rows(area: str, days: int):
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
    X = np.array([[r.get(c) for c in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)
    return X, y


def main():
    parser = argparse.ArgumentParser(description="Print feature importance")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--area", default="SE3")
    args = parser.parse_args()

    rows = _load_rows(args.area, args.days)
    if len(rows) < 500:
        log.error("Insufficient data: %d rows", len(rows))
        return 1

    X, y = _rows_to_arrays(rows)

    # 80/20 train/val split (match production-style early stopping)
    split = int(len(rows) * 0.8)
    X_train, y_train = X[:split], y[:split]
    X_val, y_val = X[split:], y[split:]

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
    val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)

    log.info("Training LightGBM with production hparams...")
    model = lgb.train(
        BASE_PARAMS,
        train_set,
        num_boost_round=1000,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )

    imp_gain = model.feature_importance(importance_type="gain")
    imp_split = model.feature_importance(importance_type="split")
    features = model.feature_name()

    # Normalize to percentages
    gain_total = imp_gain.sum() or 1
    split_total = imp_split.sum() or 1
    rank = sorted(
        [
            {
                "feature": f,
                "group": FEAT_TO_GROUP.get(f, "Other"),
                "gain_pct": imp_gain[i] / gain_total * 100,
                "split_pct": imp_split[i] / split_total * 100,
            }
            for i, f in enumerate(features)
        ],
        key=lambda r: r["gain_pct"],
        reverse=True,
    )

    print()
    print("=" * 86)
    print(f"  FEATURE IMPORTANCE — {args.days} days, area={args.area}")
    print(f"  Best iter: {model.best_iteration}   Val MAE: "
          f"{float(np.mean(np.abs(y_val - model.predict(X_val)))):.4f}")
    print("=" * 86)
    print(f"  {'#':>3}  {'Feature':<30} {'Group':<20} {'Gain %':>8} {'Split %':>8}")
    print("-" * 86)
    for i, r in enumerate(rank, 1):
        print(f"  {i:>3}  {r['feature']:<30} {r['group']:<20} "
              f"{r['gain_pct']:>7.2f}  {r['split_pct']:>7.2f}")
    print("-" * 86)

    # Group aggregation
    group_totals: dict[str, dict] = {}
    for r in rank:
        g = r["group"]
        if g not in group_totals:
            group_totals[g] = {"gain": 0.0, "split": 0.0, "n": 0}
        group_totals[g]["gain"] += r["gain_pct"]
        group_totals[g]["split"] += r["split_pct"]
        group_totals[g]["n"] += 1

    group_sorted = sorted(group_totals.items(), key=lambda kv: kv[1]["gain"], reverse=True)
    print()
    print("=" * 86)
    print(f"  GROUP-LEVEL IMPORTANCE")
    print("=" * 86)
    print(f"  {'Group':<20} {'N feats':>8} {'Gain %':>8} {'Split %':>8} {'Gain/feat':>10}")
    print("-" * 86)
    for g, v in group_sorted:
        gain_per = v["gain"] / v["n"] if v["n"] else 0
        print(f"  {g:<20} {v['n']:>8} {v['gain']:>7.2f}  {v['split']:>7.2f}  {gain_per:>9.3f}")
    print("-" * 86)

    # Bottom-10 suggestion
    bottom = rank[-15:]
    print()
    print("=" * 86)
    print(f"  BOTTOM 15 (candidates for removal)")
    print("=" * 86)
    for r in bottom:
        print(f"  {r['feature']:<30} {r['group']:<20} "
              f"gain={r['gain_pct']:.3f}%  split={r['split_pct']:.3f}%")
    print("=" * 86)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
