"""
Feature coverage analysis — how much of the feature matrix is NULL?

Measures NULL rate per feature over the last N days, identifies the
worst-covered features, and cross-references with per-day forecast MAE
to see if coverage gaps correlate with model blow-ups.

Usage:
    python -m scripts.feature_coverage
    python -m scripts.feature_coverage --days 90 --model lgbm
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.feature_service import FEATURE_COLS, TARGET_COL, build_feature_matrix
from app.services.ml_forecast_service import SHAP_GROUPS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)

_FEAT_TO_GROUP = {f: g for g, feats in SHAP_GROUPS.items() for f in feats}


def _per_day_mae(db, area: str, model: str, start: date, end: date) -> dict[date, float]:
    """Average daily MAE from forecast_accuracy."""
    rows = db.execute(
        text(
            """
            SELECT target_date, AVG(ABS(predicted_sek_kwh - actual_sek_kwh))::float AS mae
            FROM forecast_accuracy
            WHERE area = :area AND model_name = :model
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date <= :end
            GROUP BY target_date
            """
        ),
        {"area": area, "model": model, "start": start, "end": end},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--model", default="lgbm")
    args = parser.parse_args()

    end_date = date.today()
    start_date = end_date - timedelta(days=args.days)

    db = SessionLocal()
    try:
        log.info("Loading feature matrix %s..%s...", start_date, end_date)
        rows = build_feature_matrix(db, start_date, end_date, area=args.area)
        log.info("Loaded %d hourly rows (%d days)", len(rows), args.days)

        # Per-feature NULL count
        null_count: dict[str, int] = defaultdict(int)
        total_count = len(rows)
        for r in rows:
            for f in FEATURE_COLS:
                if r.get(f) is None:
                    null_count[f] += 1

        # Per-day NULL count (how many of the 61 features are NULL for each day)
        per_day_nulls: dict[date, list[int]] = defaultdict(list)  # list of per-hour null counts
        for r in rows:
            d = r.get("date")
            if d is None:
                continue
            nulls = sum(1 for f in FEATURE_COLS if r.get(f) is None)
            per_day_nulls[d].append(nulls)

        # Daily average of per-hour NULL counts
        daily_null_avg = {d: float(np.mean(vals)) for d, vals in per_day_nulls.items()}

        # Daily MAE for correlation
        daily_mae = _per_day_mae(db, args.area, args.model, start_date, end_date)

        # Print per-feature NULL rate, sorted
        print()
        print("=" * 84)
        print(f"  FEATURE NULL RATE — last {args.days} days ({total_count} hourly rows)")
        print("=" * 84)
        print(f"  {'#':>3}  {'Feature':<32} {'Group':<20} {'NULL %':>8} {'NULL count':>12}")
        print("-" * 84)
        ranked = sorted(
            FEATURE_COLS,
            key=lambda f: null_count.get(f, 0),
            reverse=True,
        )
        for i, f in enumerate(ranked, 1):
            nc = null_count.get(f, 0)
            rate = nc / total_count * 100 if total_count else 0
            if nc == 0:
                continue  # hide fully-populated features for signal
            print(f"  {i:>3}  {f:<32} {_FEAT_TO_GROUP.get(f, 'Other'):<20} "
                  f"{rate:>7.2f}  {nc:>12}")
        print("-" * 84)
        fully = sum(1 for f in FEATURE_COLS if null_count.get(f, 0) == 0)
        partial = sum(1 for f in FEATURE_COLS if 0 < null_count.get(f, 0) < total_count)
        all_null = sum(1 for f in FEATURE_COLS if null_count.get(f, 0) == total_count)
        print(f"  fully-populated: {fully}    partial-null: {partial}    all-null: {all_null}")

        # Group-level coverage
        group_totals: dict[str, dict] = defaultdict(lambda: {"null": 0, "total": 0, "features": 0})
        for f in FEATURE_COLS:
            g = _FEAT_TO_GROUP.get(f, "Other")
            group_totals[g]["null"] += null_count.get(f, 0)
            group_totals[g]["total"] += total_count
            group_totals[g]["features"] += 1

        print()
        print("=" * 84)
        print("  GROUP-LEVEL NULL RATE")
        print("=" * 84)
        print(f"  {'Group':<20} {'N feats':>8} {'NULL %':>8}")
        print("-" * 84)
        for g, v in sorted(group_totals.items(), key=lambda kv: kv[1]["null"], reverse=True):
            rate = v["null"] / v["total"] * 100 if v["total"] else 0
            print(f"  {g:<20} {v['features']:>8} {rate:>7.2f}")
        print("-" * 84)

        # Worst 10 days by NULL avg
        worst_nulls = sorted(daily_null_avg.items(), key=lambda kv: kv[1], reverse=True)[:10]
        print()
        print("=" * 84)
        print(f"  TOP 10 DAYS BY NULL FEATURES (avg NULL per hour)")
        print("=" * 84)
        print(f"  {'Date':<12} {'NULL/hr':>8} {'MAE':>8}")
        print("-" * 84)
        for d, n in worst_nulls:
            mae = daily_mae.get(d)
            mae_str = f"{mae:.4f}" if mae is not None else "    -"
            print(f"  {d}  {n:>7.2f}  {mae_str}")
        print("-" * 84)

        # Correlation: is there overlap between high-NULL days and high-MAE days?
        paired = [(daily_null_avg[d], daily_mae[d]) for d in daily_null_avg if d in daily_mae]
        if len(paired) >= 5:
            nulls_arr = np.array([p[0] for p in paired])
            mae_arr = np.array([p[1] for p in paired])
            corr = float(np.corrcoef(nulls_arr, mae_arr)[0, 1])
            print()
            print(f"  Correlation (null_count_per_hour vs daily_mae): {corr:+.3f}  "
                  f"(n={len(paired)} days)")
            if corr > 0.3:
                print("  → Strong positive: data gaps DRIVE the MAE blow-ups")
            elif corr < -0.2:
                print("  → Negative: MAE blow-ups happen on days with MORE data. "
                      "Not a coverage problem.")
            else:
                print("  → Weak correlation: coverage and MAE are largely independent. "
                      "MAE spikes are likely regime shifts, not data gaps.")
            print()

        # Worst MAE days, with their NULL status
        if daily_mae:
            worst_mae = sorted(daily_mae.items(), key=lambda kv: kv[1], reverse=True)[:10]
            print("=" * 84)
            print("  TOP 10 DAYS BY MAE — with NULL feature count")
            print("=" * 84)
            print(f"  {'Date':<12} {'MAE':>8} {'NULL/hr':>8}")
            print("-" * 84)
            for d, m in worst_mae:
                nulls = daily_null_avg.get(d, float("nan"))
                print(f"  {d}  {m:>7.4f}  {nulls:>7.2f}")
            print("=" * 84)

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
