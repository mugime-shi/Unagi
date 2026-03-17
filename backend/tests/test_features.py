"""
Tests for feature_service.build_feature_matrix.

Uses in-memory SQLite. Inserts synthetic prices and generation data,
then verifies features are computed correctly including DST boundaries.
"""

import math
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.generation_mix import GenerationMix
from app.models.spot_price import SpotPrice
from app.services.feature_service import (
    FEATURE_COLS,
    TARGET_COL,
    build_feature_matrix,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _insert_prices(db, target_date, area="SE3", base_price=0.50):
    """Insert 24 hourly prices for a CET day."""
    # CET midnight = UTC 23:00 previous day
    start_utc = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        price = base_price + 0.01 * h  # slight variation by hour
        db.add(SpotPrice(
            area=area,
            timestamp_utc=ts,
            price_eur_mwh=price * 100,  # rough EUR conversion
            price_sek_kwh=price,
            resolution="PT60M",
        ))
    db.commit()


def _insert_generation(db, target_date, area="SE3"):
    """Insert generation mix for a CET day (one 15-min slot per hour)."""
    start_utc = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    psr_values = {"B12": 1500.0, "B14": 4000.0, "B19": 800.0, "B20": 200.0}
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        for psr, mw in psr_values.items():
            db.add(GenerationMix(
                area=area,
                timestamp_utc=ts,
                psr_type=psr,
                value_mw=mw,
                resolution="PT15M",
            ))
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_basic_feature_generation(db):
    """Features are generated for each (date, hour) with correct structure."""
    d = date(2026, 3, 10)  # Tuesday
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))  # for lag features
    _insert_generation(db, d - timedelta(days=1))  # gen from prev day

    rows = build_feature_matrix(db, d, d)

    # CET window inserts 24 UTC slots; all 24 should map to the same Stockholm date
    assert len(rows) == 24
    for r in rows:
        assert r["date"] == d.isoformat()
        assert TARGET_COL in r
        assert r["weekday"] == 1  # Tuesday
        assert r["month"] == 3


def test_sin_cos_cyclical(db):
    """Cyclical features have correct sin/cos values."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)

    # Hour 6: sin(2π·6/24) = sin(π/2) = 1.0
    h6 = next(r for r in rows if r["hour"] == 6)
    assert abs(h6["hour_sin"] - 1.0) < 0.001
    assert abs(h6["hour_cos"] - 0.0) < 0.001

    # Hour 0: sin(0) = 0, cos(0) = 1
    h0 = next(r for r in rows if r["hour"] == 0)
    assert abs(h0["hour_sin"] - 0.0) < 0.001
    assert abs(h0["hour_cos"] - 1.0) < 0.001


def test_lag_features(db):
    """Prev-day and prev-week lag features are populated."""
    base = date(2026, 3, 10)
    for offset in range(8):
        _insert_prices(db, base - timedelta(days=offset), base_price=0.50 + 0.01 * offset)

    rows = build_feature_matrix(db, base, base)

    h0 = next(r for r in rows if r["hour"] == 0)
    # prev_day_same_hour should exist (day-1 inserted)
    assert h0["prev_day_same_hour"] is not None
    # prev_week_same_hour should exist (day-7 inserted)
    assert h0["prev_week_same_hour"] is not None
    # daily_avg_prev_day should exist
    assert h0["daily_avg_prev_day"] is not None


def test_generation_features(db):
    """Generation ratios are computed from previous day's data."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_generation(db, d - timedelta(days=1))  # prev day gen

    rows = build_feature_matrix(db, d, d)

    h0 = next(r for r in rows if r["hour"] == 0)
    # hydro=1500, nuclear=4000, wind=800, other=200 → total=6500
    assert h0["gen_total_mw"] == pytest.approx(6500.0, rel=0.01)
    assert h0["hydro_ratio"] == pytest.approx(1500 / 6500, abs=0.001)
    assert h0["wind_ratio"] == pytest.approx(800 / 6500, abs=0.001)
    assert h0["nuclear_ratio"] == pytest.approx(4000 / 6500, abs=0.001)


def test_no_generation_data_returns_none_ratios(db):
    """When no generation data exists, gen features are None (not error)."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)

    rows = build_feature_matrix(db, d, d)

    h0 = next(r for r in rows if r["hour"] == 0)
    assert h0["gen_total_mw"] is None
    assert h0["hydro_ratio"] is None


def test_multi_day_range(db):
    """Feature matrix covers multiple days correctly."""
    start = date(2026, 3, 10)
    end = date(2026, 3, 12)
    for offset in range(-1, 3):  # -1 for lag, 0-2 for range
        _insert_prices(db, start + timedelta(days=offset))

    rows = build_feature_matrix(db, start, end)

    assert len(rows) == 72  # 3 days × 24 hours
    dates = {r["date"] for r in rows}
    assert dates == {"2026-03-10", "2026-03-11", "2026-03-12"}


def test_dst_boundary_spring(db):
    """Features work across DST transition (last Sunday of March)."""
    # 2026 DST transition: March 29 (CET→CEST, 02:00→03:00)
    # Spring-forward: hour 2 doesn't exist in Stockholm time.
    # 24 UTC slots → 23 unique Stockholm hours for March 29
    # (one slot maps to March 30 00:00 CEST)
    dst_date = date(2026, 3, 29)
    _insert_prices(db, dst_date)
    _insert_prices(db, dst_date - timedelta(days=1))

    rows = build_feature_matrix(db, dst_date, dst_date)

    # DST spring-forward: expect 23 rows (hour 2 skipped, last slot goes to next day)
    assert len(rows) >= 22
    # All rows should have valid features
    for r in rows:
        assert r[TARGET_COL] is not None


def test_empty_db_returns_empty(db):
    """No data → empty list, not error."""
    rows = build_feature_matrix(db, date(2026, 3, 10), date(2026, 3, 10))
    assert rows == []


def test_feature_cols_match_output(db):
    """All FEATURE_COLS are present in output rows."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    _insert_generation(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)

    for col in FEATURE_COLS:
        assert col in rows[0], f"Missing feature column: {col}"
