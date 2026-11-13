"""
GET /api/v1/generation/today reads the DB only; the hourly_generation scheduler task keeps it fresh.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.generation_mix import GenerationMix
from app.routers import generation as gen_router
from app.services.entsoe_client import EntsoEError
from app.utils.timezone import stockholm_midnight_utc, stockholm_today

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def client(monkeypatch):
    Base.metadata.create_all(bind=engine)
    gen_router._generation_cache.clear()

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    gen_router._generation_cache.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def fetch(monkeypatch):
    mock = MagicMock(side_effect=EntsoEError("no data"))
    monkeypatch.setattr(gen_router, "fetch_and_store_generation", mock)
    return mock


def _seed(day, hours_after_midnight=1):
    ts = stockholm_midnight_utc(day).replace(tzinfo=None) + timedelta(hours=hours_after_midnight)
    with TestingSessionLocal() as db:
        db.add(GenerationMix(area="SE3", timestamp_utc=ts, psr_type="B12", value_mw=100))
        db.commit()


def test_old_today_rows_are_served_without_live_fetch(client, fetch):
    _seed(stockholm_today(), hours_after_midnight=0)  # may be hours older than 45 min
    resp = client.get("/api/v1/generation/today?area=SE3")
    assert resp.status_code == 200
    assert resp.json()["date"] == stockholm_today().isoformat()
    fetch.assert_not_called()


def test_yesterday_rows_served_without_live_fetch(client, fetch):
    yesterday = stockholm_today() - timedelta(days=1)
    _seed(yesterday)
    resp = client.get("/api/v1/generation/today?area=SE3")
    assert resp.status_code == 200
    assert resp.json()["date"] == yesterday.isoformat()
    fetch.assert_not_called()


def test_empty_db_falls_back_to_live_fetch(client, fetch):
    resp = client.get("/api/v1/generation/today?area=SE3")
    assert resp.status_code == 404
    assert fetch.call_count == 2  # today, then yesterday
    assert fetch.call_args_list[0].args[1] == stockholm_today()


def test_empty_db_live_fetch_result_is_served(client, monkeypatch):
    today = stockholm_today()

    def fake_fetch(db, day, area):
        _seed(day)
        return db.query(GenerationMix).all()

    monkeypatch.setattr(gen_router, "fetch_and_store_generation", fake_fetch)
    resp = client.get("/api/v1/generation/today?area=SE3")
    assert resp.status_code == 200
    assert resp.json()["date"] == today.isoformat()
