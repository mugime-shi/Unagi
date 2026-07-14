"""
Print the three product-level evaluation metrics per area:
regime-split MAE, cheapest-hours capture rate, interval coverage by regime.

Reads forecast_accuracy only — run it against synced production history or
after a backtest. Regime tagging needs same_weekday_avg rows in the window
(production records them nightly; scripts/run_backtest.py records them too,
but run_backtest_horizon.py does not).

Usage:
    python -m scripts.eval_report                        # 90 days, SE3, lgbm
    python -m scripts.eval_report --days 90 --area all
    python -m scripts.eval_report --area SE4 --model lgbm_d2 --threshold 0.35
"""

import argparse
import sys

from app.db.database import SessionLocal
from app.services.evaluation_service import (
    get_capture_rate,
    get_coverage_by_regime,
    get_regime_split,
)

ALL_AREAS = ["SE1", "SE2", "SE3", "SE4"]


def _fmt(value, spec: str = ".4f", none: str = "     -") -> str:
    return format(value, spec) if value is not None else none


def print_report(db, area: str, days: int, model: str, threshold: float) -> None:
    """Print regime/capture/coverage block for one area. Reused by run_backtest."""
    regime = get_regime_split(db, area=area, days=days, model=model, threshold=threshold)
    capture = get_capture_rate(db, area=area, days=days, model=model)
    capture_base = get_capture_rate(db, area=area, days=days, model=regime["baseline"])
    coverage = get_coverage_by_regime(db, area=area, days=days, model=model, threshold=threshold)

    print()
    print("=" * 72)
    print(f"  EVALUATION — area={area}, model={model}, last {days} days")
    print(f"  Regime threshold: baseline daily MAE >= {threshold} → volatile")
    print("=" * 72)

    print(f"  [Regime-split MAE]  ({regime['n_days']} days tagged)")
    print(f"  {'regime':<10} {'days':>5} {'model MAE':>11} {'base MAE':>10} {'win rate':>10}")
    for name in ("calm", "volatile"):
        r = regime[name]
        win = f"{r['win_rate'] * 100:.0f}%" if r["win_rate"] is not None else "-"
        print(
            f"  {name:<10} {r['n_days']:>5} {_fmt(r['model_mae']):>11} {_fmt(r['baseline_mae']):>10} {win:>10}"
        )

    print("-" * 72)
    print(f"  [Capture rate]  (cheapest {capture['n_hours']}h, {capture['n_days']} days scored)")
    for c in (capture, capture_base):
        mean_pct = f"{c['mean_capture'] * 100:.0f}%" if c["mean_capture"] is not None else "-"
        med_pct = f"{c['median_capture'] * 100:.0f}%" if c["median_capture"] is not None else "-"
        print(
            f"  {c['model']:<18} mean {mean_pct:>5}  median {med_pct:>5}"
            f"  (flat days skipped: {c['n_days_skipped_flat']},"
            f" avg spread: {_fmt(c['mean_daily_spread_sek_kwh'])} SEK/kWh)"
        )

    print("-" * 72)
    print(f"  [Interval coverage]  (expected {coverage['expected_pct']:.0f}%)")
    for name in ("overall", "calm", "volatile"):
        c = coverage[name]
        pct = f"{c['coverage_pct']:.1f}%" if c["coverage_pct"] is not None else "-"
        print(f"  {name:<10} {pct:>7}  (n={c['n_samples']})")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regime/capture/coverage evaluation report")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--area", default="SE3", help="SE1-SE4 or 'all'")
    parser.add_argument("--model", default="lgbm")
    parser.add_argument("--threshold", type=float, default=0.35)
    args = parser.parse_args()

    areas = ALL_AREAS if args.area.lower() == "all" else [args.area]

    db = SessionLocal()
    try:
        for area in areas:
            print_report(db, area, args.days, args.model, args.threshold)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
