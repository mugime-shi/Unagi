"""
Equivalence test: the story's PostgreSQL daily aggregates vs the Python bucketing.

Skipped by default. Run with (inside the dev container, db reachable as `db`):
    RUN_PG_TESTS=1 TEST_DATABASE_URL=postgresql+psycopg2://unagi:unagi@db:5432/unagi_test \
        pytest tests/test_story_sql_aggregation.py -v

Requires a running local PostgreSQL (docker compose up -d db).
"""

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.spot_price import SpotPrice
from app.services.story_service import (
    AREAS,
    StoryData,
    _bucket_price_rows,
    _load_daily_aggregates,
    _utc_naive,
)
from app.utils.timezone import stockholm_midnight_utc

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_TESTS") != "1",
    reason="Set RUN_PG_TESTS=1 to run PostgreSQL equivalence tests",
)

PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://unagi:unagi@localhost:5533/unagi_test",
)

_SCHEMA = "unagi_story_agg_test"

SPRING = date(2026, 3, 29)  # last Sunday of March: 23 h
AUTUMN = date(2026, 10, 25)  # last Sunday of October: 25 h


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
    engine.dispose()
    engine = create_engine(PG_URL, connect_args={"options": f"-csearch_path={_SCHEMA}"})
    Base.metadata.create_all(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
    session.query(SpotPrice).delete()
    session.commit()
    yield session
    session.close()


def _seed_day(db, area, day, resolution, base):
    """One row per slot between the day's two Stockholm midnights, so DST days get 23/25 hours."""
    step = timedelta(minutes=15 if resolution == "PT15M" else 60)
    ts, end, i = stockholm_midnight_utc(day), stockholm_midnight_utc(day + timedelta(days=1)), 0
    while ts < end:
        # Spread of values incl. negatives so min/max/avg are all non-trivial.
        price = round(base + ((i * 37) % 23 - 8) / 100, 4)
        db.add(SpotPrice(area=area, timestamp_utc=ts, price_eur_mwh=0, price_sek_kwh=price, resolution=resolution))
        ts += step
        i += 1


def test_sql_daily_aggregates_match_python(pg_session):
    days = [SPRING - timedelta(days=1), SPRING, SPRING + timedelta(days=1), AUTUMN - timedelta(days=1), AUTUMN]
    for n, area in enumerate(AREAS):
        for k, day in enumerate(days):
            _seed_day(pg_session, area, day, "PT15M" if (n + k) % 2 else "PT60M", base=0.3 + 0.1 * n + 0.02 * k)
    # A mixed-resolution day: hourly rows up to noon, quarter-hourly after.
    mixed = date(2026, 6, 10)
    start = stockholm_midnight_utc(mixed)
    for h in range(12):
        pg_session.add(
            SpotPrice(
                area="SE3",
                timestamp_utc=start + timedelta(hours=h),
                price_eur_mwh=0,
                price_sek_kwh=0.5 + h / 100,
                resolution="PT60M",
            )
        )
    for q in range(48):
        pg_session.add(
            SpotPrice(
                area="SE3",
                timestamp_utc=start + timedelta(hours=12, minutes=15 * q),
                price_eur_mwh=0,
                price_sek_kwh=-0.02 + q / 100,
                resolution="PT15M",
            )
        )
    pg_session.commit()

    lo, hi = _utc_naive(date(2026, 3, 1)), _utc_naive(date(2026, 11, 1))

    sql_data = StoryData()
    _load_daily_aggregates(pg_session, sql_data, lo, hi)

    rows = pg_session.execute(
        text(
            "SELECT area, timestamp_utc, price_sek_kwh, resolution FROM spot_prices "
            "WHERE timestamp_utc >= :lo AND timestamp_utc < :hi"
        ),
        {"lo": lo, "hi": hi},
    ).all()
    py_data = StoryData()
    _bucket_price_rows(py_data, rows, date(2100, 1, 1))  # no hourly bucketing needed here

    for area in AREAS:
        assert sql_data.prices[area].keys() == py_data.prices[area].keys()
        for day, py in py_data.prices[area].items():
            sq = sql_data.prices[area][day]
            assert sq.minutes == py.minutes, (area, day)
            assert sq.weighted_sum == pytest.approx(py.weighted_sum, abs=1e-9), (area, day)
            assert sq.avg == pytest.approx(py.avg, abs=1e-12), (area, day)
            assert sq.min_price == py.min_price, (area, day)
            assert sq.max_price == py.max_price, (area, day)
            assert sq.complete == py.complete, (area, day)

    # DST days keep their real length, which the 20-hour coverage guard relies on.
    assert sql_data.prices["SE3"][SPRING].minutes == 23 * 60
    assert sql_data.prices["SE3"][AUTUMN].minutes == 25 * 60
    assert sql_data.prices["SE3"][mixed].minutes == 24 * 60
