"""
Regime classifier — Phase 3 of the M ensemble.

Predicts P(target_date is volatile) using the top-20 daily features identified
by gain in scripts/train_classifier.py. The probability drives the soft blend
in build_lgbm_forecast_ensemble:

    final = (1 - p) * model_A + p * model_B

Trained on forecast_accuracy where actual prices are joined (≈125 days). The
training cadence is daily — cache key includes target_date - 1 as the training
end so the classifier auto-refreshes whenever a new actual lands.
"""

import hashlib
import logging
import os
import pickle
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.feature_service import build_feature_matrix

logger = logging.getLogger(__name__)


_CACHE_DIR = Path(os.environ.get("LGBM_CACHE_DIR", "/tmp/unagi_lgbm"))
_DAYS_BACK = 365  # window from which to draw labels; only days with actuals are used
_MIN_LABELLED_DAYS = 60


# Top-20 features by gain (Phase 1 walk-forward CV result).
# Constant within a day (lookback / calendar / daily summaries):
_DAILY_CONSTANT_COLS = [
    "rolling_7d_std",
    "daily_avg_prev_day",
    "daily_range_prev_day",
    "price_change_d1_d2",
    "gas_price_change",
    "hydro_stored_gwh",
    "hydro_stored_change_gwh",
    "daylight_hours",
]
# Hourly forecasts → daily aggregates. Tuple = (column, suffix).
_DAILY_AGGREGATE_COLS: list[tuple[str, list[str]]] = [
    ("gen_wind_mw", ["avg", "range"]),
    ("gen_total_mw", ["avg", "range", "std"]),
    ("load_forecast_hour", ["range"]),
    ("wind_speed_10m_fc", ["avg", "std"]),
    ("temp_forecast", ["range"]),
    ("radiation_forecast", ["range"]),
]
# Self-aware aggregates of Model A's own forecast for target_date
_SELF_AWARE_COLS = [
    "model_a_pred_range",
    "model_a_cqr_width_avg",
    "model_a_cqr_width_max",
]

CLASSIFIER_FEATURES: list[str] = (
    list(_DAILY_CONSTANT_COLS)
    + [f"{c}_{s}" for c, suffixes in _DAILY_AGGREGATE_COLS for s in suffixes]
    + list(_SELF_AWARE_COLS)
)


# ---------------------------------------------------------------------------
# Feature aggregation
# ---------------------------------------------------------------------------


def _aggregate_daily_features(feature_rows: list[dict]) -> dict | None:
    """Reduce 24 hourly feature rows to a single daily feature row."""
    if not feature_rows:
        return None
    out: dict[str, float | None] = {}

    for col in _DAILY_CONSTANT_COLS:
        out[col] = feature_rows[0].get(col)

    for col, suffixes in _DAILY_AGGREGATE_COLS:
        vals = [r.get(col) for r in feature_rows if r.get(col) is not None]
        for s in suffixes:
            if not vals:
                out[f"{col}_{s}"] = None
            elif s == "avg":
                out[f"{col}_{s}"] = float(np.mean(vals))
            elif s == "std":
                out[f"{col}_{s}"] = float(np.std(vals))
            elif s == "range":
                out[f"{col}_{s}"] = float(max(vals) - min(vals))

    return out


def _self_aware_from_forecast_slots(slots: list[dict]) -> dict:
    """Compute Model-A-derived features from a fresh forecast result."""
    preds = [s["avg_sek_kwh"] for s in slots if s.get("avg_sek_kwh") is not None]
    widths = [
        s["high_sek_kwh"] - s["low_sek_kwh"]
        for s in slots
        if s.get("low_sek_kwh") is not None and s.get("high_sek_kwh") is not None
    ]
    return {
        "model_a_pred_range": float(max(preds) - min(preds)) if preds else None,
        "model_a_cqr_width_avg": float(np.mean(widths)) if widths else None,
        "model_a_cqr_width_max": float(max(widths)) if widths else None,
    }


def _self_aware_from_history(db: Session, area: str, days_back: int, as_of: date) -> dict[date, dict]:
    """Pull historical Model A predictions from forecast_accuracy.

    Strict upper bound (target_date < as_of) prevents future leakage in backtest.
    """
    start = as_of - timedelta(days=days_back)
    rows = db.execute(
        text(
            """
            SELECT target_date, predicted_sek_kwh,
                   predicted_low_sek_kwh, predicted_high_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND target_date >= :start AND target_date < :as_of
            """
        ),
        {"area": area, "start": start, "as_of": as_of},
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
            "model_a_pred_range": float(max(preds) - min(preds)),
            "model_a_cqr_width_avg": float(np.mean(widths)) if widths else None,
            "model_a_cqr_width_max": float(max(widths)) if widths else None,
        }
    return out


