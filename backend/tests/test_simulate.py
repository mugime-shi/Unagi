"""
Tests for /api/v1/simulate/consumption and consumption_optimizer helpers.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.services.consumption_optimizer import (
    PriceComponents,
    _avg_spot_dynamic,
    _avg_spot_optimized,
    simulate,
)
from app.services.entsoe_client import PricePoint
from app.services.price_service import upsert_prices
from app.utils.timezone import stockholm_today

# ---------------------------------------------------------------------------
# Shared SQLite test DB
# ---------------------------------------------------------------------------

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


def _make_price_point(ts: datetime, sek: float) -> PricePoint:
    return PricePoint(
        timestamp_utc=ts,
        price_eur_mwh=round(sek / 11 * 1000, 2),
        price_sek_kwh=sek,
        resolution="PT60M",
    )


def _insert_30_days_prices(db, sek: float = 0.50):
    """Insert uniform prices for the last 30 days."""
    today = stockholm_today()
    for offset in range(30):
        day = today - timedelta(days=offset)
        # CET window: day-1 23:00 UTC → day 22:00 UTC
        base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=1)
        points = [
            _make_price_point(base + timedelta(hours=h), sek)
            for h in range(24)
        ]
        upsert_prices(db, points)


# ---------------------------------------------------------------------------
# Unit tests: consumption_optimizer helpers
# ---------------------------------------------------------------------------

def test_avg_spot_dynamic_flat():
    prices = [0.50] * 24
    assert _avg_spot_dynamic(prices) == pytest.approx(0.50)


def test_avg_spot_dynamic_empty():
    assert _avg_spot_dynamic([]) == 0.0


def test_avg_spot_optimized_shifts_to_cheap():
    # Day with 8 cheap hours (0.20) and 16 expensive (1.00)
    cheap = [0.20] * 8
    expensive = [1.00] * 16
    prices_day = cheap + expensive
    result = _avg_spot_optimized([prices_day], shiftable_pct=0.30, shift_hours=8)
    # full_avg = (8*0.20 + 16*1.00) / 24 ≈ 0.7333
    # optimized = 0.30 * 0.20 + 0.70 * full_avg
    full_avg = (8 * 0.20 + 16 * 1.00) / 24
    expected = 0.30 * 0.20 + 0.70 * full_avg
    assert result == pytest.approx(expected, rel=1e-3)


def test_avg_spot_optimized_less_than_dynamic():
    prices_day = [0.20] * 8 + [1.00] * 16
    dynamic = _avg_spot_dynamic(prices_day)
    optimized = _avg_spot_optimized([prices_day])
    assert optimized < dynamic


def test_price_components_total():
    comp = PriceComponents()
    # (0.50 + 0.086 + 0.30 + 0.439 + 0.01) * 1.25
    expected = (0.50 + 0.835) * 1.25
    assert comp.total_per_kwh(0.50) == pytest.approx(expected, rel=1e-3)


def test_simulate_basic():
    prices = [0.50] * 240   # 10 days × 24h
    daily_groups = [[0.50] * 24 for _ in range(10)]
    result = simulate(
        monthly_kwh=500,
        fixed_price_sek_kwh=1.80,
        spot_prices_sek=prices,
        daily_price_groups=daily_groups,
    )
    assert result["fixed"]["monthly_cost_sek"] == pytest.approx(900.0)
    assert result["dynamic"]["monthly_cost_sek"] > 0
    assert result["optimized"]["monthly_cost_sek"] <= result["dynamic"]["monthly_cost_sek"]


def test_simulate_savings_positive_when_dynamic_cheaper():
    # If dynamic is cheaper than fixed, savings should be positive
    prices = [0.30] * 240   # cheap spot → dynamic cheaper than 1.80 fixed
    daily_groups = [[0.30] * 24 for _ in range(10)]
    result = simulate(500, 1.80, prices, daily_groups)
    assert result["dynamic"]["savings_vs_fixed_sek"] > 0
    assert result["optimized"]["savings_vs_fixed_sek"] > 0


def test_simulate_optimized_always_leq_dynamic():
    import random
    random.seed(42)
    prices = [random.uniform(0.20, 1.20) for _ in range(240)]
    daily_groups = [prices[i * 24 : (i + 1) * 24] for i in range(10)]
    result = simulate(500, 1.80, prices, daily_groups)
    assert result["optimized"]["monthly_cost_sek"] <= result["dynamic"]["monthly_cost_sek"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

def test_simulate_consumption_returns_200(client, db):
    _insert_30_days_prices(db)
    resp = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": 500,
        "fixed_price_sek_kwh": 1.80,
    })
    assert resp.status_code == 200


def test_simulate_consumption_response_shape(client, db):
    _insert_30_days_prices(db)
    data = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": 500,
        "fixed_price_sek_kwh": 1.80,
    }).json()
    assert "fixed" in data
    assert "dynamic" in data
    assert "optimized" in data
    assert "period" in data
    assert "price_components" in data
    assert data["fixed"]["monthly_cost_sek"] == pytest.approx(900.0)


def test_simulate_consumption_503_when_no_data(client):
    resp = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": 500,
        "fixed_price_sek_kwh": 1.80,
    })
    assert resp.status_code == 503


def test_simulate_consumption_optimized_leq_dynamic(client, db):
    _insert_30_days_prices(db, sek=0.40)
    data = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": 500,
        "fixed_price_sek_kwh": 1.80,
    }).json()
    # With uniform prices, optimized ≈ dynamic (allow small floating-point rounding)
    assert data["optimized"]["monthly_cost_sek"] <= data["dynamic"]["monthly_cost_sek"] + 0.10


def test_simulate_consumption_custom_shiftable(client, db):
    _insert_30_days_prices(db)
    data = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": 500,
        "fixed_price_sek_kwh": 1.80,
        "shiftable_pct": 0.50,
        "shift_hours": 6,
    }).json()
    assert data["optimized"]["description"] == "Shift 50% of daily consumption to cheapest 6h"


def test_simulate_consumption_invalid_kwh(client):
    resp = client.post("/api/v1/simulate/consumption", json={
        "monthly_kwh": -10,
        "fixed_price_sek_kwh": 1.80,
    })
    assert resp.status_code == 422
