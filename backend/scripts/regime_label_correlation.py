"""
Investigate whether actual-price volatility metrics can proxy daily LGBM MAE.

If `daily_price_range`, `daily_std`, or similar correlate strongly with the
daily forecast MAE (from forecast_accuracy, model=lgbm), we can use those
proxies to label a longer history (365 days of spot_prices) for the regime
classifier — even for days when no production forecast exists.

Outputs:
  - Pearson & Spearman correlation of candidate price stats vs daily MAE
  - Label agreement (median-split) between MAE-based and proxy-based labels
  - Suggested proxy threshold that maximizes label overlap
"""

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.db.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def daily_mae(db, days: int, area: str, model: str) -> dict[date, float]:
    end = date.today()
    start = end - timedelta(days=days)
    rows = db.execute(
        text(
            """
            SELECT target_date, hour, predicted_sek_kwh, actual_sek_kwh
            FROM forecast_accuracy
            WHERE area = :area AND model_name = :model
              AND actual_sek_kwh IS NOT NULL
              AND target_date >= :start AND target_date <= :end
            """
        ),
        {"area": area, "model": model, "start": start, "end": end},
    ).fetchall()
    by_day = defaultdict(list)
    for target_date_, _, pred, actual in rows:
        by_day[target_date_].append(abs(float(pred) - float(actual)))
    return {d: float(np.mean(errs)) for d, errs in by_day.items()}


def daily_price_stats(db, start: date, end: date, area: str) -> dict[date, dict]:
    """Compute daily stats from spot_prices for the given window."""
    # Aggregate PT15M/PT60M to hourly, then compute daily stats.
    rows = db.execute(
        text(
            """
            SELECT
              (hour_local)::date AS day,
              AVG(price_sek_kwh) AS price
            FROM (
              SELECT
                date_trunc('hour', timestamp_utc AT TIME ZONE 'Europe/Stockholm')
                  AS hour_local,
                price_sek_kwh
              FROM spot_prices
              WHERE area = :area
                AND timestamp_utc >= :start
                AND timestamp_utc < :end_excl
                AND price_sek_kwh IS NOT NULL
            ) t
            GROUP BY hour_local
            ORDER BY hour_local
            """
        ),
        {"area": area, "start": start, "end_excl": end + timedelta(days=1)},
    ).fetchall()
    by_day: dict[date, list[float]] = defaultdict(list)
    for d, p in rows:
        by_day[d].append(float(p))

    stats = {}
    # Need sorted days to compute day-over-day changes
    sorted_days = sorted(by_day.keys())
    prev_mean = None
    for d in sorted_days:
        prices = by_day[d]
        if len(prices) < 20:  # incomplete day (DST or missing)
            continue
        arr = np.array(prices)
        diffs = np.abs(np.diff(arr))
        daily_range = float(arr.max() - arr.min())
        daily_std = float(arr.std())
        daily_mean = float(arr.mean())
        h2h_mean = float(diffs.mean()) if len(diffs) > 0 else 0.0
        h2h_max = float(diffs.max()) if len(diffs) > 0 else 0.0
        stats[d] = {
            "range": daily_range,
            "std": daily_std,
            "mean": daily_mean,
            "h2h_mean": h2h_mean,
            "h2h_max": h2h_max,
            "day_over_day_change": abs(daily_mean - prev_mean) if prev_mean is not None else 0.0,
            "cv": daily_std / daily_mean if daily_mean > 0.01 else 0.0,
        }
        prev_mean = daily_mean
    return stats


def correlation(x: list[float], y: list[float]) -> tuple[float, float]:
    """Return (pearson, spearman) correlation coefficients."""
    if len(x) < 2:
        return 0.0, 0.0
    xa, ya = np.array(x), np.array(y)
    pearson = float(np.corrcoef(xa, ya)[0, 1])
    # Spearman via rank
    xr = np.argsort(np.argsort(xa))
    yr = np.argsort(np.argsort(ya))
    spearman = float(np.corrcoef(xr, yr)[0, 1])
    return pearson, spearman


