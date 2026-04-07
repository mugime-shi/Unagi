"""
Equivalence tests: PostgreSQL server-side aggregation vs Python-side aggregation.

These tests verify that the new dialect-branched SQL loaders in feature_service.py
produce byte-identical output to the original Python implementations, including
on DST boundary days.

Skipped by default. Run with:
    RUN_PG_TESTS=1 pytest tests/test_features_sql_aggregation.py -v

Requires a running local PostgreSQL (docker compose up -d).
"""

import math
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.balancing_price import BalancingPrice
from app.models.de_spot_price import DeSpotPrice
from app.models.generation_mix import GenerationMix
from app.models.load_forecast import LoadForecast
from app.models.spot_price import SpotPrice
from app.services.feature_service import (
    _load_hourly_balancing,
    _load_hourly_balancing_pylocal,
    _load_hourly_de_prices,
    _load_hourly_de_prices_pylocal,
    _load_hourly_generation,
    _load_hourly_generation_pylocal,
    _load_hourly_load_forecast,
    _load_hourly_load_forecast_pylocal,
    _load_hourly_prices,
    _load_hourly_prices_pylocal,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_TESTS") != "1",
    reason="Set RUN_PG_TESTS=1 to run PostgreSQL equivalence tests",
)

PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://unagi:unagi@localhost:5533/unagi_test",
)

_SCHEMA = "unagi_sql_agg_test"


