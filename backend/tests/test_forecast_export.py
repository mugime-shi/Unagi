"""
Tests for the static JSON forecast export (public v1 feed).

Uses an in-memory SQLite DB with StaticPool, same pattern as test_prices.py.
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.forecast_accuracy import ForecastAccuracy
from app.services.forecast_export_service import (
    SCHEMA_VERSION,
    build_forecast_export,
    write_forecast_exports,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

TODAY = date(2026, 7, 13)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    yield session
    session.close()


def _seed_prediction(db, target_date, model_name, area="SE3", base_price=0.50, hours=range(24)):
    for hour in hours:
        # Cheapest hours at 02-04 so cheapest_hours is deterministic
        price = base_price - 0.30 if hour in (2, 3, 4) else base_price + hour * 0.01
        db.add(
            ForecastAccuracy(
                target_date=target_date,
                area=area,
                model_name=model_name,
                hour=hour,
                predicted_sek_kwh=price,
                predicted_low_sek_kwh=price - 0.1,
                predicted_high_sek_kwh=price + 0.1,
            )
        )
    db.commit()


def _seed_scored_history(db, area="SE3"):
    """Past predictions with actuals so the accuracy block has data."""
    for offset in range(1, 4):
        target = TODAY - timedelta(days=offset)
        for hour in range(24):
            db.add(
                ForecastAccuracy(
                    target_date=target,
                    area=area,
                    model_name="lgbm",
                    hour=hour,
                    predicted_sek_kwh=0.50,
                    predicted_low_sek_kwh=0.30,
                    predicted_high_sek_kwh=0.70,
                    actual_sek_kwh=0.55,
                )
            )
    db.commit()


def test_export_structure_and_metadata(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["area"] == "SE3"
    assert doc["unit"] == "SEK/kWh"
    assert doc["timezone"] == "Europe/Stockholm"
    assert "license" in doc and "no warranty" in doc["license"].lower()
    assert len(doc["days"]) == 1

    day = doc["days"][0]
    assert day["horizon_days"] == 1
    assert len(day["hours"]) == 24
    slot = day["hours"][0]
    # Mid-July Stockholm is CEST (UTC+2)
    assert slot["start"] == "2026-07-14T00:00:00+02:00"
    assert slot["end"] == "2026-07-14T01:00:00+02:00"
    assert slot["low"] < slot["value"] < slot["high"]


def test_cheapest_hours_precomputed(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    doc = build_forecast_export(db, "SE3", today=TODAY)
    assert doc["days"][0]["cheapest_hours"] == [2, 3, 4]


def test_freshest_horizon_wins_dedup(db):
    target = TODAY + timedelta(days=2)
    _seed_prediction(db, target, "lgbm_d3", base_price=0.90)  # stale (recorded 3 days out)
    _seed_prediction(db, target, "lgbm_d2", base_price=0.50)  # fresher (recorded 2 days out)
    doc = build_forecast_export(db, "SE3", today=TODAY)

    assert len(doc["days"]) == 1
    day = doc["days"][0]
    assert day["horizon_days"] == 2
    assert len(day["hours"]) == 24  # 24 slots, not 48 stacked
    # Values must come from the fresher lgbm_d2 seed (base 0.50, not 0.90)
    assert day["hours"][0]["value"] == pytest.approx(0.50)


def test_excludes_past_and_other_areas(db):
    _seed_prediction(db, TODAY, "lgbm")  # today is not a forecast
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm", area="SE1")
    doc = build_forecast_export(db, "SE3", today=TODAY)
    assert doc["days"] == []


def test_accuracy_block(db):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    _seed_scored_history(db)
    doc = build_forecast_export(db, "SE3", today=TODAY)

    acc = doc["accuracy"]
    assert acc["window_days"] == 28
    assert acc["mae_sek_kwh"] == pytest.approx(0.05)
    assert acc["by_horizon"][0]["horizon_days"] == 1
    # All actuals (0.55) fall inside [0.30, 0.70] → 100% coverage
    assert acc["interval_coverage_pct"] == pytest.approx(100.0)


def test_write_forecast_exports_layout(db, tmp_path):
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm")
    _seed_prediction(db, TODAY + timedelta(days=1), "lgbm", area="SE1")

    written = write_forecast_exports(db, tmp_path, areas=("SE1", "SE3"))

    latest = tmp_path / "v1" / "forecast" / "SE3.json"
    index = tmp_path / "v1" / "index.json"
    assert latest.exists() and index.exists()
    archives = list((tmp_path / "v1" / "archive").glob("*/SE3.json"))
    assert len(archives) == 1
    assert latest in written

    doc = json.loads(latest.read_text())
    assert doc["area"] == "SE3"
    idx = json.loads(index.read_text())
    assert idx["areas"] == {"SE1": "forecast/SE1.json", "SE3": "forecast/SE3.json"}
    # Latest and archive snapshot must be byte-identical (audit trail)
    assert latest.read_text() == archives[0].read_text()
