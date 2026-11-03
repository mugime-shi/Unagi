"""
Tests for POST /api/v1/events and the usage summary (cohort return rate).
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.models.usage_event import UsageEvent
from app.services.usage_service import STOCKHOLM, summarize_usage

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
# POST /events
# ---------------------------------------------------------------------------


def test_visit_is_recorded(client, db):
    res = client.post(
        "/api/v1/events",
        json={"event": "visit", "label": "SweClockers.com", "days_since_first": 3, "days_since_last": 1},
    )
    assert res.status_code == 204
    row = db.query(UsageEvent).one()
    assert (row.event, row.label, row.days_since_first, row.days_since_last) == ("visit", "sweclockers.com", 3, 1)


def test_view_event_drops_day_offsets(client, db):
    res = client.post("/api/v1/events", json={"event": "tab_view", "label": "tomorrow", "days_since_first": 5})
    assert res.status_code == 204
    row = db.query(UsageEvent).one()
    assert row.days_since_first is None and row.days_since_last is None


@pytest.mark.parametrize(
    "body",
    [
        {"event": "purchase"},  # unknown event
        {"event": "visit"},  # visit without offsets
        {"event": "visit", "days_since_first": 2, "days_since_last": 5},  # last > first
        {"event": "visit", "days_since_first": -1},
        {"event": "tab_view", "label": "user@example.com"},  # free text rejected
        {"event": "tab_view", "label": "x" * 65},
    ],
)
def test_invalid_events_rejected(client, db, body):
    assert client.post("/api/v1/events", json=body).status_code == 422
    assert db.query(UsageEvent).count() == 0


# ---------------------------------------------------------------------------
# summarize_usage
# ---------------------------------------------------------------------------

TODAY = date(2026, 11, 20)


def _visit(db, day: date, first: int, last: int | None, label: str | None = None, hour: int = 12):
    ts = datetime(day.year, day.month, day.day, hour, tzinfo=STOCKHOLM)
    db.add(UsageEvent(occurred_at=ts, event="visit", label=label, days_since_first=first, days_since_last=last))


def test_cohort_return_rate(db):
    d1 = TODAY - timedelta(days=12)
    # Browser A: new on d1, back after 3 days, then again 2 days later
    _visit(db, d1, 0, None)
    _visit(db, d1 + timedelta(days=3), 3, 3)
    _visit(db, d1 + timedelta(days=5), 5, 2)  # not a first return → not double-counted
    # Browser B: new on d1, back only after 10 days (outside the 7-day window)
    _visit(db, d1, 0, None)
    _visit(db, d1 + timedelta(days=10), 10, 10)
    # Browser C: new 3 days ago — window not complete, excluded from the rate
    _visit(db, TODAY - timedelta(days=3), 0, None)
    _visit(db, TODAY - timedelta(days=1), 2, 2)
    db.commit()

    s = summarize_usage(db, days=30, today=TODAY)
    assert (s.cohort_returned, s.cohort_size) == (1, 2)
    assert s.return_rate == 0.5
    assert s.visits_by_day[d1] == (2, 0)
    assert s.visits_by_day[TODAY - timedelta(days=1)] == (0, 1)


def test_visit_day_uses_stockholm_time(db):
    # 00:30 local on the 15th is 23:30 UTC on the 14th
    _visit(db, date(2026, 11, 15), 0, None, hour=0)
    db.commit()
    s = summarize_usage(db, days=30, today=TODAY)
    assert s.visits_by_day[date(2026, 11, 15)] == (1, 0)
    assert s.visits_by_day[date(2026, 11, 14)] == (0, 0)


def test_referrers_and_views(db):
    _visit(db, TODAY, 0, None, label="flashback.org")
    _visit(db, TODAY, 0, None)
    db.add(UsageEvent(occurred_at=datetime(2026, 11, 20, 9, tzinfo=STOCKHOLM), event="layer_view", label="prices"))
    db.commit()

    s = summarize_usage(db, days=7, today=TODAY)
    assert s.referrers == {"flashback.org": 1, "(direct)": 1}
    assert s.views["layer_view"]["prices"] == 1
    assert s.return_rate is None
