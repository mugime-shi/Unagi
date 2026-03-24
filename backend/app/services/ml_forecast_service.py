"""
LightGBM-based price forecast service.

Trains on recent historical data and predicts next-day hourly prices.
Model binary is cached in /tmp/ for Lambda warm-start reuse.
Output format matches build_forecast() for drop-in compatibility.
"""

import hashlib
import logging
import os
import pickle
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(os.environ.get("LGBM_CACHE_DIR", "/tmp/unagi_lgbm"))
_TRAIN_DAYS = int(os.environ.get("LGBM_TRAIN_DAYS", "365"))
_TEST_DAYS = 30  # held-out set for early stopping + CQR calibration
_MIN_TRAIN_ROWS = 200  # minimum rows to attempt training


# ---------------------------------------------------------------------------
# Model cache (warm Lambda reuse)
# ---------------------------------------------------------------------------


def _cache_key(area: str, target_date: date) -> str:
    """Deterministic key from area + target_date + train_days."""
    raw = f"{area}:{target_date.isoformat()}:{_TRAIN_DAYS}:v8-cqr30"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _cache_path(area: str, target_date: date) -> Path:
    return _CACHE_DIR / f"lgbm_{_cache_key(area, target_date)}.pkl"


def _load_cached(area: str, target_date: date):
    """Load cached model if it exists."""
    path = _cache_path(area, target_date)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            logger.warning("Cache load failed, will retrain")
    return None


