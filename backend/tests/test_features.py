"""
Tests for feature_service.build_feature_matrix.

Uses in-memory SQLite. Inserts synthetic prices and generation data,
then verifies features are computed correctly including DST boundaries.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.de_spot_price import DeSpotPrice  # noqa: F401 — register model for create_all
from app.models.gas_price import GasPrice  # noqa: F401 — register model for create_all
from app.models.generation_mix import GenerationMix
from app.models.load_forecast import LoadForecast  # noqa: F401 — register model for create_all
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
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        price = base_price + 0.01 * h  # slight variation by hour
        db.add(
            SpotPrice(
                area=area,
                timestamp_utc=ts,
                price_eur_mwh=price * 100,  # rough EUR conversion
                price_sek_kwh=price,
                resolution="PT60M",
            )
        )
    db.commit()


def _insert_generation(db, target_date, area="SE3"):
    """Insert generation mix for a CET day (one 15-min slot per hour)."""
    start_utc = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    psr_values = {"B12": 1500.0, "B14": 4000.0, "B19": 800.0, "B20": 200.0}
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        for psr, mw in psr_values.items():
            db.add(
                GenerationMix(
                    area=area,
                    timestamp_utc=ts,
                    psr_type=psr,
                    value_mw=mw,
                    resolution="PT15M",
                )
            )
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


def test_feature_cols_count(db):
    """FEATURE_COLS has exactly 59 features (41 original + 6 Phase A + 6 Phase B + 6 Phase C)."""
    assert len(FEATURE_COLS) == 59


def test_holiday_features_normal_weekday(db):
    """Non-holiday weekday has is_holiday_se=0, holiday_score=0."""
    d = date(2026, 3, 10)  # Tuesday, no holiday
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["is_holiday_se"] == 0
    assert h0["holiday_score"] == 0.0
    assert h0["is_bridge_day"] == 0


def test_holiday_features_christmas(db):
    """Christmas Day is a holiday in SE, NO, and DE (score=1.0)."""
    d = date(2025, 12, 25)  # Thursday, Christmas
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["is_holiday_se"] == 1
    assert h0["holiday_score"] == pytest.approx(1.0, abs=0.01)


def test_bridge_day(db):
    """A weekday between a holiday and a weekend is a bridge day."""
    # 2025-12-26 is Friday (Annandag Jul in SE), 2025-12-27 is Saturday
    # 2025-12-24 is Wednesday (Julafton not a public holiday in holidays lib)
    # Let's check 2026-01-02: Friday between Jan 1 (holiday) and weekend (Sat)
    d = date(2026, 1, 2)  # Friday
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    # Jan 1 (Thu) = holiday, Jan 3 (Sat) = weekend → Jan 2 is bridge day
    assert h0["is_bridge_day"] == 1


def test_solar_features_noon_summer(db):
    """Sun elevation is positive at noon in summer Stockholm."""
    d = date(2026, 6, 21)  # Summer solstice
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h12 = next(r for r in rows if r["hour"] == 12)
    assert h12["sun_elevation"] > 40  # high noon in midsummer
    assert h12["daylight_hours"] > 18  # ~18.5h daylight


def test_solar_features_midnight_winter(db):
    """Sun elevation is negative at midnight in winter Stockholm."""
    d = date(2025, 12, 21)  # Winter solstice
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = next(r for r in rows if r["hour"] == 0)
    assert h0["sun_elevation"] < 0  # below horizon at midnight
    assert h0["daylight_hours"] < 7  # ~6.1h daylight


def test_solar_features_all_hours_have_values(db):
    """All 24 hours have sun_elevation, sun_azimuth, daylight_hours."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    for r in rows:
        assert r["sun_elevation"] is not None
        assert r["sun_azimuth"] is not None
        assert r["daylight_hours"] is not None


# ---------------------------------------------------------------------------
# Load forecast feature tests (Phase B)
# ---------------------------------------------------------------------------


def _insert_load_forecast(db, target_date, area="SE3", base_load=12000.0):
    """Insert 24 hourly load forecast values for a CET day."""

    start_utc = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        # Simulate load curve: higher during day, lower at night
        load = base_load + 2000 * (1 if 8 <= h <= 20 else 0) + 100 * h
        db.add(
            LoadForecast(
                area=area,
                timestamp_utc=ts,
                load_mw=load,
                resolution="PT60M",
            )
        )
    db.commit()


def test_load_forecast_features_present(db):
    """Load forecast features are populated when data exists."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    _insert_load_forecast(db, d)

    rows = build_feature_matrix(db, d, d)
    h12 = next(r for r in rows if r["hour"] == 12)
    assert h12["load_forecast_hour"] is not None
    assert h12["load_forecast_max"] is not None
    assert h12["load_forecast_min"] is not None
    assert h12["load_forecast_range"] is not None


def test_load_forecast_features_none_without_data(db):
    """Load forecast features are None when no data exists."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["load_forecast_hour"] is None
    assert h0["load_forecast_max"] is None
    assert h0["load_x_hour"] is None


