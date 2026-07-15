"""
Tests for evaluation_service: regime-split MAE, capture rate, coverage by regime.

Uses an in-memory SQLite DB (same pattern as test_prices.py).
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.forecast_accuracy import ForecastAccuracy  # noqa: F401 — register with Base for create_all
from app.services.evaluation_service import (
    get_capture_rate,
    get_coverage_by_regime,
    get_regime_split,
)

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


def _insert_row(db, target_date, hour, predicted, actual, low=None, high=None, model="lgbm", area="SE3"):
    db.execute(
        text("""
        INSERT INTO forecast_accuracy
            (target_date, area, model_name, hour, predicted_sek_kwh,
             predicted_low_sek_kwh, predicted_high_sek_kwh, actual_sek_kwh)
        VALUES (:date, :area, :model, :hour, :predicted, :low, :high, :actual)
        """),
        {
            "date": target_date,
            "area": area,
            "model": model,
            "hour": hour,
            "predicted": predicted,
            "low": low,
            "high": high,
            "actual": actual,
        },
    )
    db.commit()


def _insert_day(db, target_date, model, predicted_by_hour, actual_by_hour, low=None, high=None):
    """Insert 24 hourly rows for one model/day."""
    for h in range(24):
        _insert_row(
            db,
            target_date,
            h,
            predicted=predicted_by_hour[h],
            actual=actual_by_hour[h],
            low=low[h] if low else None,
            high=high[h] if high else None,
            model=model,
        )


# ---------------------------------------------------------------------------
# Regime split
# ---------------------------------------------------------------------------


class TestRegimeSplit:
    def test_calm_volatile_tagging_and_win_rate(self, db):
        """Day 1: baseline MAE 0.2 (calm), model wins. Day 2: baseline 0.5 (volatile), model loses."""
        calm_day = date.today() - timedelta(days=2)
        vol_day = date.today() - timedelta(days=3)
        actual = [1.0] * 24

        # Calm day: baseline off by 0.2, model off by 0.1 → model wins
        _insert_day(db, calm_day, "same_weekday_avg", [1.2] * 24, actual)
        _insert_day(db, calm_day, "lgbm", [1.1] * 24, actual)
        # Volatile day: baseline off by 0.5, model off by 0.6 → model loses
        _insert_day(db, vol_day, "same_weekday_avg", [1.5] * 24, actual)
        _insert_day(db, vol_day, "lgbm", [1.6] * 24, actual)

        result = get_regime_split(db, area="SE3", days=30)

        assert result["n_days"] == 2
        assert result["regime_by_date"][calm_day] == "calm"
        assert result["regime_by_date"][vol_day] == "volatile"

        assert result["calm"]["n_days"] == 1
        assert result["calm"]["model_mae"] == pytest.approx(0.1)
        assert result["calm"]["baseline_mae"] == pytest.approx(0.2)
        assert result["calm"]["win_rate"] == 1.0

        assert result["volatile"]["n_days"] == 1
        assert result["volatile"]["model_mae"] == pytest.approx(0.6)
        assert result["volatile"]["baseline_mae"] == pytest.approx(0.5)
        assert result["volatile"]["win_rate"] == 0.0

    def test_threshold_boundary_is_volatile(self, db):
        """Baseline daily MAE exactly at threshold counts as volatile (>=)."""
        d = date.today() - timedelta(days=2)
        _insert_day(db, d, "same_weekday_avg", [1.35] * 24, [1.0] * 24)
        _insert_day(db, d, "lgbm", [1.1] * 24, [1.0] * 24)

        result = get_regime_split(db, area="SE3", days=30, threshold=0.35)
        assert result["regime_by_date"][d] == "volatile"

    def test_partial_day_excluded(self, db):
        """Days with fewer than min_hours scored hours are not tagged."""
        d = date.today() - timedelta(days=2)
        for h in range(10):  # only 10 hours
            _insert_row(db, d, h, predicted=1.2, actual=1.0, model="same_weekday_avg")
            _insert_row(db, d, h, predicted=1.1, actual=1.0, model="lgbm")

        result = get_regime_split(db, area="SE3", days=30)
        assert result["n_days"] == 0

    def test_empty_db(self, db):
        result = get_regime_split(db, area="SE3", days=30)
        assert result["n_days"] == 0
        assert result["calm"]["win_rate"] is None
        assert result["volatile"]["model_mae"] is None


# ---------------------------------------------------------------------------
# Capture rate
# ---------------------------------------------------------------------------


class TestCaptureRate:
    def test_perfect_picks(self, db):
        """Predicted ranking matches actual → capture 1.0."""
        d = date.today() - timedelta(days=2)
        actual = [0.1 * (h + 1) for h in range(24)]  # cheapest hours: 0, 1, 2
        _insert_day(db, d, "lgbm", actual, actual)  # predictions identical to actuals

        result = get_capture_rate(db, area="SE3", days=30)
        assert result["n_days"] == 1
        assert result["mean_capture"] == pytest.approx(1.0)

    def test_worst_picks_negative(self, db):
        """Predictions inverted → picks the most expensive hours → capture < 0."""
        d = date.today() - timedelta(days=2)
        actual = [0.1 * (h + 1) for h in range(24)]
        inverted = list(reversed(actual))  # predicts hour 23 cheapest
        _insert_day(db, d, "lgbm", inverted, actual)

        result = get_capture_rate(db, area="SE3", days=30)
        assert result["n_days"] == 1
        assert result["mean_capture"] < 0

    def test_flat_day_skipped(self, db):
        """Constant prices → nothing to capture → day skipped, counted."""
        d = date.today() - timedelta(days=2)
        _insert_day(db, d, "lgbm", [0.5] * 24, [0.5] * 24)

        result = get_capture_rate(db, area="SE3", days=30)
        assert result["n_days"] == 0
        assert result["n_days_skipped_flat"] == 1
        assert result["mean_capture"] is None
        assert result["mean_daily_spread_sek_kwh"] == pytest.approx(0.0)

    def test_partial_day_ignored(self, db):
        """Days without all 24 hours are not scored at all."""
        d = date.today() - timedelta(days=2)
        for h in range(20):
            _insert_row(db, d, h, predicted=0.1 * h, actual=0.1 * h)

        result = get_capture_rate(db, area="SE3", days=30)
        assert result["n_days"] == 0
        assert result["n_days_skipped_flat"] == 0

    def test_spread_reported_over_all_full_days(self, db):
        """Spread = mean(actual) - mean(cheapest 3 actuals), averaged over full days."""
        d = date.today() - timedelta(days=2)
        actual = [0.1 * (h + 1) for h in range(24)]
        _insert_day(db, d, "lgbm", actual, actual)

        result = get_capture_rate(db, area="SE3", days=30)
        # nothing/n = mean(actual) = 1.25 ; perfect/n = (0.1+0.2+0.3)/3 = 0.2
        assert result["mean_daily_spread_sek_kwh"] == pytest.approx(1.05)


# ---------------------------------------------------------------------------
# Coverage by regime
# ---------------------------------------------------------------------------


class TestCoverageByRegime:
    def test_split_coverage(self, db):
        """Calm day fully covered, volatile day fully uncovered."""
        calm_day = date.today() - timedelta(days=2)
        vol_day = date.today() - timedelta(days=3)
        actual = [1.0] * 24

        _insert_day(db, calm_day, "same_weekday_avg", [1.1] * 24, actual)
        _insert_day(db, calm_day, "lgbm", [1.0] * 24, actual, low=[0.8] * 24, high=[1.2] * 24)
        _insert_day(db, vol_day, "same_weekday_avg", [1.5] * 24, actual)
        _insert_day(db, vol_day, "lgbm", [1.6] * 24, actual, low=[1.4] * 24, high=[1.8] * 24)

        result = get_coverage_by_regime(db, area="SE3", days=30)
        assert result["calm"]["coverage_pct"] == 100.0
        assert result["volatile"]["coverage_pct"] == 0.0
        assert result["overall"]["coverage_pct"] == 50.0
        assert result["overall"]["n_samples"] == 48

    def test_untagged_days_count_in_overall_only(self, db):
        """Rows on days the baseline didn't score appear in overall but not calm/volatile."""
        d = date.today() - timedelta(days=2)
        _insert_day(db, d, "lgbm", [1.0] * 24, [1.0] * 24, low=[0.8] * 24, high=[1.2] * 24)
        # no baseline rows → day cannot be regime-tagged

        result = get_coverage_by_regime(db, area="SE3", days=30)
        assert result["overall"]["n_samples"] == 24
        assert result["calm"]["n_samples"] == 0
        assert result["volatile"]["n_samples"] == 0

    def test_rows_without_bounds_excluded(self, db):
        d = date.today() - timedelta(days=2)
        _insert_day(db, d, "same_weekday_avg", [1.1] * 24, [1.0] * 24)
        _insert_day(db, d, "lgbm", [1.0] * 24, [1.0] * 24)  # no low/high

        result = get_coverage_by_regime(db, area="SE3", days=30)
        assert result["overall"]["n_samples"] == 0
        assert result["overall"]["coverage_pct"] is None