def _load_day_mae_labels(db: Session, area: str, days_back: int, as_of: date) -> dict[date, float]:
    """Day MAE labels, strictly before as_of (backtest-safe)."""
    start = as_of - timedelta(days=days_back)
    rows = db.execute(
        text(
            """
            SELECT target_date, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date < :as_of
            """
        ),
        {"area": area, "start": start, "as_of": as_of},
    ).fetchall()
    by_day: dict[date, list[float]] = defaultdict(list)
    for d, pred, actual in rows:
        by_day[d].append(abs(float(pred) - float(actual)))
    return {d: float(np.mean(errs)) for d, errs in by_day.items() if len(errs) >= 20}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


_LGBM_CLF_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "verbose": -1,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 5,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
}


def _train_classifier(db: Session, area: str, as_of: date) -> dict | None:
    """Build labelled dataset, train LightGBM binary, return {model, ...}.

    Trains strictly on data before `as_of` so the same code path is correct
    for production (as_of=target_date) and backtest (as_of=past target_date).
    """
    import lightgbm as lgb

    mae = _load_day_mae_labels(db, area, _DAYS_BACK, as_of=as_of)
    if len(mae) < _MIN_LABELLED_DAYS:
        logger.warning("Classifier: only %d labelled days (need %d)", len(mae), _MIN_LABELLED_DAYS)
        return None
    median_mae = float(np.median(list(mae.values())))
    labels = {d: int(m > median_mae) for d, m in mae.items()}

    self_aware = _self_aware_from_history(db, area, _DAYS_BACK, as_of=as_of)

    X_rows: list[list[float]] = []
    y_rows: list[int] = []
    for d in sorted(labels.keys()):
        feature_rows = build_feature_matrix(db, d, d, area=area, include_target=False)
        daily = _aggregate_daily_features(feature_rows)
        sa = self_aware.get(d)
        if daily is None or sa is None:
            continue
        merged = {**daily, **sa}
        X_rows.append([merged.get(col) for col in CLASSIFIER_FEATURES])
        y_rows.append(labels[d])

    if len(X_rows) < _MIN_LABELLED_DAYS:
        logger.warning("Classifier: only %d usable rows after feature build", len(X_rows))
        return None

    X = np.array(X_rows, dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array(y_rows, dtype=np.int64)

    train_set = lgb.Dataset(X, label=y, feature_name=CLASSIFIER_FEATURES)
    model = lgb.train(
        _LGBM_CLF_PARAMS,
        train_set,
        num_boost_round=200,
        callbacks=[lgb.log_evaluation(period=0)],
    )
    logger.info(
        "Regime classifier trained: %d rows, %d features, %d rounds, vol_rate=%.2f",
        len(X),
        len(CLASSIFIER_FEATURES),
        model.num_trees(),
        float(np.mean(y)),
    )
    return {"model": model, "median_mae": median_mae, "n_train": len(X)}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _classifier_cache_path(area: str, target_date: date) -> Path:
    train_end = target_date - timedelta(days=1)
    raw = f"{area}:{train_end.isoformat()}:clf-v1"
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return _CACHE_DIR / f"clf_{digest}.pkl"


def get_or_train_classifier(db: Session, target_date: date, area: str = "SE3") -> dict | None:
    path = _classifier_cache_path(area, target_date)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            logger.warning("Classifier cache load failed, will retrain")
    bundle = _train_classifier(db, area, as_of=target_date)
    if bundle is None:
        return None
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "wb") as f:
            pickle.dump(bundle, f)
    except Exception:
        logger.warning("Classifier cache save failed", exc_info=True)
    return bundle


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def predict_volatility(
    db: Session,
    target_date: date,
    area: str,
    *,
    classifier_bundle: dict,
    model_a_slots: list[dict],
) -> float | None:
    """Return P(target_date is volatile) ∈ [0, 1] given a fresh Model A forecast."""
    feature_rows = build_feature_matrix(db, target_date, target_date, area=area, include_target=False)
    daily = _aggregate_daily_features(feature_rows)
    if daily is None:
        logger.warning("Classifier: no daily features for %s", target_date)
        return None
    sa = _self_aware_from_forecast_slots(model_a_slots)
    merged = {**daily, **sa}
    x = np.array([[merged.get(col) for col in CLASSIFIER_FEATURES]], dtype=object)
    x = np.where(x == None, np.nan, x).astype(np.float64)  # noqa: E711
    p = float(classifier_bundle["model"].predict(x)[0])
    return max(0.0, min(1.0, p))