def label_agreement(mae_by_day: dict[date, float], stat_by_day: dict[date, float]) -> dict:
    """Compare median-split labels: how often do MAE-labels and stat-labels agree?"""
    common = sorted(set(mae_by_day) & set(stat_by_day))
    if len(common) < 4:
        return {"n_common": len(common), "agreement": None}
    mae_vals = [mae_by_day[d] for d in common]
    stat_vals = [stat_by_day[d] for d in common]
    mae_median = float(np.median(mae_vals))
    stat_median = float(np.median(stat_vals))
    mae_labels = [1 if v > mae_median else 0 for v in mae_vals]
    stat_labels = [1 if v > stat_median else 0 for v in stat_vals]
    agree = sum(1 for a, b in zip(mae_labels, stat_labels) if a == b)
    # Also compute precision/recall for "volatile" class
    tp = sum(1 for a, b in zip(mae_labels, stat_labels) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(mae_labels, stat_labels) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(mae_labels, stat_labels) if a == 1 and b == 0)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "n_common": len(common),
        "agreement": agree / len(common),
        "mae_median": mae_median,
        "stat_median": stat_median,
        "precision_volatile": precision,
        "recall_volatile": recall,
        "f1_volatile": f1,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--area", default="SE3")
    parser.add_argument("--model", default="lgbm")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mae = daily_mae(db, args.days, args.area, args.model)
        if not mae:
            log.error("No MAE data in last %d days", args.days)
            return 1
        w_start = min(mae)
        w_end = max(mae)
        stats = daily_price_stats(db, w_start, w_end, args.area)
    finally:
        db.close()

    common = sorted(set(mae) & set(stats))
    log.info("MAE days: %d, stat days: %d, common: %d", len(mae), len(stats), len(common))
    if len(common) < 10:
        log.error("Not enough overlapping days")
        return 1

    print()
    print("=" * 78)
    print(f"  REGIME LABEL CORRELATION — model={args.model}, area={args.area}")
    print(f"  Window: {w_start} → {w_end}  ({len(common)} days with both MAE & price stats)")
    print("=" * 78)
    print(f"  {'Stat':<22} {'Pearson r':>10} {'Spearman':>10} "
          f"{'Agreement':>10} {'F1':>6} {'P':>6} {'R':>6}")
    print("-" * 78)

    mae_list = [mae[d] for d in common]
    for key in ["range", "std", "h2h_mean", "h2h_max", "cv", "day_over_day_change", "mean"]:
        stat_list = [stats[d][key] for d in common]
        pearson, spearman = correlation(stat_list, mae_list)
        agree = label_agreement(mae, {d: stats[d][key] for d in common})
        print(
            f"  {key:<22} {pearson:>10.3f} {spearman:>10.3f} "
            f"{agree['agreement']:>10.2%} "
            f"{agree['f1_volatile']:>6.2f} "
            f"{agree['precision_volatile']:>6.2f} "
            f"{agree['recall_volatile']:>6.2f}"
        )

    # Composite: normalized sum of top stats
    print("-" * 78)
    print("  Composite: normalize(range) + normalize(std) + normalize(h2h_mean)")
    composite = {}
    r_vals = np.array([stats[d]["range"] for d in common])
    s_vals = np.array([stats[d]["std"] for d in common])
    h_vals = np.array([stats[d]["h2h_mean"] for d in common])
    def norm(arr):
        lo, hi = arr.min(), arr.max()
        return (arr - lo) / (hi - lo) if hi > lo else np.zeros_like(arr)
    comp_vals = norm(r_vals) + norm(s_vals) + norm(h_vals)
    for d, v in zip(common, comp_vals):
        composite[d] = float(v)
    clist = [composite[d] for d in common]
    pearson, spearman = correlation(clist, mae_list)
    agree = label_agreement(mae, composite)
    print(
        f"  {'composite':<22} {pearson:>10.3f} {spearman:>10.3f} "
        f"{agree['agreement']:>10.2%} "
        f"{agree['f1_volatile']:>6.2f} "
        f"{agree['precision_volatile']:>6.2f} "
        f"{agree['recall_volatile']:>6.2f}"
    )
    print("=" * 78)

    # Top 5 volatile-by-MAE days
    top5 = sorted(common, key=lambda d: mae[d], reverse=True)[:10]
    print()
    print("  Top 10 MAE days: is the proxy picking them up?")
    print(f"  {'Date':<12} {'MAE':>8} {'range':>8} {'std':>8} {'h2h':>8} {'composite':>10}")
    for d in top5:
        s = stats[d]
        print(
            f"  {d!s:<12} {mae[d]:>8.4f} {s['range']:>8.3f} {s['std']:>8.3f} "
            f"{s['h2h_mean']:>8.3f} {composite[d]:>10.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
