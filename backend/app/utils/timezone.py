"""Stockholm timezone utilities — single source of truth for CET/CEST handling."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def stockholm_midnight_utc(d: date) -> datetime:
    """
    Convert a Stockholm calendar date to its UTC midnight equivalent.

    Handles CET (UTC+1) and CEST (UTC+2) automatically:
      - CET:  2026-01-15 00:00 Stockholm = 2026-01-14 23:00 UTC
      - CEST: 2026-07-15 00:00 Stockholm = 2026-07-14 22:00 UTC

    Use this instead of `datetime(..., utc) - timedelta(hours=1)`.
    """
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=STOCKHOLM)
    return local_midnight.astimezone(timezone.utc)


def stockholm_day_range_utc(d: date) -> tuple[datetime, datetime]:
    """
    Return (start_utc, end_utc) for a full Stockholm calendar day.

    Correctly handles DST transitions:
      - Normal day: 24h span
      - Spring forward (Mar): 23h span
      - Fall back (Oct): 25h span
    """
    start = stockholm_midnight_utc(d)
    end = stockholm_midnight_utc(d + timedelta(days=1))
    return start, end
