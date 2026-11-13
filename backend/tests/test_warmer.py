"""
Tests for the EventBridge warmer routed by app.main.handler.
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app import main as main_mod
from app.routers import story as story_router
from app.services import generation_service
from app.services.entsoe_client import EntsoEError
from app.utils.timezone import STOCKHOLM

EVENT = {"warmer": True}
NOT_DUE = datetime(2026, 11, 12, 10, 7, tzinfo=timezone.utc)
DUE = datetime(2026, 11, 12, 10, 16, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    story_router._story_cache.clear()
    mangum = MagicMock(return_value={"statusCode": 200})
    monkeypatch.setattr(main_mod, "_mangum", mangum)
    # The story build needs a DB; the real one is covered by test_story.py
    fake_db = MagicMock()
    monkeypatch.setattr(story_router, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(story_router, "get_story", MagicMock(return_value={"headline": "h"}))
    # Generation refresh has its own tests below; here it must never reach ENTSO-E
    monkeypatch.setattr(main_mod, "refresh_today_generation", MagicMock(return_value=None))
    yield mangum
    story_router._story_cache.clear()


def _today_key():
    return datetime.now(STOCKHOLM).date().isoformat()


def test_warmer_returns_dict_and_skips_mangum(isolate):
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": True, "generation": None}
    isolate.assert_not_called()


def test_empty_cache_is_filled_and_served(isolate):
    main_mod.handler(EVENT, None)
    assert _today_key() in story_router._story_cache
    assert story_router._get_cached(_today_key()) == {"headline": "h"}


def test_stale_cache_is_refreshed():
    story_router._story_cache[_today_key()] = ({"headline": "old"}, time.time() - 25 * 60)
    assert main_mod.handler(EVENT, None)["story_refreshed"] is True
    assert story_router._story_cache[_today_key()][0] == {"headline": "h"}


def test_fresh_cache_is_not_recomputed():
    story_router._story_cache[_today_key()] = ({"headline": "old"}, time.time() - 60)
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "generation": None}
    story_router.get_story.assert_not_called()


def test_refresh_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(story_router, "get_story", MagicMock(side_effect=RuntimeError("db down")))
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "generation": None}


def test_http_event_goes_to_mangum(isolate):
    http_event = {"version": "2.0", "rawPath": "/health"}
    assert main_mod.handler(http_event, None) == {"statusCode": 200}
    isolate.assert_called_once_with(http_event, None)


def test_warmer_includes_generation_result(monkeypatch):
    monkeypatch.setattr(main_mod, "refresh_today_generation", MagicMock(return_value={"SE3": "ok"}))
    assert main_mod.handler(EVENT, None)["generation"] == {"SE3": "ok"}


def test_warmer_never_raises_when_both_refreshes_fail(monkeypatch):
    monkeypatch.setattr(main_mod, "refresh_today_generation", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(main_mod, "refresh_today_story", MagicMock(side_effect=RuntimeError("db down")))
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "generation": None}


def test_generation_failure_does_not_skip_story(monkeypatch):
    monkeypatch.setattr(main_mod, "refresh_today_generation", MagicMock(side_effect=RuntimeError("boom")))
    assert main_mod.handler(EVENT, None)["story_refreshed"] is True


def test_generation_refresh_skipped_when_not_due(monkeypatch):
    fetch = MagicMock()
    monkeypatch.setattr(generation_service, "fetch_and_store_generation", fetch)
    assert generation_service.refresh_today_generation(NOT_DUE) is None
    fetch.assert_not_called()


def test_generation_refresh_fetches_all_areas_when_due(monkeypatch):
    fetch = MagicMock(return_value=[])
    monkeypatch.setattr(generation_service, "fetch_and_store_generation", fetch)
    monkeypatch.setattr(generation_service, "SessionLocal", lambda: MagicMock())
    result = generation_service.refresh_today_generation(DUE)
    assert result == {"SE1": "ok", "SE2": "ok", "SE3": "ok", "SE4": "ok"}
    assert sorted(c.args[2] for c in fetch.call_args_list) == ["SE1", "SE2", "SE3", "SE4"]
    assert all(c.kwargs["timeout"] == 12.0 for c in fetch.call_args_list)


def test_generation_refresh_area_failure_is_isolated(monkeypatch):
    def fake_fetch(db, day, area, timeout):
        if area == "SE2":
            raise EntsoEError("no data yet")
        if area == "SE4":
            raise RuntimeError("unexpected")
        return []

    monkeypatch.setattr(generation_service, "fetch_and_store_generation", fake_fetch)
    monkeypatch.setattr(generation_service, "SessionLocal", lambda: MagicMock())
    assert generation_service.refresh_today_generation(DUE) == {
        "SE1": "ok",
        "SE2": "error",
        "SE3": "ok",
        "SE4": "error",
    }
