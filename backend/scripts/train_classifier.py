"""
Phase 1 of M (volatile specialist): regime classifier.

Train a LightGBM binary classifier to predict whether `target_date` will be
volatile (production-model day MAE > median over the labelled window). Output
goes to a soft blend in Phase 3:

    final = (1 - p) * model_A + p * model_B   where  p = classifier(target)

Pass criteria for Phase 2 (volatile specialist regression):
    AUC > 0.65 AND F1 > 0.55

Labelling: forecast_accuracy day MAE → median split (~125 days available).
Features: ~20 daily-aggregated features available the morning of target_date
(rolling stats, lagged daily summaries, weather forecast aggregates, calendar,
external prices). Self-aware Model-A features are deliberately skipped in
Phase 1 — added only if AUC falls below 0.65 with the simpler signal set.

Usage:
    docker exec unagi-api-1 python -m scripts.train_classifier --area SE3
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.feature_service import build_feature_matrix

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Daily feature aggregation
# ---------------------------------------------------------------------------

# Columns whose value is identical across all 24 rows of a single target_date
# (lookback summaries, calendar, daily aggregates). We take the first row.
_DAILY_CONSTANT_COLS = [
    "rolling_7d_mean",
    "rolling_7d_std",
    "daily_avg_prev_day",
    "daily_max_prev_day",
    "daily_min_prev_day",
    "daily_range_prev_day",
    "price_change_d1_d2",
    "is_weekend",
    "is_holiday_se",
    "holiday_score",
    "weekday",
    "month",
    "load_forecast_max",
    "load_forecast_min",
    "load_forecast_range",
    "daily_avg_temp_prev_day",
    "de_price_prev_day",
    "de_se3_spread_prev_day",
    "gas_price_eur_mwh",
    "gas_price_7d_avg",
    "gas_price_change",
    "hydro_stored_gwh",
    "hydro_stored_change_gwh",
    "daylight_hours",
]

# Hourly forecast columns: aggregate to daily mean/std/range
_DAILY_AGGREGATE_COLS = [
    "wind_speed_10m_fc",
    "wind_speed_100m_fc",
    "temp_forecast",
    "radiation_forecast",
    "gen_total_mw",
    "gen_wind_mw",
    "load_forecast_hour",
]


def aggregate_daily_features(rows: list[dict]) -> dict | None:
    """Reduce 24 hourly feature rows to a single daily feature row."""
    if not rows:
        return None
    out: dict[str, float | None] = {}

    for col in _DAILY_CONSTANT_COLS:
        out[col] = rows[0].get(col)

    for col in _DAILY_AGGREGATE_COLS:
        vals = [r.get(col) for r in rows if r.get(col) is not None]
        if vals:
            out[f"{col}_avg"] = float(np.mean(vals))
            out[f"{col}_std"] = float(np.std(vals))
            out[f"{col}_range"] = float(max(vals) - min(vals))
        else:
            for s in ("avg", "std", "range"):
                out[f"{col}_{s}"] = None

    return out


# Self-aware: aggregates of Model A's own predictions on target_date.
# At training time these come from forecast_accuracy.predicted_*. At runtime
# they will come from a fresh Model A predict() call before the classifier runs.
_SELF_AWARE_COLS = [
    "model_a_pred_avg",
    "model_a_pred_std",
    "model_a_pred_range",
    "model_a_pred_max",
    "model_a_cqr_width_avg",
    "model_a_cqr_width_max",
]


# Stable feature ordering for the classifier
CLASSIFIER_FEATURES: list[str] = sorted(
    _DAILY_CONSTANT_COLS
    + [f"{c}_{s}" for c in _DAILY_AGGREGATE_COLS for s in ("avg", "std", "range")]
    + _SELF_AWARE_COLS
)


# ---------------------------------------------------------------------------
# Label loading
# ---------------------------------------------------------------------------


def load_day_mae_labels(db, area: str, days_back: int = 365) -> dict[date, float]:
    """Pull production-model day MAE per target_date from forecast_accuracy."""
    end = date.today()
    start = end - timedelta(days=days_back)
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
    return {d: float(np.mean(errs)) for d, errs in by_day.items() if len(errs) >= 20}


def load_self_aware_features(db, area: str, days_back: int = 365) -> dict[date, dict]:
    """Daily aggregates of Model A's own forecast_accuracy.predicted_* columns."""
    end = date.today()
    start = end - timedelta(days=days_back)
    rows = db.execute(
        text(
            """
            SELECT target_date, predicted_sek_kwh,
                   predicted_low_sek_kwh, predicted_high_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"area": area, "start": start, "end": end},
    ).fetchall()
    grouped: dict[date, list[tuple[float, float | None, float | None]]] = defaultdict(list)
    for tdate, pred, lo, hi in rows:
        grouped[tdate].append(
            (float(pred), float(lo) if lo is not None else None, float(hi) if hi is not None else None)
        )
    out: dict[date, dict] = {}
    for d, items in grouped.items():
        if len(items) < 20:
            continue
        preds = [p for p, _, _ in items]
        widths = [hi - lo for _, lo, hi in items if lo is not None and hi is not None]
        out[d] = {
            "model_a_pred_avg": float(np.mean(preds)),
            "model_a_pred_std": float(np.std(preds)),
            "model_a_pred_range": float(max(preds) - min(preds)),
            "model_a_pred_max": float(max(preds)),
            "model_a_cqr_width_avg": float(np.mean(widths)) if widths else None,
            "model_a_cqr_width_max": float(max(widths)) if widths else None,
        }
    return out


# ---------------------------------------------------------------------------
# Build dataset (X, y, dates)
# ---------------------------------------------------------------------------


def build_dataset(db, area: str, day_labels: dict[date, bool], self_aware: dict[date, dict]):
    """For each labelled day, build aggregated features. Returns sorted X, y, dates."""
    days_sorted = sorted(day_labels.keys())
    X_rows: list[list[float]] = []
    y_rows: list[int] = []
    kept_days: list[date] = []
    skipped = 0
    skipped_no_self_aware = 0
    for i, d in enumerate(days_sorted, 1):
        feature_rows = build_feature_matrix(db, d, d, area=area, include_target=False)
        daily = aggregate_daily_features(feature_rows)
        if daily is None:
            skipped += 1
            continue
        sa = self_aware.get(d)
        if sa is None:
            skipped_no_self_aware += 1
            continue
        merged = {**daily, **sa}
        row = [merged.get(col) for col in CLASSIFIER_FEATURES]
        X_rows.append(row)
        y_rows.append(int(day_labels[d]))
        kept_days.append(d)
        if i % 25 == 0:
            log.info("  built features for %d/%d days", i, len(days_sorted))
    if skipped:
        log.warning("skipped %d days (no feature rows available)", skipped)
    if skipped_no_self_aware:
        log.warning("skipped %d days (no Model A predictions available)", skipped_no_self_aware)
    X = np.array(X_rows, dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array(y_rows, dtype=np.int64)
    return X, y, kept_days


# ---------------------------------------------------------------------------
# Walk-forward training & evaluation
# ---------------------------------------------------------------------------


LGBM_CLF_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "verbose": -1,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 5,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
}


def train_one_fold(X_train, y_train, X_val, y_val):
    import lightgbm as lgb

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=CLASSIFIER_FEATURES)
    val_set = lgb.Dataset(X_val, label=y_val, feature_name=CLASSIFIER_FEATURES, reference=train_set)
    return lgb.train(
        LGBM_CLF_PARAMS,
        train_set,
        num_boost_round=300,
        valid_sets=[val_set],
        callbacks=[lgb.log_evaluation(period=0), lgb.early_stopping(stopping_rounds=20, verbose=False)],
    )


def walk_forward_eval(X, y, n_splits: int = 5):
    from sklearn.metrics import (
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_results = []
    all_y = []
    all_p = []
    importance_sum = np.zeros(len(CLASSIFIER_FEATURES), dtype=np.float64)
    for fold, (tr_idx, va_idx) in enumerate(tscv.split(X), 1):
        X_tr, X_va = X[tr_idx], X[va_idx]
        y_tr, y_va = y[tr_idx], y[va_idx]
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_va)) < 2:
            log.warning("fold %d: skipping (single-class split)", fold)
            continue
        model = train_one_fold(X_tr, y_tr, X_va, y_va)
        importance_sum += np.asarray(model.feature_importance(importance_type="gain"), dtype=np.float64)
        proba = model.predict(X_va)
        pred = (proba >= 0.5).astype(int)
        auc = float(roc_auc_score(y_va, proba))
        f1 = float(f1_score(y_va, pred, zero_division=0))
        prec = float(precision_score(y_va, pred, zero_division=0))
        rec = float(recall_score(y_va, pred, zero_division=0))
        cm = confusion_matrix(y_va, pred, labels=[0, 1])
        fold_results.append(
            {
                "fold": fold,
                "n_train": len(tr_idx),
                "n_val": len(va_idx),
                "vol_rate_val": float(np.mean(y_va)),
                "auc": auc,
                "f1": f1,
                "precision": prec,
                "recall": rec,
                "cm": cm,
            }
        )
        all_y.append(y_va)
        all_p.append(proba)
        log.info(
            "fold %d  n_tr=%d  n_va=%d  AUC=%.3f  F1=%.3f  P=%.3f  R=%.3f",
            fold,
            len(tr_idx),
            len(va_idx),
            auc,
            f1,
            prec,
            rec,
        )

    importance_sum /= max(1, len(fold_results))
    return (
        fold_results,
        np.concatenate(all_y) if all_y else np.array([]),
        np.concatenate(all_p) if all_p else np.array([]),
        importance_sum,
    )


def threshold_sweep(y_true, y_proba, thresholds=(0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)):
    from sklearn.metrics import f1_score, precision_score, recall_score

    print()
    print("  Threshold sweep (pooled across folds)")
    print(f"  {'thr':>5}  {'F1':>6}  {'Prec':>6}  {'Rec':>6}  {'pred_pos':>9}")
    print(f"  {'-' * 5}  {'-' * 6}  {'-' * 6}  {'-' * 6}  {'-' * 9}")
    for thr in thresholds:
        pred = (y_proba >= thr).astype(int)
        f1 = f1_score(y_true, pred, zero_division=0)
        prec = precision_score(y_true, pred, zero_division=0)
        rec = recall_score(y_true, pred, zero_division=0)
        print(f"  {thr:>5.2f}  {f1:>6.3f}  {prec:>6.3f}  {rec:>6.3f}  {int(pred.sum()):>9d}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    global CLASSIFIER_FEATURES  # noqa: PLW0603 — second pass swaps in a pruned subset
    parser = argparse.ArgumentParser()
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument(
        "--top-k",
        type=int,
        default=0,
        help="If >0, prune to top-K features after first pass and re-evaluate",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mae = load_day_mae_labels(db, args.area, args.days_back)
        if not mae:
            log.error("no MAE labels found")
            return 1
        median_mae = float(np.median(list(mae.values())))
        labels = {d: m > median_mae for d, m in mae.items()}
        log.info(
            "loaded %d labelled days  median_MAE=%.4f  vol_rate=%.2f",
            len(labels),
            median_mae,
            float(np.mean(list(labels.values()))),
        )

        self_aware = load_self_aware_features(db, args.area, args.days_back)
        log.info("loaded %d days of self-aware (Model A) features", len(self_aware))

        X, y, days = build_dataset(db, args.area, labels, self_aware)
        log.info("dataset: X=%s  y=%s  span=%s..%s", X.shape, y.shape, days[0], days[-1])

        fold_results, all_y, all_p, importance = walk_forward_eval(X, y, n_splits=args.n_splits)
        if not fold_results:
            log.error("no usable folds")
            return 1

        # Aggregate
        mean_auc = float(np.mean([f["auc"] for f in fold_results]))
        mean_f1 = float(np.mean([f["f1"] for f in fold_results]))
        mean_prec = float(np.mean([f["precision"] for f in fold_results]))
        mean_rec = float(np.mean([f["recall"] for f in fold_results]))

        print()
        print("=" * 72)
        print(f"  TRAIN_CLASSIFIER — area={args.area}  median_MAE={median_mae:.4f}")
        print(f"  Days={len(days)}  Features={len(CLASSIFIER_FEATURES)}  Folds={len(fold_results)}")
        print("-" * 72)
        print(f"  Walk-forward AUC mean = {mean_auc:.3f}")
        print(f"  Walk-forward F1 mean  = {mean_f1:.3f}")
        print(f"  Precision mean        = {mean_prec:.3f}")
        print(f"  Recall mean           = {mean_rec:.3f}")
        print()
        print(f"  Pass criteria: AUC > 0.65 AND F1 > 0.55")
        if mean_auc > 0.65 and mean_f1 > 0.55:
            print(f"  → PASS — proceed to Phase 2")
        else:
            print(f"  → FAIL — consider self-aware features or richer labels")
        print("=" * 72)

        threshold_sweep(all_y, all_p)

        print()
        print("  Feature importance (mean gain across folds, top 20)")
        order = np.argsort(importance)[::-1]
        total = float(importance.sum()) or 1.0
        for rank, idx in enumerate(order[:20], 1):
            pct = 100.0 * importance[idx] / total
            print(f"    {rank:>2}. {CLASSIFIER_FEATURES[idx]:30s}  gain={importance[idx]:>10.1f}  ({pct:>5.1f}%)")

        # Optional second pass with pruned feature set
        if args.top_k > 0 and args.top_k < len(CLASSIFIER_FEATURES):
            keep_idx = order[: args.top_k]
            kept_features = [CLASSIFIER_FEATURES[i] for i in keep_idx]
            log.info("\n--- second pass: top-%d features only ---", args.top_k)
            X2 = X[:, keep_idx]
            # Swap module-level FEATURE list so train_one_fold uses pruned names
            saved = CLASSIFIER_FEATURES
            CLASSIFIER_FEATURES = kept_features
            try:
                fold_results2, all_y2, all_p2, _ = walk_forward_eval(X2, y, n_splits=args.n_splits)
            finally:
                CLASSIFIER_FEATURES = saved
            if fold_results2:
                mean_auc2 = float(np.mean([f["auc"] for f in fold_results2]))
                mean_f12 = float(np.mean([f["f1"] for f in fold_results2]))
                print()
                print(f"  --- Top-{args.top_k} pruned ---  AUC mean = {mean_auc2:.3f}  F1 mean = {mean_f12:.3f}")
                threshold_sweep(all_y2, all_p2)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