def test_load_forecast_d1_fallback(db):
    """D-1 load forecast used as fallback when current day missing."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    # Only insert D-1 load forecast (not D)
    _insert_load_forecast(db, d - timedelta(days=1), base_load=11000.0)

    rows = build_feature_matrix(db, d, d, include_target=False)
    h12 = next(r for r in rows if r["hour"] == 12)
    assert h12["load_forecast_hour"] is not None  # D-1 fallback
    assert h12["load_forecast_max"] is not None
    assert h12["load_forecast_range"] is not None
    assert h12["load_x_hour"] is not None


def test_load_forecast_range_correct(db):
    """load_forecast_range = max - min of the day."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    _insert_load_forecast(db, d, base_load=10000.0)

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["load_forecast_range"] is not None
    assert h0["load_forecast_range"] == pytest.approx(h0["load_forecast_max"] - h0["load_forecast_min"], abs=1.0)


def test_load_forecast_vs_avg(db):
    """load_forecast_vs_avg uses 7-day rolling max average."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    _insert_load_forecast(db, d, base_load=12000.0)
    # Insert 7 days of history for rolling average
    for offset in range(1, 8):
        _insert_load_forecast(db, d - timedelta(days=offset), base_load=10000.0)

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    # Today's max is higher than the 7-day avg, so ratio > 1.0
    assert h0["load_forecast_vs_avg"] is not None
    assert h0["load_forecast_vs_avg"] > 1.0


# ---------------------------------------------------------------------------
# Phase C: Gas price + DE-LU price helpers + tests
# ---------------------------------------------------------------------------


def _insert_gas_prices(db, target_date, price=35.0, days_back=7):
    """Insert gas prices for target_date and several days before it."""

    for i in range(days_back):
        d = target_date - timedelta(days=i)
        # Skip weekends (no trading)
        if d.weekday() >= 5:
            continue
        db.add(
            GasPrice(
                trade_date=d,
                price_eur_mwh=price + i * 0.5,
                source="the_reference",
            )
        )
    db.commit()


def _insert_de_prices(db, target_date, base_price=80.0):
    """Insert 24 hourly DE-LU spot prices for a CET day."""

    start_utc = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=timezone.utc,
    ) - timedelta(hours=1)
    for h in range(24):
        ts = start_utc + timedelta(hours=h)
        price = base_price + 5.0 * (1 if 8 <= h <= 20 else 0) + 0.5 * h
        db.add(
            DeSpotPrice(
                timestamp_utc=ts,
                price_eur_mwh=price,
                resolution="PT60M",
            )
        )
    db.commit()


def test_gas_price_features_present(db):
    """Gas price features are populated when data exists."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))
    _insert_gas_prices(db, d)

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["gas_price_eur_mwh"] is not None
    assert h0["gas_price_7d_avg"] is not None
    assert h0["gas_price_change"] is not None


def test_gas_price_features_none_without_data(db):
    """Gas price features are None when no data exists."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["gas_price_eur_mwh"] is None
    assert h0["gas_price_7d_avg"] is None


def test_de_price_features_present(db):
    """DE-LU price features are populated when previous day data exists."""
    d = date(2026, 3, 10)
    prev = d - timedelta(days=1)
    _insert_prices(db, d)
    _insert_prices(db, prev)
    _insert_de_prices(db, prev)  # previous day DE prices

    rows = build_feature_matrix(db, d, d)
    h12 = next(r for r in rows if r["hour"] == 12)
    assert h12["de_price_prev_day"] is not None
    assert h12["de_se3_spread_prev_day"] is not None
    assert h12["de_price_same_hour_prev_day"] is not None


def test_de_price_features_none_without_data(db):
    """DE-LU price features are None when no previous day data exists."""
    d = date(2026, 3, 10)
    _insert_prices(db, d)
    _insert_prices(db, d - timedelta(days=1))

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["de_price_prev_day"] is None
    assert h0["de_se3_spread_prev_day"] is None
    assert h0["de_price_same_hour_prev_day"] is None


def test_de_se3_spread_sign(db):
    """de_se3_spread > 0 when DE price > SE3 price (export pressure)."""
    d = date(2026, 3, 10)
    prev = d - timedelta(days=1)
    _insert_prices(db, d, base_price=0.5)  # SE3: ~0.5 SEK/kWh ≈ 50 EUR/MWh
    _insert_prices(db, prev, base_price=0.5)
    _insert_de_prices(db, prev, base_price=200.0)  # DE: 200 EUR/MWh >> SE3

    rows = build_feature_matrix(db, d, d)
    h0 = rows[0]
    assert h0["de_se3_spread_prev_day"] is not None
    assert h0["de_se3_spread_prev_day"] > 0  # DE much higher → positive spread
