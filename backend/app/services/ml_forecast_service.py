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

try:
    import shap as _shap
except ImportError:
    _shap = None

from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_DIR = Path(os.environ.get("LGBM_CACHE_DIR", "/tmp/unagi_lgbm"))
_TRAIN_DAYS = int(os.environ.get("LGBM_TRAIN_DAYS", "500"))
_TEST_DAYS = 30  # held-out set for early stopping + CQR calibration
_MIN_TRAIN_ROWS = 200  # minimum rows to attempt training

# ---------------------------------------------------------------------------
# SHAP feature groups: 59 raw features → 10 human-readable groups
# ---------------------------------------------------------------------------

SHAP_GROUPS: dict[str, list[str]] = {
    "Price history": [
        "prev_day_same_hour",
        "prev_2day_same_hour",
        "prev_3day_same_hour",
        "prev_week_same_hour",
        "daily_avg_prev_day",
        "daily_max_prev_day",
        "daily_min_prev_day",
        "daily_range_prev_day",
        "price_change_d1_d2",
        "rolling_7d_mean",
        "rolling_7d_std",
    ],
    "Wind": ["gen_wind_mw", "wind_ratio", "wind_speed_10m_fc", "wind_speed_100m_fc", "wind_x_hour"],
    "Temperature": ["temperature_c", "temp_forecast", "daily_avg_temp_prev_day", "temp_deviation", "temp_x_month"],
    "Hydro": ["gen_hydro_mw", "hydro_ratio", "hydro_stored_gwh", "hydro_stored_change_gwh"],
    "Nuclear": ["gen_nuclear_mw", "nuclear_ratio"],
    "Solar & daylight": [
        "sun_elevation",
        "sun_azimuth",
        "daylight_hours",
        "radiation_wm2",
        "radiation_forecast",
        "gen_total_mw",
    ],
    "Demand": [
        "load_forecast_max",
        "load_forecast_min",
        "load_forecast_hour",
        "load_forecast_range",
        "load_forecast_vs_avg",
        "load_x_hour",
    ],
    "Calendar": [
        "hour",
        "weekday",
        "month",
        "hour_sin",
        "hour_cos",
        "weekday_sin",
        "weekday_cos",
        "month_sin",
        "month_cos",
        "is_weekend",
        "is_holiday_se",
        "holiday_score",
        "is_bridge_day",
    ],
    "Gas & imports": [
        "gas_price_eur_mwh",
        "gas_price_7d_avg",
        "gas_price_change",
        "de_price_prev_day",
        "de_se3_spread_prev_day",
        "de_price_same_hour_prev_day",
    ],
    "Grid balance": ["bal_up_avg_prev_day", "bal_down_avg_prev_day", "bal_spread_prev_day"],
}

# Reverse lookup: feature_name → group_name
_FEAT_TO_GROUP: dict[str, str] = {}
for _grp, _feats in SHAP_GROUPS.items():
    for _f in _feats:
        _FEAT_TO_GROUP[_f] = _grp


def _compute_shap_explanations(point_model, X_pred: np.ndarray, top_n: int = 5) -> dict:
    """Compute per-hour SHAP explanations grouped by feature category.

    Returns dict with 'base_value' and 'hours' list, each containing
    the top_n contributing feature groups sorted by absolute impact.
    """
    if _shap is None:
        return None
    explainer = _shap.TreeExplainer(point_model)
    shap_values = explainer.shap_values(X_pred)  # shape: (24, 59)
    base_value = float(explainer.expected_value)

    # Aggregate SHAP values by group for each hour
    hours = []
    for hour_idx in range(shap_values.shape[0]):
        group_impacts: dict[str, float] = {}
        for feat_idx, feat_name in enumerate(FEATURE_COLS):
            grp = _FEAT_TO_GROUP.get(feat_name, "Other")
            group_impacts[grp] = group_impacts.get(grp, 0.0) + shap_values[hour_idx, feat_idx]

        # Sort by absolute impact, take top N
        sorted_groups = sorted(group_impacts.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]
        top = [
            {
                "group": name,
                "impact": round(float(val), 4),
                "direction": "higher" if val > 0 else "lower",
            }
            for name, val in sorted_groups
        ]
        hours.append({"hour": hour_idx, "top": top})

    return {"base_value": round(base_value, 4), "hours": hours}


# ---------------------------------------------------------------------------
# Model cache (warm Lambda reuse)
# ---------------------------------------------------------------------------


def _cache_key(area: str, target_date: date, variant: str = "A") -> str:
    """Deterministic key from area + target_date + train_days + variant."""
    raw = f"{area}:{target_date.isoformat()}:{_TRAIN_DAYS}:v8-cqr30:{variant}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _cache_path(area: str, target_date: date, variant: str = "A") -> Path:
    return _CACHE_DIR / f"lgbm_{_cache_key(area, target_date, variant)}.pkl"


