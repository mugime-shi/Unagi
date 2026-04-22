"""
Deep-dive SHAP analysis for a single "worst day" to understand what
signal the model missed. Trains a fresh model through the day BEFORE
the target, predicts the target, and shows per-hour predicted vs actual
with SHAP top-5 feature-group attributions.

Usage:
    python -m scripts.worst_day_analysis --date 2026-02-10
    python -m scripts.worst_day_analysis --date 2026-02-19 --area SE3
"""

import argparse
import logging
from datetime import date, timedelta

import numpy as np

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix
from app.services.ml_forecast_service import (
    SHAP_GROUPS,
    _compute_shap_explanations,
    _train_model,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

_FEAT_TO_GROUP = {f: g for g, feats in SHAP_GROUPS.items() for f in feats}


def _parse_date(s: str) -> date:
    y, m, d = [int(p) for p in s.split("-")]
    return date(y, m, d)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--compare-days", type=int, default=7,
                        help="Show feature trend over N prior days")
    args = parser.parse_args()

    target = _parse_date(args.date)

    db = SessionLocal()
    try:
        log.info("Training model through %s (day before target %s)...",
                 target - timedelta(days=1), target)
        models = _train_model(db, target, args.area, huber_delta=1.0)
        if models is None:
            log.error("Training failed (insufficient data)")
            return 1

        # Build features for target day
        rows = build_feature_matrix(db, target, target, area=args.area)
        if not rows:
            log.error("No feature rows for %s", target)
            return 1

        X = np.array([[r.get(c) for c in FEATURE_COLS] for r in rows], dtype=object)
        X = np.where(X == None, np.nan, X).astype(np.float64)  # noqa: E711

        point = models["point"]
        low = models["low"]
        high = models["high"]
        q_hat = models.get("q_hat", 0.0)

        preds = point.predict(X)
        low_preds = low.predict(X) - q_hat
        high_preds = high.predict(X) + q_hat

        actuals = [r.get(TARGET_COL) for r in rows]
        hours = [int(r["hour"]) for r in rows]

        # Per-hour table
        print()
        print("=" * 98)
        print(f"  WORST DAY ANALYSIS — {target}, area={args.area}")
        print("=" * 98)
        print(f"  {'h':>3}  {'pred':>8}  {'low':>8}  {'high':>8}  {'actual':>8}  "
              f"{'err':>9}  {'in_band':>8}  {'null_feats':>10}")
        print("-" * 98)
        total_err = 0.0
        in_band = 0
        for i, hr in enumerate(hours):
            p = float(preds[i])
            lo = float(low_preds[i])
            hi = float(high_preds[i])
            a = actuals[i]
            nulls = sum(1 for f in FEATURE_COLS if rows[i].get(f) is None)
            if a is None:
                a_str = "    -   "
                err_str = "    -    "
                band_str = "   -  "
            else:
                a = float(a)
                err = p - a
                total_err += abs(err)
                band = lo <= a <= hi
                if band:
                    in_band += 1
                a_str = f"{a:>8.4f}"
                err_str = f"{err:>+9.4f}"
                band_str = "  YES " if band else "  NO  "
            print(f"  {hr:>3}  {p:>8.4f}  {lo:>8.4f}  {hi:>8.4f}  "
                  f"{a_str}  {err_str}  {band_str}  {nulls:>10}")
        print("-" * 98)
        n_acts = sum(1 for a in actuals if a is not None)
        if n_acts > 0:
            mae = total_err / n_acts
            print(f"  MAE: {mae:.4f}   Band coverage: {in_band}/{n_acts} = {in_band/n_acts*100:.1f}%")

        # SHAP top-5 per hour for 4 representative hours
        log.info("Computing SHAP...")
        shap_res = _compute_shap_explanations(point, X, top_n=5)
        if shap_res:
            print()
            print("=" * 98)
            print(f"  SHAP TOP-5 PER HOUR (base_value={shap_res['base_value']})")
            print("=" * 98)
            for hour_entry in shap_res["hours"]:
                hr = hour_entry["hour"]
                # Only print a few representative hours
                if hr not in (3, 8, 12, 17, 19):
                    continue
                top = hour_entry["top"]
                p = float(preds[hr])
                a = actuals[hr] if hr < len(actuals) else None
                a_str = f"{float(a):.4f}" if a is not None else "-"
                print(f"  h{hr:02d}  pred={p:.4f}  actual={a_str}")
                for t in top:
                    print(f"    {t['group']:<20} impact={t['impact']:+.4f} ({t['direction']})")
                print()

        # Feature-value comparison: target day vs prior N days
        print("=" * 98)
        print(f"  KEY FEATURE VALUES — target {target} vs prior {args.compare_days} days (hour 12)")
        print("=" * 98)
        key_features = [
            "prev_day_same_hour",
            "rolling_7d_mean",
            "rolling_7d_std",
            "daily_avg_prev_day",
            "daily_max_prev_day",
            "daily_range_prev_day",
            "gas_price_eur_mwh",
            "gas_price_7d_avg",
            "gas_price_change",
            "de_price_prev_day",
            "de_se3_spread_prev_day",
            "load_forecast_max",
            "load_forecast_hour",
            "temp_forecast",
            "wind_speed_10m_fc",
            "wind_speed_100m_fc",
            "bal_up_avg_prev_day",
            "bal_down_avg_prev_day",
        ]

        hdr = "  feature".ljust(32)
        for i in range(args.compare_days, -1, -1):
            d = target - timedelta(days=i)
            hdr += f"{d.month:02d}-{d.day:02d}".rjust(10)
        print(hdr)
        print("-" * 98)

        for feat in key_features:
            line = f"  {feat}".ljust(32)
            for i in range(args.compare_days, -1, -1):
                d = target - timedelta(days=i)
                rows_d = build_feature_matrix(db, d, d, area=args.area)
                if not rows_d:
                    line += "     -   ".rjust(10)
                    continue
                r12 = next((r for r in rows_d if r.get("hour") == 12), None)
                if r12 is None:
                    line += "     -   ".rjust(10)
                    continue
                v = r12.get(feat)
                if v is None:
                    s = "   null"
                elif isinstance(v, float):
                    s = f"{v:.3f}"
                else:
                    s = str(v)
                line += s.rjust(10)
            print(line)
        print("=" * 98)

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
