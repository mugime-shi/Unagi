"""
Tests for the weekly forecast's published-actuals path.

Once ENTSO-E publishes day-ahead prices (~13:00 CET), d+1 is settled fact and
the weekly card must stop showing the 00:20 UTC model prediction for it.

Scope note: these exercise `_published_hourly_slots` directly rather than
GET /prices/forecast/weekly, because that endpoint's query uses PostgreSQL's
DISTINCT ON, which SQLite cannot execute. See tests/README or the endpoint
docstring — full-endpoint coverage needs a Postgres-backed fixture.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.forecast_accuracy import ForecastAccuracy  # noqa: F401 — register with Base for create_all
from app.routers.prices import _published_hourly_slots
from app.services.entsoe_client import PricePoint
from app.services.price_service import upsert_prices
from app.utils.timezone import stockholm_day_range_utc

_STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Sweden's 2026 DST boundaries: 23-hour day in March, 25-hour day in October.
SPRING_FORWARD = date(2026, 3, 29)
FALL_BACK = date(2026, 10, 25)
NORMAL_DAY = date(2026, 7, 16)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _publish(
    db,
    target_date: date,
    area: str = "SE3",
    skip_hours: tuple[int, ...] = (),
    price_for_hour=lambda hour: 0.5,
) -> None:
    """Insert 15-min spot prices across the full Stockholm day, minus skip_hours."""
    start, end = stockholm_day_range_utc(target_date)
    points = []
    cursor = start
    while cursor < end:
        hour = cursor.astimezone(_STOCKHOLM).hour
        if hour not in skip_hours:
            sek = price_for_hour(hour)
            points.append(
                PricePoint(
                    timestamp_utc=cursor,
                    price_eur_mwh=round(sek * 1000 / 11, 4),
                    price_sek_kwh=sek,
                    resolution="PT15M",
                )
            )
        cursor += timedelta(minutes=15)
    upsert_prices(db, points, area=area)


def test_returns_none_when_nothing_published(db):
    assert _published_hourly_slots(db, NORMAL_DAY, "SE3") is None


def test_full_day_returns_24_hourly_slots(db):
    _publish(db, NORMAL_DAY)
    slots = _published_hourly_slots(db, NORMAL_DAY, "SE3")

    assert slots is not None
    assert len(slots) == 24
    assert [s["hour"] for s in slots] == list(range(24))


def test_quarter_hours_are_averaged_into_the_hour(db):
    # Four 15-min slots per hour all priced the same as the hour index / 10,
    # so hour 7 must average to 0.7 — not sum to 2.8.
    _publish(db, NORMAL_DAY, price_for_hour=lambda h: round(h / 10, 4))
    slots = _published_hourly_slots(db, NORMAL_DAY, "SE3")

    by_hour = {s["hour"]: s["avg_sek_kwh"] for s in slots}
    assert by_hour[7] == pytest.approx(0.7)
    assert by_hour[23] == pytest.approx(2.3)


def test_partial_day_falls_back_to_forecast(db):
    # A half-published day would average to a misleading daily figure.
    _publish(db, NORMAL_DAY, skip_hours=(18,))
    assert _published_hourly_slots(db, NORMAL_DAY, "SE3") is None


def test_other_area_does_not_leak(db):
    _publish(db, NORMAL_DAY, area="SE3")
    assert _published_hourly_slots(db, NORMAL_DAY, "SE4") is None


def test_spring_forward_day_has_23_hours(db):
    # 02:00 never happens; a complete day is 23 labels, not 24.
    _publish(db, SPRING_FORWARD)
    slots = _published_hourly_slots(db, SPRING_FORWARD, "SE3")

    assert slots is not None, "complete 23-hour day must not be rejected as partial"
    assert len(slots) == 23
    assert 2 not in [s["hour"] for s in slots]


def test_fall_back_day_collapses_the_repeated_hour(db):
    # 02:00 occurs twice (CEST then CET). Both bucket into hour 2, matching
    # fill_actuals, so a complete 25-hour day yields 24 labels.
    _publish(db, FALL_BACK)
    slots = _published_hourly_slots(db, FALL_BACK, "SE3")

    assert slots is not None, "complete 25-hour day must not be rejected as partial"
    assert len(slots) == 24
    assert [s["hour"] for s in slots] == list(range(24))


def test_fall_back_day_missing_an_hour_is_still_partial(db):
    _publish(db, FALL_BACK, skip_hours=(5,))
    assert _published_hourly_slots(db, FALL_BACK, "SE3") is None


def test_naive_timestamps_are_read_as_utc(db):
    # SQLite hands datetimes back without tzinfo; a naive value must not be
    # reinterpreted in the host's local zone.
    _publish(db, NORMAL_DAY)
    rows_start, _ = stockholm_day_range_utc(NORMAL_DAY)
    assert rows_start.tzinfo is not None

    slots = _published_hourly_slots(db, NORMAL_DAY, "SE3")
    assert slots is not None and len(slots) == 24


def test_published_slots_carry_no_prediction_band(db):
    # An actual has no interval — the CQR band belongs to forecasts only.
    _publish(db, NORMAL_DAY)
    slots = _published_hourly_slots(db, NORMAL_DAY, "SE3")

    assert all(s["low_sek_kwh"] is None and s["high_sek_kwh"] is None for s in slots)


def test_utc_midnight_rows_do_not_count_as_the_stockholm_day(db):
    # Stockholm's day starts 22:00/23:00 UTC the day before; a naive UTC-day
    # window would pull in the wrong 2 hours.
    start, end = stockholm_day_range_utc(NORMAL_DAY)
    assert start < datetime(NORMAL_DAY.year, NORMAL_DAY.month, NORMAL_DAY.day, tzinfo=timezone.utc)
    assert end < datetime(NORMAL_DAY.year, NORMAL_DAY.month, NORMAL_DAY.day + 1, tzinfo=timezone.utc)
