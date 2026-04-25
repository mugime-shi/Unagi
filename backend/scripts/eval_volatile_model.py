"""
Phase 2 verification: confirm production-grade volatile model reproduces the
+5.6% improvement on volatile target days seen in validate_volatile_model.py.

Differs from validate_volatile_model.py only in that this script calls the
public service functions (get_or_train_model / get_or_train_volatile_model)
so the production code path itself is being exercised. If MAE numbers match
the prior aggregate (A=0.2540, B=0.2398, Δ=-5.6%, B-wins=26/44), Phase 2 is
complete and Phase 3 (soft blend orchestration) can proceed.

Usage:
    docker exec unagi-api-1 python -m scripts.eval_volatile_model --days 90
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.ml_forecast_service import (
    get_or_train_model,
    get_or_train_volatile_model,
    predict_with_model,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="MAE label window")
    parser.add_argument("--area", default="SE3")
    parser.add_argument(
        "--subset",
        default="volatile",
        choices=["volatile", "calm", "all"],
        help="Which target-day subset to evaluate",
    )
    parser.add_argument("--max-days", type=int, default=None, help="Cap target days")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mae = get_production_mae_labels(db, args.days, args.area)
        if not mae:
            log.error("no MAE labels")
            return 1
        median_mae = float(np.median(list(mae.values())))

        if args.subset == "volatile":
            target_days = sorted([d for d, m in mae.items() if m > median_mae])
        elif args.subset == "calm":
            target_days = sorted([d for d, m in mae.items() if m <= median_mae])
        else:
            target_days = sorted(mae.keys())

        if args.max_days:
            target_days = target_days[: args.max_days]

        log.info(
            "running on %d %s target days (median split MAE=%.4f)",
            len(target_days),
            args.subset,
            median_mae,
        )

        results = []
        for i, d in enumerate(target_days, 1):
            log.info("[%d/%d] %s", i, len(target_days), d)

            model_a = get_or_train_model(db, d, area=args.area)
            model_b = get_or_train_volatile_model(db, d, area=args.area)
            if model_a is None or model_b is None:
                log.warning("    skip — model training failed")
                continue

            pred_a = predict_with_model(model_a, db, d, area=args.area)
            pred_b = predict_with_model(model_b, db, d, area=args.area)
            actuals = get_actuals_for_day(db, d, args.area)
            if not actuals:
                log.warning("    skip — no actuals")
                continue

            errs_a = []
            errs_b = []
            for slot_a, slot_b in zip(pred_a["slots"], pred_b["slots"]):
                h = slot_a["hour"]
                if h not in actuals:
                    continue
                a = slot_a.get("avg_sek_kwh")
                b = slot_b.get("avg_sek_kwh")
                if a is None or b is None:
                    continue
                errs_a.append(abs(a - actuals[h]))
                errs_b.append(abs(b - actuals[h]))

            if not errs_a:
                continue
            mae_a = float(np.mean(errs_a))
            mae_b = float(np.mean(errs_b))
            results.append({"date": d, "n_hours": len(errs_a), "mae_a": mae_a, "mae_b": mae_b})
            log.info(
                "    A=%.4f  B=%.4f  Δ=%+.4f (%+.1f%%)",
                mae_a,
                mae_b,
                mae_b - mae_a,
                (mae_b / mae_a - 1) * 100 if mae_a > 0 else 0.0,
            )
    finally:
        db.close()

    if not results:
        log.error("no results")
        return 1

    # Aggregate
    total_a = sum(r["mae_a"] * r["n_hours"] for r in results)
    total_b = sum(r["mae_b"] * r["n_hours"] for r in results)
    total_n = sum(r["n_hours"] for r in results)
    agg_a = total_a / total_n
    agg_b = total_b / total_n
    wins_b = sum(1 for r in results if r["mae_b"] < r["mae_a"])

    print()
    print("=" * 72)
    print(f"  EVAL_VOLATILE_MODEL — subset={args.subset}, area={args.area}")
    print(f"  Days processed: {len(results)}  ({total_n} hourly preds)")
    print("-" * 72)
    print(f"  Model A (production):    MAE = {agg_a:.4f}")
    print(f"  Model B (volatile spec): MAE = {agg_b:.4f}")
    delta = agg_b - agg_a
    pct = (agg_b / agg_a - 1) * 100 if agg_a > 0 else 0.0
    print(f"  Δ = {delta:+.4f}  ({pct:+.1f}%)  |  B wins on {wins_b}/{len(results)} days")
    print("=" * 72)
    print()
    print("  Reference (validate_volatile_model.py @ TRAIN_DAYS=500):")
    print("    A=0.2540  B=0.2398  Δ=-5.6%  B-wins=26/44 days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
