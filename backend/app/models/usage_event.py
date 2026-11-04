"""
SQLAlchemy ORM model for usage_events table.

First-party, ID-less usage tracking. Vercel Analytics resets its visitor hash
every 24h and gates custom events behind Pro, so it cannot measure return
visits. Instead the browser keeps its own first/last visit dates in
localStorage and reports only day *offsets* here — no visitor ID, IP or
user agent is stored.

A browser sends at most one `visit` per local calendar day. Its first return
visit is the one where days_since_first == days_since_last, which lets the
report compute cohort return rates without linking rows to a visitor.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # visit | layer_view | tab_view | area_select (validated in the router)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    # layer / tab / area name, or referrer hostname for `visit`
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # `visit` only: 0 for a first-ever visit
    days_since_first: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # `visit` only: NULL for a first-ever visit
    days_since_last: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("idx_usage_events_event_time", "event", "occurred_at"),)
