from datetime import date, datetime, timezone

from app.utils.timezone import stockholm_today


def test_stockholm_today_summer_rolls_over_before_utc():
    # 23:30 UTC = 01:30 CEST next day
    assert stockholm_today(datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)) == date(2026, 7, 16)


def test_stockholm_today_winter_rolls_over_before_utc():
    # 23:30 UTC = 00:30 CET next day
    assert stockholm_today(datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)) == date(2026, 1, 16)


def test_stockholm_today_midday_is_same_date():
    assert stockholm_today(datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)) == date(2026, 4, 10)


def test_stockholm_today_summer_same_day_before_local_midnight():
    # 21:59 UTC = 23:59 CEST same day
    assert stockholm_today(datetime(2026, 7, 15, 21, 59, tzinfo=timezone.utc)) == date(2026, 7, 15)
