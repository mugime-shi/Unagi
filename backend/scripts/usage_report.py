"""
Usage report from first-party usage_events.

    ./unagi usage --days 30
"""

import argparse

from app.db.database import SessionLocal
from app.services.usage_service import RETURN_WINDOW_DAYS, summarize_usage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        s = summarize_usage(db, days=args.days)
    finally:
        db.close()

    total_new = sum(n for n, _ in s.visits_by_day.values())
    total_ret = sum(r for _, r in s.visits_by_day.values())
    print(f"Usage {s.start} .. {s.end} (Europe/Stockholm)")
    print(f"  visits: {total_new + total_ret}  (new {total_new} / returning {total_ret})")
    if s.return_rate is None:
        print(
            f"  {RETURN_WINDOW_DAYS}-day return rate: n/a (no cohort with a complete {RETURN_WINDOW_DAYS}-day window)"
        )
    else:
        print(
            f"  {RETURN_WINDOW_DAYS}-day return rate: {s.return_rate:.1%}"
            f"  ({s.cohort_returned}/{s.cohort_size} first-time visitors came back)"
        )

    print("\nDaily visits (new / returning)")
    for day, (new, ret) in s.visits_by_day.items():
        print(f"  {day}  {new:4d} / {ret:4d}  {'#' * (new + ret)}")

    print("\nReferrers")
    for label, n in s.referrers.most_common(10):
        print(f"  {n:5d}  {label}")

    for event, counts in sorted(s.views.items()):
        print(f"\n{event}")
        for label, n in counts.most_common():
            print(f"  {n:5d}  {label}")


if __name__ == "__main__":
    main()
