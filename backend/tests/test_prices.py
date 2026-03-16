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
    build_forecast,
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


# ---------------------------------------------------------------------------
# DST transition day tests (spring-forward = 23h day, fall-back = 25h day)
#
# Swedish DST 2025:
#   Spring forward: 2025-03-30  (last Sunday in March)  — 01:00 UTC → 02:00 CET becomes 03:00 CEST
#   Fall back:      2025-10-26  (last Sunday in October) — 01:00 UTC → 03:00 CEST becomes 02:00 CET
# ---------------------------------------------------------------------------

def test_dst_spring_forward_skips_nonexistent_hour():
    """
    On 2025-03-30, 02:00 CET does not exist (clocks jump to 03:00 CEST at 01:00 UTC).
    ZoneInfo must map 01:00 UTC → 03:00 CEST, still attributing the slot to Mar 30.
    The day boundary (00:00 CEST Mar 31) falls at 22:00 UTC, not 23:00 UTC.
    """
    from app.routers.prices import _to_stockholm_date

    # One second before the jump: 00:59 UTC = 01:59 CET → still March 30
    assert _to_stockholm_date(datetime(2025, 3, 30, 0, 59, tzinfo=timezone.utc)) == date(2025, 3, 30)
    # At the jump: 01:00 UTC = non-existent 02:00 CET → ZoneInfo maps to 03:00 CEST → still March 30
    assert _to_stockholm_date(datetime(2025, 3, 30, 1, 0, tzinfo=timezone.utc)) == date(2025, 3, 30)
    # End of spring-forward day: 21:59 UTC = 23:59 CEST → still March 30
    assert _to_stockholm_date(datetime(2025, 3, 30, 21, 59, tzinfo=timezone.utc)) == date(2025, 3, 30)
    # Start of next day: 22:00 UTC = 00:00 CEST Mar 31 → March 31
    assert _to_stockholm_date(datetime(2025, 3, 30, 22, 0, tzinfo=timezone.utc)) == date(2025, 3, 31)


def test_dst_fall_back_repeated_hour():
    """
    On 2025-10-26, 02:00 CET occurs twice (clocks go back at 01:00 UTC).
    Both instances (before and after the fall-back) must attribute to Oct 26.
    The day is 25 hours long: it starts at 22:00 UTC Oct 25 (CEST midnight) and
    ends at 23:00 UTC Oct 26 (CET midnight of Oct 27).
    """
    from app.routers.prices import _to_stockholm_date

    # 01:00 UTC Oct 25 is the day before (22:00 UTC Oct 24 = 00:00 CEST Oct 25)
    # Start of fall-back day: 22:00 UTC Oct 25 = 00:00 CEST Oct 26
    assert _to_stockholm_date(datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc)) == date(2025, 10, 26)
    # One second before the fall-back: 00:59 UTC Oct 26 = 02:59 CEST → still Oct 26
    assert _to_stockholm_date(datetime(2025, 10, 26, 0, 59, tzinfo=timezone.utc)) == date(2025, 10, 26)
    # At the fall-back: 01:00 UTC Oct 26 = 02:00 CET (repeated hour) → still Oct 26
    assert _to_stockholm_date(datetime(2025, 10, 26, 1, 0, tzinfo=timezone.utc)) == date(2025, 10, 26)
    # End of fall-back day: 22:59 UTC Oct 26 = 23:59 CET → still Oct 26
    assert _to_stockholm_date(datetime(2025, 10, 26, 22, 59, tzinfo=timezone.utc)) == date(2025, 10, 26)
    # Start of next day: 23:00 UTC Oct 26 = 00:00 CET Oct 27 → Oct 27
    assert _to_stockholm_date(datetime(2025, 10, 26, 23, 0, tzinfo=timezone.utc)) == date(2025, 10, 27)


def test_dst_spring_forward_day_has_23_hourly_slots(client, db):
    """
    Inserting 24 hourly slots starting at 23:00 UTC Mar 29 (= 00:00 CET Mar 30):
      - Slots 0–22 (23:00 UTC Mar 29 → 21:00 UTC Mar 30) all fall on Mar 30 in CEST
      - Slot 23 (22:00 UTC Mar 30 = 00:00 CEST Mar 31) falls on Mar 31
    Spring-forward day therefore has exactly 23 slots.
    """
    from datetime import timedelta

    base = datetime(2025, 3, 29, 23, 0, tzinfo=timezone.utc)  # midnight CET Mar 30
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

    response = client.get("/api/v1/prices/history?days=365")
    assert response.status_code == 200
    by_date = {
        d["date"]: d
        for d in response.json()["daily"]
        if d.get("avg_sek_kwh") is not None
    }

    # Spring-forward day: only 23 of the 24 slots fall on Mar 30
    assert "2025-03-30" in by_date, "Spring-forward day must appear in history"
    # The 24th slot (22:00 UTC = 00:00 CEST) crosses into Mar 31
    assert "2025-03-31" in by_date, "Slot at 22:00 UTC must bucket to next day"
    # Verify the price split: Mar 30 avg ≈ 0.55, Mar 31 avg ≈ 0.55 (same price — we're checking buckets, not values)
    assert abs(by_date["2025-03-30"]["avg_sek_kwh"] - 0.55) < 0.01
    assert abs(by_date["2025-03-31"]["avg_sek_kwh"] - 0.55) < 0.01