def _load_cached(area: str, target_date: date, variant: str = "A"):
    """Load cached model if it exists."""
    path = _cache_path(area, target_date, variant)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            logger.warning("Cache load failed, will retrain")
    return None


def _save_cache(area: str, target_date: date, model, variant: str = "A"):
    """Save model to cache."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(area, target_date, variant)
    try:
        with open(path, "wb") as f:
            pickle.dump(model, f)
    except Exception:
        logger.warning("Cache save failed", exc_info=True)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


# Tuned via Optuna (100 trials, 4-fold walk-forward CV, 2026-03-18)
# Re-validated with 53 features (2026-03-19): still optimal on walk-forward sweep
_BASE_LGBM_PARAMS = {
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


def _fit_quantile_set(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    huber_delta: float = 1.0,
    log_label: str = "model",
) -> dict:
    """Train point + low/high quantile models with shared base params and CQR.

    Returns {'point', 'low', 'high', 'q_hat'} ready for predict_with_model().
    """
    import lightgbm as lgb

    def _fit(params):
        train_set = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
        callbacks = [lgb.log_evaluation(period=0)]
        if len(X_val) > 0:
            val_set = lgb.Dataset(X_val, label=y_val, feature_name=FEATURE_COLS, reference=train_set)
            callbacks.append(lgb.early_stopping(stopping_rounds=20, verbose=False))
            return lgb.train(params, train_set, num_boost_round=500, valid_sets=[val_set], callbacks=callbacks)
        return lgb.train(params, train_set, num_boost_round=200, callbacks=callbacks)

    point_model = _fit({**_BASE_LGBM_PARAMS, "objective": "huber", "huber_delta": huber_delta, "metric": "mae"})
    logger.info(
        "LightGBM %s point: %d rounds, %d features, %d train rows",
        log_label,
        point_model.best_iteration,
        len(FEATURE_COLS),
        len(X_train),
    )

    low_model = _fit({**_BASE_LGBM_PARAMS, "objective": "quantile", "alpha": 0.10, "metric": "quantile"})
    high_model = _fit({**_BASE_LGBM_PARAMS, "objective": "quantile", "alpha": 0.90, "metric": "quantile"})

    if len(X_val) > 0:
        val_low = low_model.predict(X_val)
        val_high = high_model.predict(X_val)
        scores = np.maximum(val_low - y_val, y_val - val_high)
        n = len(scores)
        quantile_level = min(1.0, (1 - 0.20) * (1 + 1 / n))
        q_hat = float(np.quantile(scores, quantile_level))
        logger.info("CQR calibration (%s): q_hat=%.4f (n=%d val samples)", log_label, q_hat, n)
    else:
        q_hat = 0.0
        logger.warning("%s: no validation set — skipping CQR calibration", log_label)

    return {"point": point_model, "low": low_model, "high": high_model, "q_hat": q_hat}


def _rows_to_xy(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Project feature rows to (X, y) numpy arrays with NaN handling."""
    X = np.array([[r.get(col) for col in FEATURE_COLS] for r in rows], dtype=object)
    X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711
    y = np.array([r[TARGET_COL] for r in rows], dtype=np.float64)
    return X, y


def _label_volatile_days(rows: list[dict]) -> dict[str, bool]:
    """Median-split each training day's actual price std → volatile=True if above median.

    Proxy label used because we don't have production-MAE labels covering the
    full 500-day training window. Validated in scripts/validate_volatile_model.py
    where Model B beat Model A by 5.6% on volatile target days at TRAIN_DAYS=500.
    """
    by_day: dict[str, list[float]] = {}
    for r in rows:
        price = r.get(TARGET_COL)
        if price is None:
            continue
        by_day.setdefault(r["date"], []).append(float(price))
    stds: dict[str, float] = {d: float(np.std(p)) for d, p in by_day.items() if len(p) >= 20}
    if not stds:
        return {}
    median_std = float(np.median(list(stds.values())))
    return {d: (s > median_std) for d, s in stds.items()}


def _train_model(db: Session, target_date: date, area: str, *, huber_delta: float = 1.0):
    """Train Model A — full-history LightGBM (current production)."""
    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=_TRAIN_DAYS - 1)

    rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(rows) < _MIN_TRAIN_ROWS:
        logger.warning("Insufficient training data: %d rows (need %d)", len(rows), _MIN_TRAIN_ROWS)
        return None

    X, y = _rows_to_xy(rows)

    split_idx = len(rows) - _TEST_DAYS * 24
    if split_idx < _MIN_TRAIN_ROWS // 2:
        split_idx = len(rows)

    return _fit_quantile_set(
        X[:split_idx], y[:split_idx], X[split_idx:], y[split_idx:],
        huber_delta=huber_delta, log_label="A",
    )


