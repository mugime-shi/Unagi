"""
Tests for /api/v1/prices/* endpoints and price_service helpers.

Uses an in-memory SQLite DB with StaticPool so all connections share the same
in-memory database (avoids "no such table" errors between fixtures/requests).
No PostgreSQL required to run these tests.
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.services.entsoe_client import EntsoEError, PricePoint
from app.services.price_service import (
    _generate_mock_prices,
    find_cheapest_window,
    get_or_fetch_prices,
    get_prices_for_date,
    get_prices_for_date_range,
    upsert_prices,
)

# ---------------------------------------------------------------------------
# In-memory SQLite with StaticPool (single shared connection)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_point(hour: int, price_eur: float = 50.0) -> PricePoint:
    ts = datetime(2026, 3, 11, hour, 0, tzinfo=timezone.utc)
    return PricePoint(
        timestamp_utc=ts,
        price_eur_mwh=price_eur,
        price_sek_kwh=round(price_eur * 11 / 1000, 4),
        resolution="PT60M",
    )


# ---------------------------------------------------------------------------
# price_service unit tests
# ---------------------------------------------------------------------------

def test_upsert_prices_inserts_rows(db):
    points = [_make_point(h) for h in range(3)]
    count = upsert_prices(db, points)
    assert count == 3


def test_upsert_prices_is_idempotent(db):
    upsert_prices(db, [_make_point(0, price_eur=50.0)])
    upsert_prices(db, [_make_point(0, price_eur=80.0)])  # same timestamp, new price

    rows = get_prices_for_date(db, date(2026, 3, 11))
    assert len(rows) == 1
    assert float(rows[0].price_eur_mwh) == 80.0


def test_get_prices_for_date_empty(db):
    rows = get_prices_for_date(db, date(2026, 3, 11))
    assert rows == []


def test_generate_mock_prices_returns_24_hours():
    prices = _generate_mock_prices(date(2026, 3, 11))
    assert len(prices) == 24
    assert all(p["is_mock"] for p in prices)
    assert all(p["price_sek_kwh"] > 0 for p in prices)


def test_mock_prices_realistic_range():
    prices = _generate_mock_prices(date(2026, 3, 11))
    sek_values = [p["price_sek_kwh"] for p in prices]
    # SE3 typical range: 0.20 – 1.20 SEK/kWh
    assert min(sek_values) >= 0.15
    assert max(sek_values) <= 1.30


def test_get_or_fetch_prices_falls_back_to_mock(db):
    with patch("app.services.price_service.fetch_day_ahead_prices", side_effect=EntsoEError("no key")):
        prices, is_mock = get_or_fetch_prices(db, date(2026, 3, 11))
    assert is_mock is True
    assert len(prices) == 24


def test_get_or_fetch_prices_returns_db_data(db):
    upsert_prices(db, [_make_point(h) for h in range(24)])
    prices, is_mock = get_or_fetch_prices(db, date(2026, 3, 11))
    assert is_mock is False
    assert len(prices) == 24


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

def test_get_today_prices_returns_200(client):
    response = client.get("/api/v1/prices/today")
    assert response.status_code == 200


def test_get_today_prices_response_shape(client):
    data = client.get("/api/v1/prices/today").json()
    assert data["area"] == "SE3"
    assert "date" in data
    assert "prices" in data
    assert "summary" in data
    assert "is_mock" in data
    assert "count" in data


def test_get_today_prices_mock_when_no_db_data(client):
    with patch("app.services.price_service.fetch_day_ahead_prices", side_effect=EntsoEError("no key")):
        data = client.get("/api/v1/prices/today").json()
    assert data["is_mock"] is True
    assert data["count"] == 24


def test_get_today_prices_real_data_when_db_populated(client, db):
    upsert_prices(db, [_make_point(h) for h in range(24)])
    data = client.get("/api/v1/prices/today").json()
    assert data["is_mock"] is False


def test_get_tomorrow_prices_returns_200(client):
    response = client.get("/api/v1/prices/tomorrow")
    assert response.status_code == 200
    data = response.json()
    assert "prices" in data
    assert data["count"] > 0


def test_summary_min_max_avg(client):
    summary = client.get("/api/v1/prices/today").json()["summary"]
    assert summary["min_sek_kwh"] <= summary["avg_sek_kwh"] <= summary["max_sek_kwh"]


def test_tomorrow_has_published_field(client):
    data = client.get("/api/v1/prices/tomorrow").json()
    assert "published" in data


# ---------------------------------------------------------------------------
# range endpoint
# ---------------------------------------------------------------------------

def test_range_returns_200(client, db):
    upsert_prices(db, [_make_point(h) for h in range(24)], "SE3")
    resp = client.get("/api/v1/prices/range?start=2026-03-11&end=2026-03-11")
    assert resp.status_code == 200


def test_range_response_shape(client, db):
    upsert_prices(db, [_make_point(h) for h in range(24)], "SE3")
    data = client.get("/api/v1/prices/range?start=2026-03-11&end=2026-03-11").json()
    assert data["area"] == "SE3"
    assert len(data["dates"]) == 1
    assert "summary" in data["dates"][0]


def test_range_end_before_start_returns_422(client):
    resp = client.get("/api/v1/prices/range?start=2026-03-12&end=2026-03-11")
    assert resp.status_code == 422


def test_range_too_large_returns_422(client):
    resp = client.get("/api/v1/prices/range?start=2026-01-01&end=2026-03-01")
    assert resp.status_code == 422


def test_range_empty_db_returns_empty_prices(client):
    data = client.get("/api/v1/prices/range?start=2026-03-11&end=2026-03-11").json()
    assert data["dates"][0]["count"] == 0


# ---------------------------------------------------------------------------
# cheapest-hours endpoint
# ---------------------------------------------------------------------------

def test_cheapest_hours_returns_200(client):
    resp = client.get("/api/v1/prices/cheapest-hours?date=2026-03-11&duration=2")
    assert resp.status_code == 200


def test_cheapest_hours_response_shape(client):
    data = client.get("/api/v1/prices/cheapest-hours?date=2026-03-11&duration=2").json()
    assert "cheapest_window" in data
    w = data["cheapest_window"]
    assert w["duration_hours"] == 2
    assert "start_utc" in w
    assert "end_utc" in w
    assert "avg_sek_kwh" in w
    assert len(w["slots"]) == 2


def test_cheapest_hours_finds_correct_window(client):
    # Use find_cheapest_window directly via the mock-data path (no ENTSO-E, no DB)
    # Mock prices: first 2 hours are cheap (0.11), rest expensive (1.10)
    from datetime import timedelta
    cheap_prices = []
    base = datetime(2026, 3, 10, 23, 0, tzinfo=timezone.utc)
    for h in range(24):
        price = 0.11 if h < 2 else 1.10
        cheap_prices.append({
            "timestamp_utc": (base + timedelta(hours=h)).isoformat(),
            "price_sek_kwh": price,
            "price_eur_mwh": round(price / 11 * 1000, 2),
            "resolution": "PT60M",
            "is_mock": True,
        })

    with patch("app.routers.prices.get_or_fetch_prices", return_value=(cheap_prices, True)):
        data = client.get("/api/v1/prices/cheapest-hours?date=2026-03-11&duration=2").json()

    w = data["cheapest_window"]
    assert w["avg_sek_kwh"] < 0.20  # should find the cheap 0.11 window


# ---------------------------------------------------------------------------
# find_cheapest_window unit tests
# ---------------------------------------------------------------------------

def test_find_cheapest_window_returns_none_for_empty():
    assert find_cheapest_window([], 2) is None


def test_find_cheapest_window_picks_minimum():
    prices = _generate_mock_prices(date(2026, 3, 11))
    window = find_cheapest_window(prices, 3)
    assert window is not None
    assert window["duration_hours"] == 3
    # The cheapest window avg must be at or below the overall average
    overall_avg = sum(p["price_sek_kwh"] for p in prices) / len(prices)
    assert window["avg_sek_kwh"] <= overall_avg


# ---------------------------------------------------------------------------
# CET/CEST timezone bucketing tests
# ---------------------------------------------------------------------------

def test_stockholm_timezone_cest_boundary():
    """
    22:00 UTC in summer (CEST = UTC+2) is midnight Stockholm → next calendar day.
    This verifies the fix over the old UTC+1 hardcoded offset.
    """
    from app.routers.prices import _to_stockholm_date
    # 2025-07-01 22:00 UTC = 2025-07-02 00:00 CEST  → 2025-07-02
    dt = datetime(2025, 7, 1, 22, 0, tzinfo=timezone.utc)
    assert _to_stockholm_date(dt) == date(2025, 7, 2)

    # 2025-07-01 21:59 UTC = 2025-07-01 23:59 CEST  → 2025-07-01
    dt2 = datetime(2025, 7, 1, 21, 59, tzinfo=timezone.utc)
    assert _to_stockholm_date(dt2) == date(2025, 7, 1)


def test_stockholm_timezone_cet_boundary():
    """
    23:00 UTC in winter (CET = UTC+1) is midnight Stockholm → next calendar day.
    """
    from app.routers.prices import _to_stockholm_date
    # 2026-01-05 23:00 UTC = 2026-01-06 00:00 CET  → 2026-01-06
    dt = datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc)
    assert _to_stockholm_date(dt) == date(2026, 1, 6)

    # 2026-01-05 22:59 UTC = 2026-01-05 23:59 CET  → 2026-01-05
    dt2 = datetime(2026, 1, 5, 22, 59, tzinfo=timezone.utc)
    assert _to_stockholm_date(dt2) == date(2026, 1, 5)


def test_history_cest_bucketing_via_endpoint(client, db):
    """History endpoint correctly buckets CEST-boundary prices across calendar dates."""
    # Use dates within 365-day window; days=365 is max allowed
    # 2025-07-01 22:00 UTC = 2025-07-02 00:00 CEST → should appear under 2025-07-02
    # 2025-07-01 21:00 UTC = 2025-07-01 23:00 CEST → should appear under 2025-07-01
    points = [
        PricePoint(
            timestamp_utc=datetime(2025, 7, 1, 21, 0, tzinfo=timezone.utc),
            price_eur_mwh=50.0, price_sek_kwh=0.55, resolution="PT60M",
        ),
        PricePoint(
            timestamp_utc=datetime(2025, 7, 1, 22, 0, tzinfo=timezone.utc),
            price_eur_mwh=60.0, price_sek_kwh=0.66, resolution="PT60M",
        ),
    ]
    upsert_prices(db, points)

    response = client.get("/api/v1/prices/history?days=365")
    assert response.status_code == 200
    by_date = {d["date"]: d for d in response.json()["daily"] if d["avg_sek_kwh"] is not None}

    assert "2025-07-01" in by_date, "21:00 UTC (23:00 CEST) must bucket to 2025-07-01"
    assert "2025-07-02" in by_date, "22:00 UTC (00:00 CEST next day) must bucket to 2025-07-02"
    assert abs(by_date["2025-07-01"]["avg_sek_kwh"] - 0.55) < 0.01
    assert abs(by_date["2025-07-02"]["avg_sek_kwh"] - 0.66) < 0.01