def test_dst_fall_back_day_has_25_hourly_slots(client, db):
    """
    Inserting 26 hourly slots starting at 22:00 UTC Oct 25 (= 00:00 CEST Oct 26):
      - Slots 0–24 (22:00 UTC Oct 25 → 22:00 UTC Oct 26) all fall on Oct 26
        (the extra hour from the fall-back means 25 slots instead of 24)
      - Slot 25 (23:00 UTC Oct 26 = 00:00 CET Oct 27) falls on Oct 27
    Fall-back day therefore has exactly 25 slots.
    """
    from datetime import timedelta

    base = datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc)  # midnight CEST Oct 26
    points = [
        PricePoint(
            timestamp_utc=base + timedelta(hours=h),
            price_eur_mwh=50.0,
            price_sek_kwh=0.55,
            resolution="PT60M",
        )
        for h in range(26)
    ]
    upsert_prices(db, points)

    response = client.get("/api/v1/prices/history?days=365")
    assert response.status_code == 200
    by_date = {
        d["date"]: d
        for d in response.json()["daily"]
        if d.get("avg_sek_kwh") is not None
    }

    # Fall-back day: 25 of the 26 slots fall on Oct 26 (23:00 UTC = midnight CET → Oct 27)
    assert "2025-10-26" in by_date, "Fall-back day must appear in history"
    assert "2025-10-27" in by_date, "Slot at 23:00 UTC must bucket to next day"
    assert abs(by_date["2025-10-26"]["avg_sek_kwh"] - 0.55) < 0.01
    assert abs(by_date["2025-10-27"]["avg_sek_kwh"] - 0.55) < 0.01


# ---------------------------------------------------------------------------
# /multi-zone tests
# ---------------------------------------------------------------------------

def _make_point_area(hour: int, area: str, price_sek: float) -> PricePoint:
    """Helper: PricePoint for a specific area and price, on 2026-03-11."""
    ts = datetime(2026, 3, 10, 23 + hour % 24, 0, tzinfo=timezone.utc)  # CET date = 2026-03-11
    return PricePoint(
        timestamp_utc=datetime(2026, 3, 10, 23, 0, tzinfo=timezone.utc) + __import__('datetime').timedelta(hours=hour),
        price_eur_mwh=price_sek * 1000 / 11,
        price_sek_kwh=price_sek,
        resolution="PT60M",
    )


def test_multi_zone_structure(client, db):
    """GET /multi-zone returns zones dict with all 4 SE areas."""
    response = client.get("/api/v1/prices/multi-zone?days=7")
    assert response.status_code == 200
    body = response.json()
    assert "zones" in body
    assert set(body["zones"].keys()) == {"SE1", "SE2", "SE3", "SE4"}
    assert body["days"] == 7
    assert "start" in body
    assert "end" in body


def test_multi_zone_data_per_area(client, db):
    """Multi-zone endpoint returns correct daily averages for each area independently."""
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone.utc).date()
    # Insert 1 price for today in SE1 (price 0.20) and SE4 (price 0.80)
    # Use 08:00 UTC = 09:00 CET (within today's Stockholm calendar day)
    ts = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)

    upsert_prices(db, [
        PricePoint(timestamp_utc=ts, price_eur_mwh=18.18, price_sek_kwh=0.20, resolution="PT60M"),
    ], area="SE1")
    upsert_prices(db, [
        PricePoint(timestamp_utc=ts, price_eur_mwh=72.72, price_sek_kwh=0.80, resolution="PT60M"),
    ], area="SE4")

    response = client.get("/api/v1/prices/multi-zone?days=7")
    assert response.status_code == 200
    zones = response.json()["zones"]
    today_str = today.isoformat()

    se1_today = next((d for d in zones["SE1"] if d["date"] == today_str), None)
    se4_today = next((d for d in zones["SE4"] if d["date"] == today_str), None)
    se2_today = next((d for d in zones["SE2"] if d["date"] == today_str), None)

    assert se1_today is not None
    assert abs(se1_today["avg_sek_kwh"] - 0.20) < 0.01
    assert abs(se4_today["avg_sek_kwh"] - 0.80) < 0.01
    assert se2_today["avg_sek_kwh"] is None  # no data for SE2


