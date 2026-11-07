"""
SQLAlchemy ORM model for generation_outages (ENTSO-E A77 / A80).

One row per ENTSO-E outage document (mRID). A replanned outage gets a NEW mRID
and the old document stays behind as cancelled (A09), so rows are upserted by
mRID. `status` is active / cancelled / withdrawn (withdrawn = a once-active
document that ENTSO-E stopped returning for its window).
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationOutage(Base):
    __tablename__ = "generation_outages"

    id: Mapped[int] = mapped_column(primary_key=True)
    mrid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    document_type: Mapped[str] = mapped_column(String(3), nullable=False)  # A77 | A80
    business_type: Mapped[str | None] = mapped_column(String(3), nullable=True)  # A53 planned | A54 forced
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    area: Mapped[str] = mapped_column(String(4), nullable=False)
    resource_eic: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    psr_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    nominal_mw: Mapped[float | None] = mapped_column(Numeric(8, 1), nullable=True)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # [{"start": iso, "end": iso, "mw": float}, ...] — available MW, absolute periods
    available_periods: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (Index("idx_generation_outages_area_window", "area", "start_utc", "end_utc"),)
