"""
Tests for the EventBridge warmer routed by app.main.handler.
"""

import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app import main as main_mod
from app.routers import story as story_router
from app.utils.timezone import STOCKHOLM

EVENT = {"warmer": True}


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    story_router._story_cache.clear()
    mangum = MagicMock(return_value={"statusCode": 200})
    monkeypatch.setattr(main_mod, "_mangum", mangum)
    # The story build needs a DB; the real one is covered by test_story.py
    fake_db = MagicMock()
    monkeypatch.setattr(story_router, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(story_router, "get_story", MagicMock(return_value={"headline": "h"}))
    # The shared DB cache is covered by test_response_cache.py
    monkeypatch.setattr(story_router, "put_cached", MagicMock())
    monkeypatch.setattr(story_router, "prune_story", MagicMock())
    # Warmer tests must not touch a DB for the national refresh either
    monkeypatch.setattr(main_mod, "refresh_national_24h", MagicMock(return_value=True))
    yield mangum
    story_router._story_cache.clear()


def _today_key():
    return datetime.now(STOCKHOLM).date().isoformat()


def test_warmer_returns_dict_and_skips_mangum(isolate):
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": True, "national_refreshed": True}
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
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "national_refreshed": True}
    story_router.get_story.assert_not_called()


def test_refresh_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(story_router, "get_story", MagicMock(side_effect=RuntimeError("db down")))
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "national_refreshed": True}


def test_national_failure_does_not_stop_story_refresh(monkeypatch):
    monkeypatch.setattr(main_mod, "refresh_national_24h", MagicMock(side_effect=RuntimeError("boom")))
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": True, "national_refreshed": False}


def test_story_failure_does_not_stop_national_refresh(monkeypatch):
    monkeypatch.setattr(main_mod, "refresh_today_story", MagicMock(side_effect=RuntimeError("boom")))
    assert main_mod.handler(EVENT, None) == {"warmed": True, "story_refreshed": False, "national_refreshed": True}
    main_mod.refresh_national_24h.assert_called_once()


def test_http_event_goes_to_mangum(isolate):
    http_event = {"version": "2.0", "rawPath": "/health"}
    assert main_mod.handler(http_event, None) == {"statusCode": 200}
    isolate.assert_called_once_with(http_event, None)
