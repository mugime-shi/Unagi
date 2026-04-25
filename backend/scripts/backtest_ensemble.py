"""
Phase 4 of M ensemble: head-to-head backtest of soft-blend vs Model A.

Iterates over the last N days with actuals available, computes both
build_lgbm_forecast (Model A) and build_lgbm_forecast_ensemble (M soft-blend),
and compares MAE without writing to forecast_accuracy.

Pass criteria (from handover):
    Overall  MAE: 0.2197 → ≤ 0.21  (3% improvement)
    Volatile MAE: 0.2540 → ≤ 0.24  (5% improvement)

Volatile / calm split uses the same median-MAE rule as the classifier labels.

Usage:
    docker exec unagi-api-1 python -m scripts.backtest_ensemble --days 90
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.ml_forecast_service import (
    build_lgbm_forecast_ensemble,
    get_or_train_model,
    predict_with_model,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


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


def get_production_mae_labels(db, days: int, area: str) -> dict[date, float]:
    end = date.today()
    start = end - timedelta(days=days)
    rows = db.execute(
        text(
            """
            SELECT target_date, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = 'lgbm'
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"area": area, "start": start, "end": end},
    ).fetchall()
    by_day: dict[date, list[float]] = defaultdict(list)
    for d, pred, actual in rows:
        by_day[d].append(abs(float(pred) - float(actual)))
    return {d: float(np.mean(errs)) for d, errs in by_day.items() if len(errs) >= 20}


def predict_a_only(db, target_date: date, area: str) -> dict | None:
    models = get_or_train_model(db, target_date, area)
    if models is None:
        return None
    return predict_with_model(models, db, target_date, area)


def err_for_slots(slots: list[dict], actuals: dict[int, float]) -> list[float] | None:
    errs = []
    for s in slots:
        h = s["hour"]
        avg = s.get("avg_sek_kwh")
        if avg is None or h not in actuals:
            continue
        errs.append(abs(avg - actuals[h]))
    return errs if errs else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Backtest window")
    parser.add_argument("--area", default="SE3")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        end_day = date.today() - timedelta(days=1)
        start_day = end_day - timedelta(days=args.days - 1)

        # Use production MAE labels to split calm/volatile target days
        labels_mae = get_production_mae_labels(db, args.days + 5, args.area)
        if not labels_mae:
            log.error("no production MAE labels in window")
            return 1
        median_mae = float(np.median(list(labels_mae.values())))
        log.info(
            "Backtest window: %s..%s  area=%s  median_MAE=%.4f",
            start_day,
            end_day,
            args.area,
            median_mae,
        )

        results = []
        for offset in range(args.days):
            d = start_day + timedelta(days=offset)
            actuals = get_actuals_for_day(db, d, args.area)
            if not actuals or len(actuals) < 20:
                continue

            try:
                forecast_a = predict_a_only(db, d, args.area)
            except Exception as exc:
                log.warning("[%s] Model A failed: %s", d, exc)
                continue
            if forecast_a is None:
                continue

            try:
                forecast_e = build_lgbm_forecast_ensemble(db, d, args.area)
            except Exception as exc:
                log.warning("[%s] ensemble failed: %s", d, exc)
                forecast_e = None

            errs_a = err_for_slots(forecast_a["slots"], actuals)
            if errs_a is None:
                continue
            mae_a = float(np.mean(errs_a))

            mae_e = None
            p_used = None
            if forecast_e is not None:
                errs_e = err_for_slots(forecast_e["slots"], actuals)
                if errs_e is not None:
                    mae_e = float(np.mean(errs_e))
                    p_used = forecast_e.get("ensemble_p")

            is_volatile = bool(labels_mae.get(d, 0.0) > median_mae)
            results.append(
                {
                    "date": d,
                    "n_hours": len(errs_a),
                    "mae_a": mae_a,
                    "mae_e": mae_e,
                    "p": p_used,
                    "volatile": is_volatile,
                }
            )
            tag = "vol" if is_volatile else "calm"
            if mae_e is not None and p_used is not None:
                log.info(
                    "[%s] %s  A=%.4f  E=%.4f  Δ=%+.4f (%+.1f%%)  p=%.2f",
                    d,
                    tag,
                    mae_a,
                    mae_e,
                    mae_e - mae_a,
                    (mae_e / mae_a - 1) * 100 if mae_a > 0 else 0.0,
                    p_used,
                )
            else:
                log.info("[%s] %s  A=%.4f  E=N/A", d, tag, mae_a)
    finally:
        db.close()

    if not results:
        log.error("no results")
        return 1

    have_e = [r for r in results if r["mae_e"] is not None]
    vol_results = [r for r in have_e if r["volatile"]]
    calm_results = [r for r in have_e if not r["volatile"]]

    def agg(rows, key):
        total = sum(r[key] * r["n_hours"] for r in rows)
        n = sum(r["n_hours"] for r in rows)
        return total / n if n else 0.0

    overall_a = agg(have_e, "mae_a")
    overall_e = agg(have_e, "mae_e")
    vol_a = agg(vol_results, "mae_a")
    vol_e = agg(vol_results, "mae_e")
    calm_a = agg(calm_results, "mae_a")
    calm_e = agg(calm_results, "mae_e")

    wins_e = sum(1 for r in have_e if r["mae_e"] < r["mae_a"])
    wins_e_vol = sum(1 for r in vol_results if r["mae_e"] < r["mae_a"])

    print()
    print("=" * 78)
    print(f"  BACKTEST_ENSEMBLE — area={args.area}  days={args.days}")
    print(f"  Days with both A & E: {len(have_e)}  ({sum(r['n_hours'] for r in have_e)} hourly preds)")
    print("-" * 78)
    print(f"  Overall   MAE   A = {overall_a:.4f}   E = {overall_e:.4f}   Δ = {(overall_e/overall_a-1)*100:+.1f}%")
    print(f"  Volatile  MAE   A = {vol_a:.4f}   E = {vol_e:.4f}   Δ = {(vol_e/vol_a-1)*100:+.1f}%   "
          f"(n={len(vol_results)} days, E-wins {wins_e_vol}/{len(vol_results)})")
    print(f"  Calm      MAE   A = {calm_a:.4f}   E = {calm_e:.4f}   Δ = {(calm_e/calm_a-1)*100:+.1f}%   "
          f"(n={len(calm_results)} days)")
    print("-" * 78)
    print(f"  Pass criteria:  Overall ≤ 0.21  AND/OR  Volatile ≤ 0.24")
    overall_ok = overall_e <= 0.21
    vol_ok = vol_e <= 0.24
    if overall_ok and vol_ok:
        print(f"  → PASS — both targets met")
    elif overall_ok:
        print(f"  → PARTIAL PASS — overall met, volatile not")
    elif vol_ok:
        print(f"  → PARTIAL PASS — volatile met, overall not")
    else:
        print(f"  → FAIL — neither target met")
    print(f"  Ensemble wins on {wins_e}/{len(have_e)} days overall")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
