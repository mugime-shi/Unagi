"""
Tests for the 04:20 predict retry (skip_if_recorded): areas whose d+1 lgbm
predictions already exist must not be retrained.
"""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.forecast_accuracy import ForecastAccuracy
from app.tasks.fetch_prices import ALL_AREAS, _areas_missing_predictions, lambda_handler

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

TARGET = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    with patch("app.tasks.fetch_prices.SessionLocal", TestSession):
        yield
    Base.metadata.drop_all(engine)


def _seed(area: str, model_name: str = "lgbm", target: date = TARGET) -> None:
    db = TestSession()
    db.add(ForecastAccuracy(target_date=target, area=area, model_name=model_name, hour=0, predicted_sek_kwh=0.5))
    db.commit()
    db.close()


def test_missing_areas_ignores_other_models_and_dates():
    _seed("SE1")
    _seed("SE2", model_name="lgbm_d2")  # written by the previous day's run
    _seed("SE3", model_name="same_weekday_avg")
    _seed("SE4", target=date(2026, 11, 1))

    assert _areas_missing_predictions(ALL_AREAS, TARGET) == ["SE2", "SE3", "SE4"]


@patch("app.tasks.fetch_prices._record_predictions")
def test_retry_skips_entirely_when_all_recorded(mock_predict):
    for area in ALL_AREAS:
        _seed(area)

    result = lambda_handler({"predict_only": True, "skip_if_recorded": True, "target_date": "2026-11-02"}, None)

    mock_predict.assert_not_called()
    assert result["statusCode"] == 200
    assert result["skipped"] == ALL_AREAS


@patch("app.tasks.fetch_prices._record_predictions", return_value=[])
def test_retry_runs_only_missing_areas(mock_predict):
    _seed("SE1")
    _seed("SE3")

    result = lambda_handler({"predict_only": True, "skip_if_recorded": True, "target_date": "2026-11-02"}, None)

    mock_predict.assert_called_once()
    assert mock_predict.call_args[0][0] == ["SE2", "SE4"]
    assert result["areas"] == ["SE2", "SE4"]


@patch("app.tasks.fetch_prices._record_predictions", return_value=[])
def test_nightly_run_without_flag_always_predicts(mock_predict):
    for area in ALL_AREAS:
        _seed(area)

    lambda_handler({"predict_only": True, "target_date": "2026-11-02"}, None)

    assert mock_predict.call_args[0][0] == ALL_AREAS
