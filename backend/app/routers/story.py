"""
Today story router — one rule-based headline about Swedish electricity.

Endpoints:
  GET /api/v1/story/today?date=YYYY-MM-DD   — headline + up to 3 supporting facts
"""

import logging
import time
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, get_db
from app.services.response_cache_service import get_cached as get_db_cached
from app.services.response_cache_service import prune_story, put_cached, story_key
from app.services.story_service import get_story
from app.utils.timezone import STOCKHOLM

log = logging.getLogger(__name__)

router = APIRouter(prefix="/story", tags=["story"])

DbDep = Annotated[Session, Depends(get_db)]

_CACHE_TTL = 30 * 60  # seconds
_CACHE_MAX = 100  # `date` is client-controlled; keep the cache bounded
_story_cache: dict[str, tuple[dict, float]] = {}


def _get_cached(key: str) -> dict | None:
    if key in _story_cache:
        resp, cached_at = _story_cache[key]
        if time.time() - cached_at <= _CACHE_TTL:
            return resp
        del _story_cache[key]
    return None


def _set_memory(day: date, result: dict) -> None:
    if len(_story_cache) >= _CACHE_MAX:
        _story_cache.clear()
    _story_cache[day.isoformat()] = (result, time.time())


def _compute_and_cache(db: Session, day: date, today: date) -> dict:
    started = time.monotonic()
    result = get_story(db, day, today)
    log.info("story computed in %.1fs", time.monotonic() - started)
    put_cached(db, story_key(day), result)
    _set_memory(day, result)
    return result


def refresh_today_story(min_age: float = 20 * 60) -> bool:
    """Warmer entry point: recompute today's story unless the cached one is younger than min_age.

    Opens its own session (no request scope). min_age < _CACHE_TTL so the cache never
    expires between warmer ticks and real visitors always hit it.
    """
    today = datetime.now(STOCKHOLM).date()
    entry = _story_cache.get(today.isoformat())
    if entry is not None and time.time() - entry[1] < min_age:
        return False
    db = SessionLocal()
    try:
        _compute_and_cache(db, today, today)
        prune_story(db)
    finally:
        db.close()
    return True


@router.get("/today")
def get_today_story(
    db: DbDep,
    date_: Annotated[
        date | None,
        Query(alias="date", description="Stockholm date, defaults to today"),
    ] = None,
):
    today = datetime.now(STOCKHOLM).date()
    day = date_ or today
    if day > today:
        raise HTTPException(status_code=422, detail="date must not be in the future")

    key = day.isoformat()
    cached = _get_cached(key)
    if cached is not None:
        return cached

    shared = get_db_cached(db, story_key(day), _CACHE_TTL)
    if shared is not None:
        _set_memory(day, shared)
        return shared

    return _compute_and_cache(db, day, today)
