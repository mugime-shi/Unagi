"""
Tests for /api/v1/notify/* endpoints and notify_service helpers.

Push sending is mocked — no real VAPID keys or network needed.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.push_subscription import PushSubscription
from app.services.notify_service import _build_notification, notify_subscribers

# ---------------------------------------------------------------------------
# In-memory SQLite (same pattern as test_prices.py)
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
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

SAMPLE_SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint",
    "p256dh": "BNSfake256dhkey==",
    "auth": "fakeauthsecret==",
    "area": "SE3",
}


# ---------------------------------------------------------------------------
# VAPID public key endpoint
# ---------------------------------------------------------------------------

def test_vapid_key_not_configured(client):
    """Returns 503 when VAPID keys are not set."""
    with patch("app.routers.notify.settings") as mock_settings:
        mock_settings.vapid_public_key = ""
        resp = client.get("/api/v1/notify/vapid-public-key")
    assert resp.status_code == 503


def test_vapid_key_configured(client):
    """Returns public key when VAPID_PUBLIC_KEY is set."""
    with patch("app.routers.notify.settings") as mock_settings:
        mock_settings.vapid_public_key = "BFakePublicKey123"
        resp = client.get("/api/v1/notify/vapid-public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == "BFakePublicKey123"


# ---------------------------------------------------------------------------
# Subscribe endpoint
# ---------------------------------------------------------------------------

def test_subscribe_creates_record(client, db):
    resp = client.post("/api/v1/notify/subscribe", json=SAMPLE_SUB)
    assert resp.status_code == 201
    assert resp.json()["status"] == "subscribed"

    sub = db.query(PushSubscription).first()
    assert sub is not None
    assert sub.endpoint == SAMPLE_SUB["endpoint"]
    assert sub.area == "SE3"


def test_subscribe_upserts_on_same_endpoint(client, db):
    """Re-subscribing the same endpoint updates keys without creating a duplicate."""
    client.post("/api/v1/notify/subscribe", json=SAMPLE_SUB)
    updated = {**SAMPLE_SUB, "p256dh": "BNewKey==", "area": "SE1"}
    client.post("/api/v1/notify/subscribe", json=updated)

    subs = db.query(PushSubscription).all()
    assert len(subs) == 1
    assert subs[0].p256dh == "BNewKey=="
    assert subs[0].area == "SE1"


def test_subscribe_multiple_different_endpoints(client, db):
    client.post("/api/v1/notify/subscribe", json=SAMPLE_SUB)
    other = {**SAMPLE_SUB, "endpoint": "https://fcm.example.com/other"}
    client.post("/api/v1/notify/subscribe", json=other)
    assert db.query(PushSubscription).count() == 2


# ---------------------------------------------------------------------------
# Unsubscribe endpoint
# ---------------------------------------------------------------------------

def test_unsubscribe_removes_record(client, db):
    client.post("/api/v1/notify/subscribe", json=SAMPLE_SUB)
    resp = client.request(
        "DELETE",
        "/api/v1/notify/subscribe",
        json={"endpoint": SAMPLE_SUB["endpoint"]},
    )
    assert resp.status_code == 200
    assert db.query(PushSubscription).count() == 0


def test_unsubscribe_nonexistent_is_idempotent(client):
    """Deleting a subscription that doesn't exist returns 200 (not 404)."""
    resp = client.request(
        "DELETE",
        "/api/v1/notify/subscribe",
        json={"endpoint": "https://nonexistent.example.com"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# notify_service: _build_notification
# ---------------------------------------------------------------------------

def test_build_notification_no_data(db):
    """Returns None when no tomorrow prices are in DB."""
    result = _build_notification(db, "SE3")
    assert result is None


def test_build_notification_with_prices(db):
    """Returns notification dict with title and body when prices exist."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    from app.models.spot_price import SpotPrice

    tomorrow = (datetime.now(tz=ZoneInfo("Europe/Stockholm")) + timedelta(days=1)).date()
    # Insert 3 hourly slots for tomorrow
    for hour, price in [(0, 0.50), (1, 0.30), (2, 0.70)]:
        ts = datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, tzinfo=timezone.utc)
        db.add(SpotPrice(
            area="SE3",
            timestamp_utc=ts,
            price_eur_mwh=50.0,
            price_sek_kwh=price,
            resolution="PT60M",
        ))
    db.commit()

    result = _build_notification(db, "SE3")
    assert result is not None
    assert "SE3" in result["body"]
    assert "0.50" in result["body"]  # avg = (0.50+0.30+0.70)/3 = 0.50
    assert "0.30" in result["body"]  # min
    assert "0.70" in result["body"]  # max


# ---------------------------------------------------------------------------
# notify_service: notify_subscribers
# ---------------------------------------------------------------------------

def test_notify_no_subscribers(db):
    """Returns 0 sent when no subscriptions exist."""
    result = notify_subscribers(db, "SE3")
    assert result["sent"] == 0


def test_notify_skips_when_no_data(db):
    """Returns skipped=no_data when tomorrow's prices are not in DB."""
    db.add(PushSubscription(**SAMPLE_SUB))
    db.commit()

    result = notify_subscribers(db, "SE3")
    assert result.get("skipped") == "no_data"


def test_notify_sends_to_subscribers(db):
    """Sends notification to all matching subscribers (mocked)."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo

    from app.models.spot_price import SpotPrice

    db.add(PushSubscription(**SAMPLE_SUB))
    db.commit()

    tomorrow = (datetime.now(tz=ZoneInfo("Europe/Stockholm")) + timedelta(days=1)).date()
    ts = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, tzinfo=timezone.utc)
    db.add(SpotPrice(area="SE3", timestamp_utc=ts, price_eur_mwh=50.0,
                     price_sek_kwh=0.50, resolution="PT60M"))
    db.commit()

    with patch("app.services.notify_service._send_push", return_value=True) as mock_send:
        result = notify_subscribers(db, "SE3")

    assert result["sent"] == 1
    assert result["failed"] == 0
    mock_send.assert_called_once()
