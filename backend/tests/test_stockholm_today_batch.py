"""
Batch/service layer must use the Stockholm calendar day, not the UTC one.

Lambda's clock is UTC, so between 22:00/23:00 UTC and midnight UTC the UTC date is
a day behind Stockholm. hourly_generation (cron :05 every hour) runs in that window.
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.tasks import fetch_prices
from app.utils.timezone import stockholm_today

# (now UTC, expected Stockholm date)
CASES = [
    # CET: 23:05 UTC = 00:05 next day Stockholm
    (datetime(2026, 1, 14, 23, 5, tzinfo=timezone.utc), date(2026, 1, 15)),
    # CEST: 22:05 UTC = 00:05 next day Stockholm; 21:59 UTC is still the same day
    (datetime(2026, 7, 14, 22, 5, tzinfo=timezone.utc), date(2026, 7, 15)),
    (datetime(2026, 7, 14, 21, 59, tzinfo=timezone.utc), date(2026, 7, 14)),
    # DST boundaries (23h day 2026-03-29, 25h day 2026-10-25)
    (datetime(2026, 3, 28, 23, 5, tzinfo=timezone.utc), date(2026, 3, 29)),
    (datetime(2026, 3, 29, 22, 5, tzinfo=timezone.utc), date(2026, 3, 30)),
    (datetime(2026, 10, 24, 22, 5, tzinfo=timezone.utc), date(2026, 10, 25)),
    (datetime(2026, 10, 25, 23, 5, tzinfo=timezone.utc), date(2026, 10, 26)),
    # 00:05 UTC (midnight_collect) is 01:05/02:05 Stockholm: same date either way
    (datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc), date(2026, 7, 15)),
]


@pytest.mark.parametrize("now,expected", CASES)
def test_stockholm_today(now, expected):
    assert stockholm_today(now) == expected


@pytest.mark.parametrize("now,expected", CASES)
def test_hourly_generation_uses_stockholm_date(now, expected):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    fetched: list[date] = []
    with (
        patch("app.utils.timezone.datetime", FrozenDatetime),
        patch.object(
            fetch_prices,
            "fetch_generation_date",
            side_effect=lambda d, a: fetched.append(d) or {"status": "ok"},
        ),
        patch.object(
            fetch_prices, "fetch_load_forecast_date", return_value={"status": "ok"}
        ),
        patch.object(fetch_prices, "fetch_hydro_date", return_value={"status": "ok"}),
    ):
        fetch_prices.lambda_handler({"hourly_generation": True, "area": "SE3"}, None)

    assert expected in fetched
    assert date.fromordinal(expected.toordinal() - 1) in fetched
