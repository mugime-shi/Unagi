"""
Tests for the DB-backed shared response cache and its use by story / national-24h.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.response_cache import ResponseCache
from app.routers import generation as generation_router
from app.routers import story as story_router
from app.services import response_cache_service as svc
from app.utils.timezone import STOCKHOLM

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db(monkeypatch):
    Base.metadata.create_all(engine)
    story_router._story_cache.clear()
    generation_router._national_cache = None
    monkeypatch.setattr(story_router, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(generation_router, "SessionLocal", TestingSessionLocal)
    yield
    story_router._story_cache.clear()
    generation_router._national_cache = None
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def _age(db, key, seconds):
    row = db.get(ResponseCache, key)
    row.computed_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    db.commit()


# --- service ---------------------------------------------------------------


def test_put_then_get(db):
    svc.put_cached(db, "k", {"a": 1})
    assert svc.get_cached(db, "k", 60) == {"a": 1}


def test_put_overwrites_existing(db):
    svc.put_cached(db, "k", {"a": 1})
    svc.put_cached(db, "k", {"a": 2})
    assert svc.get_cached(db, "k", 60) == {"a": 2}
    assert db.query(ResponseCache).count() == 1


def test_get_missing_key(db):
    assert svc.get_cached(db, "nope", 60) is None


def test_get_expired_returns_none(db):
    svc.put_cached(db, "k", {"a": 1})
    _age(db, "k", 120)
    assert svc.get_cached(db, "k", 60) is None
    assert svc.get_cached(db, "k", 600) == {"a": 1}


def test_naive_computed_at_is_treated_as_utc(db):
    naive_recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).replace(tzinfo=None)
    db.add(ResponseCache(key="k", payload={"a": 1}, computed_at=naive_recent))
    db.commit()
    db.expire_all()
    assert db.get(ResponseCache, "k").computed_at.tzinfo is None  # SQLite round-trips naive
    assert svc.get_cached(db, "k", 60) == {"a": 1}


def test_get_and_put_swallow_missing_table(db):
    Base.metadata.drop_all(engine)
    assert svc.get_cached(db, "k", 60) is None
    svc.put_cached(db, "k", {"a": 1})  # must not raise
    svc.prune_story(db)  # must not raise


def test_get_and_put_swallow_broken_session():
    broken = MagicMock()
    broken.get.side_effect = RuntimeError("conn lost")
    assert svc.get_cached(broken, "k", 60) is None
    svc.put_cached(broken, "k", {"a": 1})
    broken.rollback.assert_called()


def test_put_swallows_integrity_race(db):
    # Another instance inserted between our select and our commit
    other = TestingSessionLocal()
    other.add(ResponseCache(key="k", payload={"a": 0}, computed_at=datetime.now(timezone.utc)))
    other.commit()
    other.close()
    real_get = db.get
    db.get = MagicMock(return_value=None)  # our select saw nothing
    try:
        svc.put_cached(db, "k", {"a": 1})  # IntegrityError on commit -> swallowed
    finally:
        db.get = real_get
    assert svc.get_cached(db, "k", 60) == {"a": 0}


def test_prune_story_deletes_only_old_story_rows(db):
    for key in ("story:2026-01-01", "story:2026-11-14", "national-24h"):
        svc.put_cached(db, key, {"x": 1})
    _age(db, "story:2026-01-01", 31 * 86400)
    _age(db, "national-24h", 60 * 86400)
    svc.prune_story(db)
    keys = {r.key for r in db.query(ResponseCache).all()}
    assert keys == {"story:2026-11-14", "national-24h"}


def test_keys():
    assert svc.story_key(date(2026, 1, 2)) == "story:2026-01-02"
    assert svc.NATIONAL_24H_KEY == "national-24h"


# --- story -----------------------------------------------------------------


def _today():
    return datetime.now(STOCKHOLM).date()


def test_story_db_hit_skips_compute(client, db, monkeypatch):
    compute = MagicMock(return_value={"headline": "computed"})
    monkeypatch.setattr(story_router, "get_story", compute)
    svc.put_cached(db, svc.story_key(_today()), {"headline": "shared"})
    resp = client.get("/api/v1/story/today")
    assert resp.json() == {"headline": "shared"}
    compute.assert_not_called()
    assert story_router._get_cached(_today().isoformat()) == {"headline": "shared"}  # memory filled


def test_story_expired_db_row_recomputes(client, db, monkeypatch):
    monkeypatch.setattr(story_router, "get_story", MagicMock(return_value={"headline": "fresh"}))
    key = svc.story_key(_today())
    svc.put_cached(db, key, {"headline": "old"})
    _age(db, key, 31 * 60)
    assert client.get("/api/v1/story/today").json() == {"headline": "fresh"}
    assert svc.get_cached(db, key, 60) == {"headline": "fresh"}


def test_story_miss_computes_and_writes_db(client, db, monkeypatch):
    compute = MagicMock(return_value={"headline": "computed"})
    monkeypatch.setattr(story_router, "get_story", compute)
    assert client.get("/api/v1/story/today").json() == {"headline": "computed"}
    compute.assert_called_once()
    assert svc.get_cached(db, svc.story_key(_today()), 60) == {"headline": "computed"}


def test_refresh_today_story_writes_db(db, monkeypatch):
    monkeypatch.setattr(story_router, "get_story", MagicMock(return_value={"headline": "w"}))
    assert story_router.refresh_today_story() is True
    assert svc.get_cached(db, svc.story_key(_today()), 60) == {"headline": "w"}


def test_refresh_today_story_prunes_once_per_refresh(monkeypatch):
    monkeypatch.setattr(story_router, "get_story", MagicMock(return_value={"headline": "w"}))
    prune = MagicMock()
    monkeypatch.setattr(story_router, "prune_story", prune)
    story_router.refresh_today_story()
    story_router.refresh_today_story()  # memory still fresh -> no refresh, no prune
    assert prune.call_count == 1


# --- national-24h ----------------------------------------------------------

NATIONAL = {"count": 1, "latest_slot": "x", "hourly": [{"hydro": 1}]}


def test_national_db_hit_skips_compute(client, db, monkeypatch):
    compute = MagicMock(return_value={"count": 0})
    monkeypatch.setattr(generation_router, "_compute_national_24h", compute)
    svc.put_cached(db, svc.NATIONAL_24H_KEY, NATIONAL)
    assert client.get("/api/v1/generation/national-24h").json() == NATIONAL
    compute.assert_not_called()


def test_national_miss_computes_and_stores(client, db, monkeypatch):
    compute = MagicMock(return_value=NATIONAL)
    monkeypatch.setattr(generation_router, "_compute_national_24h", compute)
    assert client.get("/api/v1/generation/national-24h").json() == NATIONAL
    assert svc.get_cached(db, svc.NATIONAL_24H_KEY, 60) == NATIONAL
    # second call is served from memory
    assert client.get("/api/v1/generation/national-24h").json() == NATIONAL
    compute.assert_called_once()


def test_refresh_national_skips_when_fresh(db, monkeypatch):
    compute = MagicMock(return_value=NATIONAL)
    monkeypatch.setattr(generation_router, "_compute_national_24h", compute)
    svc.put_cached(db, svc.NATIONAL_24H_KEY, {"old": True})
    assert generation_router.refresh_national_24h() is False
    compute.assert_not_called()


def test_refresh_national_recomputes_when_stale_or_missing(db, monkeypatch):
    compute = MagicMock(return_value=NATIONAL)
    monkeypatch.setattr(generation_router, "_compute_national_24h", compute)
    assert generation_router.refresh_national_24h() is True  # missing
    _age(db, svc.NATIONAL_24H_KEY, 16 * 60)
    assert generation_router.refresh_national_24h() is True  # stale
    assert compute.call_count == 2
    assert svc.get_cached(db, svc.NATIONAL_24H_KEY, 60) == NATIONAL


def test_refresh_national_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(generation_router, "_compute_national_24h", MagicMock(side_effect=RuntimeError("db")))
    assert generation_router.refresh_national_24h() is False


def test_refresh_national_swallows_session_factory_failure(monkeypatch):
    monkeypatch.setattr(generation_router, "SessionLocal", MagicMock(side_effect=RuntimeError("no db")))
    assert generation_router.refresh_national_24h() is False
