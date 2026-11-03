"""
Aggregate usage_events into the success metrics of
work/PLAN_2026-11-01_public_data_story.md (return rate, new vs returning,
referrers, tab usage).

Cohort return rate works without visitor IDs: a browser's first-ever visit
has days_since_first == 0, and its *first return* is the only visit where
days_since_first == days_since_last (nothing in between). Subtracting
days_since_first from the visit date recovers the cohort date.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.usage_event import UsageEvent

STOCKHOLM = ZoneInfo("Europe/Stockholm")
RETURN_WINDOW_DAYS = 7


@dataclass
class UsageSummary:
    start: date
    end: date
    visits_by_day: dict[date, tuple[int, int]] = field(default_factory=dict)  # day -> (new, returning)
    cohort_size: int = 0
    cohort_returned: int = 0
    referrers: Counter = field(default_factory=Counter)
    views: dict[str, Counter] = field(default_factory=dict)  # event -> label counts

    @property
    def return_rate(self) -> float | None:
        return self.cohort_returned / self.cohort_size if self.cohort_size else None


def _local_day(ts: datetime) -> date:
    if ts.tzinfo is None:  # SQLite drops tzinfo; stored values are UTC
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(STOCKHOLM).date()


def summarize_usage(db: Session, days: int, today: date | None = None) -> UsageSummary:
    """Summarize the last `days` local days ending `today` (inclusive).

    Return rate covers only cohorts whose 7-day window has fully elapsed,
    so recent first visits do not drag the rate down.
    """
    today = today or datetime.now(STOCKHOLM).date()
    start = today - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time(), STOCKHOLM).astimezone(timezone.utc)

    rows = db.query(UsageEvent).filter(UsageEvent.occurred_at >= since).all()

    summary = UsageSummary(start=start, end=today)
    new_by_day: Counter = Counter()
    returning_by_day: Counter = Counter()
    first_returns: Counter = Counter()  # cohort day -> browsers back within the window
    last_complete_cohort = today - timedelta(days=RETURN_WINDOW_DAYS)

    for r in rows:
        day = _local_day(r.occurred_at)
        if day > today:
            continue
        if r.event != "visit":
            summary.views.setdefault(r.event, Counter())[r.label or "(none)"] += 1
            continue

        summary.referrers[r.label or "(direct)"] += 1
        if r.days_since_first == 0:
            new_by_day[day] += 1
        else:
            returning_by_day[day] += 1
            if r.days_since_last == r.days_since_first and r.days_since_first <= RETURN_WINDOW_DAYS:
                first_returns[day - timedelta(days=r.days_since_first)] += 1

    d = start
    while d <= today:
        summary.visits_by_day[d] = (new_by_day[d], returning_by_day[d])
        if d <= last_complete_cohort:
            summary.cohort_size += new_by_day[d]
            summary.cohort_returned += first_returns[d]
        d += timedelta(days=1)

    return summary