def _train_volatile_model(db: Session, target_date: date, area: str, *, huber_delta: float = 1.0):
    """Train Model B — volatile-specialist LightGBM for the M ensemble.

    Same training window as Model A but filters to days whose actual-price std
    exceeds the window median. Returns the same {point, low, high, q_hat}
    structure as _train_model so predict_with_model() works unchanged.
    """
    train_end = target_date - timedelta(days=1)
    train_start = train_end - timedelta(days=_TRAIN_DAYS - 1)

    rows = build_feature_matrix(db, train_start, train_end, area=area)
    if len(rows) < _MIN_TRAIN_ROWS:
        logger.warning("Model B: insufficient training data: %d rows", len(rows))
        return None

    day_is_volatile = _label_volatile_days(rows)
    if not day_is_volatile:
        logger.warning("Model B: volatile labelling failed (no day with ≥20 hourly prices)")
        return None

    rows_sorted = sorted(rows, key=lambda r: (r["date"], r["hour"]))
    vol_rows = [r for r in rows_sorted if day_is_volatile.get(r["date"], False)]
    if len(vol_rows) < _MIN_TRAIN_ROWS // 2:
        logger.warning("Model B: too few volatile rows (%d)", len(vol_rows))
        return None

    X_vol, y_vol = _rows_to_xy(vol_rows)

    # Validation set: last 30 distinct volatile training days (matches
    # validate_volatile_model.py for behavioural parity)
    vol_days_sorted = sorted({r["date"] for r in vol_rows})
    if len(vol_days_sorted) >= 30:
        val_cutoff_day = vol_days_sorted[-30]
        val_mask = np.array([r["date"] >= val_cutoff_day for r in vol_rows])
        X_train_b, y_train_b = X_vol[~val_mask], y_vol[~val_mask]
        X_val_b, y_val_b = X_vol[val_mask], y_vol[val_mask]
        if len(X_train_b) < _MIN_TRAIN_ROWS // 2:
            X_train_b, y_train_b = X_vol, y_vol
            X_val_b, y_val_b = X_vol[:0], y_vol[:0]
    else:
        X_train_b, y_train_b = X_vol, y_vol
        X_val_b, y_val_b = X_vol[:0], y_vol[:0]

    return _fit_quantile_set(
        X_train_b, y_train_b, X_val_b, y_val_b,
        huber_delta=huber_delta, log_label="B(volatile)",
    )


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
    """Load cached Model A (current production) or train a new one.

    target_date is the d+1 prediction target (model trains on data through target_date - 1).
    Returns model dict with 'point', 'low', 'high', 'q_hat' keys, or None on failure.
    """
    models = _load_cached(area, target_date, variant="A")
    if models is None:
        models = _train_model(db, target_date, area)
        if models is None:
            return None
        _save_cache(area, target_date, models, variant="A")

    # Support both old (single model) and new (dict) cache format
    if not isinstance(models, dict):
        models = {"point": models, "low": None, "high": None, "q_hat": 0.0}

    return models


def get_or_train_volatile_model(db: Session, target_date: date, area: str = "SE3") -> dict | None:
    """Load cached Model B (volatile specialist) or train a new one.

    Same window as Model A but trained on volatile-only days. Returns the same
    structure as get_or_train_model() so predict_with_model() works unchanged.
    """
    models = _load_cached(area, target_date, variant="B")
    if models is None:
        models = _train_volatile_model(db, target_date, area)
        if models is None:
            return None
        _save_cache(area, target_date, models, variant="B")
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

    # SHAP explanations (point model only)
    try:
        explanations = _compute_shap_explanations(point_model, X_pred)
    except Exception:
        logger.warning("SHAP computation failed, skipping explanations", exc_info=True)
        explanations = None

    valid = [(s["low_sek_kwh"], s["avg_sek_kwh"], s["high_sek_kwh"]) for s in slots]
    result = {
        "slots": slots,
        "summary": {
            "predicted_avg_sek_kwh": round(sum(v[1] for v in valid) / len(valid), 4),
            "predicted_low_sek_kwh": round(min(v[0] for v in valid), 4),
            "predicted_high_sek_kwh": round(max(v[2] for v in valid), 4),
        },
    }
    if explanations is not None:
        result["explanations"] = explanations
    return result


