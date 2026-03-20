"""
SQLAlchemy ORM model for load_forecast table.
Stores ENTSO-E A65 day-ahead load forecasts for SE3.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LoadForecast(Base):
    __tablename__ = "load_forecast"

    id: Mapped[int] = mapped_column(primary_key=True)
    area: Mapped[str] = mapped_column(String(4), nullable=False, default="SE3")
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    load_mw: Mapped[float] = mapped_column(Numeric(10, 1), nullable=False)
    resolution: Mapped[str] = mapped_column(String(10), default="PT60M")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("area", "timestamp_utc", "resolution", name="uq_load_forecast"),
        Index("idx_load_forecast_area_time", "area", "timestamp_utc"),
    )