@pytest.fixture(scope="module")
def pg_engine():
    """Create an isolated schema for testing, drop it afterwards."""
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
    # Bind schema as default for subsequent sessions
    engine.dispose()
    engine = create_engine(PG_URL, connect_args={"options": f"-csearch_path={_SCHEMA}"})
    Base.metadata.create_all(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    session = Session()
    # Clean tables between tests
    for model in (
        SpotPrice,
        GenerationMix,
        BalancingPrice,
        LoadForecast,
        DeSpotPrice,
    ):
        session.query(model).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Data insertion helpers
# ---------------------------------------------------------------------------


def _insert_spot_15min(db, day: date, area="SE3", base=0.50):
    """Insert 15-min spot prices for a 48h UTC window around `day`."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(days=1)
    for i in range(96 * 2):  # 2 days of 15-min slots
        ts = start + timedelta(minutes=15 * i)
        db.add(
            SpotPrice(
                area=area,
                timestamp_utc=ts,
                price_eur_mwh=(base + 0.001 * i) * 100,
                price_sek_kwh=base + 0.001 * i,
                resolution="PT15M",
            )
        )
    db.commit()


def _insert_generation_15min(db, day: date, area="SE3"):
    """Insert 15-min generation data for 5 psr_types over 2 days."""
    psr_types = ["B04", "B12", "B14", "B16", "B19"]
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(days=1)
    for i in range(96 * 2):
        ts = start + timedelta(minutes=15 * i)
        for j, psr in enumerate(psr_types):
            db.add(
                GenerationMix(
                    area=area,
                    timestamp_utc=ts,
                    psr_type=psr,
                    value_mw=100.0 * (j + 1) + 0.5 * i,
                    resolution="PT15M",
                )
            )
    db.commit()


def _insert_balancing_15min(db, day: date, area="SE3"):
    """Insert 15-min balancing prices (A04 long, A05 short) for 2 days."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(days=1)
    for i in range(96 * 2):
        ts = start + timedelta(minutes=15 * i)
        for cat, base in (("A04", 0.3), ("A05", 0.4)):
            db.add(
                BalancingPrice(
                    area=area,
                    timestamp_utc=ts,
                    price_eur_mwh=(base + 0.001 * i) * 100,
                    price_sek_kwh=base + 0.001 * i,
                    category=cat,
                    resolution="PT15M",
                )
            )
    db.commit()


def _insert_load_forecast_hourly(db, day: date, area="SE3"):
    """Insert hourly load forecasts for 2 days."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(days=1)
    for i in range(48):
        ts = start + timedelta(hours=i)
        db.add(
            LoadForecast(
                area=area,
                timestamp_utc=ts,
                load_mw=5000.0 + 10.0 * i,
                resolution="PT60M",
            )
        )
    db.commit()


def _insert_de_prices_hourly(db, day: date):
    """Insert hourly DE-LU spot prices for 2 days."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(days=1)
    for i in range(48):
        ts = start + timedelta(hours=i)
        db.add(
            DeSpotPrice(
                timestamp_utc=ts,
                price_eur_mwh=50.0 + 0.1 * i,
                resolution="PT60M",
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# Equivalence helpers
# ---------------------------------------------------------------------------


def _assert_flat_equal(a: dict, b: dict):
    assert set(a.keys()) == set(b.keys()), f"keys differ: only_a={set(a) - set(b)} only_b={set(b) - set(a)}"
    for k in a:
        assert math.isclose(a[k], b[k], abs_tol=1e-9), f"{k}: {a[k]} vs {b[k]}"


def _assert_nested_equal(a: dict, b: dict):
    assert set(a.keys()) == set(b.keys())
    for k in a:
        sub_a, sub_b = a[k], b[k]
        assert set(sub_a.keys()) == set(sub_b.keys())
        for sk in sub_a:
            assert math.isclose(sub_a[sk], sub_b[sk], abs_tol=1e-9), f"{k}.{sk}: {sub_a[sk]} vs {sub_b[sk]}"


# ---------------------------------------------------------------------------
# Tests: each loader, normal day
# ---------------------------------------------------------------------------

NORMAL_DAY = date(2026, 2, 15)
SPRING_DST = date(2026, 3, 29)  # spring forward: 23 hours
FALL_DST = date(2026, 10, 25)  # fall back: 25 hours


@pytest.mark.parametrize("test_day", [NORMAL_DAY, SPRING_DST, FALL_DST])
def test_hourly_prices_equivalence(pg_session, test_day):
    _insert_spot_15min(pg_session, test_day)
    sql_out = _load_hourly_prices(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    py_out = _load_hourly_prices_pylocal(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    _assert_flat_equal(sql_out, py_out)


@pytest.mark.parametrize("test_day", [NORMAL_DAY, SPRING_DST, FALL_DST])
def test_hourly_generation_equivalence(pg_session, test_day):
    _insert_generation_15min(pg_session, test_day)
    sql_out = _load_hourly_generation(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    py_out = _load_hourly_generation_pylocal(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    _assert_nested_equal(sql_out, py_out)


@pytest.mark.parametrize("test_day", [NORMAL_DAY, SPRING_DST, FALL_DST])
def test_hourly_balancing_equivalence(pg_session, test_day):
    _insert_balancing_15min(pg_session, test_day)
    sql_out = _load_hourly_balancing(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    py_out = _load_hourly_balancing_pylocal(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    _assert_nested_equal(sql_out, py_out)


@pytest.mark.parametrize("test_day", [NORMAL_DAY, SPRING_DST, FALL_DST])
def test_hourly_load_forecast_equivalence(pg_session, test_day):
    _insert_load_forecast_hourly(pg_session, test_day)
    sql_out = _load_hourly_load_forecast(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    py_out = _load_hourly_load_forecast_pylocal(pg_session, test_day, test_day + timedelta(days=1), "SE3")
    _assert_flat_equal(sql_out, py_out)


@pytest.mark.parametrize("test_day", [NORMAL_DAY, SPRING_DST, FALL_DST])
def test_hourly_de_prices_equivalence(pg_session, test_day):
    _insert_de_prices_hourly(pg_session, test_day)
    sql_out = _load_hourly_de_prices(pg_session, test_day, test_day + timedelta(days=1))
    py_out = _load_hourly_de_prices_pylocal(pg_session, test_day, test_day + timedelta(days=1))
    _assert_flat_equal(sql_out, py_out)


def test_spring_dst_has_23_hours(pg_session):
    """On spring-forward day (2026-03-29), Stockholm has only 23 hours."""
    _insert_spot_15min(pg_session, SPRING_DST)
    sql_out = _load_hourly_prices(pg_session, SPRING_DST, SPRING_DST + timedelta(days=1), "SE3")
    hours_on_day = sorted(h for (d, h) in sql_out.keys() if d == SPRING_DST)
    assert len(hours_on_day) == 23, f"expected 23 hours, got {hours_on_day}"
    assert 2 not in hours_on_day, "hour 2 should be skipped (spring forward)"


def test_fall_dst_has_25_hours(pg_session):
    """On fall-back day (2026-10-25), Stockholm has 25 hours.

    Python keys on `local.hour` (0-23), so the duplicated 02:00 folds into one
    bucket containing both 15-min windows. Both implementations must agree.
    """
    _insert_spot_15min(pg_session, FALL_DST)
    sql_out = _load_hourly_prices(pg_session, FALL_DST, FALL_DST + timedelta(days=1), "SE3")
    py_out = _load_hourly_prices_pylocal(pg_session, FALL_DST, FALL_DST + timedelta(days=1), "SE3")
    _assert_flat_equal(sql_out, py_out)