def _blend_forecasts(forecast_a: dict, forecast_b: dict, p: float) -> dict:
    """Soft-blend two 24h LightGBM forecasts: out = (1-p)*A + p*B.

    Blends point, low, and high jointly so the prediction interval scales
    proportionally with the volatility prior. SHAP and metadata come from A.
    """
    blended_slots = []
    for slot_a, slot_b in zip(forecast_a["slots"], forecast_b["slots"]):
        a_avg = slot_a.get("avg_sek_kwh")
        b_avg = slot_b.get("avg_sek_kwh")
        a_lo = slot_a.get("low_sek_kwh")
        b_lo = slot_b.get("low_sek_kwh")
        a_hi = slot_a.get("high_sek_kwh")
        b_hi = slot_b.get("high_sek_kwh")
        slot = {"hour": slot_a["hour"]}
        slot["avg_sek_kwh"] = (
            round((1 - p) * a_avg + p * b_avg, 4) if a_avg is not None and b_avg is not None else a_avg
        )
        slot["low_sek_kwh"] = (
            round(max(0.0, (1 - p) * a_lo + p * b_lo), 4) if a_lo is not None and b_lo is not None else a_lo
        )
        slot["high_sek_kwh"] = (
            round((1 - p) * a_hi + p * b_hi, 4) if a_hi is not None and b_hi is not None else a_hi
        )
        blended_slots.append(slot)

    valid = [(s["low_sek_kwh"], s["avg_sek_kwh"], s["high_sek_kwh"]) for s in blended_slots if s["avg_sek_kwh"] is not None]
    summary = {
        "predicted_avg_sek_kwh": round(sum(v[1] for v in valid) / len(valid), 4) if valid else None,
        "predicted_low_sek_kwh": round(min(v[0] for v in valid), 4) if valid else None,
        "predicted_high_sek_kwh": round(max(v[2] for v in valid), 4) if valid else None,
    }
    out = {"slots": blended_slots, "summary": summary, "ensemble_p": round(p, 4)}
    if "explanations" in forecast_a:
        out["explanations"] = forecast_a["explanations"]
    return out


def build_lgbm_forecast(
    db: Session,
    target_date: date,
    area: str = "SE3",
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> dict:
    """Generate a 24-hour price forecast using LightGBM.

    Convenience wrapper around get_or_train_model() + predict_with_model().
    For multi-horizon forecasting, use those functions directly to avoid retraining.

    When LGBM_USE_ENSEMBLE=1, falls through to the M soft-blend path.
    """
    if os.environ.get("LGBM_USE_ENSEMBLE") == "1":
        ensemble = build_lgbm_forecast_ensemble(db, target_date, area, price_overrides=price_overrides)
        if ensemble is not None:
            return ensemble
        # graceful fallback to Model A on ensemble failure
        logger.warning("Ensemble path failed for %s/%s, falling back to Model A", area, target_date)

    models = get_or_train_model(db, target_date, area)
    if models is None:
        return _NULL_RESPONSE
    return predict_with_model(models, db, target_date, area, price_overrides=price_overrides)


def build_lgbm_forecast_ensemble(
    db: Session,
    target_date: date,
    area: str = "SE3",
    price_overrides: dict[tuple[date, int], float] | None = None,
) -> dict | None:
    """M soft-blend forecast: classifier produces p, output = (1-p)*A + p*B.

    Returns None if any component fails so the caller can decide whether to
    fall back to plain Model A.
    """
    from app.services.regime_classifier_service import (
        get_or_train_classifier,
        predict_volatility,
    )

    model_a = get_or_train_model(db, target_date, area)
    if model_a is None:
        return None
    forecast_a = predict_with_model(model_a, db, target_date, area, price_overrides=price_overrides)
    if forecast_a is _NULL_RESPONSE or forecast_a["summary"]["predicted_avg_sek_kwh"] is None:
        return None

    classifier = get_or_train_classifier(db, target_date, area)
    if classifier is None:
        return None

    p = predict_volatility(
        db,
        target_date,
        area,
        classifier_bundle=classifier,
        model_a_slots=forecast_a["slots"],
    )
    if p is None:
        return None

    model_b = get_or_train_volatile_model(db, target_date, area)
    if model_b is None:
        return None
    forecast_b = predict_with_model(model_b, db, target_date, area, price_overrides=price_overrides)
    if forecast_b is _NULL_RESPONSE or forecast_b["summary"]["predicted_avg_sek_kwh"] is None:
        return None

    logger.info("Ensemble blend: p=%.3f for %s/%s", p, area, target_date)
    return _blend_forecasts(forecast_a, forecast_b, p)


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
            models,
            db,
            target,
            area,
            price_overrides=cumulative_overrides if horizon > 1 else None,
        )

        results.append(
            {
                "horizon": horizon,
                "target_date": target,
                "forecast": forecast,
            }
        )

        # Accumulate predictions for next horizon's lag features
        for slot in forecast["slots"]:
            if slot.get("avg_sek_kwh") is not None:
                cumulative_overrides[(target, slot["hour"])] = slot["avg_sek_kwh"]

    return results
