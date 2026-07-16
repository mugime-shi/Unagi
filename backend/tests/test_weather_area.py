"""
Tests for per-area weather: loader area filtering with SE3 fallback,
LOCAL_WEATHER_AREAS env parsing, and Open-Meteo actuals storage.

Uses in-memory SQLite for the loaders (plain ORM queries) and mock
sessions for the PostgreSQL-specific upserts.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.weather_data import WeatherData
from app.models.weather_forecast import WeatherForecast
from app.services.feature_service import _load_hourly_forecast, _load_hourly_weather
from app.services.openmeteo_client import local_weather_areas, store_weather_actuals

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

DAY = date(2026, 7, 10)


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


def _seed_weather(db, area: str, temp: float):
    for hour in range(24):
        db.add(
            WeatherData(
                station_id=0,
                area=area,
                timestamp_utc=datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=timezone.utc),
                temperature_c=temp,
                global_radiation_wm2=100.0,
                source="open-meteo",
            )
        )
    db.commit()


def _seed_forecast(db, area: str, temp: float):
    issued = DAY - timedelta(days=1)
    for hour in range(24):
        db.add(
            WeatherForecast(
                issued_date=issued,
                area=area,
                target_utc=datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=timezone.utc),
                temperature_c=temp,
                wind_speed_10m=10.0,
                wind_speed_100m=20.0,
                global_radiation_wm2=50.0,
                source="open-meteo",
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# _load_hourly_weather — area filter + SE3 fallback
# ---------------------------------------------------------------------------


def test_weather_prefers_local_area_rows(db):
    _seed_weather(db, "SE3", temp=20.0)
    _seed_weather(db, "SE1", temp=5.0)

    result = _load_hourly_weather(db, DAY, DAY, area="SE1")

    assert result[(DAY, 12)]["temperature_c"] == 5.0


def test_weather_falls_back_to_se3_when_area_empty(db):
    _seed_weather(db, "SE3", temp=20.0)

    result = _load_hourly_weather(db, DAY, DAY, area="SE1")

    assert result[(DAY, 12)]["temperature_c"] == 20.0


def test_weather_se3_does_not_see_other_areas(db):
    _seed_weather(db, "SE1", temp=5.0)

    result = _load_hourly_weather(db, DAY, DAY, area="SE3")

    assert result == {}


# ---------------------------------------------------------------------------
# _load_hourly_forecast — area filter + SE3 fallback
# ---------------------------------------------------------------------------


def test_forecast_prefers_local_area_rows(db):
    _seed_forecast(db, "SE3", temp=20.0)
    _seed_forecast(db, "SE2", temp=5.0)

    result = _load_hourly_forecast(db, DAY, area="SE2")

    assert result[12]["temp_forecast"] == 5.0
    assert result[12]["wind_speed_100m"] == 20.0


def test_forecast_falls_back_to_se3_when_area_empty(db):
    _seed_forecast(db, "SE3", temp=20.0)

    result = _load_hourly_forecast(db, DAY, area="SE2")

    assert result[12]["temp_forecast"] == 20.0


def test_forecast_actuals_fallback_respects_area(db):
    # No forecast rows at all → falls back to weather_data pseudo-forecast
    _seed_weather(db, "SE1", temp=5.0)
    _seed_weather(db, "SE3", temp=20.0)

    result = _load_hourly_forecast(db, DAY, area="SE1")

    assert result[12]["temp_forecast"] == 5.0


# ---------------------------------------------------------------------------
# local_weather_areas — env parsing
# ---------------------------------------------------------------------------


def test_local_weather_areas_unset_is_empty():
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("LOCAL_WEATHER_AREAS", None)
        assert local_weather_areas() == []


def test_local_weather_areas_parses_and_filters():
    with patch.dict(
        "os.environ", {"LOCAL_WEATHER_AREAS": "SE1, SE2, SE3, SE9, garbage"}, clear=False
    ):
        # SE3 (the always-on default) and unknown areas are dropped
        assert local_weather_areas() == ["SE1", "SE2"]


# ---------------------------------------------------------------------------
# store_weather_actuals — mock DB (pg_insert is PostgreSQL-specific)
# ---------------------------------------------------------------------------


def test_store_weather_actuals_empty_noop():
    mock_db = MagicMock()
    assert store_weather_actuals(mock_db, [], "SE1") == 0
    mock_db.execute.assert_not_called()


def test_store_weather_actuals_returns_count():
    mock_db = MagicMock()
    slots = [
        {
            "timestamp_utc": datetime(2026, 7, 10, h, tzinfo=timezone.utc),
            "temperature_c": 12.0,
            "global_radiation_wm2": 80.0,
        }
        for h in range(3)
    ]
    assert store_weather_actuals(mock_db, slots, "SE1") == 3
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
