"""
Replay the today-story headline for the last N days (tune thresholds, check rotation).

    ./unagi story --days 30 [--end YYYY-MM-DD]
"""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta

from app.db.database import SessionLocal
from app.services.story_service import build_story, load_story_data
from app.utils.timezone import STOCKHOLM


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last day (default: today)")
    args = parser.parse_args()

    today = datetime.now(STOCKHOLM).date()
    end = args.end or today
    start = end - timedelta(days=args.days - 1)

    db = SessionLocal()
    try:
        data = load_story_data(db, start, end)
    finally:
        db.close()

    kinds = []
    print(f"Story {start} .. {end} (Europe/Stockholm)")
    for i in range(args.days):
        day = start + timedelta(days=i)
        h = build_story(data, day, today)["headline"]
        kinds.append(h["kind"])
        print(f"{day}  {h['kind']:<9} {h['area']:<4} {h['text']}")

    runs, run = 0, 1
    for prev, cur in zip(kinds, kinds[1:] + [None]):
        if cur == prev:
            run += 1
        else:
            runs += run >= 3
            run = 1

    print("\nHeadlines by kind")
    for kind, n in Counter(kinds).most_common():
        print(f"  {n:3d}  {kind}")
    print(f"\nRuns of 3+ days with the same kind: {runs} (should be 0)")


if __name__ == "__main__":
    main()
