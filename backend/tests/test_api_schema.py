"""
API response schema tests — ensures backend responses match frontend TypeScript types.

These tests prevent silent breakage where the API returns different key names
than the frontend expects (e.g. 'hydro' vs 'hydro_mw'). Run on every CI push.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.forecast_accuracy import ForecastAccuracy  # noqa: F401
from app.models.generation_mix import GenerationMix
from app.services.entsoe_client import PricePoint
from app.services.price_service import upsert_prices

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


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_prices(db, target_date):
    """Insert 24 hourly price points for target_date."""
    from app.utils.timezone import stockholm_midnight_utc

    base = stockholm_midnight_utc(target_date)
    points = [
        PricePoint(
            timestamp_utc=base + timedelta(hours=h),
            price_eur_mwh=50.0,
            price_sek_kwh=0.55,
            resolution="PT60M",
        )
        for h in range(24)
    ]
    upsert_prices(db, points)


def _seed_generation(db, target_date):
    """Insert generation mix data for target_date.

    Uses naive UTC datetimes (no tzinfo) because SQLite stores datetimes
    without timezone info. The application code handles this via
    replace(tzinfo=utc) guards.
    """

    # Use naive UTC datetimes — SQLite doesn't store tzinfo.
    # Start from "just now" minus a few hours so the staleness check passes
    # (router considers data stale if latest_ts > 45 min old).
    now_naive = datetime.utcnow().replace(second=0, microsecond=0)
    base = now_naive - timedelta(hours=2)
    psr_types = ["B01", "B11", "B14", "B16", "B18", "B19"]  # fossil, hydro, nuclear, solar, wind, other
    for h in range(3):
        ts = base + timedelta(hours=h)
        for psr in psr_types:
            db.add(
                GenerationMix(
                    area="SE3",
                    timestamp_utc=ts,
                    psr_type=psr,
                    value_mw=1000.0 if psr == "B11" else 500.0,
                )
            )
    db.commit()


# ---------------------------------------------------------------------------
# /api/v1/prices/today — PricesResponse schema
# ---------------------------------------------------------------------------


class TestPricesSchema:
    """Verify /prices/today response matches frontend PricesResponse type."""

    def test_prices_today_top_level_keys(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_prices(db, today)

        resp = client.get("/api/v1/prices/today?area=SE3")
        assert resp.status_code == 200
        data = resp.json()

        # Frontend expects these exact top-level keys
        assert "date" in data
        assert "area" in data
        assert "count" in data
        assert "is_estimate" in data
        assert "prices" in data
        assert "summary" in data

    def test_prices_price_point_keys(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_prices(db, today)

        resp = client.get("/api/v1/prices/today?area=SE3")
        data = resp.json()
        assert len(data["prices"]) > 0

        price = data["prices"][0]
        # Frontend PricePoint type expects these keys
        assert "timestamp_utc" in price
        assert "price_sek_kwh" in price
        assert "price_eur_mwh" in price

    def test_prices_summary_keys(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_prices(db, today)

        resp = client.get("/api/v1/prices/today?area=SE3")
        summary = resp.json()["summary"]

        # Frontend PriceSummary type
        assert "min_sek_kwh" in summary
        assert "avg_sek_kwh" in summary
        assert "max_sek_kwh" in summary


# ---------------------------------------------------------------------------
# /api/v1/generation/today — GenerationResponse schema
# ---------------------------------------------------------------------------


class TestGenerationSchema:
    """Verify /generation/date response matches frontend GenerationPoint type.

    Uses /generation/date (DB-only, no live fetch) to avoid ENTSO-E API
    dependency and staleness check complications with SQLite.
    """

    def test_generation_top_level_keys(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_generation(db, today)

        resp = client.get(f"/api/v1/generation/date?date={today.isoformat()}&area=SE3")
        assert resp.status_code == 200
        data = resp.json()

        assert "area" in data
        assert "time_series" in data
        assert "renewable_pct" in data
        assert "carbon_free_pct" in data
        assert "carbon_intensity" in data
        assert "latest_slot" in data

    def test_generation_time_series_keys(self, client, db):
        """
        Frontend GenerationPoint expects: timestamp_utc, total_mw,
        hydro, wind, nuclear, solar, other, carbon_intensity.
        NOT hydro_mw, wind_mw, etc.
        """
        today = datetime.now(timezone.utc).date()
        _seed_generation(db, today)

        resp = client.get(f"/api/v1/generation/date?date={today.isoformat()}&area=SE3")
        ts = resp.json()["time_series"]
        assert len(ts) > 0

        entry = ts[0]
        # These are the EXACT keys the frontend reads
        assert "timestamp_utc" in entry
        assert "total_mw" in entry
        assert "hydro" in entry, "Frontend expects 'hydro', not 'hydro_mw'"
        assert "wind" in entry, "Frontend expects 'wind', not 'wind_mw'"
        assert "nuclear" in entry, "Frontend expects 'nuclear', not 'nuclear_mw'"
        assert "solar" in entry, "Frontend expects 'solar', not 'solar_mw'"
        assert "other" in entry, "Frontend expects 'other', not 'other_mw'"
        assert "carbon_intensity" in entry

        # These should NOT exist (old naming)
        assert "hydro_mw" not in entry, "API should return 'hydro', not 'hydro_mw'"
        assert "wind_mw" not in entry, "API should return 'wind', not 'wind_mw'"
        assert "nuclear_mw" not in entry

    def test_generation_values_are_numeric(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_generation(db, today)

        resp = client.get(f"/api/v1/generation/date?date={today.isoformat()}&area=SE3")
        entry = resp.json()["time_series"][0]

        assert isinstance(entry["hydro"], (int, float))
        assert isinstance(entry["wind"], (int, float))
        assert isinstance(entry["total_mw"], (int, float))


# ---------------------------------------------------------------------------
# /api/v1/prices/forecast/accuracy — ForecastAccuracyResponse schema
# ---------------------------------------------------------------------------


class TestForecastAccuracySchema:
    def test_accuracy_response_keys(self, client, db):
        resp = client.get("/api/v1/prices/forecast/accuracy?area=SE3")
        assert resp.status_code == 200
        data = resp.json()

        assert "area" in data
        assert "models" in data
        assert isinstance(data["models"], dict)


# ---------------------------------------------------------------------------
# /api/v1/prices/history — HistoryResponse schema
# ---------------------------------------------------------------------------


class TestHistorySchema:
    def test_history_daily_keys(self, client, db):
        today = datetime.now(timezone.utc).date()
        _seed_prices(db, today)

        resp = client.get("/api/v1/prices/history?days=7&area=SE3")
        assert resp.status_code == 200
        data = resp.json()

        assert "daily" in data
        assert len(data["daily"]) > 0

        day = data["daily"][0]
        assert "date" in day
        assert "avg_sek_kwh" in day


# ---------------------------------------------------------------------------
# SHAP persistence via record_predictions + get_retrospective
# ---------------------------------------------------------------------------


class TestShapPersistence:
    """Verify SHAP explanations are stored and returned via retrospective."""

    def test_record_predictions_with_shap(self, db):
        from app.services.backtest_service import get_retrospective, record_predictions

        target = datetime.now(timezone.utc).date()
        slots = [{"hour": h, "avg_sek_kwh": 0.5 + h * 0.01} for h in range(24)]
        shap = {
            "base_value": 0.55,
            "hours": [{"hour": h, "top": [{"group": "Wind", "impact": 0.1, "direction": "higher"}]} for h in range(24)],
        }

        n = record_predictions(db, target, "SE3", "lgbm", slots, shap_explanations=shap)
        assert n == 24

        result = get_retrospective(db, target, "SE3")
        assert "lgbm" in result["models"]
        assert result["shap_explanations"] is not None
        assert result["shap_explanations"]["base_value"] == 0.55
        assert len(result["shap_explanations"]["hours"]) == 24

    def test_record_predictions_without_shap(self, db):
        from app.services.backtest_service import get_retrospective, record_predictions

        target = datetime.now(timezone.utc).date()
        slots = [{"hour": h, "avg_sek_kwh": 0.5} for h in range(24)]

        record_predictions(db, target, "SE3", "same_weekday_avg", slots)
        result = get_retrospective(db, target, "SE3")
        assert result["shap_explanations"] is None

    def test_retrospective_endpoint_includes_shap(self, client, db):
        from app.services.backtest_service import record_predictions

        target = datetime.now(timezone.utc).date()
        slots = [{"hour": h, "avg_sek_kwh": 0.5} for h in range(24)]
        shap = {"base_value": 0.42, "hours": [{"hour": 0, "top": []}]}

        record_predictions(db, target, "SE3", "lgbm", slots, shap_explanations=shap)

        resp = client.get(f"/api/v1/prices/forecast/retrospective?date={target.isoformat()}&area=SE3")
        assert resp.status_code == 200
        data = resp.json()
        assert "shap_explanations" in data
        assert data["shap_explanations"]["base_value"] == 0.42