def _save_cache(area: str, target_date: date, model):
    """Save model to cache."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(area, target_date)
    try:
        with open(path, "wb") as f:
            pickle.dump(model, f)
    except Exception:
        logger.warning("Cache save failed", exc_info=True)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _train_model(db: Session, target_date: date, area: str):
    """
    Train LightGBM models on historical data.

    Training window: [target_date - TRAIN_DAYS, target_date - 1]
    The last TEST_DAYS are held out for validation (early stopping).

    Returns a dict with 'point', 'low', 'high' models:
    - point: MAE regression for the best point forecast
    - low:   quantile regression (alpha=0.10) for the 10th percentile
    - high:  quantile regression (alpha=0.90) for the 90th percentile
    """
    import lightgbm as lgb

    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=_TRAIN_DAYS - 1)

    rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(rows) < _MIN_TRAIN_ROWS:
        logger.warning("Insufficient training data: %d rows (need %d)", len(rows), _MIN_TRAIN_ROWS)
        return None

    # Convert to numpy arrays
    X = np.array([[r.get(col) for col in FEATURE_COLS] for r in rows], dtype=np.float64)
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)

    # Replace None with NaN (LightGBM handles NaN natively)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711

    # Train/validation split: last TEST_DAYS for early stopping
    split_idx = len(rows) - _TEST_DAYS * 24
    if split_idx < _MIN_TRAIN_ROWS // 2:
        split_idx = len(rows)

    X_train, y_train = X[:split_idx], y[:split_idx]
    X_val, y_val = X[split_idx:], y[split_idx:]

    # Tuned via Optuna (100 trials, 4-fold walk-forward CV, 2026-03-18)
    # Re-validated with 53 features (2026-03-19): still optimal on walk-forward sweep
    base_params = {
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

    def _fit(params):
        train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
        callbacks = [lgb.log_evaluation(period=0)]
        if len(X_val) > 0:
            val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)
            callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))
            return lgb.train(params, train_set, num_boost_round=500, valid_sets=[val_set], callbacks=callbacks)
        return lgb.train(params, train_set, num_boost_round=200, callbacks=callbacks)

    # Point forecast (Huber loss — reduces spike influence while keeping calm precision)
    point_model = _fit({**base_params, "objective": "huber", "huber_delta": 0.5, "metric": "mae"})
    logger.info("LightGBM point model: %d rounds, %d features", point_model.best_iteration, len(FEATURE_COLS))

    # Quantile models for prediction intervals
    low_model = _fit({**base_params, "objective": "quantile", "alpha": 0.10, "metric": "quantile"})
    high_model = _fit({**base_params, "objective": "quantile", "alpha": 0.90, "metric": "quantile"})

    # Conformal calibration (CQR): compute correction factor on validation set
    # so that the prediction interval achieves ~80% coverage in practice.
    if len(X_val) > 0:
        val_low = low_model.predict(X_val)
        val_high = high_model.predict(X_val)
        scores = np.maximum(val_low - y_val, y_val - val_high)
        n = len(scores)
        quantile_level = min(1.0, (1 - 0.20) * (1 + 1 / n))
        q_hat = float(np.quantile(scores, quantile_level))
        logger.info("CQR calibration: q_hat=%.4f (n=%d val samples)", q_hat, n)
    else:
        q_hat = 0.0
        logger.warning("No validation set — skipping CQR calibration")

    return {"point": point_model, "low": low_model, "high": high_model, "q_hat": q_hat}


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def _build_prediction_features(
    db: Session,
    target_date: date,
    area: str,
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> list[dict] | None:
    """
    Build feature rows for predicting target_date (24 hours).

    Delegates to build_feature_matrix(include_target=False) so that
    training and prediction features are always in sync.

    price_overrides: inject predicted prices as pseudo-actuals for lag
    features (used in recursive multi-horizon forecasting).
    """
    rows = build_feature_matrix(
        db,
        target_date,
        target_date,
        area=area,
        include_target=False,
        price_overrides=price_overrides,
    )
    return rows if rows else None


_NULL_RESPONSE = {
    "slots": [{"hour": h, "avg_sek_kwh": None, "low_sek_kwh": None, "high_sek_kwh": None} for h in range(24)],
    "summary": {
        "predicted_avg_sek_kwh": None,
        "predicted_low_sek_kwh": None,
        "predicted_high_sek_kwh": None,
    },
}


def get_or_train_model(db: Session, target_date: date, area: str = "SE3") -> dict | None:
    """Load cached model or train a new one.

    target_date is the d+1 prediction target (model trains on data through target_date - 1).
    Returns model dict with 'point', 'low', 'high', 'q_hat' keys, or None on failure.
    """
    models = _load_cached(area, target_date)
    if models is None:
        models = _train_model(db, target_date, area)
        if models is None:
            return None
        _save_cache(area, target_date, models)

    # Support both old (single model) and new (dict) cache format
    if not isinstance(models, dict):
        models = {"point": models, "low": None, "high": None, "q_hat": 0.0}

    return models


def predict_with_model(
    models: dict,
    db: Session,
    target_date: date,
    area: str = "SE3",
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> dict:
    """Generate a 24-hour forecast using a pre-trained model.

    Use with get_or_train_model() to avoid retraining for each horizon:
        models = get_or_train_model(db, d1_target, area)
        d1 = predict_with_model(models, db, d1_target, area)
        d2 = predict_with_model(models, db, d2_target, area, price_overrides=...)

    Returns same format as build_lgbm_forecast().
    """
    pred_rows = _build_prediction_features(db, target_date, area, price_overrides=price_overrides)
    if pred_rows is None:
        return _NULL_RESPONSE

    X_pred = np.array([[r.get(col) for col in FEATURE_COLS] for r in pred_rows], dtype=object)
    X_pred = np.where(X_pred == None, np.nan, X_pred).astype(np.float64)  # noqa: E711

    point_model = models["point"]
    low_model = models.get("low")
    high_model = models.get("high")
    q_hat = models.get("q_hat", 0.0)

    predictions = point_model.predict(X_pred)

    if low_model is not None and high_model is not None:
        low_preds = low_model.predict(X_pred) - q_hat
        high_preds = high_model.predict(X_pred) + q_hat
    else:
        low_preds = predictions - 0.10
        high_preds = predictions + 0.10

    slots = []
    for i, pred in enumerate(predictions):
        slots.append(
            {
                "hour": i,
                "avg_sek_kwh": round(float(pred), 4),
                "low_sek_kwh": round(max(0.0, float(low_preds[i])), 4),
                "high_sek_kwh": round(float(high_preds[i]), 4),
            }
        )

    valid = [(s["low_sek_kwh"], s["avg_sek_kwh"], s["high_sek_kwh"]) for s in slots]
    return {
        "slots": slots,
        "summary": {
            "predicted_avg_sek_kwh": round(sum(v[1] for v in valid) / len(valid), 4),
            "predicted_low_sek_kwh": round(min(v[0] for v in valid), 4),
            "predicted_high_sek_kwh": round(max(v[2] for v in valid), 4),
        },
    }


def build_lgbm_forecast(
    db: Session,
    target_date: date,
    area: str = "SE3",
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> dict:
    """Generate a 24-hour price forecast using LightGBM.

    Convenience wrapper around get_or_train_model() + predict_with_model().
    For multi-horizon forecasting, use those functions directly to avoid retraining.
    """
    models = get_or_train_model(db, target_date, area)
    if models is None:
        return _NULL_RESPONSE
    return predict_with_model(models, db, target_date, area, price_overrides=price_overrides)


def build_multi_horizon_forecast(
    db: Session,
    base_date: date,
    area: str = "SE3",
    max_horizon: int = 7,
) -> list[dict]:
    """Generate recursive forecasts for d+1 through d+max_horizon.

    Trains one model (for d+1) and reuses it for all horizons.
    Each horizon's predictions become lag features for the next.

    Returns list of dicts, each with keys:
        horizon (int), target_date (date), forecast (dict with slots/summary)
    """
    d1_target = base_date + timedelta(days=1)
    models = get_or_train_model(db, d1_target, area)
    if models is None:
        return []

    results = []
    cumulative_overrides: dict[tuple[date, int], float] = {}

    for horizon in range(1, max_horizon + 1):
        target = base_date + timedelta(days=horizon)
        forecast = predict_with_model(
            models, db, target, area,
            price_overrides=cumulative_overrides if horizon > 1 else None,
        )

        results.append({
            "horizon": horizon,
            "target_date": target,
            "forecast": forecast,
        })

        # Accumulate predictions for next horizon's lag features
        for slot in forecast["slots"]:
            if slot.get("avg_sek_kwh") is not None:
                cumulative_overrides[(target, slot["hour"])] = slot["avg_sek_kwh"]

    return results