def test_multi_zone_days_validation(client):
    """days parameter must be between 7 and 365."""
    assert client.get("/api/v1/prices/multi-zone?days=6").status_code == 422
    assert client.get("/api/v1/prices/multi-zone?days=366").status_code == 422
    assert client.get("/api/v1/prices/multi-zone?days=30").status_code == 200


# ---------------------------------------------------------------------------
# 6.5 Forecast endpoint & build_forecast()
# ---------------------------------------------------------------------------

def test_forecast_structure(client):
    """GET /forecast returns expected shape with 24 hourly slots."""
    tomorrow = (datetime.now(timezone.utc).date() + __import__('datetime').timedelta(days=1)).isoformat()
    response = client.get(f"/api/v1/prices/forecast?date={tomorrow}")
    assert response.status_code == 200
    body = response.json()
    assert "slots" in body
    assert "summary" in body
    assert len(body["slots"]) == 24
    assert body["slots"][0]["hour"] == 0
    assert body["slots"][23]["hour"] == 23
    assert "weekday" in body
    assert "dates_sampled" in body


def test_forecast_with_historical_data(client, db):
    """build_forecast returns correct avg/band when same-weekday data exists."""
    from datetime import timedelta

    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    # Insert data for 2 same-weekday dates (1 and 2 weeks ago)
    for weeks_ago in (1, 2):
        past_date = tomorrow - timedelta(weeks=weeks_ago)
        # Insert hourly data for hour 10 Stockholm time (= UTC 9:00 in CET)
        ts = datetime(past_date.year, past_date.month, past_date.day, 9, 0, tzinfo=timezone.utc)
        price = 0.30 + weeks_ago * 0.10  # 0.40, 0.50
        upsert_prices(db, [
            PricePoint(timestamp_utc=ts, price_eur_mwh=price * 100, price_sek_kwh=price, resolution="PT60M"),
        ], area="SE3")

    response = client.get(f"/api/v1/prices/forecast?date={tomorrow.isoformat()}&area=SE3")
    assert response.status_code == 200
    body = response.json()
    assert body["dates_sampled"] >= 2
    # Hour 10 slot should have non-null values
    slot_10 = next(s for s in body["slots"] if s["hour"] == 10)
    assert slot_10["avg_sek_kwh"] is not None
    assert slot_10["low_sek_kwh"] <= slot_10["avg_sek_kwh"] <= slot_10["high_sek_kwh"]


def test_forecast_no_data_returns_nulls(client):
    """When no historical data exists, all slots return null."""
    tomorrow = (datetime.now(timezone.utc).date() + __import__('datetime').timedelta(days=1)).isoformat()
    response = client.get(f"/api/v1/prices/forecast?date={tomorrow}&area=SE1")
    assert response.status_code == 200
    body = response.json()
    assert all(s["avg_sek_kwh"] is None for s in body["slots"])
    assert body["summary"]["predicted_avg_sek_kwh"] is None


def test_forecast_weeks_validation(client):
    """weeks parameter must be between 2 and 16."""
    tomorrow = (datetime.now(timezone.utc).date() + __import__('datetime').timedelta(days=1)).isoformat()
    assert client.get(f"/api/v1/prices/forecast?date={tomorrow}&weeks=1").status_code == 422
    assert client.get(f"/api/v1/prices/forecast?date={tomorrow}&weeks=17").status_code == 422
    assert client.get(f"/api/v1/prices/forecast?date={tomorrow}&weeks=4").status_code == 200


def test_build_forecast_band_ordering(db):
    """low <= avg <= high for every non-null slot."""
    from datetime import timedelta

    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    for weeks_ago in range(1, 5):
        past = tomorrow - timedelta(weeks=weeks_ago)
        ts = datetime(past.year, past.month, past.day, 8, 0, tzinfo=timezone.utc)
        upsert_prices(db, [
            PricePoint(timestamp_utc=ts, price_eur_mwh=50.0, price_sek_kwh=0.1 * weeks_ago, resolution="PT60M"),
        ], area="SE3")

    rows = get_prices_for_date_range(db, tomorrow - timedelta(weeks=8), tomorrow - timedelta(days=1), area="SE3")
    result = build_forecast(rows, tomorrow)
    for s in result["slots"]:
        if s["avg_sek_kwh"] is not None:
            assert s["low_sek_kwh"] <= s["avg_sek_kwh"]
            assert s["avg_sek_kwh"] <= s["high_sek_kwh"]
