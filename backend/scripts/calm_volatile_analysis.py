"""
Split forecast MAE into calm vs volatile periods.

A "volatile day" is one whose daily MAE is above the median daily MAE
for the analysis window (same definition used in scripts/ablation_gas.py).
This reveals how much of the overall MAE is explained by regime.

Usage:
    python -m scripts.calm_volatile_analysis
    python -m scripts.calm_volatile_analysis --days 90 --model lgbm
    python -m scripts.calm_volatile_analysis --days 80 --model lgbm_d2
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def analyze(db, days: int, model: str, area: str) -> dict | None:
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    rows = db.execute(
        text(
            """
            SELECT target_date, hour, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area
              AND model_name = :model
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start
              AND target_date <= :end
            ORDER BY target_date, hour
            """
        ),
        {"area": area, "model": model, "start": start_date, "end": end_date},
    ).fetchall()

    if not rows:
        log.error("No rows for model=%s area=%s in last %d days", model, area, days)
        return None

    # Group errors by day
    by_day: dict[date, list[float]] = defaultdict(list)
    for target_date_, hour, pred, actual in rows:
        abs_err = abs(float(pred) - float(actual))
        by_day[target_date_].append(abs_err)

    daily_mae = {d: float(np.mean(errs)) for d, errs in by_day.items()}
    daily_vals = list(daily_mae.values())

    median_mae = float(np.median(daily_vals))
    q25 = float(np.quantile(daily_vals, 0.25))
    q75 = float(np.quantile(daily_vals, 0.75))
    q90 = float(np.quantile(daily_vals, 0.90))

    # Classify & aggregate hourly errors
    calm_errs: list[float] = []
    volatile_errs: list[float] = []
    calm_days = []
    volatile_days = []
    for d, errs in by_day.items():
        if daily_mae[d] <= median_mae:
            calm_errs.extend(errs)
            calm_days.append((d, daily_mae[d]))
        else:
            volatile_errs.extend(errs)
            volatile_days.append((d, daily_mae[d]))

    # Worst 5 days
    worst = sorted(daily_mae.items(), key=lambda kv: kv[1], reverse=True)[:5]
    best = sorted(daily_mae.items(), key=lambda kv: kv[1])[:5]

    return {
        "window": (start_date, end_date),
        "model": model,
        "area": area,
        "n_days": len(by_day),
        "n_hours": len(rows),
        "overall_mae": float(np.mean([abs(float(p) - float(a)) for _, _, p, a in rows])),
        "median_daily_mae": median_mae,
        "q25_daily_mae": q25,
        "q75_daily_mae": q75,
        "q90_daily_mae": q90,
        "calm": {
            "n_days": len(calm_days),
            "n_hours": len(calm_errs),
            "mae": float(np.mean(calm_errs)) if calm_errs else None,
        },
        "volatile": {
            "n_days": len(volatile_days),
            "n_hours": len(volatile_errs),
            "mae": float(np.mean(volatile_errs)) if volatile_errs else None,
        },
        "worst_5": worst,
        "best_5": best,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--model", default="lgbm")
    parser.add_argument("--area", default="SE3")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        out = analyze(db, args.days, args.model, args.area)
    finally:
        db.close()

    if not out:
        return 1

    w_start, w_end = out["window"]
    print()
    print("=" * 76)
    print(f"  CALM / VOLATILE SPLIT — model={out['model']}, area={out['area']}")
    print(f"  Window: {w_start} .. {w_end}  ({out['n_days']} days, {out['n_hours']} hours)")
    print("=" * 76)
    print(f"  Overall MAE:      {out['overall_mae']:.4f}")
    print(f"  Median daily MAE: {out['median_daily_mae']:.4f}  (split threshold)")
    print(f"  Q25 / Q75 / Q90 daily MAE: {out['q25_daily_mae']:.4f} / "
          f"{out['q75_daily_mae']:.4f} / {out['q90_daily_mae']:.4f}")
    print("-" * 76)
    print(f"  Calm     days ({out['calm']['n_days']}): "
          f"MAE = {out['calm']['mae']:.4f}   "
          f"({out['calm']['n_hours']} hours)")
    print(f"  Volatile days ({out['volatile']['n_days']}): "
          f"MAE = {out['volatile']['mae']:.4f}   "
          f"({out['volatile']['n_hours']} hours)")
    print(f"  Gap:              {out['volatile']['mae'] - out['calm']['mae']:.4f}  "
          f"({(out['volatile']['mae'] / out['calm']['mae'] - 1) * 100:+.1f}%)")
    print("-" * 76)
    print("  Best 5 days (lowest daily MAE):")
    for d, v in out["best_5"]:
        print(f"    {d}  MAE={v:.4f}")
    print("  Worst 5 days (highest daily MAE):")
    for d, v in out["worst_5"]:
        print(f"    {d}  MAE={v:.4f}")
    print("=" * 76)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
