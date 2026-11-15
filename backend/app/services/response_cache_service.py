"""
DB-backed shared response cache (table response_cache).

Every function here is best-effort: any failure (table not migrated yet, concurrent
insert race, connection error) is logged and swallowed so callers fall back to computing.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.response_cache import ResponseCache

log = logging.getLogger(__name__)

NATIONAL_24H_KEY = "national-24h"
STORY_KEY_PREFIX = "story:"


def story_key(day: date) -> str:
    return f"{STORY_KEY_PREFIX}{day.isoformat()}"


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; everything is stored as UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # pragma: no cover — session already unusable
        pass


def get_cached(db: Session, key: str, max_age_seconds: float) -> dict | None:
    """Return the payload if it is at most max_age_seconds old, else None. Never raises."""
    try:
        row = db.get(ResponseCache, key)
        if row is None:
            return None
        age = (datetime.now(timezone.utc) - _as_utc(row.computed_at)).total_seconds()
        if age > max_age_seconds:
            return None
        return row.payload
    except Exception as exc:
        log.warning("response_cache get(%s) failed: %s", key, exc)
        _rollback(db)
        return None


def put_cached(db: Session, key: str, payload: dict) -> None:
    """Upsert the payload with computed_at = now (UTC). Never raises."""
    try:
        now = datetime.now(timezone.utc)
        row = db.get(ResponseCache, key)
        if row is None:
            db.add(ResponseCache(key=key, payload=payload, computed_at=now))
        else:
            row.payload = payload
            row.computed_at = now
        db.commit()
    except Exception as exc:
        log.warning("response_cache put(%s) failed: %s", key, exc)
        _rollback(db)


def prune_story(db: Session, older_than_days: int = 30) -> None:
    """Delete story:* rows older than older_than_days. Never raises."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        db.execute(
            delete(ResponseCache).where(
                ResponseCache.key.like(f"{STORY_KEY_PREFIX}%"),
                ResponseCache.computed_at < cutoff,
            )
        )
        db.commit()
    except Exception as exc:
        log.warning("response_cache prune failed: %s", exc)
        _rollback(db)
