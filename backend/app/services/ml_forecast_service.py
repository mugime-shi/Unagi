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

_CACHE_DIR = Path(os.environ.get("LGBM_CACHE_DIR", "/tmp/namazu_lgbm"))
_TRAIN_DAYS = 90       # days of history for training
_TEST_DAYS = 7         # held-out test set (last N days of training window)
_MIN_TRAIN_ROWS = 200  # minimum rows to attempt training


# ---------------------------------------------------------------------------
# Model cache (warm Lambda reuse)
# ---------------------------------------------------------------------------

def _cache_key(area: str, target_date: date) -> str:
    """Deterministic key from area + target_date."""
    raw = f"{area}:{target_date.isoformat()}"
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
    Train a LightGBM model on historical data.

    Training window: [target_date - TRAIN_DAYS, target_date - 1]
    The last TEST_DAYS are held out for validation (early stopping).
    """
    import lightgbm as lgb

    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=_TRAIN_DAYS - 1)

    rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(rows) < _MIN_TRAIN_ROWS:
        logger.warning(
            "Insufficient training data: %d rows (need %d)", len(rows), _MIN_TRAIN_ROWS
        )
        return None

    # Convert to numpy arrays
    X = np.array([
        [r.get(col) for col in FEATURE_COLS]
        for r in rows
    ], dtype=np.float64)
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)

    # Replace None with NaN (LightGBM handles NaN natively)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711

    # Train/validation split: last TEST_DAYS for early stopping
    split_idx = len(rows) - _TEST_DAYS * 24
    if split_idx < _MIN_TRAIN_ROWS // 2:
        # Not enough data for proper split; train on everything
        split_idx = len(rows)

    X_train, y_train = X[:split_idx], y[:split_idx]
    X_val, y_val = X[split_idx:], y[split_idx:]

    params = {
        "objective": "regression",
        "metric": "mae",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    }

    train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)

    callbacks = [lgb.log_evaluation(period=0)]  # silent
    if len(X_val) > 0:
        val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)
        callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))
        model = lgb.train(
            params, train_set,
            num_boost_round=500,
            valid_sets=[val_set],
            callbacks=callbacks,
        )
    else:
        model = lgb.train(
            params, train_set,
            num_boost_round=200,
            callbacks=callbacks,
        )

    logger.info("LightGBM trained: %d rounds, %d features", model.best_iteration, len(FEATURE_COLS))
    return model


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def _build_prediction_features(
    db: Session, target_date: date, area: str,
) -> list[dict] | None:
    """
    Build feature rows for predicting target_date (24 hours).

    Since target_date hasn't happened yet, we:
    - Use (target_date - 1) prices for lag features
    - Use (target_date - 1) generation data
    - Calendar features are deterministic
    """
    import math

    prev_day = target_date - timedelta(days=1)
    prev_week = target_date - timedelta(days=7)

    # Load historical prices for lag features
    from app.services.feature_service import _ensure_utc, _load_hourly_generation, _load_hourly_prices

    prices = _load_hourly_prices(db, prev_week, prev_day, area)
    gen = _load_hourly_generation(db, prev_day - timedelta(days=1), prev_day, area)

    if not prices:
        return None

    # Daily average of previous day
    prev_day_prices = [p for (d, h), p in prices.items() if d == prev_day]
    daily_avg_prev = sum(prev_day_prices) / len(prev_day_prices) if prev_day_prices else None

    rows = []
    for hour in range(24):
        gen_prev = gen.get((prev_day, hour), {})
        gen_total = sum(gen_prev.values()) if gen_prev else 0.0

        row = {
            "hour": hour,
            "weekday": target_date.weekday(),
            "month": target_date.month,
            "hour_sin": round(math.sin(2 * math.pi * hour / 24), 6),
            "hour_cos": round(math.cos(2 * math.pi * hour / 24), 6),
            "weekday_sin": round(math.sin(2 * math.pi * target_date.weekday() / 7), 6),
            "weekday_cos": round(math.cos(2 * math.pi * target_date.weekday() / 7), 6),
            "month_sin": round(math.sin(2 * math.pi * (target_date.month - 1) / 12), 6),
            "month_cos": round(math.cos(2 * math.pi * (target_date.month - 1) / 12), 6),
            "prev_day_same_hour": prices.get((prev_day, hour)),
            "prev_week_same_hour": prices.get((prev_week, hour)),
            "daily_avg_prev_day": daily_avg_prev,
            "gen_hydro_mw": gen_prev.get("hydro"),
            "gen_wind_mw": gen_prev.get("wind"),
            "gen_nuclear_mw": gen_prev.get("nuclear"),
            "gen_total_mw": gen_total if gen_total > 0 else None,
            "hydro_ratio": (
                round(gen_prev.get("hydro", 0) / gen_total, 4)
                if gen_total > 0 else None
            ),
            "wind_ratio": (
                round(gen_prev.get("wind", 0) / gen_total, 4)
                if gen_total > 0 else None
            ),
            "nuclear_ratio": (
                round(gen_prev.get("nuclear", 0) / gen_total, 4)
                if gen_total > 0 else None
            ),
        }
        rows.append(row)

    return rows


def build_lgbm_forecast(db: Session, target_date: date, area: str = "SE3") -> dict:
    """
    Generate a 24-hour price forecast using LightGBM.

    Returns the same format as build_forecast():
    {
        "slots": [{"hour": 0-23, "avg_sek_kwh", "low_sek_kwh", "high_sek_kwh"}],
        "summary": {"predicted_avg_sek_kwh", "predicted_low_sek_kwh", "predicted_high_sek_kwh"}
    }

    For low/high, uses the model's prediction ± training residual std
    as a simple prediction interval.
    """
    # Try cache first
    model = _load_cached(area, target_date)
    if model is None:
        model = _train_model(db, target_date, area)
        if model is None:
            # Not enough data; return all nulls
            return {
                "slots": [
                    {"hour": h, "avg_sek_kwh": None, "low_sek_kwh": None, "high_sek_kwh": None}
                    for h in range(24)
                ],
                "summary": {
                    "predicted_avg_sek_kwh": None,
                    "predicted_low_sek_kwh": None,
                    "predicted_high_sek_kwh": None,
                },
            }
        _save_cache(area, target_date, model)

    # Build prediction features
    pred_rows = _build_prediction_features(db, target_date, area)
    if pred_rows is None:
        return {
            "slots": [
                {"hour": h, "avg_sek_kwh": None, "low_sek_kwh": None, "high_sek_kwh": None}
                for h in range(24)
            ],
            "summary": {
                "predicted_avg_sek_kwh": None,
                "predicted_low_sek_kwh": None,
                "predicted_high_sek_kwh": None,
            },
        }

    X_pred = np.array([
        [r.get(col) for col in FEATURE_COLS]
        for r in pred_rows
    ], dtype=object)
    X_pred = np.where(X_pred == None, np.nan, X_pred).astype(np.float64)  # noqa: E711

    predictions = model.predict(X_pred)

    # Compute prediction interval from training residuals
    # Use ±1 std of residuals as rough low/high bound
    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=_TRAIN_DAYS - 1)
    train_rows = build_feature_matrix(db, train_start, train_end, area=area)

    residual_std = 0.10  # default fallback
    if train_rows:
        X_train = np.array([
            [r.get(col) for col in FEATURE_COLS]
            for r in train_rows
        ], dtype=object)
        X_train = np.where(X_train == None, np.nan, X_train).astype(np.float64)  # noqa: E711
        y_train = np.array([r[TARGET_COL] for r in train_rows])
        train_preds = model.predict(X_train)
        residuals = y_train - train_preds
        residual_std = float(np.std(residuals))

    slots = []
    for i, pred in enumerate(predictions):
        pred_val = round(float(pred), 4)
        low_val = round(max(0.0, float(pred) - residual_std), 4)
        high_val = round(float(pred) + residual_std, 4)
        slots.append({
            "hour": i,
            "avg_sek_kwh": pred_val,
            "low_sek_kwh": low_val,
            "high_sek_kwh": high_val,
        })

    valid = [(s["low_sek_kwh"], s["avg_sek_kwh"], s["high_sek_kwh"]) for s in slots]
    return {
        "slots": slots,
        "summary": {
            "predicted_avg_sek_kwh": round(sum(v[1] for v in valid) / len(valid), 4),
            "predicted_low_sek_kwh": round(min(v[0] for v in valid), 4),
            "predicted_high_sek_kwh": round(max(v[2] for v in valid), 4),
        },
    }
